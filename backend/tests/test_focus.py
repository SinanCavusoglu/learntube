import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import FocusSession, StudyActivity, StudyPlan
from app.routers import focus
from app.services.backups import BackupService


class FocusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(f'sqlite:///{(self.root / "focus.db").as_posix()}', connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX ux_focus_active ON focussession((1)) WHERE status IN ('running','paused')"))
        self.engine_patch = patch.object(focus, 'engine', self.engine)
        self.engine_patch.start()
        app = FastAPI()
        app.include_router(focus.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def task_payload(self, **changes):
        return {'request_id': str(uuid4()), 'title': 'IELTS Writing', 'description': 'Task 2',
                'category': 'Writing', 'date': '2026-11-19', 'timezone': 'Europe/Berlin',
                'estimated_pomodoros': 3, 'focus_minutes': 30,
                'short_break_minutes': None, 'long_break_minutes': None, **changes}

    def create_task(self, **changes):
        response = self.client.post('/api/focus/tasks', json=self.task_payload(**changes))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['plan_id']

    def start(self, phase='focus', plan_id=None, day='2026-11-19', session_id=None):
        payload = {'id': session_id or str(uuid4()), 'phase': phase, 'task_plan_id': plan_id,
                   'task_occurrence_date': day if plan_id else None, 'task_date': day if plan_id else None}
        return self.client.post('/api/focus/sessions', json=payload)

    def age(self, session_id, seconds):
        with Session(self.engine) as session:
            row = session.get(FocusSession, session_id)
            row.started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
            session.add(row)
            session.commit()

    def test_shared_tasks_and_individual_durations(self):
        writing = self.create_task()
        vocab = self.create_task(title='Vocabulary', category='Vocabulary', focus_minutes=20, estimated_pomodoros=2)
        tasks = self.client.get('/api/focus/tasks?day=2026-11-19').json()
        self.assertEqual({row['title'] for row in tasks}, {'IELTS Writing', 'Vocabulary'})
        with Session(self.engine) as session:
            self.assertTrue(session.get(StudyPlan, writing).is_untimed)
        row = self.start(plan_id=writing).json()
        self.assertEqual(row['target_seconds'], 1800)
        self.assertEqual(row['task_date'], '2026-11-19')
        self.assertEqual(self.start(plan_id=vocab).status_code, 409)
        self.assertEqual(self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'stop', 'revision': 0, 'verified_seconds': 0}).status_code, 200)
        self.assertEqual(self.start(plan_id=vocab).json()['target_seconds'], 1200)
        edit = self.task_payload(title='Edited Writing', focus_minutes=40, estimated_pomodoros=4)
        self.assertEqual(self.client.put(f'/api/focus/tasks/{writing}?occurrence=2026-11-19', json=edit).status_code, 200)
        tasks = self.client.get('/api/focus/tasks?day=2026-11-19').json()
        self.assertEqual(next(row for row in tasks if row['plan_id'] == writing)['focus_minutes'], 40)
        self.assertEqual(self.client.put(f'/api/focus/tasks/{writing}/status?occurrence=2026-11-19&completed=true').status_code, 200)
        with Session(self.engine) as session:
            self.assertEqual(session.get(StudyPlan, writing).status, 'completed')
        self.assertEqual(self.client.put(f'/api/focus/tasks/{writing}/status?occurrence=2026-11-19&completed=false').status_code, 200)

    def test_settings_break_overrides_and_session_duration_is_fixed(self):
        defaults = self.client.get('/api/focus/settings').json()
        self.assertEqual(defaults['focus_minutes'], 30)
        saved = self.client.put('/api/focus/settings', json={**defaults, 'focus_minutes': 40,
                                                               'short_break_minutes': 7, 'long_break_after': 3})
        self.assertEqual(saved.status_code, 200, saved.text)
        plan_id = self.create_task(focus_minutes=20, short_break_minutes=3)
        identifier = str(uuid4())
        focus_row = self.start(plan_id=plan_id, session_id=identifier).json()
        self.assertEqual(focus_row['target_seconds'], 1200)
        self.assertEqual(self.start(plan_id=plan_id, session_id=identifier).json()['id'], identifier)
        edit = self.task_payload(focus_minutes=25, short_break_minutes=4)
        self.assertEqual(self.client.put(f'/api/focus/tasks/{plan_id}?occurrence=2026-11-19', json=edit).status_code, 200)
        with Session(self.engine) as session:
            self.assertEqual(session.get(FocusSession, identifier).target_seconds, 1200)
        self.assertEqual(self.client.put(f'/api/focus/sessions/{identifier}', json={'action': 'stop', 'revision': 0, 'verified_seconds': 0}).status_code, 200)
        self.assertEqual(self.start('short_break', plan_id=plan_id).json()['target_seconds'], 240)

    def test_paused_session_can_be_stopped_without_credit(self):
        row = self.start().json()
        paused = self.client.put(f"/api/focus/sessions/{row['id']}", json={
            'action': 'pause', 'revision': 0, 'verified_seconds': 0}).json()
        rejected = self.client.put(f"/api/focus/sessions/{row['id']}", json={
            'action': 'stop', 'revision': paused['revision'], 'verified_seconds': 10})
        self.assertEqual(rejected.status_code, 422)
        stopped = self.client.put(f"/api/focus/sessions/{row['id']}", json={
            'action': 'stop', 'revision': paused['revision'], 'verified_seconds': 0})
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()['status'], 'stopped')
        self.assertEqual(self.client.get('/api/focus/stats?day=2026-11-19').json()['completed_total'], 0)

    def test_completion_idempotence_breaks_history_and_actual_time(self):
        plan_id = self.create_task(focus_minutes=1, estimated_pomodoros=1)
        row = self.start(plan_id=plan_id).json()
        self.age(row['id'], 70)
        paused = self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'pause', 'revision': 0, 'verified_seconds': 30})
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertEqual(paused.json()['verified_seconds'], 30)
        self.assertEqual(self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'complete', 'revision': 1, 'verified_seconds': 60}).status_code, 409)
        resumed = self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'resume', 'revision': 1, 'verified_seconds': 30}).json()
        completed = self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'complete', 'revision': resumed['revision'], 'verified_seconds': 60})
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(self.client.put(f"/api/focus/sessions/{row['id']}", json={'action': 'complete', 'revision': 0, 'verified_seconds': 60}).status_code, 200)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(FocusSession).where(FocusSession.status == 'completed')).all()), 1)
            self.assertEqual(len(session.exec(select(StudyActivity)).all()), 0)
        self.assertEqual(self.client.get('/api/focus/tasks?day=2026-11-19').json()[0]['completed_pomodoros'], 1)
        self.assertEqual(self.client.delete(f'/api/focus/tasks/{plan_id}?occurrence=2026-11-19').status_code, 204)
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(FocusSession, row['id']))
        short = self.start('short_break').json()
        self.age(short['id'], 400)
        self.assertEqual(self.client.put(f"/api/focus/sessions/{short['id']}", json={'action': 'complete', 'revision': 0, 'verified_seconds': 300}).status_code, 200)
        with Session(self.engine) as session:
            for key in (row['id'], short['id']):
                saved = session.get(FocusSession, key)
                saved.completed_at = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
                session.add(saved)
            session.commit()
        stats = self.client.get('/api/focus/stats?day=2026-11-19&timezone_name=Europe/Berlin').json()
        self.assertEqual(stats['today']['tasks_total'], 0)
        self.assertEqual(stats['today']['pomodoros'], 1)
        self.assertEqual(stats['today']['focus_seconds'], 60)
        history = self.client.get('/api/focus/sessions/history?start=2026-11-19&end=2026-11-19&timezone_name=Europe/Berlin').json()
        self.assertEqual(len(history), 2)
        self.assertTrue(all(item['completed_at'].endswith('Z') or item['completed_at'].endswith('+00:00') for item in history))

    def test_recurrence_occurrence_and_backup(self):
        with Session(self.engine) as session:
            plan = StudyPlan(request_id=str(uuid4()), title='Daily vocabulary', category='Vocabulary',
                             start_date=date(2026, 11, 19), recurrence='daily', is_untimed=True,
                             focus_minutes=20, estimated_pomodoros=2)
            session.add(plan);session.commit();session.refresh(plan)
            plan_id = plan.id
        payload = self.task_payload(title='Thursday vocabulary', category='Vocabulary', focus_minutes=25,
                                    estimated_pomodoros=3)
        edited = self.client.put(f'/api/focus/tasks/{plan_id}?occurrence=2026-11-19', json=payload)
        self.assertEqual(edited.status_code, 200, edited.text)
        today = self.client.get('/api/focus/tasks?day=2026-11-19').json()[0]
        tomorrow = self.client.get('/api/focus/tasks?day=2026-11-20').json()[0]
        self.assertEqual((today['title'], today['focus_minutes']), ('Thursday vocabulary', 25))
        self.assertEqual((tomorrow['title'], tomorrow['focus_minutes']), ('Daily vocabulary', 20))
        self.assertEqual(self.client.put(f'/api/focus/tasks/{plan_id}/status?occurrence=2026-11-19&completed=true').status_code, 200)
        self.assertEqual(self.client.get('/api/focus/tasks?day=2026-11-20').json()[0]['status'], 'planned')
        moved = self.task_payload(title='Moved vocabulary', category='Vocabulary', date='2026-11-18', focus_minutes=25)
        self.assertEqual(self.client.put(f'/api/focus/tasks/{plan_id}?occurrence=2026-11-19&day=2026-11-19', json=moved).status_code, 200)
        self.assertEqual(self.client.get('/api/focus/tasks?day=2026-11-18').json()[0]['title'], 'Moved vocabulary')
        self.assertEqual(self.client.put(f'/api/focus/tasks/{plan_id}/status?occurrence=2026-11-19&day=2026-11-18&completed=false').status_code, 200)
        service = BackupService(self.engine, self.root/'pdfs', self.root/'safety', self.root/'state')
        archive = self.root/'focus.zip'
        service.create(archive)
        self.assertTrue(archive.is_file())
        self.assertGreater(service.validate(archive, self.root/'staging')['counts']['studyplan'], 0)

    def test_backup_pauses_running_timer_only_in_portable_copy(self):
        row = self.start().json()
        service = BackupService(self.engine, self.root/'pdfs', self.root/'safety', self.root/'state')
        archive = self.root/'active.zip'
        service.create(archive)
        staging = self.root/'staged-active'
        service.validate(archive, staging)
        with closing(sqlite3.connect(staging/'database.sqlite3')) as connection:
            self.assertEqual(connection.execute('SELECT status FROM focussession WHERE id=?', (row['id'],)).fetchone()[0], 'paused')
        with Session(self.engine) as session:
            self.assertEqual(session.get(FocusSession, row['id']).status, 'running')

    def test_focus_settings_tasks_and_sessions_restore_in_temporary_database(self):
        plan_id = self.create_task(focus_minutes=1, estimated_pomodoros=2)
        defaults = self.client.get('/api/focus/settings').json()
        self.assertEqual(self.client.put('/api/focus/settings', json={**defaults, 'focus_minutes': 45}).status_code, 200)
        row = self.start(plan_id=plan_id).json()
        self.age(row['id'], 70)
        self.assertEqual(self.client.put(f"/api/focus/sessions/{row['id']}", json={
            'action': 'complete', 'revision': 0, 'verified_seconds': 60}).status_code, 200)
        service = BackupService(self.engine, self.root/'pdfs', self.root/'safety', self.root/'state')
        archive = self.root/'restore-focus.zip'
        service.create(archive)
        inspected = service.validate(archive, self.root/'inspected')
        self.assertEqual(self.client.delete(f'/api/focus/tasks/{plan_id}?occurrence=2026-11-19').status_code, 204)
        self.assertEqual(self.client.put('/api/focus/settings', json={**defaults, 'focus_minutes': 20}).status_code, 200)
        service.restore(archive, inspected['archive_sha256'])
        self.assertEqual(self.client.get('/api/focus/settings').json()['focus_minutes'], 45)
        tasks = self.client.get('/api/focus/tasks?day=2026-11-19').json()
        self.assertEqual(tasks[0]['completed_pomodoros'], 1)
        self.assertEqual(tasks[0]['estimated_pomodoros'], 2)
        with Session(self.engine) as session:
            restored = session.get(FocusSession, row['id'])
            self.assertEqual(restored.status, 'completed')
            self.assertEqual(restored.task_date, date(2026, 11, 19))
