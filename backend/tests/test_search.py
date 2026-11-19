import io
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import (Notebook, NotebookNote, PDFDocument, PDFNote, TranscriptSegment, Video, VideoNote,
                        VocabularyItem)
from app.routers import search as search_router
from app.services.backups import BackupService
from app.services.search_index import ensure_index, search
from tests.test_pdfs import sample_pdf


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf_dir = self.root / 'pdfs'
        self.pdf_dir.mkdir()
        self.engine = create_engine(f'sqlite:///{(self.root / "data.db").as_posix()}')
        SQLModel.metadata.create_all(self.engine)
        self.fts = ensure_index(self.engine, self.pdf_dir)
        app = FastAPI()
        app.include_router(search_router.router)
        self.old_pdf_dir = search_router.PDF_STORAGE_DIR
        search_router.PDF_STORAGE_DIR = self.pdf_dir
        def session_override():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = session_override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        search_router.PDF_STORAGE_DIR = self.old_pdf_dir
        self.engine.dispose()
        self.temp.cleanup()

    def results(self, q, group='all'):
        response = self.client.get('/api/search', params={'q': q, 'type': group})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['groups']

    def test_all_sources_and_navigation(self):
        data = sample_pdf()
        filename = f'{uuid4().hex}.pdf'
        (self.pdf_dir / filename).write_bytes(data)
        with Session(self.engine) as session:
            video = Video(youtube_id='climate123', url='https://youtube.com/watch?v=climate123', title='Climate change')
            session.add(video); session.flush()
            session.add(VideoNote(video_id=video.id, content='greenhouse effect'))
            session.add(TranscriptSegment(video_id=video.id, text='A sustainable environment', start=272))
            pdf = PDFDocument(title='IELTS Reading Book', original_filename='reading.pdf', stored_filename=filename,
                              file_size_bytes=len(data), total_pages=2)
            session.add(pdf); session.flush()
            session.add(PDFNote(pdf_id=pdf.id, content='Exam strategy'))
            notebook = Notebook(name='Environment Notebook')
            session.add(notebook); session.flush()
            session.add(NotebookNote(notebook_id=notebook.id, title='Grammar', content='**Environmental** vocabulary'))
            session.add(VocabularyItem(text='ecology', meaning='Study of the environment', example_sentence='Protect the environment.', personal_note='Remember this'))
            session.commit()
            video_id, pdf_id, notebook_id = video.id, pdf.id, notebook.id
        ensure_index(self.engine, self.pdf_dir)
        self.assertEqual(self.results('ecology', 'vocabulary')['vocabulary'][0]['url'], '/vocabulary?item=1')
        self.assertTrue(self.results('Study of the environment', 'vocabulary')['vocabulary'])
        self.assertTrue(self.results('Protect the environment', 'vocabulary')['vocabulary'])
        self.assertTrue(self.results('Remember this', 'vocabulary')['vocabulary'])
        self.assertTrue(self.results('Climate', 'videos')['videos'])
        transcript = next(item for item in self.results('sustainable', 'videos')['videos'] if item['kind'] == 'transcript')
        self.assertEqual(transcript['url'], f'/videos/{video_id}?t=272&segment={transcript["id"]}')
        self.assertEqual(transcript['location'], '4:32')
        self.assertTrue(self.results('greenhouse', 'videos')['videos'])
        self.assertTrue(self.results('Reading Book', 'pdfs')['pdfs'])
        page = next(item for item in self.results('Practice page 2', 'pdfs')['pdfs'] if item['kind'] == 'pdf_page')
        self.assertEqual(page['url'], f'/pdfs/{pdf_id}?page=2')
        self.assertTrue(self.results('Exam strategy', 'pdfs')['pdfs'])
        self.assertTrue(self.results('Environment Notebook', 'notebook')['notebook'])
        note = next(item for item in self.results('Environmental', 'notebook')['notebook'] if item['kind'] == 'notebook_note')
        self.assertEqual(note['url'], f'/notebook/{notebook_id}/{note["id"]}')
        self.assertEqual(self.results('unlikely search text')['vocabulary'], [])
        with Session(self.engine) as session:
            session.delete(session.exec(select(PDFNote).where(PDFNote.pdf_id == pdf_id)).first())
            session.delete(session.get(PDFDocument, pdf_id))
            session.commit()
        self.assertFalse(self.results('Practice page 2', 'pdfs')['pdfs'])
        self.assertFalse(self.results('Reading Book', 'pdfs')['pdfs'])

    def test_updates_deletes_unicode_and_pagination(self):
        with Session(self.engine) as session:
            notebook = Notebook(name='Türkçe')
            session.add(notebook); session.flush()
            note = NotebookNote(notebook_id=notebook.id, title='Old title', content='old content')
            session.add(note)
            for number in range(12): session.add(VocabularyItem(text=f'focus {number}'))
            session.commit()
            note_id = note.id
        self.assertTrue(self.results('Türkçe', 'notebook')['notebook'])
        self.assertTrue(self.results('old content', 'notebook')['notebook'])
        with Session(self.engine) as session:
            note = session.get(NotebookNote, note_id)
            note.title = 'New title'; note.content = 'fresh markdown'
            session.add(note); session.commit()
        self.assertFalse(self.results('old content', 'notebook')['notebook'])
        self.assertTrue(self.results('fresh markdown', 'notebook')['notebook'])
        with Session(self.engine) as session:
            destination = Notebook(name='Moved')
            session.add(destination); session.flush()
            moved_id = destination.id
            note = session.get(NotebookNote, note_id)
            note.notebook_id = moved_id
            session.add(note); session.commit()
        self.assertEqual(self.results('fresh markdown', 'notebook')['notebook'][0]['url'], f'/notebook/{moved_id}/{note_id}')
        with Session(self.engine) as session:
            session.delete(session.get(NotebookNote, note_id))
            session.commit()
        self.assertFalse(self.results('fresh markdown', 'notebook')['notebook'])
        first = self.client.get('/api/search', params={'q': 'focus', 'type': 'vocabulary', 'limit': 5, 'offset': 0}).json()
        second = self.client.get('/api/search', params={'q': 'focus', 'type': 'vocabulary', 'limit': 5, 'offset': 5}).json()
        self.assertTrue(first['has_more']['vocabulary'])
        self.assertEqual(len(first['groups']['vocabulary']), 5)
        self.assertFalse({item['id'] for item in first['groups']['vocabulary']} & {item['id'] for item in second['groups']['vocabulary']})
        self.assertEqual(self.client.get('/api/search', params={'q': 'x' * 201}).status_code, 422)
        self.assertEqual(self.client.get('/api/search', params={'q': 'focus', 'type': 'invalid'}).status_code, 422)
        self.assertEqual(self.client.get('/api/search', params={'q': '" OR *'}).status_code, 200)

    def test_scanned_pdf_and_deleted_pdf(self):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        stream = io.BytesIO(); writer.write(stream)
        data = stream.getvalue()
        filename = f'{uuid4().hex}.pdf'
        (self.pdf_dir / filename).write_bytes(data)
        with Session(self.engine) as session:
            pdf = PDFDocument(title='Scanned Workbook', original_filename='scan.pdf', stored_filename=filename,
                              file_size_bytes=len(data), total_pages=1)
            session.add(pdf); session.commit(); pdf_id = pdf.id
        ensure_index(self.engine, self.pdf_dir)
        self.assertTrue(self.results('Scanned', 'pdfs')['pdfs'])
        self.assertFalse(self.results('nonexistent page text', 'pdfs')['pdfs'])
        with Session(self.engine) as session:
            session.delete(session.get(PDFDocument, pdf_id)); session.commit()
        self.assertFalse(self.results('Scanned', 'pdfs')['pdfs'])

    def test_video_edit_and_delete_refresh_index(self):
        with Session(self.engine) as session:
            video = Video(youtube_id='update123', url='https://example.test', title='Original video')
            session.add(video); session.flush()
            segment = TranscriptSegment(video_id=video.id, text='First transcript', start=10)
            session.add(segment); session.commit()
            video_id, segment_id = video.id, segment.id
        self.assertTrue(self.results('Original', 'videos')['videos'])
        self.assertTrue(self.results('First transcript', 'videos')['videos'])
        with Session(self.engine) as session:
            video = session.get(Video, video_id); video.title = 'Revised video'; session.add(video)
            segment = session.get(TranscriptSegment, segment_id); segment.text = 'Second transcript'; session.add(segment)
            session.commit()
        self.assertFalse(self.results('Original', 'videos')['videos'])
        self.assertFalse(self.results('First transcript', 'videos')['videos'])
        self.assertTrue(self.results('Second transcript', 'videos')['videos'])
        with Session(self.engine) as session:
            session.delete(session.get(TranscriptSegment, segment_id))
            session.delete(session.get(Video, video_id))
            session.commit()
        self.assertFalse(self.results('Second transcript', 'videos')['videos'])

    def test_plain_sqlite_fallback(self):
        fallback = create_engine(f'sqlite:///{(self.root / "fallback.db").as_posix()}')
        try:
            SQLModel.metadata.create_all(fallback)
            with fallback.begin() as connection:
                connection.exec_driver_sql('CREATE TABLE search_entries (kind TEXT, entity_id INTEGER, parent_id INTEGER, location TEXT, title TEXT, body TEXT)')
            self.assertFalse(ensure_index(fallback, self.pdf_dir))
            with Session(fallback) as session:
                session.add(VocabularyItem(text='fallback', meaning='local SQLite search'))
                session.commit()
            self.assertEqual(search(fallback, 'SQLite', 'vocabulary', 8, 0, False)['groups']['vocabulary'][0]['title'], 'fallback')
        finally:
            fallback.dispose()

    def test_backup_restore_preserves_or_rebuilds_index(self):
        with Session(self.engine) as session:
            session.add(VocabularyItem(text='recoverable', meaning='Saved in backup'))
            session.commit()
        backup = BackupService(self.engine, self.pdf_dir, self.root / 'safety', self.root / 'state')
        archive = self.root / 'backup.zip'
        backup.create(archive)
        with ZipFile(archive) as zip_file:
            snapshot = self.root / 'portable.db'
            snapshot.write_bytes(zip_file.read('database.sqlite3'))
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='search_entries'").fetchone())
        digest = backup.validate(archive, self.root / 'inspect')['archive_sha256']
        with Session(self.engine) as session:
            item = session.exec(select(VocabularyItem)).first()
            session.delete(item); session.commit()
        self.assertFalse(self.results('recoverable', 'vocabulary')['vocabulary'])
        backup.restore(archive, digest)
        ensure_index(self.engine, self.pdf_dir)
        self.assertTrue(self.results('recoverable', 'vocabulary')['vocabulary'])


if __name__ == '__main__':
    unittest.main()
