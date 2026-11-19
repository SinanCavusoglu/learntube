import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import MAX_PDF_SIZE_MB, PDF_STORAGE_DIR
from app.db import get_session
from app.models import Bookmark, PDFDocument, PDFNote, VocabularyItem, now
from app.schemas import NoteUpdate
from app.services.search_index import ensure_index

router = APIRouter(prefix='/api/pdfs', tags=['pdfs'])
CHUNK_BYTES = 1024 * 1024

def pdf_or_404(session: Session, pdf_id: int) -> PDFDocument:
    document = session.get(PDFDocument, pdf_id)
    if document is None:
        raise HTTPException(404, 'PDF not found')
    return document

def file_path(document: PDFDocument) -> Path:
    if not re.fullmatch(r'[0-9a-f]{32}\.pdf', document.stored_filename):
        raise HTTPException(500, 'Invalid stored PDF filename')
    path = (PDF_STORAGE_DIR / document.stored_filename).resolve()
    if path.parent != PDF_STORAGE_DIR:
        raise HTTPException(500, 'Invalid PDF path')
    return path

class ProgressUpdate(BaseModel):
    page: int = Field(ge=1)
    zoom: float = Field(ge=0.5, le=3)

@router.get('')
def list_pdfs(session: Session = Depends(get_session)):
    return session.exec(select(PDFDocument).order_by(PDFDocument.created_at.desc())).all()

@router.post('/upload', status_code=status.HTTP_201_CREATED)
def upload_pdf(file: UploadFile = File(...), session: Session = Depends(get_session)):
    original_name = ''.join(char for char in (file.filename or '').replace('\\', '/').split('/')[-1].strip() if char.isprintable())
    if not original_name or not original_name.lower().endswith('.pdf'):
        raise HTTPException(415, 'Choose a .pdf file')
    original_name = original_name[:255]
    PDF_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f'{uuid4().hex}.pdf'
    final_path = PDF_STORAGE_DIR / stored_name
    temp_path = PDF_STORAGE_DIR / f'{uuid4().hex}.uploading'
    size = 0
    try:
        with temp_path.open('xb') as target:
            first = file.file.read(CHUNK_BYTES)
            if not first.startswith(b'%PDF-'):
                raise HTTPException(415, 'File does not have a PDF signature')
            while first:
                size += len(first)
                if size > MAX_PDF_SIZE_MB * 1024 * 1024:
                    raise HTTPException(413, f'PDF exceeds the {MAX_PDF_SIZE_MB} MB limit')
                target.write(first)
                first = file.file.read(CHUNK_BYTES)
        reader = None
        try:
            reader = PdfReader(temp_path, strict=False)
            if reader.is_encrypted:
                raise HTTPException(422, 'Password-protected PDFs are not supported')
            pages = len(reader.pages)
            if pages < 1:
                raise ValueError('PDF has no pages')
            reader.pages[0].mediabox
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, 'PDF is malformed or cannot be read') from exc
        finally:
            if reader is not None:
                reader.close()
        os.replace(temp_path, final_path)
        document = PDFDocument(title=Path(original_name).stem or 'Untitled PDF', original_filename=original_name,
                               stored_filename=stored_name, file_size_bytes=size, total_pages=pages)
        session.add(document)
        session.commit()
        session.refresh(document)
        try:
            ensure_index(session.get_bind(), PDF_STORAGE_DIR)
        except Exception:
            # A readable PDF remains usable even if text extraction fails.
            pass
        return document
    except Exception:
        temp_path.unlink(missing_ok=True)
        if final_path.exists():
            final_path.unlink()
        raise

@router.get('/{pdf_id}')
def get_pdf(pdf_id: int, session: Session = Depends(get_session)):
    document = pdf_or_404(session, pdf_id)
    if not file_path(document).is_file():
        raise HTTPException(404, 'PDF file is missing')
    document.last_opened_at = now()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document

@router.get('/{pdf_id}/file')
def get_pdf_file(pdf_id: int, session: Session = Depends(get_session)):
    document = pdf_or_404(session, pdf_id)
    path = file_path(document)
    if not path.is_file():
        raise HTTPException(404, 'PDF file is missing')
    return FileResponse(path, media_type='application/pdf', filename=document.original_filename,
                        content_disposition_type='inline', headers={'Cache-Control': 'private, max-age=60'})

@router.patch('/{pdf_id}/progress')
def update_progress(pdf_id: int, payload: ProgressUpdate, session: Session = Depends(get_session)):
    document = pdf_or_404(session, pdf_id)
    if payload.page > document.total_pages:
        raise HTTPException(422, 'Page is outside the document')
    document.last_page = payload.page
    document.zoom = payload.zoom
    document.reading_progress = round((payload.page - 1) / (document.total_pages - 1) * 100, 1) if document.total_pages > 1 else 0
    document.last_opened_at = now()
    document.updated_at = document.last_opened_at
    session.add(document)
    session.commit()
    session.refresh(document)
    return document

@router.get('/{pdf_id}/notes')
def get_notes(pdf_id: int, session: Session = Depends(get_session)):
    pdf_or_404(session, pdf_id)
    return session.exec(select(PDFNote).where(PDFNote.pdf_id == pdf_id)).first() or PDFNote(pdf_id=pdf_id)

@router.put('/{pdf_id}/notes')
def update_notes(pdf_id: int, payload: NoteUpdate, session: Session = Depends(get_session)):
    pdf_or_404(session, pdf_id)
    note = session.exec(select(PDFNote).where(PDFNote.pdf_id == pdf_id)).first() or PDFNote(pdf_id=pdf_id)
    note.content = payload.content
    note.updated_at = now()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note

@router.get('/{pdf_id}/vocabulary')
def pdf_vocabulary(pdf_id: int, session: Session = Depends(get_session)):
    pdf_or_404(session, pdf_id)
    return session.exec(select(VocabularyItem).where(VocabularyItem.source_pdf_id == pdf_id).order_by(VocabularyItem.created_at.desc())).all()

@router.delete('/{pdf_id}', status_code=204)
def delete_pdf(pdf_id: int, session: Session = Depends(get_session)):
    document = pdf_or_404(session, pdf_id)
    path = file_path(document)
    parked = path.with_name(f'{uuid4().hex}.deleting')
    if path.exists():
        os.replace(path, parked)
    try:
        for item in session.exec(select(VocabularyItem).where(VocabularyItem.source_pdf_id == pdf_id)).all():
            item.source_pdf_id = None
            item.source_pdf_title = document.title
            session.add(item)
        session.exec(delete(PDFNote).where(PDFNote.pdf_id == pdf_id))
        session.exec(delete(Bookmark).where(Bookmark.pdf_id == pdf_id))
        session.delete(document)
        session.commit()
    except Exception:
        session.rollback()
        if parked.exists():
            os.replace(parked, path)
        raise
    parked.unlink(missing_ok=True)
