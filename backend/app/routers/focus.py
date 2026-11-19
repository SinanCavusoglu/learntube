"""Local focus sessions; Planner remains the single owner of study tasks."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import engine
from app.models import FocusSession, FocusSettings, StudyPlan, StudyPlanOverride
from app.services.planner import occurs_on, occurrences

router = APIRouter(prefix='/api/focus', tags=['focus'])
Category = Literal['Vocabulary', 'Flashcards', 'Listening', 'Reading', 'Writing', 'Grammar', 'General Study']
Phase = Literal['focus', 'short_break', 'long_break']


@contextmanager
def write_session():
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            with Session(bind=connection) as session:
                yield session
                session.flush()
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def settings(session: Session) -> FocusSettings:
    return session.get(FocusSettings, 1) or FocusSettings(id=1)


class SettingsInput(BaseModel):
    focus_minutes: int = Field(ge=1, le=180)
    short_break_minutes: int = Field(ge=1, le=60)
    long_break_minutes: int = Field(ge=1, le=90)
    long_break_after: int = Field(ge=2, le=12)
    auto_start_breaks: bool = False
    auto_start_focus: bool = False
    notification_sound: bool = True
    browser_notifications: bool = False
    ticking_sound: bool = False


class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=4000)
    category: Category
    date: date
    timezone: str = Field(max_length=100)
    estimated_pomodoros: int = Field(ge=1, le=99)
    focus_minutes: int = Field(ge=1, le=180)
    short_break_minutes: int | None = Field(default=None, ge=1, le=60)
    long_break_minutes: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode='after')
    def valid(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError('Task name is required')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Choose a valid local timezone') from exc
        return self


class TaskCreate(TaskInput):
    request_id: UUID


class StartInput(BaseModel):
    id: UUID
    phase: Phase
    task_plan_id: int | None = Field(default=None, ge=1)
    task_occurrence_date: date | None = None
    task_date: date | None = None


class ActionInput(BaseModel):
    action: Literal['checkpoint', 'pause', 'resume', 'complete', 'stop']
    revision: int = Field(ge=0)
    verified_seconds: float = Field(ge=0)


def _task(session: Session, plan_id: int, original: date, day: date) -> tuple[StudyPlan, StudyPlanOverride | None, dict]:
    plan = session.get(StudyPlan, plan_id)
    if not plan:
        raise HTTPException(404, 'Study task not found')
    event = next((row for row in occurrences(session, day, day)
                  if row['plan_id'] == plan_id and row['occurrence_date'] == original), None)
    if not event:
        raise HTTPException(404, 'Study task occurrence not found')
    override = session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == plan_id,
                                                            StudyPlanOverride.occurrence_date == original)).first()
    return plan, override, event


def _config(plan: StudyPlan, override: StudyPlanOverride | None, defaults: FocusSettings) -> dict:
    def value(name: str):
        chosen = getattr(override, name) if override else None
        return chosen if chosen is not None else getattr(plan, name)
    return {
        'estimated_pomodoros': value('estimated_pomodoros') or 1,
        'focus_minutes': value('focus_minutes') or defaults.focus_minutes,
        'short_break_minutes': value('short_break_minutes'),
        'long_break_minutes': value('long_break_minutes'),
    }


def _task_rows(session: Session, day: date) -> list[dict]:
    defaults = settings(session)
    events = occurrences(session, day, day)
    ids = {row['plan_id'] for row in events}
    plans = {plan.id: plan for plan in session.exec(select(StudyPlan).where(StudyPlan.id.in_(ids))).all()} if ids else {}
    originals = {row['occurrence_date'] for row in events}
    overrides = session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id.in_(ids),
                                                            StudyPlanOverride.occurrence_date.in_(originals))).all() if ids else []
    changed = {(row.plan_id, row.occurrence_date): row for row in overrides}
    counts = session.exec(select(FocusSession.task_plan_id, FocusSession.task_occurrence_date, FocusSession.id)
                          .where(FocusSession.phase == 'focus', FocusSession.status == 'completed',
                                 FocusSession.task_plan_id.in_(ids),
                                 FocusSession.task_occurrence_date.in_(originals))).all() if ids else []
    completed: dict[tuple[int, date], int] = {}
    for plan_id, original, _ in counts:
        key = (plan_id, original)
        completed[key] = completed.get(key, 0) + 1
    return [{**event, **_config(plans[event['plan_id']], changed.get((event['plan_id'], event['occurrence_date'])), defaults),
             'completed_pomodoros': completed.get((event['plan_id'], event['occurrence_date']), 0)}
            for event in events]


@router.get('/settings', response_model=SettingsInput)
def get_settings():
    with Session(engine) as session:
        return settings(session)


@router.put('/settings', response_model=SettingsInput)
def save_settings(payload: SettingsInput):
    with write_session() as session:
        row = settings(session)
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        session.add(row)
    return payload


@router.get('/tasks')
def tasks(day: date):
    with Session(engine) as session:
        return _task_rows(session, day)


@router.post('/tasks', status_code=201)
def create_task(payload: TaskCreate):
    with write_session() as session:
        existing = session.exec(select(StudyPlan).where(StudyPlan.request_id == str(payload.request_id))).first()
        if existing:
            return {'plan_id': existing.id, 'date': existing.start_date}
        plan = StudyPlan(request_id=str(payload.request_id), title=payload.title, description=payload.description,
                         category=payload.category, start_date=payload.date, timezone=payload.timezone,
                         is_untimed=True, estimated_pomodoros=payload.estimated_pomodoros,
                         focus_minutes=payload.focus_minutes, short_break_minutes=payload.short_break_minutes,
                         long_break_minutes=payload.long_break_minutes)
        session.add(plan)
        session.flush()
        result = {'plan_id': plan.id, 'date': plan.start_date}
    return result


@router.put('/tasks/{plan_id}')
def edit_task(plan_id: int, payload: TaskInput, occurrence: date, day: date | None = None):
    with write_session() as session:
        plan, override, event = _task(session, plan_id, occurrence, day or occurrence)
        if plan.recurrence == 'none':
            for field, value in {'title': payload.title, 'description': payload.description,
                                 'category': payload.category, 'start_date': payload.date,
                                 'timezone': payload.timezone, 'estimated_pomodoros': payload.estimated_pomodoros,
                                 'focus_minutes': payload.focus_minutes,
                                 'short_break_minutes': payload.short_break_minutes,
                                 'long_break_minutes': payload.long_break_minutes}.items():
                setattr(plan, field, value)
            plan.updated_at = datetime.now(timezone.utc)
            session.add(plan)
        else:
            if payload.date != event['date'] and occurs_on(plan, payload.date):
                raise HTTPException(409, 'This series already has an occurrence on that date')
            other_move = session.exec(select(StudyPlanOverride.id).where(
                StudyPlanOverride.plan_id == plan_id,
                StudyPlanOverride.occurrence_date != occurrence,
                StudyPlanOverride.date_override == payload.date,
                StudyPlanOverride.status != 'deleted')).first()
            if other_move:
                raise HTTPException(409, 'Another occurrence was moved to that date')
            row = override or StudyPlanOverride(plan_id=plan_id, occurrence_date=occurrence)
            for field in ('start_time', 'end_time', 'is_untimed', 'resource_type', 'resource_id'):
                if not row.is_modified:
                    setattr(row, field, getattr(plan, field))
            row.title = payload.title
            row.description = payload.description
            row.category = payload.category
            row.date_override = payload.date if payload.date != occurrence else None
            row.is_modified = True
            row.estimated_pomodoros = payload.estimated_pomodoros
            row.focus_minutes = payload.focus_minutes
            row.short_break_minutes = payload.short_break_minutes
            row.long_break_minutes = payload.long_break_minutes
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
    return {'plan_id': plan_id, 'date': payload.date}


@router.delete('/tasks/{plan_id}', status_code=204)
def delete_task(plan_id: int, occurrence: date, day: date | None = None):
    with write_session() as session:
        plan, override, _ = _task(session, plan_id, occurrence, day or occurrence)
        if plan.recurrence == 'none':
            session.delete(plan)
        else:
            row = override or StudyPlanOverride(plan_id=plan_id, occurrence_date=occurrence)
            row.status = 'deleted'
            session.add(row)
    return Response(status_code=204)


@router.put('/tasks/{plan_id}/status')
def task_status(plan_id: int, occurrence: date, completed: bool, day: date | None = None):
    with write_session() as session:
        plan, override, _ = _task(session, plan_id, occurrence, day or occurrence)
        if plan.recurrence == 'none':
            plan.status = 'completed' if completed else 'planned'
            session.add(plan)
        else:
            row = override or StudyPlanOverride(plan_id=plan_id, occurrence_date=occurrence)
            row.status = 'completed' if completed else 'planned'
            session.add(row)
    return {'status': 'completed' if completed else 'planned'}


@router.get('/sessions/active')
def active_session():
    with Session(engine) as session:
        return session.exec(select(FocusSession).where(FocusSession.status.in_(['running', 'paused']))).first()


@router.post('/sessions', status_code=201)
def start_session(payload: StartInput):
    with write_session() as session:
        existing = session.get(FocusSession, str(payload.id))
        if existing:
            return existing
        if session.exec(select(FocusSession.id).where(FocusSession.status.in_(['running', 'paused']))).first():
            raise HTTPException(409, 'A focus timer is already active')
        defaults = settings(session)
        task_title = ''
        category = 'General Study'
        config = None
        if payload.task_plan_id is not None:
            if not payload.task_occurrence_date or not payload.task_date:
                raise HTTPException(422, 'Choose a task occurrence date')
            plan, override, event = _task(session, payload.task_plan_id, payload.task_occurrence_date, payload.task_date)
            task_title = event['title']
            category = event['category']
            config = _config(plan, override, defaults)
        if payload.phase == 'focus':
            minutes = config['focus_minutes'] if config else defaults.focus_minutes
        elif payload.phase == 'short_break':
            minutes = (config['short_break_minutes'] if config else None) or defaults.short_break_minutes
        else:
            minutes = (config['long_break_minutes'] if config else None) or defaults.long_break_minutes
        row = FocusSession(id=str(payload.id), phase=payload.phase, status='running', target_seconds=minutes * 60,
                           task_plan_id=payload.task_plan_id, task_occurrence_date=payload.task_occurrence_date,
                           task_date=payload.task_date,
                           task_title=task_title, category=category)
        session.add(row)
    return row


@router.put('/sessions/{session_id}')
def change_session(session_id: UUID, payload: ActionInput):
    with write_session() as session:
        row = session.get(FocusSession, str(session_id))
        if not row:
            raise HTTPException(404, 'Focus session not found')
        if payload.action == 'complete' and row.status == 'completed':
            return row
        if row.revision != payload.revision:
            raise HTTPException(409, 'Timer changed in another tab. Refresh its state.')
        if payload.action == 'resume':
            if row.status != 'paused':
                raise HTTPException(409, 'Only a paused timer can resume')
            row.status = 'running'
        elif payload.action == 'stop' and row.status == 'paused':
            if abs(payload.verified_seconds - row.verified_seconds) > 1:
                raise HTTPException(422, 'Paused time cannot increase verified duration')
            row.status = 'stopped'
        else:
            if row.status != 'running':
                raise HTTPException(409, 'This timer is not running')
            if payload.verified_seconds < row.verified_seconds - 0.1 or payload.verified_seconds > row.target_seconds + 1:
                raise HTTPException(422, 'Invalid verified duration')
            wall_seconds = (datetime.now(timezone.utc) - row.started_at.replace(tzinfo=timezone.utc)).total_seconds()
            if payload.verified_seconds > wall_seconds + 3:
                raise HTTPException(422, 'Verified time exceeds elapsed time')
            row.verified_seconds = min(payload.verified_seconds, row.target_seconds)
            if payload.action == 'pause':
                row.status = 'paused'
            elif payload.action == 'stop':
                row.status = 'stopped'
            elif payload.action == 'complete':
                if row.verified_seconds < row.target_seconds - 1:
                    raise HTTPException(409, 'Timer has not reached its target duration')
                row.status = 'completed'
                row.completed_at = datetime.now(timezone.utc)
        row.revision += 1
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    return row


@router.get('/sessions/history')
def history(start: date, end: date, timezone_name: str = 'UTC'):
    if end < start or (end - start).days > 62:
        raise HTTPException(422, 'Choose at most 63 days')
    zone = _zone(timezone_name)
    lower = datetime.combine(start, time.min, zone).astimezone(timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    with Session(engine) as session:
        rows = session.exec(select(FocusSession).where(FocusSession.status == 'completed',
                                                       FocusSession.completed_at >= lower,
                                                       FocusSession.completed_at < upper)
                            .order_by(FocusSession.completed_at.desc())).all()
        # SQLite returns naive datetimes. Explicit UTC offsets keep browser history in local time.
        return [{**row.model_dump(), 'started_at': row.started_at.replace(tzinfo=timezone.utc),
                 'updated_at': row.updated_at.replace(tzinfo=timezone.utc),
                 'completed_at': row.completed_at.replace(tzinfo=timezone.utc)} for row in rows]


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, 'Invalid timezone') from exc


@router.get('/stats')
def stats(day: date, timezone_name: str = 'UTC'):
    zone = _zone(timezone_name)
    week_start = day - timedelta(days=day.weekday())
    lower = datetime.combine(week_start, time.min, zone).astimezone(timezone.utc)
    upper = datetime.combine(week_start + timedelta(days=7), time.min, zone).astimezone(timezone.utc)
    with Session(engine) as session:
        rows = session.exec(select(FocusSession).where(FocusSession.phase == 'focus',
                                                       FocusSession.status == 'completed',
                                                       FocusSession.completed_at >= lower,
                                                       FocusSession.completed_at < upper)).all()
        daily = {day.isoformat(): {'pomodoros': 0, 'focus_seconds': 0} for day in (week_start + timedelta(days=i) for i in range(7))}
        for row in rows:
            key = row.completed_at.replace(tzinfo=timezone.utc).astimezone(zone).date().isoformat()
            daily[key]['pomodoros'] += 1
            daily[key]['focus_seconds'] += row.target_seconds
        tasks = _task_rows(session, day)
        today = daily[day.isoformat()]
        completed_total = session.exec(select(func.count()).select_from(FocusSession).where(
            FocusSession.phase == 'focus', FocusSession.status == 'completed')).one()
        return {'completed_total': completed_total,
                'today': {**today, 'tasks_completed': sum(row['status'] == 'completed' for row in tasks),
                          'tasks_total': len(tasks), 'estimated_pomodoros': sum(row['estimated_pomodoros'] for row in tasks)},
                'week': {'pomodoros': sum(row['pomodoros'] for row in daily.values()),
                         'focus_seconds': sum(row['focus_seconds'] for row in daily.values()),
                         'daily': daily}}
