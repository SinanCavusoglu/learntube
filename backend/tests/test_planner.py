import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import StudyActivity, StudyPlan, StudyPlanOverride, Video
from app.routers.planner import router
from app.services.backups import BackupService


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(f'sqlite:///{(self.root / "planner.db").as_posix()}', connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(router)
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app)
        self.sequence = 0

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def payload(self, **changes):
        self.sequence += 1
        result = {'request_id': f'00000000-0000-4000-8000-{self.sequence:012d}', 'title': 'IELTS Writing',
                  'category': 'Writing', 'description': '', 'start_date': '2026-11-19',
                  'start_time': '10:00', 'end_time': '11:00', 'is_untimed': False,
                  'recurrence': 'none', 'weekdays': [], 'repeat_until': None,
                  'timezone': 'Europe/Berlin', 'resource_type': 'writing', 'resource_id': None}
        return {**result, **changes}

    def create(self, **changes):
        response = self.client.post('/api/planner', json=self.payload(**changes))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def range(self, start='2026-11-16', end='2026-11-22'):
        response = self.client.get('/api/planner', params={'start': start, 'end': end})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_edit_complete_skip_and_delete(self):
        plan = self.create()
        task = self.create(title='Review vocabulary', category='Vocabulary', is_untimed=True,
                           start_time=None, end_time=None, resource_type='vocabulary')
        self.assertEqual(len(self.range()), 2)
        self.assertEqual(self.client.get('/api/planner/stats', params={'start': '2026-11-19', 'end': '2026-11-19'}).json(),
                         {'planned_minutes': 60, 'completed_minutes': 0, 'completed_tasks': 0, 'total_tasks': 1})
        self.assertEqual(self.client.patch(f'/api/planner/{plan["id"]}/status', json={'status': 'completed'}).status_code, 200)
        self.assertEqual(self.client.patch(f'/api/planner/{task["id"]}/status', json={'status': 'completed'}).status_code, 200)
        stats = self.client.get('/api/planner/stats', params={'start': '2026-11-19', 'end': '2026-11-19'}).json()
        self.assertEqual((stats['completed_minutes'], stats['completed_tasks']), (60, 1))
        self.assertEqual(self.client.patch(f'/api/planner/{plan["id"]}/status', json={'status': 'skipped'}).status_code, 200)
        self.assertEqual(self.client.get('/api/planner/stats', params={'start': '2026-11-19', 'end': '2026-11-19'}).json()['completed_minutes'], 0)
        edit = self.payload(title='Reading', category='Reading', start_date='2026-11-20', start_time='08:00', end_time='08:45')
        self.assertEqual(self.client.patch(f'/api/planner/{plan["id"]}', json=edit).status_code, 200)
        self.assertEqual({row['date'] for row in self.range()}, {'2026-11-19', '2026-11-20'})
        self.assertEqual(self.client.delete(f'/api/planner/{plan["id"]}').status_code, 204)
        self.assertEqual(len(self.range()), 1)

    def test_recurrence_and_single_occurrence_changes(self):
        daily = self.create(title='Flashcards', category='Flashcards', recurrence='daily', repeat_until='2026-11-22')
        weekly = self.create(title='Reading', category='Reading', recurrence='weekly', start_date='2026-11-16')
        custom = self.create(title='Vocabulary', category='Vocabulary', recurrence='custom', weekdays=[0, 2, 4], start_date='2026-11-16')
        rows = self.range()
        self.assertEqual(sum(row['plan_id'] == daily['id'] for row in rows), 4)
        self.assertEqual(sum(row['plan_id'] == weekly['id'] for row in rows), 1)
        self.assertEqual(sum(row['plan_id'] == custom['id'] for row in rows), 3)
        url = f'/api/planner/{daily["id"]}/status?occurrence=2026-11-19'
        self.assertEqual(self.client.patch(url, json={'status': 'completed'}).status_code, 200)
        self.assertEqual({row['date']: row['status'] for row in self.range() if row['plan_id'] == daily['id']},
                         {'2026-11-19': 'completed', '2026-11-20': 'planned', '2026-11-21': 'planned', '2026-11-22': 'planned'})
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}/status?occurrence=2026-11-20', json={'status': 'skipped'}).status_code, 200)
        changed = self.payload(title='Edited one day', recurrence='daily', repeat_until='2026-11-22', start_date='2026-11-23')
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}?occurrence=2026-11-21', json=changed).status_code, 200)
        self.assertNotIn('2026-11-21', [row['date'] for row in self.range() if row['plan_id'] == daily['id']])
        self.assertEqual([row['title'] for row in self.range('2026-11-23', '2026-11-23') if row['plan_id'] == daily['id']], ['Edited one day'])
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}/status?occurrence=2026-11-21', json={'status': 'completed'}).status_code, 200)
        self.assertEqual(self.range('2026-11-23', '2026-11-23')[0]['status'], 'completed')
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}?occurrence=2026-11-21',
                                           json={**changed, 'start_date': '2026-11-20'}).status_code, 409)
        self.assertEqual(self.client.delete(f'/api/planner/{daily["id"]}?occurrence=2026-11-22').status_code, 204)
        self.assertNotIn('2026-11-22', [row['date'] for row in self.range() if row['plan_id'] == daily['id']])
        conflicting = self.payload(title='Series changed', recurrence='daily', repeat_until='2026-11-24')
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}', json=conflicting).status_code, 409)
        series = self.payload(title='Series changed', recurrence='daily', repeat_until='2026-11-22')
        self.assertEqual(self.client.patch(f'/api/planner/{daily["id"]}', json=series).status_code, 200)
        self.assertEqual(next(row for row in self.range() if row['plan_id'] == daily['id'] and row['date'] == '2026-11-19')['title'], 'Series changed')
        self.assertEqual(self.client.delete(f'/api/planner/{daily["id"]}').status_code, 204)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == daily['id'])).all(), [])

    def test_validation_ranges_idempotency_and_actual_activity(self):
        for changes in ({'end_time': '10:00'}, {'end_time': '09:00'}, {'recurrence': 'custom'},
                        {'timezone': 'Not/A_Zone'}, {'resource_type': 'video', 'resource_id': 999}):
            response = self.client.post('/api/planner', json=self.payload(**changes))
            self.assertIn(response.status_code, (404, 422))
        data = self.payload()
        first = self.client.post('/api/planner', json=data)
        second = self.client.post('/api/planner', json=data)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(self.client.get('/api/planner', params={'start': '2026-11-20', 'end': '2026-11-20'}).json(), [])
        self.assertEqual(self.client.get('/api/planner', params={'start': '2026-01-01', 'end': '2026-12-31'}).status_code, 422)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(StudyActivity)).all(), [])

    def test_wall_clock_recurrence_across_dst_leap_and_year(self):
        self.create(start_date='2028-02-28', recurrence='daily', repeat_until='2028-03-01', start_time='18:00', end_time='18:30')
        self.assertEqual([row['date'] for row in self.range('2028-02-28', '2028-03-01')],
                         ['2028-02-28', '2028-02-29', '2028-03-01'])
        self.create(start_date='2027-03-27', recurrence='daily', repeat_until='2027-03-29', start_time='18:00', end_time='18:30')
        self.assertEqual([row['start_time'][:5] for row in self.range('2027-03-27', '2027-03-29')], ['18:00'] * 3)
        self.create(start_date='2026-12-31', recurrence='daily', repeat_until='2027-01-02')
        self.assertEqual(len(self.range('2026-12-31', '2027-01-02')), 3)

    def test_deleted_resource_falls_back_to_category(self):
        with Session(self.engine) as session:
            video = Video(youtube_id='planner-video', url='https://example.test/video', title='Lesson')
            session.add(video); session.commit(); video_id = video.id
        plan = self.create(category='Listening', resource_type='video', resource_id=video_id)
        self.assertEqual(self.range()[0]['destination_url'], f'/videos/{video_id}')
        with Session(self.engine) as session:
            session.delete(session.get(Video, video_id)); session.commit()
        row = self.range()[0]
        self.assertEqual(row['plan_id'], plan['id'])
        self.assertEqual(row['destination_url'], '/videos')
        self.assertTrue(row['resource_missing'])

    def test_file_persists_after_engine_reopen_and_overlaps_are_allowed(self):
        first = self.create(start_time='09:00', end_time='10:00')
        second = self.create(start_time='09:30', end_time='10:30')
        self.assertEqual({row['plan_id'] for row in self.range()}, {first['id'], second['id']})
        self.engine.dispose()
        reopened = create_engine(f'sqlite:///{(self.root / "planner.db").as_posix()}')
        try:
            with Session(reopened) as session:
                self.assertEqual(len(session.exec(select(StudyPlan)).all()), 2)
        finally:
            reopened.dispose()

    def test_backup_restore_preserves_plans_and_overrides(self):
        plan = self.create(recurrence='daily')
        self.client.patch(f'/api/planner/{plan["id"]}/status?occurrence=2026-11-19', json={'status': 'completed'})
        service = BackupService(self.engine, self.root / 'pdfs', self.root / 'safety', self.root / 'state')
        archive = self.root / 'backup.zip'
        manifest = service.create(archive)
        self.assertEqual((manifest['counts']['studyplan'], manifest['counts']['studyplanoverride']), (1, 1))
        self.client.delete(f'/api/planner/{plan["id"]}')
        inspected = service.validate(archive, self.root / 'staged')
        service.restore(archive, inspected['archive_sha256'])
        self.assertEqual(self.range('2026-11-19', '2026-11-20')[0]['status'], 'completed')
        self.assertEqual(self.range('2026-11-19', '2026-11-20')[1]['status'], 'planned')


if __name__ == '__main__':
    unittest.main()
