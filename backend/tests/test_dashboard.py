import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import StudyActivity, Video, VocabularyItem, WritingSession
from app.routers.dashboard import ActivityCreate, dashboard, record_activity
from app.services.activity import daily_durations, streaks, timezone_or_422


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_empty_dashboard_and_actual_counts(self):
        with Session(self.engine) as session:
            data = dashboard('UTC', session)
            self.assertEqual(data['total_seconds'], 0)
            self.assertEqual(data['current_streak'], 0)
            self.assertEqual(data['vocabulary']['mastered'], 0)
            self.assertEqual(len(data['daily']), 365)
            session.add(VocabularyItem(text='practice', status='mastered'))
            session.add(WritingSession(task_type=2, status='completed', completed_at=datetime.now(timezone.utc)))
            session.add(Video(youtube_id='abc123', url='https://youtu.be/abc123'))
            session.commit()
            data = dashboard('UTC', session)
            self.assertEqual(data['vocabulary']['mastered'], 1)
            self.assertEqual(data['writing']['completed'], 1)
            self.assertEqual(data['videos_saved'], 1)

    def test_idempotent_recording_and_overlap_rejection(self):
        client = uuid4()
        event = uuid4()
        end = datetime.now(timezone.utc)
        payload = ActivityCreate(event_key=event, client_session_id=client, activity_type='video', ended_at=end, duration_seconds=5)
        with Session(self.engine) as session:
            self.assertTrue(record_activity(payload, session)['recorded'])
            self.assertFalse(record_activity(payload, session)['recorded'])
            with self.assertRaises(HTTPException) as caught:
                record_activity(ActivityCreate(event_key=uuid4(), client_session_id=client, activity_type='writing', ended_at=end, duration_seconds=5), session)
            self.assertEqual(caught.exception.status_code, 409)
            with self.assertRaises(HTTPException) as other_tab:
                record_activity(ActivityCreate(event_key=uuid4(), client_session_id=uuid4(), activity_type='writing', ended_at=end, duration_seconds=5), session)
            self.assertEqual(other_tab.exception.status_code, 409)
            data = dashboard('UTC', session)
            self.assertAlmostEqual(data['total_seconds'], 5)
            self.assertAlmostEqual(data['today_seconds'], data['daily'][-1]['total'])
            self.assertAlmostEqual(data['week_seconds'], sum(row['total'] for row in data['weekly']))

    def test_local_midnight_and_daylight_saving(self):
        zone = ZoneInfo('Europe/Berlin')
        crossing = StudyActivity(event_key='a', client_session_id='c', activity_type='video', started_at=datetime(2026, 3, 28, 22, 59, 30, tzinfo=timezone.utc), ended_at=datetime(2026, 3, 28, 23, 0, 30, tzinfo=timezone.utc), active_duration_seconds=60)
        spring = StudyActivity(event_key='b', client_session_id='c', activity_type='writing', started_at=datetime(2026, 3, 29, 0, 59, 30, tzinfo=timezone.utc), ended_at=datetime(2026, 3, 29, 1, 0, 30, tzinfo=timezone.utc), active_duration_seconds=60)
        fall = StudyActivity(event_key='d', client_session_id='c', activity_type='vocabulary', started_at=datetime(2026, 10, 25, 0, 59, 30, tzinfo=timezone.utc), ended_at=datetime(2026, 10, 25, 1, 0, 30, tzinfo=timezone.utc), active_duration_seconds=60)
        days = daily_durations([crossing, spring, fall], zone)
        self.assertEqual(days[date(2026, 3, 28)]['video'], 30)
        self.assertEqual(days[date(2026, 3, 29)]['video'], 30)
        self.assertEqual(days[date(2026, 3, 29)]['writing'], 60)
        self.assertEqual(days[date(2026, 10, 25)]['vocabulary'], 60)

    def test_streak_today_yesterday_threshold_and_longest(self):
        today = date(2026, 11, 15)
        days = {today-timedelta(days=n): {'video': seconds, 'vocabulary': 0, 'writing': 0} for n, seconds in [(1,60),(2,90),(3,59),(7,60),(8,61),(9,62)]}
        self.assertEqual(streaks(days, today), (2,3))
        days[today] = {'video': 60, 'vocabulary': 0, 'writing': 0}
        self.assertEqual(streaks(days, today), (3,3))

    def test_bad_timezone(self):
        with self.assertRaises(HTTPException):
            timezone_or_422('../bad')

    def test_pdf_minutes_count_for_streaks(self):
        today = datetime.now(timezone.utc).date()
        end = datetime.combine(today, datetime.min.time(), timezone.utc) + timedelta(minutes=2)
        reading = StudyActivity(event_key='pdf-minute', client_session_id='reader', activity_type='pdf',
                                started_at=end-timedelta(seconds=60), ended_at=end, active_duration_seconds=60)
        days = daily_durations([reading], ZoneInfo('UTC'))
        self.assertEqual(days[today]['pdf'], 60)
        self.assertEqual(streaks(days, today), (1, 1))


if __name__ == '__main__':
    unittest.main()
