"""Portable, validated snapshots of the SQLite database and uploaded PDFs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import models  # noqa: F401 - registers every persisted model

FORMAT_VERSION = 1
SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_EXPANDED_BYTES = 4 * 1024**3
MAX_MEMBERS = 10_000
MAX_MANIFEST_BYTES = 1024**2
PDF_NAME = re.compile(r"^[a-f0-9]{32}\.pdf$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class BackupError(Exception):
    pass


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_limited(source, target: Path, expected_size: int, expected_hash: str) -> None:
    hasher = hashlib.sha256()
    size = 0
    with target.open('wb') as output:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > expected_size:
                raise BackupError('A backup file exceeds its declared size.')
            output.write(chunk)
            hasher.update(chunk)
    if size != expected_size or hasher.hexdigest() != expected_hash:
        raise BackupError('Backup checksum verification failed.')


class BackupService:
    def __init__(self, engine: Engine, pdf_dir: Path, safety_dir: Path, state_dir: Path):
        self.engine = engine
        self.pdf_dir = pdf_dir.resolve()
        self.safety_dir = safety_dir.resolve()
        self.state_dir = state_dir.resolve()
        self.journal = self.state_dir / 'restore-in-progress.json'
        if engine.url.get_backend_name() != 'sqlite' or not engine.url.database or engine.url.database == ':memory:':
            raise BackupError('Backup requires a file-based SQLite database.')
        self.database = Path(engine.url.database).resolve()

    @staticmethod
    def _check_database(path: Path) -> dict[str, int]:
        try:
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as connection:
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise BackupError('The backup database failed its integrity check.')
                if connection.execute('PRAGMA foreign_key_check').fetchone():
                    raise BackupError('The backup database has broken references.')
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in SQLModel.metadata.tables.values():
                    if table.name not in tables:
                        if table.name in {'bookmark', 'studyplan', 'studyplanoverride', 'focussettings', 'focussession'}:
                            continue  # Archives predating these additive features remain restorable.
                        raise BackupError('The backup database schema is incompatible.')
                    columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')}
                    expected = {column.name for column in table.columns}
                    if table.name in {'studyplan', 'studyplanoverride'}:
                        expected -= {'estimated_pomodoros', 'focus_minutes', 'short_break_minutes', 'long_break_minutes'}
                    if table.name == 'focussession':
                        expected -= {'task_date'}
                    if not expected.issubset(columns):
                        raise BackupError('The backup database schema is incompatible.')
                return {table.name: connection.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
                        for table in SQLModel.metadata.tables.values() if table.name in tables}
        except (sqlite3.DatabaseError, OSError) as exc:
            raise BackupError('The backup database is unreadable.') from exc

    @staticmethod
    def _pdf_names(path: Path) -> set[str]:
        with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as connection:
            names = {row[0] for row in connection.execute('SELECT stored_filename FROM pdfdocument')}
        if any(not isinstance(name, str) or not PDF_NAME.fullmatch(name) for name in names):
            raise BackupError('The database contains an invalid PDF filename.')
        return names

    def _snapshot(self, destination: Path) -> None:
        if not self.database.is_file():
            raise BackupError('The SQLite database is unavailable.')
        try:
            with closing(sqlite3.connect(f'{self.database.as_uri()}?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
                    if target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='focussession'").fetchone():
                        # Portable backups retain history and verified progress, but never auto-run a restored timer.
                        target.execute("UPDATE focussession SET status='paused' WHERE status='running'")
                        target.commit()
        except (sqlite3.DatabaseError, OSError) as exc:
            raise BackupError('Could not create a consistent SQLite snapshot.') from exc

    @staticmethod
    def _remove_derived_search_data(path: Path) -> None:
        # Search text and FTS tables can be recreated from the saved records/PDFs.
        # Keeping them out makes backups smaller and portable to SQLite without FTS5.
        try:
            with closing(sqlite3.connect(path)) as connection:
                for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'search_%'").fetchall():
                    if not re.fullmatch(r'search_[a-z0-9_]+', name):
                        raise BackupError('Unexpected search trigger in the database.')
                    connection.execute(f'DROP TRIGGER "{name}"')
                for table in ('search_entries', 'pdf_search_page', 'pdf_search_state', 'search_meta'):
                    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        connection.execute(f'DROP TABLE "{table}"')
                connection.commit()
        except sqlite3.DatabaseError as exc:
            raise BackupError('Could not prepare the portable database snapshot.') from exc

    def create(self, destination: Path) -> dict:
        """Caller must hold the application-wide exclusive request gate."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='learntube-snapshot-') as temp:
            db_copy = Path(temp) / 'database.sqlite3'
            self._snapshot(db_copy)
            self._remove_derived_search_data(db_copy)
            counts = self._check_database(db_copy)
            names = self._pdf_names(db_copy)
            sources: list[tuple[str, Path]] = [('database.sqlite3', db_copy)]
            for name in sorted(names):
                pdf = self.pdf_dir / name
                if not pdf.is_file() or pdf.is_symlink():
                    raise BackupError('An uploaded PDF referenced by the database is missing or unsafe.')
                sources.append((f'uploads/pdfs/{name}', pdf))
            if len(sources) + 1 > MAX_MEMBERS:
                raise BackupError('Too many files to back up.')
            inventory = [{'path': name, 'size': source.stat().st_size, 'sha256': _digest(source)}
                         for name, source in sources]
            if sum(item['size'] for item in inventory) > MAX_EXPANDED_BYTES:
                raise BackupError('The data exceeds the backup size limit.')
            manifest = {'format_version': FORMAT_VERSION, 'schema_version': SCHEMA_VERSION,
                        'app_version': '0.1.0', 'created_at': datetime.now(timezone.utc).isoformat(),
                        'files': inventory, 'counts': counts}
            partial = destination.with_name(destination.name + '.partial')
            try:
                with ZipFile(partial, 'w', compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                    for item, (_, source) in zip(inventory, sources):
                        # Detect changes to uploaded files during archive creation.
                        if source.stat().st_size != item['size'] or _digest(source) != item['sha256']:
                            raise BackupError('An uploaded file changed while creating the backup.')
                        archive.write(source, item['path'])
                    archive.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')))
                if partial.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise BackupError('The backup archive exceeds the size limit.')
                self.validate(partial, Path(temp) / 'verified')
                os.replace(partial, destination)
            finally:
                partial.unlink(missing_ok=True)
        return manifest

    def validate(self, archive_path: Path, staging: Path) -> dict:
        """Validate every byte and stage only allowlisted files; never extract by ZIP path."""
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupError('The backup archive exceeds the size limit.')
        try:
            with ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > MAX_MEMBERS or len({entry.filename for entry in entries}) != len(entries):
                    raise BackupError('The backup has duplicate or too many files.')
                by_name = {entry.filename: entry for entry in entries}
                if 'manifest.json' not in by_name or by_name['manifest.json'].file_size > MAX_MANIFEST_BYTES:
                    raise BackupError('The backup manifest is missing or too large.')
                for entry in entries:
                    name = entry.filename
                    mode = entry.external_attr >> 16
                    if (entry.is_dir() or entry.flag_bits & 1 or '\\' in name or name.startswith('/')
                            or '..' in Path(name).parts or (mode and stat.S_IFMT(mode) == stat.S_IFLNK)
                            or (name not in {'manifest.json', 'database.sqlite3'}
                                and not (name.startswith('uploads/pdfs/') and PDF_NAME.fullmatch(name[13:])))):
                        raise BackupError('The backup contains an unsafe or unexpected file.')
                with archive.open('manifest.json') as item:
                    raw = item.read(MAX_MANIFEST_BYTES + 1)
                if len(raw) > MAX_MANIFEST_BYTES:
                    raise BackupError('The backup manifest is too large.')
                manifest = json.loads(raw)
                if (not isinstance(manifest, dict) or manifest.get('format_version') != FORMAT_VERSION
                        or manifest.get('schema_version') != SCHEMA_VERSION):
                    raise BackupError('This backup version is not supported.')
                if not isinstance(manifest.get('created_at'), str):
                    raise BackupError('The backup manifest is invalid.')
                datetime.fromisoformat(manifest['created_at'])
                inventory = manifest.get('files')
                if not isinstance(inventory, list) or len(inventory) != len(entries) - 1:
                    raise BackupError('The backup inventory is invalid.')
                names = set()
                expanded = 0
                staging.mkdir(parents=True, exist_ok=True)
                for record in inventory:
                    if not isinstance(record, dict):
                        raise BackupError('The backup inventory is invalid.')
                    name, size, checksum = record.get('path'), record.get('size'), record.get('sha256')
                    if (not isinstance(name, str) or name == 'manifest.json' or name not in by_name or name in names
                            or type(size) is not int or size < 0 or not isinstance(checksum, str)
                            or not SHA256.fullmatch(checksum) or by_name[name].file_size != size):
                        raise BackupError('The backup inventory is invalid.')
                    names.add(name)
                    expanded += size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise BackupError('The backup expands beyond its size limit.')
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source:
                        _copy_limited(source, target, size, checksum)
                if names != set(by_name) - {'manifest.json'} or 'database.sqlite3' not in names:
                    raise BackupError('The backup inventory is incomplete.')
            counts = self._check_database(staging / 'database.sqlite3')
            expected_pdfs = self._pdf_names(staging / 'database.sqlite3')
            if {name.removeprefix('uploads/pdfs/') for name in names if name.startswith('uploads/pdfs/')} != expected_pdfs:
                raise BackupError('The backup PDF files do not match the database.')
            if manifest.get('counts') != counts:
                raise BackupError('The backup summary does not match the database.')
            return {'created_at': manifest['created_at'], 'format_version': FORMAT_VERSION,
                    'schema_version': SCHEMA_VERSION, 'counts': counts, 'pdf_files': len(expected_pdfs),
                    'archive_sha256': _digest(archive_path)}
        except (BadZipFile, EOFError, OSError, ValueError, KeyError, TypeError, UnicodeError, RuntimeError, sqlite3.DatabaseError) as exc:
            raise BackupError('The backup archive is corrupt or invalid.') from exc

    def _write_journal(self, safety: Path, old_dir: Path) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix('.tmp')
        temporary.write_text(json.dumps({'safety': str(safety), 'old_dir': str(old_dir)}), encoding='utf-8')
        os.replace(temporary, self.journal)

    def _replace_database(self, source: Path) -> None:
        self.engine.dispose()
        with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as snapshot:
            with closing(sqlite3.connect(self.database, timeout=5)) as live:
                snapshot.backup(live)

    def _pdf_stage_on_target_volume(self, source: Path) -> Path:
        self.pdf_dir.parent.mkdir(parents=True, exist_ok=True)
        if source.stat().st_dev == self.pdf_dir.parent.stat().st_dev:
            return source
        sibling = self.pdf_dir.parent / f'.pdfs-staged-{uuid4().hex}'
        shutil.copytree(source, sibling)
        return sibling

    def _apply(self, staging: Path, old_dir: Path) -> None:
        staged_pdfs = staging / 'uploads' / 'pdfs'
        staged_pdfs.mkdir(parents=True, exist_ok=True)
        prepared = self._pdf_stage_on_target_volume(staged_pdfs)
        try:
            if self.pdf_dir.exists():
                os.replace(self.pdf_dir, old_dir)
            os.replace(prepared, self.pdf_dir)
            self._replace_database(staging / 'database.sqlite3')
            from app.db import migrate_focus_columns
            migrate_focus_columns(self.engine)
            SQLModel.metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_focus_active ON focussession((1)) WHERE status IN ('running','paused')"))
            self._check_database(self.database)
        finally:
            if prepared != staged_pdfs and prepared.exists():
                shutil.rmtree(prepared, ignore_errors=True)

    def recover_if_needed(self) -> None:
        if not self.journal.exists():
            return
        record = json.loads(self.journal.read_text(encoding='utf-8'))
        safety = Path(record['safety'])
        if not safety.is_file() or safety.parent.resolve() != self.safety_dir:
            raise BackupError('Restore recovery needs the saved safety backup.')
        with tempfile.TemporaryDirectory(prefix='learntube-recovery-', dir=self.state_dir) as temp:
            staging = Path(temp) / 'staging'
            self.validate(safety, staging)
            old_dir = Path(record['old_dir'])
            self.engine.dispose()
            damaged = self.pdf_dir.parent / f'.pdfs-interrupted-{uuid4().hex}'
            if old_dir.exists():
                if self.pdf_dir.exists():
                    os.replace(self.pdf_dir, damaged)
                os.replace(old_dir, self.pdf_dir)
            else:
                safety_pdfs = staging / 'uploads' / 'pdfs'
                safety_pdfs.mkdir(parents=True, exist_ok=True)
                prepared = self._pdf_stage_on_target_volume(safety_pdfs)
                if self.pdf_dir.exists():
                    os.replace(self.pdf_dir, damaged)
                os.replace(prepared, self.pdf_dir)
            self._replace_database(staging / 'database.sqlite3')
            self._check_database(self.database)
            if damaged.exists():
                shutil.rmtree(damaged, ignore_errors=True)
        self.journal.unlink()

    def restore(self, archive_path: Path, expected_hash: str) -> dict:
        if not SHA256.fullmatch(expected_hash):
            raise BackupError('Inspect the selected backup before restoring it.')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='learntube-restore-', dir=self.state_dir) as temp:
            staging = Path(temp) / 'staging'
            summary = self.validate(archive_path, staging)
            if summary['archive_sha256'] != expected_hash:
                raise BackupError('The selected backup changed after inspection.')
            self.safety_dir.mkdir(parents=True, exist_ok=True)
            safety = self.safety_dir / f'learntube-before-restore-{datetime.now(timezone.utc):%Y-%m-%d-%H%M%S}-{uuid4().hex[:8]}.zip'
            self.create(safety)
            old_dir = self.pdf_dir.parent / f'.pdfs-before-restore-{uuid4().hex}'
            self._write_journal(safety, old_dir)
            try:
                self._apply(staging, old_dir)
            except Exception as exc:
                try:
                    self.recover_if_needed()
                except Exception as recovery_exc:
                    raise BackupError('Restore failed and automatic recovery failed. Keep the safety backup and stop the application.') from recovery_exc
                raise BackupError('Restore failed; previous data was recovered from the safety backup.') from exc
            self.journal.unlink()
            if old_dir.exists():
                shutil.rmtree(old_dir, ignore_errors=True)
            return {**summary, 'safety_backup': safety.name}
