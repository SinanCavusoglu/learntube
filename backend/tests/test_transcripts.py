import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from app.db import get_session
from app.models import TranscriptSegment, Video
from app.routers.videos import router as videos_router
from app.services.search_index import ensure_index, search
from app.services.transcripts import fetch_english

class Track:
    def __init__(self, language_code, is_generated):
        self.language_code = language_code
        self.is_generated = is_generated

    def fetch(self):
        return [type('Line', (), {'text': self.language_code, 'start': 2.0, 'duration': 1.5})()]

class TranscriptSelectionTests(unittest.TestCase):
    @patch('app.services.transcripts.YouTubeTranscriptApi')
    def test_regional_english_and_manual_priority(self, api):
        api.return_value.list.return_value = [Track('en-US', True), Track('en-GB', False), Track('de', False)]
        self.assertEqual(fetch_english('mdrSqiyNXO4')[0]['text'], 'en-GB')

    @patch('app.services.transcripts.YouTubeTranscriptApi')
    def test_missing_english(self, api):
        api.return_value.list.return_value = [Track('de', False)]
        with self.assertRaisesRegex(ValueError, 'No English captions'):
            fetch_english('mdrSqiyNXO4')


class TranscriptRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{(Path(self.temp.name) / "test.db").as_posix()}', connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        self.fts = ensure_index(self.engine, Path(self.temp.name))
        with Session(self.engine) as session:
            video = Video(youtube_id='refresh123', url='https://example.test', title='Lesson')
            session.add(video); session.flush()
            session.add(TranscriptSegment(video_id=video.id, text='Original saved caption', start=12))
            self.video_id = video.id
            session.commit()
        app = FastAPI()
        app.include_router(videos_router)
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def captions(self):
        with Session(self.engine) as session:
            return [(row.text, row.start) for row in session.exec(select(TranscriptSegment).where(TranscriptSegment.video_id == self.video_id)).all()]

    def test_empty_first_fetch_can_be_retried_without_page_reload(self):
        with Session(self.engine) as session:
            video = Video(youtube_id='newvideo123', url='https://example.test/new', title='New lesson')
            session.add(video)
            session.commit()
            session.refresh(video)
            new_id = video.id
        with patch('app.routers.videos.fetch_english', return_value=[]):
            first = self.client.get(f'/api/videos/{new_id}/transcript')
        self.assertEqual(first.status_code, 424)
        with patch('app.routers.videos.fetch_english', return_value=[
            {'text': 'Caption now available', 'start': 1.0, 'duration': 2.0}]):
            second = self.client.get(f'/api/videos/{new_id}/transcript')
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()[0]['text'], 'Caption now available')

    def test_first_successful_fetch_returns_complete_segments(self):
        with Session(self.engine) as session:
            video = Video(youtube_id='firstfetch1', url='https://example.test/first', title='First lesson')
            session.add(video)
            session.commit()
            session.refresh(video)
            new_id = video.id
        with patch('app.routers.videos.fetch_english', return_value=[
            {'text': 'Ready immediately', 'start': 3.0, 'duration': 2.0}]):
            response = self.client.get(f'/api/videos/{new_id}/transcript')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]['text'], 'Ready immediately')
        self.assertGreater(response.json()[0]['id'], 0)

    def test_failed_refresh_preserves_transcript_and_search(self):
        with patch('app.routers.videos.fetch_english', side_effect=RuntimeError('offline')):
            result = self.client.post(f'/api/videos/{self.video_id}/transcript/refresh')
        self.assertEqual(result.status_code, 424)
        self.assertEqual(self.captions(), [('Original saved caption', 12.0)])
        self.assertTrue(search(self.engine, 'Original', 'videos', 8, 0, self.fts)['groups']['videos'])
        with patch('app.routers.videos.fetch_english', return_value=[]):
            self.assertEqual(self.client.post(f'/api/videos/{self.video_id}/transcript/refresh').status_code, 424)
        self.assertEqual(self.captions(), [('Original saved caption', 12.0)])

    def test_successful_refresh_replaces_transcript_and_search(self):
        with patch('app.routers.videos.fetch_english', return_value=[{'text': 'New caption', 'start': 30.0, 'duration': 2.0}]):
            result = self.client.post(f'/api/videos/{self.video_id}/transcript/refresh')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()[0]['text'], 'New caption')
        self.assertEqual(self.captions(), [('New caption', 30.0)])
        self.assertFalse(search(self.engine, 'Original', 'videos', 8, 0, self.fts)['groups']['videos'])
        self.assertTrue(search(self.engine, 'caption', 'videos', 8, 0, self.fts)['groups']['videos'])

    def test_blank_manual_transcript_cannot_erase_saved_captions(self):
        result = self.client.put(f'/api/videos/{self.video_id}/transcript/manual', json={'text': '  \n  '})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.captions(), [('Original saved caption', 12.0)])

    def test_manual_save_returns_complete_segments(self):
        result = self.client.put(f'/api/videos/{self.video_id}/transcript/manual', json={'text': 'One caption'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()[0]['text'], 'One caption')
