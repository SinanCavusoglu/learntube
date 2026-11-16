from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models import (EpisodeNote, EpisodeProgress, EpisodeTranscriptSegment, ExternalListening,
                        Podcast, PodcastEpisode, VocabularyItem)
from app.services.podcasts import (MAX_FEED_BYTES, MAX_TRANSCRIPT_BYTES, PodcastFetchError,
                                   fetch_public, fetch_public_metadata, parse_feed, parse_transcript)
from app.services.podcast_directory import lookup_feed, resolve_podcast_url, search_podcasts

router = APIRouter(prefix='/api/podcasts', tags=['podcasts'])


class PodcastCreate(BaseModel):
    feed_url: str = Field(min_length=8, max_length=2048)


class DirectoryCreate(BaseModel):
    directory_id: int = Field(gt=0)


class NoteUpdate(BaseModel):
    content: str = Field(max_length=100_000)


class ManualTranscript(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class ProgressUpdate(BaseModel):
    position_seconds: float = Field(ge=0, le=7 * 24 * 3600)
    duration_seconds: float | None = Field(default=None, gt=0, le=7 * 24 * 3600)
    playback_speed: float = 1
    completed: bool = False


class ExternalListenCreate(BaseModel):
    duration_seconds: float | None = Field(default=None, gt=0, le=7 * 24 * 3600)


def podcast_or_404(session: Session, podcast_id: int) -> Podcast:
    item = session.get(Podcast, podcast_id)
    if not item:
        raise HTTPException(404, 'Podcast not found')
    return item


def episode_or_404(session: Session, episode_id: int) -> PodcastEpisode:
    item = session.get(PodcastEpisode, episode_id)
    if not item:
        raise HTTPException(404, 'Episode not found')
    return item


def _load_feed(url: str):
    try:
        return resolve_podcast_url(url)
    except PodcastFetchError as exc:
        raise HTTPException(422, str(exc)) from exc


def _sync(session: Session, podcast: Podcast, feed: dict, entries: list[dict]):
    podcast.title = feed['title']
    podcast.description = feed['description']
    podcast.image_url = feed['image_url']
    podcast.publisher = feed['publisher'] or podcast.publisher
    podcast.refreshed_at = datetime.now(timezone.utc)
    session.add(podcast)
    existing = {item.guid: item for item in session.exec(select(PodcastEpisode).where(PodcastEpisode.podcast_id == podcast.id)).all()}
    new_count = 0
    seen: set[str] = set()
    for row in entries:
        if row['guid'] in seen:
            continue
        seen.add(row['guid'])
        item = existing.get(row['guid'])
        if item is None:
            item = next((saved for saved in existing.values() if saved.audio_url and saved.audio_url == row['audio_url'] and saved.title == row['title']), None)
        if item is None:
            item = PodcastEpisode(podcast_id=podcast.id, **row)
            new_count += 1
        else:
            for key, value in row.items():
                if key == 'guid' and item.guid != value:
                    continue
                setattr(item, key, value)
        session.add(item)
    session.commit()
    session.refresh(podcast)
    return podcast, new_count


@router.get('')
def list_podcasts(session: Session = Depends(get_session)):
    podcasts = session.exec(select(Podcast).order_by(Podcast.created_at.desc())).all()
    counts = dict(session.exec(select(PodcastEpisode.podcast_id, func.count()).group_by(PodcastEpisode.podcast_id)).all())
    latest = dict(session.exec(select(PodcastEpisode.podcast_id, func.max(PodcastEpisode.published_at)).group_by(PodcastEpisode.podcast_id)).all())
    return [{**item.model_dump(), 'episode_count': counts.get(item.id, 0), 'latest_episode_at': latest.get(item.id)} for item in podcasts]


@router.get('/search')
def directory_search(q: str = Query(min_length=2, max_length=100)):
    try:
        return search_podcasts(q.strip()) if q.strip() else []
    except PodcastFetchError as exc:
        raise HTTPException(502, f'Podcast search is unavailable: {exc}') from exc


@router.post('/from-directory', status_code=status.HTTP_201_CREATED)
def add_from_directory(payload: DirectoryCreate, session: Session = Depends(get_session)):
    try:
        feed_url = lookup_feed(payload.directory_id)
    except PodcastFetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _add(session, feed_url, payload.directory_id)


def _add(session: Session, url: str, directory_id: int | None = None):
    result, feed, entries = _load_feed(url)
    if session.exec(select(Podcast).where(Podcast.feed_url == result.url)).first():
        raise HTTPException(409, 'This podcast is already subscribed.')
    podcast = Podcast(feed_url=result.url, external_directory_id=directory_id, etag=result.etag,
                      last_modified=result.last_modified, **feed)
    session.add(podcast)
    session.flush()
    saved, _ = _sync(session, podcast, feed, entries)
    return saved


@router.post('', status_code=status.HTTP_201_CREATED)
def add_podcast(payload: PodcastCreate, session: Session = Depends(get_session)):
    return _add(session, payload.feed_url)


@router.get('/{podcast_id}')
def get_podcast(podcast_id: int, session: Session = Depends(get_session)):
    return podcast_or_404(session, podcast_id)


@router.post('/{podcast_id}/refresh')
def refresh_podcast(podcast_id: int, session: Session = Depends(get_session)):
    podcast = podcast_or_404(session, podcast_id)
    try:
        result = fetch_public_metadata(podcast.feed_url, MAX_FEED_BYTES, podcast.etag, podcast.last_modified)
    except PodcastFetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.not_modified:
        podcast.refreshed_at = datetime.now(timezone.utc)
        session.add(podcast)
        session.commit()
        session.refresh(podcast)
        return {'podcast': podcast, 'new_episodes': 0, 'not_modified': True}
    try:
        feed, entries = parse_feed(result.data)
    except PodcastFetchError as exc:
        raise HTTPException(422, str(exc)) from exc
    duplicate = session.exec(select(Podcast).where(Podcast.feed_url == result.url, Podcast.id != podcast_id)).first()
    if duplicate:
        raise HTTPException(409, 'The feed redirects to another subscribed podcast.')
    podcast.feed_url = result.url
    podcast.etag = result.etag
    podcast.last_modified = result.last_modified
    saved, new_count = _sync(session, podcast, feed, entries)
    return {'podcast': saved, 'new_episodes': new_count, 'not_modified': False}


@router.get('/{podcast_id}/episodes')
def list_episodes(podcast_id: int, q: str = '', session: Session = Depends(get_session)):
    podcast_or_404(session, podcast_id)
    statement = select(PodcastEpisode).where(PodcastEpisode.podcast_id == podcast_id)
    if q.strip():
        term = f'%{q.strip()[:100]}%'
        statement = statement.where(or_(PodcastEpisode.title.ilike(term), PodcastEpisode.description.ilike(term)))
    episodes = session.exec(statement.order_by(PodcastEpisode.published_at.desc(), PodcastEpisode.id.desc())).all()
    progress = {item.episode_id: item for item in session.exec(select(EpisodeProgress).where(EpisodeProgress.episode_id.in_([e.id for e in episodes]))).all()} if episodes else {}
    return [{**item.model_dump(), 'progress': progress.get(item.id)} for item in episodes]


@router.delete('/{podcast_id}', status_code=204)
def remove_podcast(podcast_id: int, session: Session = Depends(get_session)):
    podcast = podcast_or_404(session, podcast_id)
    episodes = session.exec(select(PodcastEpisode).where(PodcastEpisode.podcast_id == podcast_id)).all()
    for episode in episodes:
        for word in session.exec(select(VocabularyItem).where(VocabularyItem.source_episode_id == episode.id)).all():
            word.source_episode_id = None
            word.source_episode_title = episode.title
            word.source_podcast_title = podcast.title
            session.add(word)
        for model in (EpisodeTranscriptSegment, EpisodeNote, EpisodeProgress, ExternalListening):
            session.exec(delete(model).where(model.episode_id == episode.id))
        session.delete(episode)
    session.delete(podcast)
    session.commit()


@router.get('/episodes/search')
def search_episodes(q: str = '', session: Session = Depends(get_session)):
    term = q.strip()[:100]
    if not term:
        return []
    episodes = session.exec(select(PodcastEpisode).where(or_(PodcastEpisode.title.ilike(f'%{term}%'), PodcastEpisode.description.ilike(f'%{term}%'))).order_by(PodcastEpisode.published_at.desc()).limit(80)).all()
    podcasts = {item.id: item.title for item in session.exec(select(Podcast)).all()}
    return [{**item.model_dump(), 'podcast_title': podcasts.get(item.podcast_id, 'Podcast')} for item in episodes]


@router.get('/episodes/{episode_id}')
def get_episode(episode_id: int, session: Session = Depends(get_session)):
    episode = episode_or_404(session, episode_id)
    podcast = podcast_or_404(session, episode.podcast_id)
    progress = session.exec(select(EpisodeProgress).where(EpisodeProgress.episode_id == episode_id)).first()
    return {**episode.model_dump(), 'podcast_title': podcast.title, 'podcast_image_url': podcast.image_url, 'progress': progress}


@router.patch('/episodes/{episode_id}/progress')
def update_progress(episode_id: int, payload: ProgressUpdate, session: Session = Depends(get_session)):
    episode_or_404(session, episode_id)
    if payload.playback_speed not in {0.75, 1, 1.25, 1.5, 2}:
        raise HTTPException(422, 'Unsupported playback speed')
    item = session.exec(select(EpisodeProgress).where(EpisodeProgress.episode_id == episode_id)).first() or EpisodeProgress(episode_id=episode_id)
    item.position_seconds = payload.position_seconds
    item.duration_seconds = payload.duration_seconds
    item.playback_speed = payload.playback_speed
    item.completed = item.completed or payload.completed
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post('/episodes/{episode_id}/listened', status_code=201)
def mark_listened(episode_id: int, payload: ExternalListenCreate, session: Session = Depends(get_session)):
    episode_or_404(session, episode_id)
    item = ExternalListening(episode_id=episode_id, duration_seconds=payload.duration_seconds)
    progress = session.exec(select(EpisodeProgress).where(EpisodeProgress.episode_id == episode_id)).first() or EpisodeProgress(episode_id=episode_id)
    progress.completed = True
    progress.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.add(progress)
    session.commit()
    session.refresh(item)
    return item


@router.get('/episodes/{episode_id}/notes')
def get_notes(episode_id: int, session: Session = Depends(get_session)):
    episode_or_404(session, episode_id)
    return session.exec(select(EpisodeNote).where(EpisodeNote.episode_id == episode_id)).first() or EpisodeNote(episode_id=episode_id)


@router.put('/episodes/{episode_id}/notes')
def save_notes(episode_id: int, payload: NoteUpdate, session: Session = Depends(get_session)):
    episode_or_404(session, episode_id)
    note = session.exec(select(EpisodeNote).where(EpisodeNote.episode_id == episode_id)).first() or EpisodeNote(episode_id=episode_id)
    note.content = payload.content
    note.updated_at = datetime.now(timezone.utc)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.get('/episodes/{episode_id}/transcript')
def get_transcript(episode_id: int, session: Session = Depends(get_session)):
    episode = episode_or_404(session, episode_id)
    cached = session.exec(select(EpisodeTranscriptSegment).where(EpisodeTranscriptSegment.episode_id == episode_id).order_by(EpisodeTranscriptSegment.start, EpisodeTranscriptSegment.id)).all()
    if cached or not episode.transcript_url or not episode.transcript_type:
        return cached
    try:
        data, _, _ = fetch_public(episode.transcript_url, MAX_TRANSCRIPT_BYTES)
        rows = parse_transcript(data, episode.transcript_type)
    except PodcastFetchError as exc:
        raise HTTPException(424, f'Transcript unavailable: {exc}') from exc
    segments = [EpisodeTranscriptSegment(episode_id=episode_id, **row) for row in rows]
    session.add_all(segments)
    session.flush()
    result = [segment.model_dump() for segment in segments]
    session.commit()
    return result


@router.put('/episodes/{episode_id}/transcript/manual')
def save_manual_transcript(episode_id: int, payload: ManualTranscript, session: Session = Depends(get_session)):
    episode_or_404(session, episode_id)
    rows = [line.strip()[:4000] for line in payload.text.splitlines() if line.strip()][:5000]
    if not rows:
        raise HTTPException(422, 'Paste a transcript with readable text.')
    session.exec(delete(EpisodeTranscriptSegment).where(EpisodeTranscriptSegment.episode_id == episode_id))
    segments = [EpisodeTranscriptSegment(episode_id=episode_id, text=row, is_manual=True) for row in rows]
    session.add_all(segments)
    session.flush()
    result = [segment.model_dump() for segment in segments]
    session.commit()
    return result
