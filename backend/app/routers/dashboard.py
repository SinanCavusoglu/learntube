from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.db import get_session
from app.models import ExternalListening, PDFDocument, Podcast, PodcastEpisode, ReviewEvent, StudyActivity, Video, VocabularyItem, WritingSession
from app.services.activity import KINDS, daily_durations, streaks, timezone_or_422, utc

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])

class ActivityCreate(BaseModel):
    event_key: UUID
    client_session_id: UUID
    activity_type: str
    source_id: int | None = Field(default=None, ge=1)
    ended_at: datetime
    duration_seconds: float = Field(gt=0, le=10)

@router.post('/activity')
def record_activity(payload: ActivityCreate, session: Session = Depends(get_session)):
    if payload.activity_type not in KINDS:
        raise HTTPException(422, 'Invalid activity type')
    now = datetime.now(timezone.utc)
    end = utc(payload.ended_at)
    if abs((now - end).total_seconds()) > 120:
        raise HTTPException(422, 'Activity timestamp is out of range')
    existing = session.exec(select(StudyActivity).where(StudyActivity.event_key == str(payload.event_key))).first()
    if existing:
        return {'id': existing.id, 'recorded': False}
    if payload.source_id is not None:
        model = {'video': Video, 'vocabulary': VocabularyItem, 'writing': WritingSession, 'pdf': PDFDocument, 'podcast': PodcastEpisode}[payload.activity_type]
        if not session.get(model, payload.source_id):
            raise HTTPException(404, 'Study source not found')
    start = end - timedelta(seconds=payload.duration_seconds)
    overlap = session.exec(select(StudyActivity).where(
        StudyActivity.started_at < end,
        StudyActivity.ended_at > start,
    ).order_by(StudyActivity.ended_at.desc()).limit(1)).first()
    if overlap is not None:
        previous_end = utc(overlap.ended_at)
        if previous_end > end or (previous_end - start).total_seconds() > 0.1:
            raise HTTPException(409, 'Overlapping study activity')
        start = previous_end
    item = StudyActivity(event_key=str(payload.event_key), client_session_id=str(payload.client_session_id),
                         activity_type=payload.activity_type, source_id=payload.source_id,
                         started_at=start, ended_at=end, active_duration_seconds=(end-start).total_seconds())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {'id': item.id, 'recorded': True}

@router.get('')
def dashboard(timezone_name: str = 'UTC', session: Session = Depends(get_session)):
    zone = timezone_or_422(timezone_name)
    today = datetime.now(zone).date()
    first = today - timedelta(days=364)
    week_start = today - timedelta(days=today.weekday())
    activities = session.exec(select(StudyActivity).order_by(StudyActivity.started_at)).all()
    days = daily_durations(activities, zone)
    current_streak, longest_streak = streaks(days, today)
    daily = []
    for offset in range(365):
        day = first + timedelta(days=offset)
        kinds = days.get(day, {kind: 0 for kind in KINDS})
        daily.append({'date': day.isoformat(), **kinds, 'total': sum(kinds.values()), 'reviews': 0})
    review_events = session.exec(select(ReviewEvent).where(ReviewEvent.reviewed_at >= datetime.combine(first, datetime.min.time(), zone).astimezone(timezone.utc))).all()
    review_counts: dict[str, int] = {}
    for event in review_events:
        day = utc(event.reviewed_at).astimezone(zone).date().isoformat()
        review_counts[day] = review_counts.get(day, 0) + 1
    for row in daily:
        row['reviews'] = review_counts.get(row['date'], 0)
    weekly = [next((row for row in daily if row['date'] == (week_start + timedelta(days=i)).isoformat()), None) for i in range(7)]
    weekly = [row if row else {'date': (week_start + timedelta(days=i)).isoformat(), **{kind: 0 for kind in KINDS}, 'total': 0, 'reviews': 0} for i, row in enumerate(weekly)]
    vocab_counts = dict(session.exec(select(VocabularyItem.status, func.count()).group_by(VocabularyItem.status)).all())
    due_count = session.exec(select(func.count()).select_from(VocabularyItem).where(or_(VocabularyItem.next_review_at == None, VocabularyItem.next_review_at <= datetime.now(timezone.utc)))).one()
    completed = session.exec(select(WritingSession).where(WritingSession.status == 'completed').order_by(WritingSession.completed_at.desc())).all()
    recent_writing = completed[0] if completed else None
    total_by_kind = {kind: sum(row.get(kind, 0) for row in days.values()) for kind in KINDS}
    recent = []
    recent_activities = session.exec(select(StudyActivity).order_by(StudyActivity.ended_at.desc()).limit(60)).all()
    seen = set()
    completed_ids = {item.id for item in completed}
    video_ids = {item.source_id for item in recent_activities if item.activity_type == 'video' and item.source_id}
    video_titles = {v.id: v.title for v in session.exec(select(Video).where(Video.id.in_(video_ids))).all()} if video_ids else {}
    pdf_ids = {item.source_id for item in recent_activities if item.activity_type == 'pdf' and item.source_id}
    pdf_titles = {p.id: p.title for p in session.exec(select(PDFDocument).where(PDFDocument.id.in_(pdf_ids))).all()} if pdf_ids else {}
    podcast_ids = {item.source_id for item in recent_activities if item.activity_type == 'podcast' and item.source_id}
    podcast_titles = {e.id: e.title for e in session.exec(select(PodcastEpisode).where(PodcastEpisode.id.in_(podcast_ids))).all()} if podcast_ids else {}
    writing_ids = {item.source_id for item in recent_activities if item.activity_type == 'writing' and item.source_id}
    existing_writing = {w.id for w in session.exec(select(WritingSession).where(WritingSession.id.in_(writing_ids))).all()} if writing_ids else set()
    for item in recent_activities:
        if item.activity_type == 'vocabulary' and review_counts.get(utc(item.ended_at).astimezone(zone).date().isoformat(), 0):
            continue
        if item.activity_type == 'writing' and item.source_id in completed_ids:
            continue
        key = (item.activity_type, None if item.activity_type == 'vocabulary' else item.source_id, utc(item.ended_at).date())
        if key in seen: continue
        seen.add(key)
        if item.activity_type == 'video':
            label = video_titles.get(item.source_id, 'Saved video')
            link = f'/videos/{item.source_id}' if item.source_id in video_titles else '/videos'
        elif item.activity_type == 'pdf':
            label = f'Read {pdf_titles.get(item.source_id, "PDF document")}'
            link = f'/pdfs/{item.source_id}' if item.source_id in pdf_titles else '/pdfs'
        elif item.activity_type == 'podcast':
            label = f'Listened to {podcast_titles.get(item.source_id, "podcast episode")}'
            link = f'/podcasts/episodes/{item.source_id}' if item.source_id in podcast_titles else '/podcasts'
        elif item.activity_type == 'writing':
            label = 'Writing practice'
            link = f'/writing/{item.source_id}' if item.source_id in existing_writing else '/writing'
        else:
            label = 'Flashcard practice'
            link = '/vocabulary/review'
        recent.append({'type': item.activity_type, 'description': label, 'at': utc(item.ended_at).isoformat(), 'link': link})
    for item in completed[:10]:
        recent.append({'type': 'writing', 'description': f'Completed IELTS Writing Task {item.task_type}', 'at': utc(item.completed_at or item.updated_at).isoformat(), 'link': f'/writing/{item.id}'})
    for item in session.exec(select(ExternalListening).order_by(ExternalListening.listened_at.desc()).limit(8)).all():
        title = session.get(PodcastEpisode, item.episode_id)
        recent.append({'type': 'podcast', 'description': f'Marked {title.title if title else "podcast episode"} as listened outside LearnTube', 'at': utc(item.listened_at).isoformat(), 'link': f'/podcasts/episodes/{item.episode_id}' if title else '/podcasts'})
    reviews_by_day: dict[str, list[datetime | int]] = {}
    recent_review_events = session.exec(select(ReviewEvent).order_by(ReviewEvent.reviewed_at.desc()).limit(80)).all()
    for event in recent_review_events:
        at = utc(event.reviewed_at)
        day = at.astimezone(zone).date().isoformat()
        if day not in reviews_by_day:
            reviews_by_day[day] = [at, 0]
        reviews_by_day[day][0] = max(reviews_by_day[day][0], at)
        reviews_by_day[day][1] += 1
    for at, count in sorted(reviews_by_day.values(), key=lambda value: value[0], reverse=True)[:8]:
        recent.append({'type': 'vocabulary', 'description': f'Reviewed {count} flashcard{"s" if count != 1 else ""}', 'at': at.isoformat(), 'link': '/vocabulary'})
    added_by_day: dict[str, list[datetime | int]] = {}
    for item in session.exec(select(VocabularyItem).order_by(VocabularyItem.created_at.desc()).limit(60)).all():
        at = utc(item.created_at)
        day = at.astimezone(zone).date().isoformat()
        if day not in added_by_day:
            added_by_day[day] = [at, 0]
        added_by_day[day][0] = max(added_by_day[day][0], at)
        added_by_day[day][1] += 1
    for at, count in sorted(added_by_day.values(), key=lambda value: value[0], reverse=True)[:8]:
        recent.append({'type': 'vocabulary', 'description': f'Added {count} expression{"s" if count != 1 else ""}', 'at': at.isoformat(), 'link': '/vocabulary'})
    recent.sort(key=lambda row: row['at'], reverse=True)
    recent_pdfs = session.exec(select(PDFDocument).where(PDFDocument.last_opened_at != None).order_by(PDFDocument.last_opened_at.desc()).limit(3)).all()
    return {
        'total_seconds': sum(total_by_kind.values()), 'today_seconds': sum(days.get(today, {}).values()),
        'week_seconds': sum(row['total'] for row in weekly), 'current_streak': current_streak, 'longest_streak': longest_streak,
        'videos_saved': session.exec(select(func.count()).select_from(Video)).one(),
        'pdfs': {'total': session.exec(select(func.count()).select_from(PDFDocument)).one(), 'active_seconds': total_by_kind['pdf'], 'recent': [{'id': p.id, 'title': p.title, 'last_opened_at': utc(p.last_opened_at).isoformat(), 'last_page': p.last_page, 'total_pages': p.total_pages} for p in recent_pdfs]},
        'podcasts': {'subscriptions': session.exec(select(func.count()).select_from(Podcast)).one(), 'active_seconds': total_by_kind['podcast']},
        'vocabulary': {'total': sum(vocab_counts.values()), **{key: vocab_counts.get(key, 0) for key in ('new', 'learning', 'reviewing', 'mastered')}, 'due': due_count, 'reviewed_today': review_counts.get(today.isoformat(), 0)},
        'writing': {'completed': len(completed), 'task1': sum(x.task_type == 1 for x in completed), 'task2': sum(x.task_type == 2 for x in completed), 'active_seconds': total_by_kind['writing'], 'recent': {'id': recent_writing.id, 'task_type': recent_writing.task_type, 'completed_at': utc(recent_writing.completed_at or recent_writing.updated_at).isoformat()} if recent_writing else None},
        'daily': daily, 'weekly': weekly, 'recent': recent[:8],
    }
