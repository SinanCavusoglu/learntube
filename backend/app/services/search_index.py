"""One local search index for LearnTube records and extracted PDF pages."""

from __future__ import annotations

import re
import threading
import json
import tempfile
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.engine import Engine

_lock = threading.RLock()
_pdf_name = re.compile(r'^[a-f0-9]{32}\.pdf$')
_specs = [
    ('vocabulary', 'vocabularyitem', 'new.id', "''", 'new.text', "coalesce(new.meaning,'') || ' ' || coalesce(new.example_sentence,'') || ' ' || coalesce(new.personal_note,'')"),
    ('video', 'video', 'new.id', "''", 'new.title', "''"),
    ('video_note', 'videonote', 'new.video_id', "''", "''", 'new.content'),
    ('transcript', 'transcriptsegment', 'new.video_id', "coalesce(new.start,'')", "''", 'new.text'),
    ('pdf', 'pdfdocument', 'new.id', "''", 'new.title', 'new.original_filename'),
    ('pdf_note', 'pdfnote', 'new.pdf_id', "''", "''", 'new.content'),
    ('pdf_page', 'pdf_search_page', 'new.pdf_id', 'new.page_number', "''", 'new.content'),
    ('notebook', 'notebook', 'new.id', "''", 'new.name', 'new.description'),
    ('notebook_note', 'notebooknote', 'new.notebook_id', "''", 'new.title', 'new.content'),
]


def _schema(engine: Engine) -> bool:
    """Create derived tables/triggers; return whether FTS5 is available."""
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS pdf_search_page (id INTEGER PRIMARY KEY, pdf_id INTEGER NOT NULL, page_number INTEGER NOT NULL, content TEXT NOT NULL, UNIQUE(pdf_id,page_number))')
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_pdf_search_page_pdf ON pdf_search_page(pdf_id)')
        connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS pdf_search_state (pdf_id INTEGER PRIMARY KEY, file_size_bytes INTEGER NOT NULL, status TEXT NOT NULL)')
        connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        existed = connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='search_entries'").first() is not None
        if not existed:
            try:
                connection.exec_driver_sql("CREATE VIRTUAL TABLE search_entries USING fts5(kind UNINDEXED, entity_id UNINDEXED, parent_id UNINDEXED, location UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')")
            except Exception as exc:
                if 'no such module' not in str(exc).lower():
                    raise
                connection.exec_driver_sql('CREATE TABLE search_entries (kind TEXT NOT NULL, entity_id INTEGER NOT NULL, parent_id INTEGER NOT NULL, location TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL)')
                connection.exec_driver_sql('CREATE INDEX ix_search_entries_kind ON search_entries(kind)')
        mode = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='search_entries'").scalar_one().upper()
        fts = 'VIRTUAL TABLE' in mode
        for kind, table, parent, location, title, body in _specs:
            values = f"'{kind}',new.id,{parent},{location},{title},{body}"
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{table}_ai AFTER INSERT ON {table} BEGIN INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) VALUES({values}); END")
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{table}_au AFTER UPDATE ON {table} BEGIN DELETE FROM search_entries WHERE kind='{kind}' AND entity_id=old.id; INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) VALUES({values}); END")
            extra = ' DELETE FROM pdf_search_page WHERE pdf_id=old.id; DELETE FROM pdf_search_state WHERE pdf_id=old.id;' if table == 'pdfdocument' else ''
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{table}_ad AFTER DELETE ON {table} BEGIN DELETE FROM search_entries WHERE kind='{kind}' AND entity_id=old.id;{extra} END")
        for kind, parent, position in (('video_bookmark', 'video_id', 'timestamp_seconds'),
                                       ('pdf_bookmark', 'pdf_id', 'page_number')):
            values = f"'{kind}',new.id,new.{parent},coalesce(new.{position},''),new.title,new.note"
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{kind}_ai AFTER INSERT ON bookmark WHEN new.{parent} IS NOT NULL BEGIN INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) VALUES({values}); END")
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{kind}_au AFTER UPDATE ON bookmark BEGIN DELETE FROM search_entries WHERE kind='{kind}' AND entity_id=old.id; INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) SELECT {values} WHERE new.{parent} IS NOT NULL; END")
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS search_{kind}_ad AFTER DELETE ON bookmark BEGIN DELETE FROM search_entries WHERE kind='{kind}' AND entity_id=old.id; END")
        version = connection.exec_driver_sql("SELECT value FROM search_meta WHERE key='version'").scalar()
        if not existed or version != '2':
            connection.exec_driver_sql('DELETE FROM search_entries')
            for kind, table, parent, location, title, body in _specs:
                def old(expression: str) -> str:
                    return expression.replace('new.', 'source.')
                connection.exec_driver_sql(f"INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) SELECT '{kind}',source.id,{old(parent)},{old(location)},{old(title)},{old(body)} FROM {table} AS source")
            for kind, parent, position in (('video_bookmark', 'video_id', 'timestamp_seconds'),
                                           ('pdf_bookmark', 'pdf_id', 'page_number')):
                connection.exec_driver_sql(f"INSERT INTO search_entries(kind,entity_id,parent_id,location,title,body) SELECT '{kind}',id,{parent},coalesce({position},''),title,note FROM bookmark WHERE {parent} IS NOT NULL")
            connection.exec_driver_sql("INSERT OR REPLACE INTO search_meta(key,value) VALUES('version','2')")
        return fts


def index_pdf(engine: Engine, pdf_id: int, path: Path, expected_size: int) -> None:
    """Extract page text once; a failed extraction leaves the original PDF untouched."""
    status = 'indexed'
    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as staged:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
                raise ValueError('PDF file is unavailable')
            reader = PdfReader(path, strict=False)
            try:
                for page_number, page in enumerate(reader.pages, 1):
                    try:
                        content = re.sub(r'\s+', ' ', page.extract_text() or '').strip()[:100_000]
                        if content:
                            staged.write(json.dumps([page_number, content], ensure_ascii=False) + '\n')
                    except Exception:
                        continue
            finally:
                reader.close()
        except Exception:
            status = 'unavailable'
        staged.seek(0)
        if status == 'indexed' and (not path.is_file() or path.stat().st_size != expected_size):
            status = 'unavailable'
        with engine.connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                current = connection.exec_driver_sql('SELECT file_size_bytes FROM pdfdocument WHERE id=?', (pdf_id,)).first()
                if not current or current[0] != expected_size:
                    connection.rollback()
                    return
                connection.exec_driver_sql('DELETE FROM pdf_search_page WHERE pdf_id=?', (pdf_id,))
                if status == 'indexed':
                    for line in staged:
                        number, content = json.loads(line)
                        connection.exec_driver_sql('INSERT INTO pdf_search_page(pdf_id,page_number,content) VALUES(?,?,?)', (pdf_id, number, content))
                connection.exec_driver_sql('INSERT OR REPLACE INTO pdf_search_state(pdf_id,file_size_bytes,status) VALUES(?,?,?)', (pdf_id, expected_size, status))
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def ensure_index(engine: Engine, pdf_dir: Path, retry_failed: bool = False) -> bool:
    with _lock:
        fts = _schema(engine)
        with engine.connect() as connection:
            pending = connection.exec_driver_sql('''SELECT d.id,d.stored_filename,d.file_size_bytes FROM pdfdocument d
                LEFT JOIN pdf_search_state s ON s.pdf_id=d.id
                WHERE s.pdf_id IS NULL OR s.file_size_bytes != d.file_size_bytes OR (?=1 AND s.status!='indexed')''',
                (int(retry_failed),)).all()
        for pdf_id, filename, size in pending:
            if isinstance(filename, str) and _pdf_name.fullmatch(filename):
                index_pdf(engine, pdf_id, pdf_dir / filename, size)
        return fts


def _snippet(title: str, body: str, terms: list[str]) -> str:
    text = body if any(term.casefold() in body.casefold() for term in terms) else title or body
    text = re.sub(r'\s+', ' ', text).strip()
    folded = text.casefold()
    hits = [folded.find(term.casefold()) for term in terms]
    first = min((hit for hit in hits if hit >= 0), default=0)
    start = max(0, first - 45)
    end = min(len(text), start + 160)
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


def search(engine: Engine, query: str, selected_type: str, limit: int, offset: int, fts: bool) -> dict:
    terms = re.findall(r'\w+', query, flags=re.UNICODE)
    groups = {'vocabulary': [], 'videos': [], 'pdfs': [], 'notebook': []}
    more = {key: False for key in groups}
    if not terms:
        return {'groups': groups, 'has_more': more}
    match = ' AND '.join('"' + term.replace('"', '""') + '"*' for term in terms[:12])
    kinds = {
        'vocabulary': ('vocabulary',),
        'videos': ('video', 'video_note', 'transcript', 'video_bookmark'),
        'pdfs': ('pdf', 'pdf_note', 'pdf_page', 'pdf_bookmark'),
        'notebook': ('notebook', 'notebook_note'),
    }
    with engine.connect() as connection:
        for group, accepted in kinds.items():
            if selected_type not in {'all', group}:
                continue
            placeholders = ','.join('?' for _ in accepted)
            if fts:
                sql = f'SELECT kind,entity_id,parent_id,location,title,body FROM search_entries WHERE search_entries MATCH ? AND kind IN ({placeholders}) ORDER BY bm25(search_entries) LIMIT ? OFFSET ?'
                params = (match, *accepted, limit + 1, offset)
            else:
                conditions = ' AND '.join("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')" for _ in terms[:12])
                sql = f'SELECT kind,entity_id,parent_id,location,title,body FROM search_entries WHERE kind IN ({placeholders}) AND {conditions} LIMIT ? OFFSET ?'
                patterns = [value for term in terms[:12] for value in (f"%{term.replace('%', r'\%').replace('_', r'\_')}%",) * 2]
                params = (*accepted, *patterns, limit + 1, offset)
            rows = connection.exec_driver_sql(sql, params).all()
            more[group] = len(rows) > limit
            for kind, entity_id, parent_id, location, title, body in rows[:limit]:
                title = title or ''
                body = body or ''
                if kind in {'video_note', 'transcript'}:
                    parent = connection.exec_driver_sql('SELECT title FROM video WHERE id=?', (parent_id,)).first()
                    if not parent: continue
                    title = parent[0]
                elif kind in {'pdf_note', 'pdf_page'}:
                    parent = connection.exec_driver_sql('SELECT title FROM pdfdocument WHERE id=?', (parent_id,)).first()
                    if not parent: continue
                    title = parent[0]
                elif kind in {'video_bookmark', 'pdf_bookmark'}:
                    table = 'video' if kind == 'video_bookmark' else 'pdfdocument'
                    parent = connection.exec_driver_sql(f'SELECT title FROM {table} WHERE id=?', (parent_id,)).first()
                    if not parent: continue
                elif kind == 'notebook_note':
                    parent = connection.exec_driver_sql('SELECT name FROM notebook WHERE id=?', (parent_id,)).first()
                    if not parent: continue
                timestamp = float(location) if kind in {'transcript', 'video_bookmark'} and location not in ('', None) else None
                page = int(location) if kind in {'pdf_page', 'pdf_bookmark'} and location not in ('', None) else None
                vocabulary_status = None
                if kind == 'vocabulary':
                    row = connection.exec_driver_sql('SELECT status FROM vocabularyitem WHERE id=?', (entity_id,)).first()
                    if not row: continue
                    vocabulary_status = row[0].title()
                url = (f'/vocabulary?item={entity_id}' if group == 'vocabulary' else
                       f'/videos/{parent_id}' + (f'?t={timestamp:g}&segment={entity_id}' if kind == 'transcript' and timestamp is not None else f'?t={timestamp:g}' if timestamp is not None else '') if group == 'videos' else
                       f'/pdfs/{parent_id}' + (f'?page={page}' if page is not None else '') if group == 'pdfs' else
                       f'/notebook/{parent_id}/{entity_id}' if kind == 'notebook_note' else f'/notebook/{entity_id}')
                groups[group].append({'id': entity_id, 'kind': kind, 'type': group, 'title': title,
                                      'snippet': _snippet(title, body, terms), 'location':
                                      (f'{parent[0]} · ' if kind == 'video_bookmark' else '') + f'{timestamp // 60:.0f}:{timestamp % 60:02.0f}' if timestamp is not None else
                                      (f'{parent[0]} · ' if kind == 'pdf_bookmark' else '') + f'Page {page}' if page is not None else
                                      vocabulary_status if vocabulary_status is not None else
                                      parent[0] if kind == 'notebook_note' else kind.replace('_', ' ').title(),
                                      'url': url, 'page': page, 'timestamp': timestamp})
    return {'groups': groups, 'has_more': more}
