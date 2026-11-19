import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import Bookmark, Notebook, PDFDocument, Video, VocabularyItem, WritingSession
from app.routers import bookmarks, pdfs, videos
from app.services.backups import BackupService
from app.services.search_index import ensure_index, search


class BookmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(f'sqlite:///{(self.root / "data.db").as_posix()}')
        SQLModel.metadata.create_all(self.engine)
        self.pdf_dir = self.root / 'pdfs'
        self.pdf_dir.mkdir()
        self.old_pdf_dir = pdfs.PDF_STORAGE_DIR
        pdfs.PDF_STORAGE_DIR = self.pdf_dir
        app = FastAPI()
        app.include_router(bookmarks.router)
        app.include_router(videos.router)
        app.include_router(pdfs.router)
        def session_override():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = session_override
        self.client = TestClient(app)
        with Session(self.engine) as session:
            video = Video(youtube_id='bookmark123', url='https://example.test', title='IELTS Video')
            pdf = PDFDocument(title='IELTS PDF', original_filename='book.pdf', stored_filename=f'{uuid4().hex}.pdf',
                              file_size_bytes=0, total_pages=30)
            session.add(video); session.add(pdf)
            session.add(VocabularyItem(text='preserved'))
            session.add(Notebook(name='Saved notes'))
            session.add(WritingSession(task_type=2, question='Prompt'))
            session.commit()
            self.video_id, self.pdf_id = video.id, pdf.id
            (self.pdf_dir / pdf.stored_filename).write_bytes(b'')

    def tearDown(self):
        self.client.close()
        pdfs.PDF_STORAGE_DIR = self.old_pdf_dir
        self.engine.dispose()
        self.temp.cleanup()

    def add_video(self, seconds=512, title='Present Perfect'):
        return self.client.post(f'/api/videos/{self.video_id}/bookmarks', json={'timestamp_seconds': seconds, 'title': title, 'note': 'Review later'})

    def add_pdf(self, page=12, title='Matching Headings'):
        return self.client.post(f'/api/pdfs/{self.pdf_id}/bookmarks', json={'page_number': page, 'title': title, 'note': 'Exam practice'})

    def test_create_list_update_delete_and_filters(self):
        video = self.add_video()
        pdf = self.add_pdf()
        self.assertEqual(video.status_code, 201, video.text)
        self.assertEqual(pdf.status_code, 201, pdf.text)
        self.assertEqual(video.json()['timestamp_seconds'], 512)
        self.assertEqual(pdf.json()['page_number'], 12)
        self.assertEqual(video.json()['source_title'], 'IELTS Video')
        self.assertEqual(len(self.client.get(f'/api/videos/{self.video_id}/bookmarks').json()), 1)
        self.assertEqual(len(self.client.get(f'/api/pdfs/{self.pdf_id}/bookmarks').json()), 1)
        self.assertEqual(len(self.client.get('/api/bookmarks').json()), 2)
        self.assertEqual(len(self.client.get('/api/bookmarks?type=video').json()), 1)
        self.assertEqual(len(self.client.get('/api/bookmarks?type=pdf').json()), 1)
        self.assertEqual(len(self.client.get('/api/bookmarks?q=IELTS%20PDF').json()), 1)
        self.assertEqual(len(self.client.get('/api/bookmarks?q=Review%20later').json()), 1)
        changed = self.client.patch(f"/api/bookmarks/{video.json()['id']}", json={'title': 'Important grammar', 'note': 'New note'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()['timestamp_seconds'], 512)
        self.assertEqual(changed.json()['note'], 'New note')
        deleted = self.client.delete(f"/api/bookmarks/{video.json()['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.delete(f"/api/bookmarks/{video.json()['id']}").status_code, 404)
        self.assertEqual(len(self.client.get('/api/bookmarks').json()), 1)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(VocabularyItem)).all()), 1)
            self.assertEqual(len(session.exec(select(Notebook)).all()), 1)
            self.assertEqual(len(session.exec(select(WritingSession)).all()), 1)

    def test_rejects_invalid_positions_sources_titles_and_duplicates(self):
        self.assertEqual(self.add_video(-1).status_code, 422)
        self.assertEqual(self.add_pdf(0).status_code, 422)
        self.assertEqual(self.add_pdf(31).status_code, 422)
        self.assertEqual(self.client.post('/api/videos/99999/bookmarks', json={'timestamp_seconds': 1, 'title': 'Missing'}).status_code, 404)
        self.assertEqual(self.client.post('/api/pdfs/99999/bookmarks', json={'page_number': 1, 'title': 'Missing'}).status_code, 404)
        self.assertEqual(self.add_video(title='   ').status_code, 422)
        self.assertEqual(self.add_pdf(title='   ').status_code, 422)
        self.assertEqual(self.add_video().status_code, 201)
        self.assertEqual(self.add_video().status_code, 409)
        self.assertEqual(self.add_video(title='Second insight').status_code, 201)
        self.assertEqual(self.add_pdf().status_code, 201)
        self.assertEqual(self.add_pdf().status_code, 409)
        self.assertEqual(self.client.get('/api/bookmarks?type=other').status_code, 422)

    def test_source_deletion_removes_only_its_bookmarks(self):
        self.add_video()
        self.add_pdf()
        self.assertEqual(self.client.delete(f'/api/videos/{self.video_id}').status_code, 204)
        remaining = self.client.get('/api/bookmarks').json()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['type'], 'pdf')
        self.assertEqual(self.client.delete(f'/api/pdfs/{self.pdf_id}').status_code, 204)
        self.assertEqual(self.client.get('/api/bookmarks').json(), [])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(VocabularyItem)).all()), 1)

    def test_global_search_updates_with_bookmarks(self):
        self.assertTrue(ensure_index(self.engine, self.pdf_dir))
        video = self.add_video(title='Useful grammar')
        pdf = self.add_pdf(title='Reading strategy')
        video_result = next(item for item in search(self.engine, 'Useful grammar', 'videos', 8, 0, True)['groups']['videos'] if item['kind'] == 'video_bookmark')
        self.assertEqual(video_result['url'], f'/videos/{self.video_id}?t=512')
        pdf_result = next(item for item in search(self.engine, 'Reading strategy', 'pdfs', 8, 0, True)['groups']['pdfs'] if item['kind'] == 'pdf_bookmark')
        self.assertEqual(pdf_result['url'], f'/pdfs/{self.pdf_id}?page=12')
        self.client.patch(f"/api/bookmarks/{video.json()['id']}", json={'title': 'Updated grammar', 'note': 'A new insight'})
        self.assertFalse(search(self.engine, 'Useful grammar', 'videos', 8, 0, True)['groups']['videos'])
        self.assertTrue(search(self.engine, 'Updated grammar', 'videos', 8, 0, True)['groups']['videos'])
        self.client.delete(f"/api/bookmarks/{pdf.json()['id']}")
        self.assertFalse(search(self.engine, 'Reading strategy', 'pdfs', 8, 0, True)['groups']['pdfs'])

    def test_backup_restore_preserves_sources_and_bookmarks(self):
        pdf_file = self.pdf_dir / self.client.get('/api/pdfs').json()[0]['stored_filename']
        pdf_file.write_bytes(b'%PDF-test')
        with Session(self.engine) as session:
            document = session.get(PDFDocument, self.pdf_id)
            document.file_size_bytes = pdf_file.stat().st_size
            session.add(document); session.commit()
        self.add_video(title='Backup video note')
        self.add_pdf(title='Backup PDF note')
        backup = BackupService(self.engine, self.pdf_dir, self.root / 'safety', self.root / 'state')
        archive = self.root / 'backup.zip'
        backup.create(archive)
        digest = backup.validate(archive, self.root / 'inspect')['archive_sha256']
        with Session(self.engine) as session:
            for bookmark in session.exec(select(Bookmark)).all(): session.delete(bookmark)
            session.commit()
        self.assertEqual(self.client.get('/api/bookmarks').json(), [])
        backup.restore(archive, digest)
        restored = self.client.get('/api/bookmarks').json()
        self.assertEqual({item['title'] for item in restored}, {'Backup video note', 'Backup PDF note'})
        self.assertEqual({item['note'] for item in restored}, {'Review later', 'Exam practice'})
        self.assertEqual({item['source_title'] for item in restored}, {'IELTS Video', 'IELTS PDF'})
        self.assertEqual(len(self.client.get(f'/api/videos/{self.video_id}/bookmarks').json()), 1)
        self.assertEqual(len(self.client.get(f'/api/pdfs/{self.pdf_id}/bookmarks').json()), 1)

    def test_old_backup_without_bookmark_table_restores_and_migrates(self):
        old_path = self.root / 'old.db'
        old_engine = create_engine(f'sqlite:///{old_path.as_posix()}')
        try:
            SQLModel.metadata.create_all(old_engine, tables=[table for table in SQLModel.metadata.tables.values() if table.name != 'bookmark'])
            with Session(old_engine) as session:
                session.add(Video(youtube_id='old123', url='https://example.test', title='Old video'))
                session.commit()
            old_service = BackupService(old_engine, self.pdf_dir, self.root / 'old-safety', self.root / 'old-state')
            archive = self.root / 'old.zip'
            old_service.create(archive)
            digest = old_service.validate(archive, self.root / 'old-inspect')['archive_sha256']
        finally:
            old_engine.dispose()
        live_service = BackupService(self.engine, self.pdf_dir, self.root / 'safety', self.root / 'state')
        live_service.restore(archive, digest)
        with closing(sqlite3.connect(self.root / 'data.db')) as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='bookmark'").fetchone())
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM bookmark').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT title FROM video').fetchone()[0], 'Old video')


if __name__ == '__main__':
    unittest.main()
