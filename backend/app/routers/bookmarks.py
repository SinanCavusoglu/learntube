"""Video and PDF position bookmarks stored only in the local database."""

import math
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import get_session
from app.models import Bookmark, PDFDocument, Video, now

router = APIRouter(tags=['bookmarks'])


class VideoBookmarkCreate(BaseModel):
    timestamp_seconds: float = Field(ge=0)
    title: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=2000)


class PDFBookmarkCreate(BaseModel):
    page_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=2000)


class BookmarkUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=2000)


class BookmarkRead(BaseModel):
    id: int
    type: Literal['video', 'pdf']
    video_id: int | None
    pdf_id: int | None
    timestamp_seconds: float | None
    page_number: int | None
    title: str
    note: str
    source_title: str
    created_at: datetime
    updated_at: datetime


def _clean(title: str) -> str:
    value = title.strip()
    if not value:
        raise HTTPException(422, 'Bookmark title cannot be blank.')
    return value


def _read(bookmark: Bookmark, session: Session) -> BookmarkRead:
    if bookmark.video_id is not None:
        video = session.get(Video, bookmark.video_id)
        source_title = video.title if video else 'Unavailable video'
        source_type = 'video'
    else:
        pdf = session.get(PDFDocument, bookmark.pdf_id)
        source_title = pdf.title if pdf else 'Unavailable PDF'
        source_type = 'pdf'
    return BookmarkRead(id=bookmark.id, type=source_type, video_id=bookmark.video_id, pdf_id=bookmark.pdf_id,
                        timestamp_seconds=bookmark.timestamp_seconds, page_number=bookmark.page_number,
                        title=bookmark.title, note=bookmark.note, source_title=source_title,
                        created_at=bookmark.created_at, updated_at=bookmark.updated_at)


def _bookmark_or_404(session: Session, bookmark_id: int) -> Bookmark:
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise HTTPException(404, 'Bookmark not found.')
    return bookmark


def _save(session: Session, bookmark: Bookmark) -> BookmarkRead:
    session.add(bookmark)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, 'A bookmark with this title already exists at this position.') from exc
    session.refresh(bookmark)
    return _read(bookmark, session)


@router.get('/api/bookmarks', response_model=list[BookmarkRead])
def list_bookmarks(type: Literal['all', 'video', 'pdf'] = 'all', q: str = Query(default='', max_length=200),
                   session: Session = Depends(get_session)):
    statement = select(Bookmark)
    if type == 'video':
        statement = statement.where(Bookmark.video_id.is_not(None))
    elif type == 'pdf':
        statement = statement.where(Bookmark.pdf_id.is_not(None))
    query = q.strip()
    if query:
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        video_ids = select(Video.id).where(Video.title.ilike(pattern, escape='\\'))
        pdf_ids = select(PDFDocument.id).where(PDFDocument.title.ilike(pattern, escape='\\'))
        statement = statement.where(or_(Bookmark.title.ilike(pattern, escape='\\'),
                                        Bookmark.note.ilike(pattern, escape='\\'),
                                        Bookmark.video_id.in_(video_ids), Bookmark.pdf_id.in_(pdf_ids)))
    bookmarks = session.exec(statement.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())).all()
    return [_read(bookmark, session) for bookmark in bookmarks]


@router.get('/api/videos/{video_id}/bookmarks', response_model=list[BookmarkRead])
def video_bookmarks(video_id: int, session: Session = Depends(get_session)):
    if not session.get(Video, video_id):
        raise HTTPException(404, 'Video not found.')
    bookmarks = session.exec(select(Bookmark).where(Bookmark.video_id == video_id).order_by(Bookmark.timestamp_seconds, Bookmark.id)).all()
    return [_read(bookmark, session) for bookmark in bookmarks]


@router.post('/api/videos/{video_id}/bookmarks', response_model=BookmarkRead, status_code=status.HTTP_201_CREATED)
def create_video_bookmark(video_id: int, payload: VideoBookmarkCreate, session: Session = Depends(get_session)):
    if not session.get(Video, video_id):
        raise HTTPException(404, 'Video not found.')
    if not math.isfinite(payload.timestamp_seconds):
        raise HTTPException(422, 'Video timestamp must be finite.')
    return _save(session, Bookmark(video_id=video_id, timestamp_seconds=payload.timestamp_seconds,
                                   title=_clean(payload.title), note=payload.note))


@router.get('/api/pdfs/{pdf_id}/bookmarks', response_model=list[BookmarkRead])
def pdf_bookmarks(pdf_id: int, session: Session = Depends(get_session)):
    if not session.get(PDFDocument, pdf_id):
        raise HTTPException(404, 'PDF not found.')
    bookmarks = session.exec(select(Bookmark).where(Bookmark.pdf_id == pdf_id).order_by(Bookmark.page_number, Bookmark.id)).all()
    return [_read(bookmark, session) for bookmark in bookmarks]


@router.post('/api/pdfs/{pdf_id}/bookmarks', response_model=BookmarkRead, status_code=status.HTTP_201_CREATED)
def create_pdf_bookmark(pdf_id: int, payload: PDFBookmarkCreate, session: Session = Depends(get_session)):
    pdf = session.get(PDFDocument, pdf_id)
    if pdf is None:
        raise HTTPException(404, 'PDF not found.')
    if payload.page_number > pdf.total_pages:
        raise HTTPException(422, 'Page is outside the document.')
    return _save(session, Bookmark(pdf_id=pdf_id, page_number=payload.page_number,
                                   title=_clean(payload.title), note=payload.note))


@router.patch('/api/bookmarks/{bookmark_id}', response_model=BookmarkRead)
def update_bookmark(bookmark_id: int, payload: BookmarkUpdate, session: Session = Depends(get_session)):
    bookmark = _bookmark_or_404(session, bookmark_id)
    bookmark.title = _clean(payload.title)
    bookmark.note = payload.note
    bookmark.updated_at = now()
    return _save(session, bookmark)


@router.delete('/api/bookmarks/{bookmark_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    session.delete(_bookmark_or_404(session, bookmark_id))
    session.commit()
