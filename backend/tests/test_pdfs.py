import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import ReviewEvent, VocabularyItem
from app.routers import dashboard, pdfs, vocabulary


def sample_pdf() -> bytes:
    stream = io.BytesIO()
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
    for index in range(2):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        content = DecodedStreamObject()
        content.set_data(f'BT /F1 24 Tf 72 720 Td (IELTS Reading Practice page {index + 1}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(content)
    writer.write(stream)
    return stream.getvalue()


class PDFTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.old_storage = pdfs.PDF_STORAGE_DIR
        self.old_limit = pdfs.MAX_PDF_SIZE_MB
        pdfs.PDF_STORAGE_DIR = Path(self.temporary.name)
        pdfs.MAX_PDF_SIZE_MB = 1
        app = FastAPI()
        app.include_router(pdfs.router)
        app.include_router(vocabulary.router)
        app.include_router(dashboard.router)
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        pdfs.PDF_STORAGE_DIR = self.old_storage
        pdfs.MAX_PDF_SIZE_MB = self.old_limit
        self.engine.dispose()
        self.temporary.cleanup()

    def upload(self, filename='lesson.pdf', content=None):
        return self.client.post('/api/pdfs/upload', files={'file': (filename, content if content is not None else sample_pdf(), 'application/pdf')})

    def test_upload_range_progress_notes_vocabulary_activity_and_delete(self):
        source = sample_pdf()
        created = self.upload('../../lesson.pdf', source)
        self.assertEqual(created.status_code, 201)
        document = created.json()
        pdf_id = document['id']
        self.assertEqual(document['original_filename'], 'lesson.pdf')
        self.assertEqual(document['total_pages'], 2)
        self.assertEqual(document['reading_progress'], 0)
        self.assertEqual(len(self.client.get('/api/pdfs').json()), 1)
        full = self.client.get(f'/api/pdfs/{pdf_id}/file')
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.content, source)
        partial = self.client.get(f'/api/pdfs/{pdf_id}/file', headers={'Range': 'bytes=0-9'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, source[:10])
        self.assertEqual(partial.headers['content-range'], f'bytes 0-9/{len(source)}')
        progress = self.client.patch(f'/api/pdfs/{pdf_id}/progress', json={'page': 2, 'zoom': 1.2})
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()['reading_progress'], 100)
        self.assertEqual(self.client.get(f'/api/pdfs/{pdf_id}').json()['last_page'], 2)
        self.assertEqual(self.client.patch(f'/api/pdfs/{pdf_id}/progress', json={'page': 3, 'zoom': 1}).status_code, 422)
        self.assertEqual(self.client.put(f'/api/pdfs/{pdf_id}/notes', json={'content': 'My IELTS note'}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/pdfs/{pdf_id}/notes').json()['content'], 'My IELTS note')
        word = self.client.post('/api/vocabulary', json={'text': 'take into account', 'source_pdf_id': pdf_id, 'source_page': 2})
        self.assertEqual(word.status_code, 201)
        item = word.json()
        self.assertEqual(item['source_pdf_title'], 'lesson')
        self.assertEqual(len(self.client.get(f'/api/pdfs/{pdf_id}/vocabulary').json()), 1)
        self.assertEqual(len(self.client.get('/api/vocabulary/review/due').json()), 1)
        with Session(self.engine) as session:
            session.add(ReviewEvent(vocabulary_id=item['id'], rating='good', previous_status='new', next_status='learning', interval_days=1))
            session.commit()
        event_key = str(uuid4())
        activity = {'event_key': event_key, 'client_session_id': str(uuid4()), 'activity_type': 'pdf', 'source_id': pdf_id,
                    'ended_at': datetime.now(timezone.utc).isoformat(), 'duration_seconds': 5}
        self.assertTrue(self.client.post('/api/dashboard/activity', json=activity).json()['recorded'])
        self.assertFalse(self.client.post('/api/dashboard/activity', json=activity).json()['recorded'])
        stats = self.client.get('/api/dashboard?timezone_name=UTC').json()
        self.assertEqual(stats['pdfs']['total'], 1)
        self.assertAlmostEqual(stats['pdfs']['active_seconds'], 5)
        self.assertAlmostEqual(stats['total_seconds'], 5)
        self.assertAlmostEqual(stats['daily'][-1]['pdf'], 5)
        self.assertAlmostEqual(stats['week_seconds'], sum(day['total'] for day in stats['weekly']))
        self.assertEqual(self.client.delete(f'/api/pdfs/{pdf_id}').status_code, 204)
        self.assertEqual(self.client.get(f'/api/pdfs/{pdf_id}/file').status_code, 404)
        saved = self.client.get('/api/vocabulary').json()[0]
        self.assertIsNone(saved['source_pdf_id'])
        self.assertEqual(saved['source_pdf_title'], 'lesson')
        self.assertEqual(saved['source_page'], 2)
        self.assertEqual(len(self.client.get(f'/api/vocabulary/{item["id"]}/reviews').json()), 1)
        self.assertEqual(list(Path(self.temporary.name).glob('*.pdf')), [])

    def test_reject_invalid_malformed_and_oversized_files(self):
        self.assertEqual(self.upload('wrong.txt').status_code, 415)
        self.assertEqual(self.upload('fake.pdf', b'hello').status_code, 415)
        self.assertEqual(self.upload('broken.pdf', b'%PDF-1.7\nnot a real document').status_code, 422)
        self.assertEqual(self.upload('large.pdf', sample_pdf() + b'x' * (1024 * 1024)).status_code, 413)
        self.assertEqual(self.client.get('/api/pdfs').json(), [])
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_vocabulary_sources_remain_independent(self):
        first = self.upload('first.pdf').json()['id']
        second = self.upload('second.pdf').json()['id']
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'conclusion', 'source_pdf_id': first, 'source_page': 1}).status_code, 201)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'conclusion', 'source_pdf_id': second, 'source_page': 2}).status_code, 201)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'conclusion'}).status_code, 201)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'conclusion', 'source_pdf_id': second, 'source_page': 2}).status_code, 409)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'invalid', 'source_pdf_id': second, 'source_page': 3}).status_code, 422)
        self.assertEqual(len(self.client.get('/api/vocabulary').json()), 3)


if __name__ == '__main__':
    unittest.main()
