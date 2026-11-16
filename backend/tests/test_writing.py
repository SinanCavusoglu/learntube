import unittest
from datetime import datetime, timedelta, timezone
from app.models import WritingSession
from app.routers.writing import current_elapsed, words

class WritingTests(unittest.TestCase):
    def test_words_ignore_whitespace_and_notes(self):
        session = WritingSession(task_type=1, essay_content=' One  two\nthree ', notes='not part of essay')
        self.assertEqual(words(session.essay_content), 3)
        self.assertEqual(words(' \t\n '), 0)

    def test_elapsed_uses_real_timestamps_and_pauses(self):
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session = WritingSession(task_type=2, elapsed_seconds=12, timer_status='running', timer_started_at=started)
        self.assertEqual(current_elapsed(session, started + timedelta(seconds=8)), 20)
        session.timer_status = 'paused'
        self.assertEqual(current_elapsed(session, started + timedelta(hours=1)), 12)
