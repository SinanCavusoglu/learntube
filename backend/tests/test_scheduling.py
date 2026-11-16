import unittest
from datetime import datetime, timedelta, timezone
from app.models import VocabularyItem
from app.services.scheduling import schedule

class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_new_grades(self):
        for rating, days in [('good', 1), ('easy', 4)]:
            item = VocabularyItem(text='example')
            schedule(item, rating, self.at)
            self.assertEqual(item.interval_days, days)
            self.assertEqual(item.next_review_at, self.at + timedelta(days=days))
            self.assertEqual(item.status, 'reviewing')

    def test_again_and_mastery(self):
        item = VocabularyItem(text='example')
        schedule(item, 'again', self.at)
        self.assertEqual(item.status, 'learning')
        self.assertEqual(item.next_review_at, self.at + timedelta(minutes=10))
        for day in range(3): schedule(item, 'easy', self.at + timedelta(days=day + 1))
        self.assertGreaterEqual(item.interval_days, 21)
        self.assertEqual(item.status, 'mastered')
        self.assertGreaterEqual(item.interval_days, 0)

if __name__ == '__main__': unittest.main()
