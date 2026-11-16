from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlmodel import Session, select
from app.db import engine, get_session
from app.models import NotebookNote, PDFDocument, Podcast, PodcastEpisode, ReviewEvent, Video, VocabularyItem
from app.schemas import ReviewCreate, VocabularyCreate, VocabularyUpdate
from app.services.scheduling import schedule

router = APIRouter(prefix='/api/vocabulary', tags=['vocabulary'])

def item_or_404(session: Session, item_id: int) -> VocabularyItem:
    item = session.get(VocabularyItem, item_id)
    if item is None: raise HTTPException(404, 'Vocabulary item not found')
    return item

@router.get('')
def list_vocabulary(video_id: int | None = None, pdf_id: int | None = None, episode_id: int | None = None, session: Session = Depends(get_session)):
    query = select(VocabularyItem).order_by(VocabularyItem.created_at.desc())
    if video_id is not None: query = query.where(VocabularyItem.source_video_id == video_id)
    if pdf_id is not None: query = query.where(VocabularyItem.source_pdf_id == pdf_id)
    if episode_id is not None: query = query.where(VocabularyItem.source_episode_id == episode_id)
    return session.exec(query).all()

@router.get('/stats')
def stats(session: Session = Depends(get_session)):
    items = session.exec(select(VocabularyItem)).all()
    today = datetime.now(timezone.utc).date()
    events = session.exec(select(ReviewEvent)).all()
    return {
        'total': len(items), 'new': sum(i.status == 'new' for i in items),
        'learning': sum(i.status == 'learning' for i in items),
        'reviewing': sum(i.status == 'reviewing' for i in items),
        'mastered': sum(i.status == 'mastered' for i in items),
        'due': sum(i.next_review_at is None or i.next_review_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc) for i in items),
        'reviewed_today': sum(e.reviewed_at.date() == today for e in events),
    }

@router.get('/review/due')
def due(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    items = session.exec(select(VocabularyItem).order_by(VocabularyItem.created_at)).all()
    return [i for i in items if i.next_review_at is None or i.next_review_at.replace(tzinfo=timezone.utc) <= now]

@router.post('', status_code=status.HTTP_201_CREATED)
def create_vocabulary(payload: VocabularyCreate, session: Session = Depends(get_session)):
    if sum(value is not None for value in (payload.source_video_id, payload.source_pdf_id, payload.source_note_id, payload.source_episode_id)) > 1:
        raise HTTPException(422, 'Choose one vocabulary source')
    if payload.source_video_id is not None and not session.get(Video, payload.source_video_id): raise HTTPException(404, 'Source video not found')
    pdf = session.get(PDFDocument, payload.source_pdf_id) if payload.source_pdf_id is not None else None
    if payload.source_pdf_id is not None and pdf is None:
        raise HTTPException(404, 'Source PDF not found')
    note = session.get(NotebookNote, payload.source_note_id) if payload.source_note_id is not None else None
    if payload.source_note_id is not None and note is None:
        raise HTTPException(404, 'Source note not found')
    if payload.source_page is not None and (pdf is None or payload.source_page > pdf.total_pages):
        raise HTTPException(422, 'Invalid source page')
    if payload.source_timestamp is not None and payload.source_video_id is None:
        raise HTTPException(422, 'Video timestamp requires a video source')
    episode = session.get(PodcastEpisode, payload.source_episode_id) if payload.source_episode_id is not None else None
    if payload.source_episode_id is not None and episode is None:
        raise HTTPException(404, 'Source podcast episode not found')
    if payload.source_episode_timestamp is not None and episode is None:
        raise HTTPException(422, 'Episode timestamp requires a podcast source')
    existing = select(VocabularyItem).where(VocabularyItem.text == payload.text.strip(), VocabularyItem.source_video_id == payload.source_video_id, VocabularyItem.source_pdf_id == payload.source_pdf_id, VocabularyItem.source_note_id == payload.source_note_id, VocabularyItem.source_episode_id == payload.source_episode_id)
    if session.exec(existing).first():
        raise HTTPException(409, 'This expression already exists for this source.')
    item = VocabularyItem(**payload.model_dump()); item.text = item.text.strip(); item.source_pdf_title = pdf.title if pdf else None
    item.source_note_title = note.title if note else None
    if episode:
        item.source_episode_title = episode.title
        podcast = session.get(Podcast, episode.podcast_id)
        item.source_podcast_title = podcast.title if podcast else None
    session.add(item); session.commit(); session.refresh(item); return item

@router.get('/{item_id}')
def get_vocabulary(item_id: int, session: Session = Depends(get_session)): return item_or_404(session, item_id)

@router.patch('/{item_id}')
def update_vocabulary(item_id: int, payload: VocabularyUpdate, session: Session = Depends(get_session)):
    item = item_or_404(session, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    session.add(item); session.commit(); session.refresh(item); return item

@router.get('/{item_id}/reviews')
def review_history(item_id: int, session: Session = Depends(get_session)):
    item_or_404(session, item_id)
    return session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id).order_by(ReviewEvent.reviewed_at.desc())).all()

@router.post('/{item_id}/review')
def review(item_id: int, payload: ReviewCreate):
    if payload.rating not in {'again', 'good', 'easy'}: raise HTTPException(422, 'Rating must be again, good, or easy')
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            with Session(bind=connection) as session:
                item = item_or_404(session, item_id)
                if item.review_count != payload.expected_review_count: raise HTTPException(409, 'Card was already reviewed. Reload the queue.')
                now = datetime.now(timezone.utc)
                if item.next_review_at and item.next_review_at.replace(tzinfo=timezone.utc) > now: raise HTTPException(409, 'Card is not due yet.')
                previous = item.status
                schedule(item, payload.rating, now)
                event = ReviewEvent(vocabulary_id=item_id, rating=payload.rating, reviewed_at=now, previous_status=previous, next_status=item.status, interval_days=item.interval_days)
                session.add(item); session.add(event); session.flush()
                result = item.model_dump()
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise

@router.delete('/{item_id}', status_code=204)
def delete_vocabulary(item_id: int, session: Session = Depends(get_session)):
    item = item_or_404(session, item_id)
    for event in session.exec(select(ReviewEvent).where(ReviewEvent.vocabulary_id == item_id)).all(): session.delete(event)
    session.delete(item); session.commit()
