from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, delete
from app.db import get_session
from app.models import Bookmark, TranscriptSegment, Video, VideoNote, VocabularyItem
from app.schemas import ManualTranscript, NoteUpdate, ProgressUpdate, VideoCreate
from app.services.youtube import extract_video_id, fallback_title, fetch_title
from app.services.transcripts import fetch_english

router = APIRouter(prefix='/api/videos', tags=['videos'])
def video_or_404(session: Session, video_id: int) -> Video:
    video = session.get(Video, video_id)
    if not video: raise HTTPException(404, 'Video not found')
    return video

@router.get('')
def list_videos(session: Session = Depends(get_session)):
    videos = session.exec(select(Video).order_by(Video.created_at.desc())).all()
    # Repair a few previously saved placeholder titles per visit without changing other data.
    changed = False
    for video in [item for item in videos if item.title == fallback_title(item.youtube_id)][:3]:
        title = fetch_title(video.youtube_id)
        if title:
            video.title = title
            session.add(video)
            changed = True
    if changed:
        session.commit()
        for video in videos:
            session.refresh(video)
    return videos
@router.post('', status_code=status.HTTP_201_CREATED)
def create_video(payload: VideoCreate, session: Session = Depends(get_session)):
    youtube_id = extract_video_id(payload.url)
    if not youtube_id: raise HTTPException(422, 'Enter a valid YouTube watch, short, or youtu.be URL.')
    if session.exec(select(Video).where(Video.youtube_id == youtube_id)).first(): raise HTTPException(409, 'This video is already in your library.')
    video = Video(youtube_id=youtube_id, url=payload.url.strip(), title=fetch_title(youtube_id) or fallback_title(youtube_id))
    session.add(video); session.commit(); session.refresh(video); return video
@router.get('/{video_id}')
def get_video(video_id: int, session: Session = Depends(get_session)):
    video = video_or_404(session, video_id)
    if video.title == fallback_title(video.youtube_id):
        title = fetch_title(video.youtube_id)
        if title:
            video.title = title
            session.add(video)
            session.commit()
    return video
@router.delete('/{video_id}', status_code=204)
def delete_video(video_id: int, session: Session = Depends(get_session)):
    video_or_404(session, video_id)
    for item in session.exec(select(VocabularyItem).where(VocabularyItem.source_video_id == video_id)).all():
        item.source_video_id = None
        item.source_timestamp = None
        session.add(item)
    session.exec(delete(Bookmark).where(Bookmark.video_id == video_id)); session.exec(delete(TranscriptSegment).where(TranscriptSegment.video_id == video_id)); session.exec(delete(VideoNote).where(VideoNote.video_id == video_id)); session.delete(session.get(Video, video_id)); session.commit()
@router.put('/{video_id}/progress')
def update_progress(video_id: int, payload: ProgressUpdate, session: Session = Depends(get_session)):
    video = video_or_404(session, video_id); video.playback_position = payload.position; video.last_watched_at = datetime.now(timezone.utc); session.add(video); session.commit(); session.refresh(video); return video
@router.get('/{video_id}/notes')
def get_notes(video_id: int, session: Session = Depends(get_session)):
    video_or_404(session, video_id); return session.exec(select(VideoNote).where(VideoNote.video_id == video_id)).first() or VideoNote(video_id=video_id)
@router.put('/{video_id}/notes')
def update_notes(video_id: int, payload: NoteUpdate, session: Session = Depends(get_session)):
    video_or_404(session, video_id); note = session.exec(select(VideoNote).where(VideoNote.video_id == video_id)).first() or VideoNote(video_id=video_id); note.content=payload.content; note.updated_at=datetime.now(timezone.utc); session.add(note); session.commit(); session.refresh(note); return note
@router.get('/{video_id}/transcript')
def get_transcript(video_id: int, session: Session = Depends(get_session)):
    video = video_or_404(session, video_id); cached = session.exec(select(TranscriptSegment).where(TranscriptSegment.video_id == video_id).order_by(TranscriptSegment.start)).all()
    if cached: return cached
    try: rows = fetch_english(video.youtube_id)
    except Exception as exc: raise HTTPException(424, 'English captions could not be retrieved. Paste a transcript manually to continue.') from exc
    segments=[TranscriptSegment(video_id=video_id, **row) for row in rows]; session.add_all(segments); session.commit(); return segments
@router.post('/{video_id}/transcript/refresh')
def refresh_transcript(video_id: int, session: Session = Depends(get_session)):
    video = video_or_404(session, video_id)
    try:
        rows = fetch_english(video.youtube_id)
    except Exception as exc:
        raise HTTPException(424, 'English captions could not be retrieved. The saved transcript was kept.') from exc
    if not rows:
        raise HTTPException(424, 'No English captions were returned. The saved transcript was kept.')
    # Do not discard the cached transcript until the replacement is available.
    # Delete and insert commit together, so a database error rolls both back.
    session.exec(delete(TranscriptSegment).where(TranscriptSegment.video_id == video_id))
    segments = [TranscriptSegment(video_id=video_id, **row) for row in rows]
    session.add_all(segments)
    session.commit()
    return segments
@router.put('/{video_id}/transcript/manual')
def manual_transcript(video_id: int, payload: ManualTranscript, session: Session = Depends(get_session)):
    video_or_404(session, video_id)
    segments = [TranscriptSegment(video_id=video_id, text=line.strip(), is_manual=True)
                for line in payload.text.splitlines() if line.strip()]
    if not segments:
        raise HTTPException(422, 'Enter at least one line of transcript text')
    session.exec(delete(TranscriptSegment).where(TranscriptSegment.video_id == video_id))
    session.add_all(segments)
    session.commit()
    return segments
