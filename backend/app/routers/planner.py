from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import get_session
from app.models import StudyPlan, StudyPlanOverride
from app.services.planner import DESTINATIONS, RESOURCE_MODELS, FALLBACK, occurs_on, occurrences, summary

router = APIRouter(prefix='/api/planner', tags=['planner'])
Category = Literal['Vocabulary', 'Flashcards', 'Listening', 'Reading', 'Writing', 'Grammar', 'General Study']
Repeat = Literal['none', 'daily', 'weekly', 'custom']
PlanStatus = Literal['planned', 'completed', 'skipped']


class PlanInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    category: Category
    description: str = Field(default='', max_length=4000)
    start_date: date
    start_time: time | None = None
    end_time: time | None = None
    is_untimed: bool = False
    recurrence: Repeat = 'none'
    weekdays: list[int] = Field(default_factory=list)
    repeat_until: date | None = None
    timezone: str = Field(min_length=1, max_length=100)
    resource_type: str | None = None
    resource_id: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def validate_plan(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError('Title is required')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Invalid timezone') from exc
        if self.is_untimed:
            if self.start_time is not None or self.end_time is not None:
                raise ValueError('Untimed tasks cannot have start or end times')
        else:
            if self.start_time is None or self.end_time is None:
                raise ValueError('Timed plans need start and end times')
            if self.start_time.tzinfo or self.end_time.tzinfo:
                raise ValueError('Use local wall-clock times without UTC offsets')
            if self.start_time.second or self.end_time.second or self.start_time.microsecond or self.end_time.microsecond:
                raise ValueError('Use minute precision for plan times')
            if self.end_time <= self.start_time:
                raise ValueError('End time must be later than start time; overnight plans are not supported')
        if self.recurrence == 'custom':
            if not self.weekdays or any(day not in range(7) for day in self.weekdays):
                raise ValueError('Choose at least one valid weekday')
            self.weekdays = sorted(set(self.weekdays))
        elif self.weekdays:
            raise ValueError('Weekdays are only used for custom recurrence')
        if self.repeat_until and self.recurrence == 'none':
            raise ValueError('An end date requires recurrence')
        if self.resource_type is not None and self.resource_type not in {*DESTINATIONS, *RESOURCE_MODELS}:
            raise ValueError('Invalid LearnTube destination')
        if (self.resource_type in RESOURCE_MODELS) != (self.resource_id is not None):
            raise ValueError('Specific resources need a type and ID')
        return self


class PlanRecord(PlanInput):
    id: int
    request_id: UUID
    status: PlanStatus


class OccurrenceRecord(BaseModel):
    plan_id: int
    occurrence_date: date
    date: date
    title: str
    category: Category
    description: str
    start_time: time | None
    end_time: time | None
    is_untimed: bool
    recurring: bool
    recurrence: Repeat
    timezone: str
    status: PlanStatus
    resource_type: str | None
    resource_id: int | None
    destination_url: str
    resource_missing: bool


class PlannerStats(BaseModel):
    planned_minutes: int
    completed_minutes: int
    completed_tasks: int
    total_tasks: int


class StatusInput(BaseModel):
    status: PlanStatus


class CreateInput(PlanInput):
    request_id: UUID


def _range(start: date, end: date) -> None:
    if end < start or (end - start).days > 62:
        raise HTTPException(422, 'Choose a date range of at most 63 days')


def _plan(session: Session, plan_id: int) -> StudyPlan:
    plan = session.get(StudyPlan, plan_id)
    if plan is None:
        raise HTTPException(404, 'Study plan not found')
    return plan


def _resource(session: Session, payload: PlanInput) -> None:
    if payload.resource_type in RESOURCE_MODELS and not session.get(RESOURCE_MODELS[payload.resource_type], payload.resource_id):
        raise HTTPException(404, 'Linked study resource not found')


def _occurrence(plan: StudyPlan, original: date) -> None:
    if plan.recurrence == 'none' or not occurs_on(plan, original):
        raise HTTPException(404, 'Recurring occurrence not found')


def _override(session: Session, plan: StudyPlan, original: date) -> StudyPlanOverride:
    _occurrence(plan, original)
    row = session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == plan.id,
                                                       StudyPlanOverride.occurrence_date == original)).first()
    if row is None:
        row = StudyPlanOverride(plan_id=plan.id, occurrence_date=original)
    return row


def _apply(plan: StudyPlan, payload: PlanInput) -> None:
    for key in ('title', 'category', 'description', 'start_date', 'start_time', 'end_time', 'is_untimed',
                'recurrence', 'repeat_until', 'timezone', 'resource_type', 'resource_id'):
        setattr(plan, key, getattr(payload, key))
    plan.weekdays = ','.join(str(day) for day in payload.weekdays)
    plan.updated_at = datetime.now(timezone.utc)


@router.get('', response_model=list[OccurrenceRecord])
def calendar(start: date, end: date, session: Session = Depends(get_session)):
    _range(start, end)
    return occurrences(session, start, end)


@router.get('/stats', response_model=PlannerStats)
def stats(start: date, end: date, session: Session = Depends(get_session)):
    _range(start, end)
    return summary(occurrences(session, start, end))


@router.post('', response_model=PlanRecord, status_code=201)
def create(payload: CreateInput, session: Session = Depends(get_session)):
    if payload.repeat_until and payload.repeat_until < payload.start_date:
        raise HTTPException(422, 'Recurrence end date must be on or after the first date')
    existing = session.exec(select(StudyPlan).where(StudyPlan.request_id == str(payload.request_id))).first()
    if existing:
        return {**existing.model_dump(), 'weekdays': [int(day) for day in existing.weekdays.split(',') if day]}
    _resource(session, payload)
    plan = StudyPlan(request_id=str(payload.request_id))
    _apply(plan, payload)
    session.add(plan)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(StudyPlan).where(StudyPlan.request_id == str(payload.request_id))).first()
        if existing is None:
            raise
        return {**existing.model_dump(), 'weekdays': [int(day) for day in existing.weekdays.split(',') if day]}
    session.refresh(plan)
    return {**plan.model_dump(), 'weekdays': payload.weekdays}


@router.get('/{plan_id}', response_model=PlanRecord)
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    return {**plan.model_dump(), 'weekdays': [int(day) for day in plan.weekdays.split(',') if day]}


@router.patch('/{plan_id}', response_model=OccurrenceRecord | PlanRecord)
def edit(plan_id: int, payload: PlanInput, occurrence: date | None = None, session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    _resource(session, payload)
    if occurrence is None:
        if payload.repeat_until and payload.repeat_until < payload.start_date:
            raise HTTPException(422, 'Recurrence end date must be on or after the first date')
        if plan.recurrence == 'none' and payload.recurrence != 'none' and plan.status != 'planned':
            raise HTTPException(409, 'Mark the plan incomplete before turning it into a recurring series')
        candidate = StudyPlan(start_date=payload.start_date, recurrence=payload.recurrence,
                              weekdays=','.join(str(day) for day in payload.weekdays), repeat_until=payload.repeat_until)
        for moved_row in session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == plan.id)).all():
            if not occurs_on(candidate, moved_row.occurrence_date):
                raise HTTPException(409, 'Series changes would hide an existing occurrence change; edit that occurrence first')
            if not moved_row.is_modified or moved_row.date_override is None or moved_row.status == 'deleted':
                continue
            if (moved_row.date_override != moved_row.occurrence_date and
                    occurs_on(candidate, moved_row.date_override)):
                raise HTTPException(409, 'Series changes would duplicate a moved occurrence; move that occurrence first')
        _apply(plan, payload)
        session.add(plan); session.commit(); session.refresh(plan)
        return {**plan.model_dump(), 'weekdays': payload.weekdays}
    row = _override(session, plan, occurrence)
    if row.status == 'deleted':
        raise HTTPException(409, 'This occurrence was deleted')
    if (payload.recurrence != plan.recurrence or payload.timezone != plan.timezone or
            payload.weekdays != [int(day) for day in plan.weekdays.split(',') if day] or
            payload.repeat_until != plan.repeat_until):
        raise HTTPException(422, 'Edit the whole series to change recurrence settings')
    if payload.start_date != occurrence and occurs_on(plan, payload.start_date):
        raise HTTPException(409, 'This series already has an occurrence on the selected date')
    moved = session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == plan.id,
                                                        StudyPlanOverride.date_override == payload.start_date,
                                                        StudyPlanOverride.occurrence_date != occurrence,
                                                        StudyPlanOverride.status != 'deleted')).first()
    if moved:
        raise HTTPException(409, 'Another occurrence of this series was moved to that date')
    for key in ('title', 'category', 'description', 'start_time', 'end_time', 'is_untimed', 'resource_type', 'resource_id'):
        setattr(row, key, getattr(payload, key))
    row.date_override = payload.start_date if payload.start_date != occurrence else None
    row.is_modified = True
    row.updated_at = datetime.now(timezone.utc)
    session.add(row); session.commit()
    return next(item for item in occurrences(session, payload.start_date, payload.start_date)
                if item['plan_id'] == plan.id and item['occurrence_date'] == occurrence)


@router.patch('/{plan_id}/status', response_model=OccurrenceRecord)
def set_status(plan_id: int, payload: StatusInput, occurrence: date | None = None, session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    if plan.recurrence == 'none':
        if occurrence and occurrence != plan.start_date:
            raise HTTPException(404, 'Occurrence not found')
        plan.status = payload.status
        plan.updated_at = datetime.now(timezone.utc)
        day = plan.start_date
        session.add(plan)
    else:
        if occurrence is None:
            raise HTTPException(422, 'Choose a recurring occurrence date')
        row = _override(session, plan, occurrence)
        if row.status == 'deleted':
            raise HTTPException(409, 'This occurrence was deleted')
        row.status = payload.status
        row.updated_at = datetime.now(timezone.utc)
        day = row.date_override or occurrence
        session.add(row)
    session.commit()
    return next(item for item in occurrences(session, day, day)
                if item['plan_id'] == plan.id and item['occurrence_date'] == (occurrence or day))


@router.delete('/{plan_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete(plan_id: int, occurrence: date | None = None, session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    if occurrence is not None:
        row = _override(session, plan, occurrence)
        row.status = 'deleted'
        session.add(row)
    else:
        for row in session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id == plan_id)).all():
            session.delete(row)
        session.delete(plan)
    session.commit()
    return Response(status_code=204)
