import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import ReviewEvent, VocabularyItem
from app.routers import vocabulary
from app.services.difficulty import classify, difficult_words, difficulty_stats


class DifficultyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{(Path(self.temp.name) / "test.db").as_posix()}', connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(vocabulary.router)
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app)
        self.patch = patch.object(vocabulary, 'engine', self.engine)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def add_word(self, text, ratings=(), review_count=None, due=None):
        with Session(self.engine) as session:
            item = VocabularyItem(text=text, meaning='Definition', review_count=review_count if review_count is not None else len(ratings),
                                  interval_days=7, next_review_at=due)
            session.add(item); session.flush()
            for index, rating in enumerate(ratings):
                session.add(ReviewEvent(vocabulary_id=item.id, rating=rating,
                                        reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
                                        previous_status='learning', next_status='learning', interval_days=7))
            item_id = item.id
            session.commit()
        return item_id

    def test_recent_windows_and_recovery(self):
        self.assertFalse(classify([])['automatic_difficult'])
        self.assertFalse(classify(['again'])['automatic_difficult'])
        self.assertTrue(classify(['again', 'again'])['automatic_difficult'])
        self.assertTrue(classify(['good'] * 5 + ['again'] * 3)['automatic_difficult'] is False)
        self.assertTrue(classify(['again', 'good', 'again', 'good', 'good'])['automatic_difficult'])
        self.assertFalse(classify(['good'] * 10)['automatic_difficult'])
        self.assertFalse(classify(['good'] * 5 + ['again'] * 3 + ['good'] * 2)['automatic_difficult'])

    def test_history_only_and_stats(self):
        self.add_word('new')
        self.add_word('imported', review_count=12)
        self.add_word('one failure', ['again'])
        due_id = self.add_word('due', ['again', 'again'], due=datetime.now(timezone.utc)-timedelta(days=1))
        future_id = self.add_word('later', ['again', 'good', 'again'], due=datetime.now(timezone.utc)+timedelta(days=5))
        with Session(self.engine) as session:
            words = difficult_words(session)
        self.assertEqual({word['item']['id'] for word in words}, {due_id, future_id})
        self.assertEqual(difficulty_stats(words), {'total': 2, 'due': 1, 'practice_available': 2})
        self.assertEqual(self.client.get('/api/vocabulary/difficult/stats').json()['due'], 1)
        self.assertEqual(len(self.client.get('/api/vocabulary/difficult').json()), 2)

    def test_extra_practice_reads_do_not_schedule_and_normal_review_logs_once(self):
        item_id = self.add_word('review me', ['again', 'again'], review_count=2)
        with Session(self.engine) as session:
            before = session.get(VocabularyItem, item_id).model_dump()
            event_count = len(session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id)).all())
        self.client.get('/api/vocabulary/difficult')
        self.client.get('/api/vocabulary/difficult/stats')
        with Session(self.engine) as session:
            self.assertEqual(session.get(VocabularyItem, item_id).model_dump(), before)
            self.assertEqual(len(session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id)).all()), event_count)
        payload = {'rating': 'good', 'expected_review_count': 2}
        self.assertEqual(self.client.post(f'/api/vocabulary/{item_id}/review', json=payload).status_code, 200)
        self.assertEqual(self.client.post(f'/api/vocabulary/{item_id}/review', json=payload).status_code, 409)
        with Session(self.engine) as session:
            item = session.get(VocabularyItem, item_id)
            self.assertEqual(item.review_count, 3)
            self.assertGreater(item.next_review_at.replace(tzinfo=timezone.utc), datetime.now(timezone.utc))
            self.assertEqual(len(session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id)).all()), event_count + 1)

    def test_delete_removes_history(self):
        item_id = self.add_word('delete', ['again', 'again'])
        self.assertEqual(self.client.delete(f'/api/vocabulary/{item_id}').status_code, 204)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(VocabularyItem, item_id))
            self.assertEqual(session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id)).all(), [])


if __name__ == '__main__':
    unittest.main()
