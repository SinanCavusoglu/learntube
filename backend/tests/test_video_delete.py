import unittest
from unittest.mock import patch
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool
from app.models import TranscriptSegment, Video, VideoNote, VocabularyItem
from app.routers.videos import delete_video, list_videos

class VideoDeleteTests(unittest.TestCase):
    @patch('app.routers.videos.fetch_title', return_value='A real title')
    def test_library_returns_full_cards_after_title_update(self, _fetch):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Video(youtube_id='mdrSqiyNXO4', url='https://www.youtube.com/watch?v=mdrSqiyNXO4', title='YouTube video · mdrSqiyNXO4'))
            session.commit()
            result = list_videos(session)
            self.assertEqual(result[0].title, 'A real title')
            self.assertIsNotNone(result[0].id)
            self.assertEqual(result[0].youtube_id, 'mdrSqiyNXO4')

    def test_delete_video_keeps_vocabulary(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            video = Video(youtube_id='mdrSqiyNXO4', url='https://www.youtube.com/watch?v=mdrSqiyNXO4')
            session.add(video); session.commit(); session.refresh(video)
            video_id = video.id
            session.add(TranscriptSegment(video_id=video_id, text='caption', start=0, duration=1))
            session.add(VideoNote(video_id=video_id, content='note'))
            session.add(VocabularyItem(text='expression', source_video_id=video_id, source_timestamp=3))
            session.commit()
            delete_video(video_id, session)
            self.assertIsNone(session.get(Video, video_id))
            self.assertEqual(session.exec(select(TranscriptSegment)).all(), [])
            self.assertEqual(session.exec(select(VideoNote)).all(), [])
            item = session.exec(select(VocabularyItem)).one()
            self.assertIsNone(item.source_video_id)
            self.assertEqual(item.text, 'expression')
