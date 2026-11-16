import re
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session, select
from app.db import engine
from app.models import WritingSession

router = APIRouter(prefix='/api/writing', tags=['writing'])

def utcnow(): return datetime.now(timezone.utc)
def words(value: str) -> int: return len(re.findall(r'\S+', value))
def current_elapsed(item: WritingSession, at: datetime) -> float:
    started = item.timer_started_at
    if item.timer_status != 'running' or started is None: return item.elapsed_seconds
    return item.elapsed_seconds + max(0, (at - started.replace(tzinfo=timezone.utc)).total_seconds())
def get_or_404(session: Session, item_id: int) -> WritingSession:
    item = session.get(WritingSession, item_id)
    if not item: raise HTTPException(404, 'Writing session not found')
    return item

class CreateWriting(BaseModel):
    task_type: Literal[1, 2]
    question: str = Field(min_length=1, max_length=20000)
    timer_duration_seconds: int = Field(ge=60, le=14400)

class SaveWriting(BaseModel):
    expected_revision: int = Field(ge=0)
    question: str = Field(max_length=20000)
    essay_content: str = Field(max_length=200000)
    notes: str = Field(max_length=100000)


class SaveFeedback(BaseModel):
    content: str = Field(max_length=500000)
    expected_revision: int = Field(ge=0)

class Action(BaseModel):
    expected_revision: int = Field(ge=0)
    action: Literal['start', 'pause', 'reset']

def mutate(item_id: int, revision: int, callback):
    # BEGIN IMMEDIATE serializes writers; stale autosaves cannot overwrite newer data.
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            with Session(bind=connection) as session:
                item = get_or_404(session, item_id)
                if item.revision != revision: raise HTTPException(409, 'This session changed. Reload before saving again.')
                if item.status == 'completed': raise HTTPException(409, 'Completed sessions are read-only.')
                callback(item)
                item.updated_at = utcnow()
                item.revision += 1
                session.add(item)
                session.flush()
                result = item.model_dump()
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise

@router.get('')
def list_writing():
    with Session(engine) as session: return session.exec(select(WritingSession).order_by(WritingSession.updated_at.desc())).all()

@router.get('/stats')
def writing_stats():
    with Session(engine) as session: items = session.exec(select(WritingSession)).all()
    completed = [i for i in items if i.status == 'completed']
    return {'completed': len(completed), 'active_minutes': round(sum(current_elapsed(i, utcnow()) for i in items)/60, 1), 'task1_count': sum(i.task_type == 1 for i in items), 'task2_count': sum(i.task_type == 2 for i in items), 'completed_words': sum(i.word_count for i in completed), 'sessions_by_date': [{'date': i.created_at.date().isoformat(), 'task_type': i.task_type, 'status': i.status} for i in items]}

@router.post('', status_code=status.HTTP_201_CREATED)
def create_writing(payload: CreateWriting):
    with Session(engine) as session:
        item = WritingSession(**payload.model_dump())
        session.add(item); session.commit(); session.refresh(item); return item

@router.get('/{item_id}')
def get_writing(item_id: int):
    with Session(engine) as session: return get_or_404(session, item_id)


@router.put('/{item_id}/feedback')
def save_feedback(item_id: int, payload: SaveFeedback):
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            with Session(bind=connection) as session:
                item = get_or_404(session, item_id)
                if item.feedback_revision != payload.expected_revision:
                    raise HTTPException(409, 'Feedback changed in another session. Your local draft was kept.')
                item.chatgpt_feedback = payload.content
                item.feedback_revision += 1
                session.add(item)
                session.flush()
                result = item.model_dump()
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise

@router.patch('/{item_id}')
def save_writing(item_id: int, payload: SaveWriting):
    def change(item):
        item.question = payload.question
        item.essay_content = payload.essay_content
        item.notes = payload.notes
        item.word_count = words(payload.essay_content)
    return mutate(item_id, payload.expected_revision, change)

@router.post('/{item_id}/timer')
def timer_action(item_id: int, payload: Action):
    def change(item):
        now = utcnow()
        if payload.action == 'start':
            if item.timer_status != 'running': item.timer_started_at = now; item.timer_status = 'running'
        elif payload.action == 'pause':
            item.elapsed_seconds = current_elapsed(item, now)
            item.timer_started_at = None; item.timer_status = 'paused'
        else:
            item.elapsed_seconds = 0; item.timer_started_at = None; item.timer_status = 'idle'
    return mutate(item_id, payload.expected_revision, change)

@router.post('/{item_id}/finish')
def finish_writing(item_id: int, payload: SaveWriting):
    def change(item):
        now = utcnow()
        item.question = payload.question; item.essay_content = payload.essay_content; item.notes = payload.notes
        item.word_count = words(payload.essay_content)
        item.elapsed_seconds = current_elapsed(item, now)
        item.timer_status = 'paused'; item.timer_started_at = None
        item.status = 'completed'; item.completed_at = now
    return mutate(item_id, payload.expected_revision, change)

@router.delete('/{item_id}', status_code=204)
def delete_writing(item_id: int):
    with Session(engine) as session:
        session.delete(get_or_404(session, item_id)); session.commit()
