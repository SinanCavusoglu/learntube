from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, update
from sqlmodel import Session, select

from app.db import get_session
from app.models import Notebook, NotebookNote, VocabularyItem, now

router = APIRouter(prefix='/api/notebooks', tags=['notebooks'])

class NotebookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=1000)

class NotebookUpdate(NotebookCreate):
    pass

class NoteCreate(BaseModel):
    notebook_id: int
    title: str = Field(default='Untitled note', max_length=200)
    content: str = Field(default='', max_length=2_000_000)

class NoteUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    notebook_id: int
    title: str = Field(max_length=200)
    content: str = Field(max_length=2_000_000)
    is_pinned: bool

def notebook_or_404(session: Session, notebook_id: int) -> Notebook:
    notebook = session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(404, 'Notebook not found')
    return notebook

def note_or_404(session: Session, note_id: int) -> NotebookNote:
    note = session.get(NotebookNote, note_id)
    if note is None:
        raise HTTPException(404, 'Note not found')
    return note

@router.get('')
def list_notebooks(session: Session = Depends(get_session)):
    return session.exec(select(Notebook).order_by(Notebook.updated_at.desc())).all()

@router.post('', status_code=status.HTTP_201_CREATED)
def create_notebook(payload: NotebookCreate, session: Session = Depends(get_session)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Notebook name is required')
    notebook = Notebook(name=name, description=payload.description.strip())
    session.add(notebook)
    session.commit()
    session.refresh(notebook)
    return notebook

@router.patch('/{notebook_id}')
def update_notebook(notebook_id: int, payload: NotebookUpdate, session: Session = Depends(get_session)):
    notebook = notebook_or_404(session, notebook_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Notebook name is required')
    notebook.name = name
    notebook.description = payload.description.strip()
    notebook.updated_at = now()
    session.add(notebook)
    session.commit()
    session.refresh(notebook)
    return notebook

@router.delete('/{notebook_id}', status_code=204)
def delete_notebook(notebook_id: int, session: Session = Depends(get_session)):
    notebook = notebook_or_404(session, notebook_id)
    for note in session.exec(select(NotebookNote).where(NotebookNote.notebook_id == notebook_id)).all():
        for word in session.exec(select(VocabularyItem).where(VocabularyItem.source_note_id == note.id)).all():
            word.source_note_id = None
            word.source_note_title = note.title
            session.add(word)
    session.exec(delete(NotebookNote).where(NotebookNote.notebook_id == notebook_id))
    session.delete(notebook)
    session.commit()

@router.get('/notes/search')
def search_notes(q: str = Query(default='', max_length=200), notebook_id: int | None = None,
                 pinned: bool = False, session: Session = Depends(get_session)):
    statement = select(NotebookNote)
    if notebook_id is not None:
        notebook_or_404(session, notebook_id)
        statement = statement.where(NotebookNote.notebook_id == notebook_id)
    if pinned:
        statement = statement.where(NotebookNote.is_pinned == True)  # noqa: E712
    if q.strip():
        pattern = f'%{q.strip()}%'
        statement = statement.where(or_(NotebookNote.title.ilike(pattern), NotebookNote.content.ilike(pattern)))
    return session.exec(statement.order_by(NotebookNote.is_pinned.desc(), NotebookNote.updated_at.desc())).all()

@router.post('/notes', status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, session: Session = Depends(get_session)):
    notebook_or_404(session, payload.notebook_id)
    note = NotebookNote(notebook_id=payload.notebook_id, title=payload.title.strip() or 'Untitled note', content=payload.content)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note

@router.get('/notes/{note_id}')
def get_note(note_id: int, session: Session = Depends(get_session)):
    return note_or_404(session, note_id)

@router.patch('/notes/{note_id}')
def update_note(note_id: int, payload: NoteUpdate, session: Session = Depends(get_session)):
    note_or_404(session, note_id)
    notebook_or_404(session, payload.notebook_id)
    result = session.exec(update(NotebookNote).where(NotebookNote.id == note_id,
                                                    NotebookNote.revision == payload.expected_revision).values(
        notebook_id=payload.notebook_id, title=payload.title.strip() or 'Untitled note',
        content=payload.content, is_pinned=payload.is_pinned,
        revision=NotebookNote.revision + 1, updated_at=now()))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, 'Note changed in another session. Your draft is still available locally.')
    session.exec(update(VocabularyItem).where(VocabularyItem.source_note_id == note_id).values(source_note_title=payload.title.strip() or 'Untitled note'))
    session.commit()
    return session.get(NotebookNote, note_id)

@router.delete('/notes/{note_id}', status_code=204)
def delete_note(note_id: int, session: Session = Depends(get_session)):
    note = note_or_404(session, note_id)
    for word in session.exec(select(VocabularyItem).where(VocabularyItem.source_note_id == note.id)).all():
        word.source_note_id = None
        word.source_note_title = note.title
        session.add(word)
    session.delete(note)
    session.commit()
