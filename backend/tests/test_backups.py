import asyncio
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.middleware.backup_gate import BackupGate
from app.models import (Notebook, NotebookNote, PDFDocument, PDFNote, ReviewEvent, StudyActivity,
                        TranscriptSegment, Video, VideoNote, VocabularyItem, WritingSession)
from app.routers import backups
from app.services import backups as backup_module
from app.services.backups import BackupError, BackupService


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdfs = self.root / 'uploads' / 'pdfs'
        self.engine = create_engine(f'sqlite:///{(self.root / "data.db").as_posix()}')
        SQLModel.metadata.create_all(self.engine)
        self.service = BackupService(self.engine, self.pdfs, self.root / 'safety', self.root / 'state')
        self.archive = self.root / 'backup.zip'

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def _populate(self):
        self.pdfs.mkdir(parents=True)
        name = f'{uuid4().hex}.pdf'
        pdf_data = b'%PDF-1.4\nexample\n'
        (self.pdfs / name).write_bytes(pdf_data)
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            video = Video(youtube_id='example123', url='https://youtube.com/watch?v=example123', title='Lesson', playback_position=45)
            session.add(video); session.flush()
            session.add(TranscriptSegment(video_id=video.id, text='Transcript', start=0))
            session.add(VideoNote(video_id=video.id, content='My video note'))
            pdf = PDFDocument(title='Reading', original_filename='reading.pdf', stored_filename=name,
                              file_size_bytes=len(pdf_data), total_pages=2, last_page=2, reading_progress=100)
            session.add(pdf); session.flush()
            session.add(PDFNote(pdf_id=pdf.id, content='PDF note'))
            notebook = Notebook(name='Grammar')
            session.add(notebook); session.flush()
            session.add(NotebookNote(notebook_id=notebook.id, title='Tenses', content='Present perfect'))
            word = VocabularyItem(text='coherent', meaning='logical', example_sentence='A coherent argument.',
                                  source_video_id=video.id, source_pdf_id=pdf.id, status='reviewing',
                                  review_count=3, interval_days=7, ease_factor=2.4, next_review_at=now)
            session.add(word); session.flush()
            session.add(ReviewEvent(vocabulary_id=word.id, rating='good', previous_status='learning', next_status='reviewing', interval_days=7))
            session.add(WritingSession(task_type=2, question='Discuss both views', essay_content='My essay',
                                       chatgpt_feedback='Improve cohesion', status='completed', word_count=2))
            session.add(StudyActivity(event_key='session-1', client_session_id='client-1', activity_type='pdf',
                                      started_at=now, ended_at=now, active_duration_seconds=120))
            session.commit()
        return name, pdf_data

    def _value(self, sql):
        with closing(sqlite3.connect(self.service.database)) as connection:
            return connection.execute(sql).fetchone()[0]

    def test_empty_database_backup_and_manifest(self):
        manifest = self.service.create(self.archive)
        self.assertEqual(manifest['counts']['video'], 0)
        with ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {'database.sqlite3', 'manifest.json'})
            self.assertNotIn('GEMINI_API_KEY', archive.read('manifest.json').decode())
            snapshot = self.root / 'snapshot.db'
            snapshot.write_bytes(archive.read('database.sqlite3'))
        self.assertEqual(self.service._check_database(snapshot)['video'], 0)
        self.assertEqual(self.service.validate(self.archive, self.root / 'staged')['pdf_files'], 0)

    def test_backup_before_planner_tables_remains_restorable(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql('DROP TABLE studyplanoverride')
            connection.exec_driver_sql('DROP TABLE studyplan')
        manifest = self.service.create(self.archive)
        self.assertNotIn('studyplan', manifest['counts'])
        inspected = self.service.validate(self.archive, self.root / 'old-planner-staged')
        self.service.restore(self.archive, inspected['archive_sha256'])
        with closing(sqlite3.connect(self.service.database)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM studyplan').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM studyplanoverride').fetchone()[0], 0)

    def test_committed_wal_rows_are_in_snapshot(self):
        with closing(sqlite3.connect(self.service.database)) as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        with Session(self.engine) as session:
            session.add(Video(youtube_id='wal-row', url='https://example.test', title='Committed in WAL'))
            session.commit()
        self.service.create(self.archive)
        with ZipFile(self.archive) as archive:
            snapshot = self.root / 'wal-snapshot.db'
            snapshot.write_bytes(archive.read('database.sqlite3'))
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute('SELECT title FROM video').fetchone()[0], 'Committed in WAL')

    def test_missing_pdf_prevents_successful_backup(self):
        name, _ = self._populate()
        (self.pdfs / name).unlink()
        with self.assertRaisesRegex(BackupError, 'missing'):
            self.service.create(self.archive)
        self.assertFalse(self.archive.exists())

    def test_study_records_pdf_and_restore_with_safety_backup(self):
        name, content = self._populate()
        with closing(sqlite3.connect(self.service.database)) as connection:
            original_reviews = connection.execute('SELECT id, vocabulary_id, rating, reviewed_at, interval_days FROM reviewevent ORDER BY id').fetchall()
        manifest = self.service.create(self.archive)
        self.assertEqual(manifest['counts']['reviewevent'], 1)
        summary = self.service.validate(self.archive, self.root / 'staged')
        self.assertEqual(summary['counts']['notebooknote'], 1)
        self.assertEqual(summary['counts']['writingsession'], 1)
        self.assertEqual(summary['counts']['studyactivity'], 1)
        with ZipFile(self.archive) as archive:
            self.assertEqual(archive.read(f'uploads/pdfs/{name}'), content)
            self.assertNotIn('.env', ' '.join(archive.namelist()))
        with Session(self.engine) as session:
            session.add(Video(youtube_id='later', url='https://example.test', title='Later'))
            session.commit()
        (self.pdfs / name).write_bytes(b'changed current PDF')
        result = self.service.restore(self.archive, summary['archive_sha256'])
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 1)
        self.assertEqual(self._value('SELECT COUNT(*) FROM reviewevent'), 1)
        with closing(sqlite3.connect(self.service.database)) as connection:
            self.assertEqual(connection.execute('SELECT id, vocabulary_id, rating, reviewed_at, interval_days FROM reviewevent ORDER BY id').fetchall(), original_reviews)
        self.assertEqual(self._value('SELECT COUNT(*) FROM studyactivity'), 1)
        self.assertEqual(self._value('SELECT chatgpt_feedback FROM writingsession'), 'Improve cohesion')
        self.assertEqual(self._value('SELECT content FROM notebooknote'), 'Present perfect')
        self.assertEqual((self.pdfs / name).read_bytes(), content)
        self.assertFalse(self.service.journal.exists())
        safety = self.root / 'safety' / result['safety_backup']
        self.assertTrue(safety.is_file())
        self.assertEqual(self.service.validate(safety, self.root / 'safety-staged')['counts']['video'], 2)

    def test_invalid_archives_are_rejected_without_changing_live_data(self):
        self._populate()
        self.service.create(self.archive)
        with ZipFile(self.archive) as source:
            manifest = json.loads(source.read('manifest.json'))
            entries = {name: source.read(name) for name in source.namelist() if name != 'manifest.json'}
        for label, mutate in [
            ('checksum', lambda m, e: m['files'][0].update(sha256='0' * 64)),
            ('version', lambda m, e: m.update(format_version=999)),
            ('schema', lambda m, e: m.update(schema_version=999)),
            ('missing', lambda m, e: e.pop('database.sqlite3')),
            ('traversal', lambda m, e: e.update({'../escape': b'bad'})),
            ('bomb', lambda m, e: m['files'][0].update(size=backup_module.MAX_EXPANDED_BYTES + 1)),
        ]:
            with self.subTest(label=label):
                copy = json.loads(json.dumps(manifest))
                contents = dict(entries)
                mutate(copy, contents)
                malformed = self.root / f'{label}.zip'
                with ZipFile(malformed, 'w', ZIP_DEFLATED) as archive:
                    for name, data in contents.items():
                        archive.writestr(name, data)
                    archive.writestr('manifest.json', json.dumps(copy))
                with self.assertRaises(BackupError):
                    self.service.validate(malformed, self.root / f'stage-{label}')
        broken = self.root / 'broken.zip'
        broken.write_bytes(b'not a zip')
        with self.assertRaises(BackupError):
            self.service.validate(broken, self.root / 'stage-broken')
        corrupt_db = self.root / 'corrupt-db.zip'
        changed = json.loads(json.dumps(manifest))
        entries['database.sqlite3'] = b'not a database'
        database_record = next(item for item in changed['files'] if item['path'] == 'database.sqlite3')
        database_record.update(size=len(entries['database.sqlite3']), sha256=hashlib.sha256(entries['database.sqlite3']).hexdigest())
        with ZipFile(corrupt_db, 'w', ZIP_DEFLATED) as archive:
            for name, data in entries.items(): archive.writestr(name, data)
            archive.writestr('manifest.json', json.dumps(changed))
        with self.assertRaises(BackupError):
            self.service.validate(corrupt_db, self.root / 'stage-corrupt-db')
        symlink = self.root / 'symlink.zip'
        with ZipFile(symlink, 'w', ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                if name == 'database.sqlite3':
                    info = ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (0o120777 << 16)
                    archive.writestr(info, data)
                else:
                    archive.writestr(name, data)
            archive.writestr('manifest.json', json.dumps(changed))
        with self.assertRaises(BackupError):
            self.service.validate(symlink, self.root / 'stage-symlink')
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 1)
        self.assertFalse(list((self.root / 'safety').glob('*.zip')) if (self.root / 'safety').exists() else False)

    def test_restore_failure_recovers_current_data(self):
        self._populate()
        self.service.create(self.archive)
        inspected = self.service.validate(self.archive, self.root / 'inspected')
        with Session(self.engine) as session:
            session.add(Video(youtube_id='later', url='https://example.test', title='Later'))
            session.commit()
        with patch.object(self.service, '_apply', side_effect=RuntimeError('simulated interruption')):
            with self.assertRaisesRegex(BackupError, 'previous data was recovered'):
                self.service.restore(self.archive, inspected['archive_sha256'])
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 2)
        self.assertFalse(self.service.journal.exists())
        self.assertEqual(len(list((self.root / 'safety').glob('*.zip'))), 1)

    def test_recovery_after_data_replacement_restores_previous_state(self):
        name, _ = self._populate()
        self.service.create(self.archive)
        inspected = self.service.validate(self.archive, self.root / 'inspected')
        with Session(self.engine) as session:
            session.add(Video(youtube_id='later', url='https://example.test', title='Later'))
            session.commit()
        (self.pdfs / name).write_bytes(b'current changed PDF')
        apply = self.service._apply
        def interrupted(staging, old_dir):
            apply(staging, old_dir)
            raise RuntimeError('simulated crash after replacement')
        with patch.object(self.service, '_apply', side_effect=interrupted):
            with self.assertRaisesRegex(BackupError, 'previous data was recovered'):
                self.service.restore(self.archive, inspected['archive_sha256'])
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 2)
        self.assertEqual((self.pdfs / name).read_bytes(), b'current changed PDF')
        self.assertFalse(self.service.journal.exists())

    def test_interrupted_restore_is_recovered_before_next_start(self):
        self._populate()
        self.service.create(self.archive)
        with Session(self.engine) as session:
            session.add(Video(youtube_id='later', url='https://example.test', title='Later'))
            session.commit()
        safety = self.root / 'safety' / 'before.zip'
        self.service.create(safety)
        staging = self.root / 'interrupted-stage'
        self.service.validate(self.archive, staging)
        old_dir = self.pdfs.parent / '.pdfs-before-restore-test'
        self.service._write_journal(safety, old_dir)
        self.service._apply(staging, old_dir)
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 1)
        self.service.recover_if_needed()
        self.assertEqual(self._value('SELECT COUNT(*) FROM video'), 2)
        self.assertFalse(self.service.journal.exists())

    def test_backup_routes_are_local_and_confirmation_is_required(self):
        app = FastAPI()
        app.add_middleware(BackupGate)
        app.include_router(backups.router)
        original = backups.service
        backups.service = self.service
        try:
            with TestClient(app, base_url='http://127.0.0.1:8001') as client:
                self.assertEqual(client.post('/api/backups/create', headers={'Origin': 'https://elsewhere.example'}).status_code, 403)
                self.assertEqual(client.post('/api/backups/create', headers={'X-Forwarded-For': '100.101.1.1'}).status_code, 403)
                created = client.post('/api/backups/create', headers={'Origin': 'http://127.0.0.1:5173'})
                self.assertEqual(created.status_code, 200)
                self.assertTrue(created.content.startswith(b'PK'))
                inspected = client.post('/api/backups/inspect', files={'file': ('backup.zip', created.content, 'application/zip')})
                self.assertEqual(inspected.status_code, 200)
                denied = client.post('/api/backups/restore', files={'file': ('backup.zip', created.content, 'application/zip')},
                                     data={'expected_hash': inspected.json()['archive_sha256'], 'confirmation': 'NO'})
                self.assertEqual(denied.status_code, 400)
        finally:
            backups.service = original


class BackupGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_backup_waits_for_active_request_and_other_backup(self):
        entered = []
        release = asyncio.Event()

        async def app(scope, receive, send):
            entered.append(scope['path'])
            if scope['path'] == '/api/videos':
                await release.wait()
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})

        gate = BackupGate(app)
        headers = [(b'host', b'127.0.0.1:8001'), (b'origin', b'http://127.0.0.1:5173')]

        async def request(path):
            scope = {'type': 'http', 'path': path, 'headers': headers, 'client': ('127.0.0.1', 50000)}
            async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message): pass
            await gate(scope, receive, send)

        first = asyncio.create_task(request('/api/videos'))
        await asyncio.sleep(0)
        backup = asyncio.create_task(request('/api/backups/create'))
        await asyncio.sleep(0)
        self.assertEqual(entered, ['/api/videos'])
        release.set()
        await asyncio.wait_for(asyncio.gather(first, backup), 2)
        self.assertEqual(entered, ['/api/videos', '/api/backups/create'])

    async def test_two_backup_operations_do_not_overlap(self):
        entered = []
        release = asyncio.Event()

        async def app(scope, receive, send):
            entered.append(scope['path'])
            if scope['path'] == '/api/backups/create':
                await release.wait()
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})

        gate = BackupGate(app)
        async def run(path):
            scope = {'type': 'http', 'path': path, 'client': ('127.0.0.1', 50000),
                     'headers': [(b'host', b'127.0.0.1:8001')]}
            async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message): pass
            await gate(scope, receive, send)

        create = asyncio.create_task(run('/api/backups/create'))
        await asyncio.sleep(0)
        restore = asyncio.create_task(run('/api/backups/restore'))
        await asyncio.sleep(0)
        self.assertEqual(entered, ['/api/backups/create'])
        release.set()
        await asyncio.wait_for(asyncio.gather(create, restore), 2)
        self.assertEqual(entered, ['/api/backups/create', '/api/backups/restore'])


if __name__ == '__main__':
    unittest.main()
