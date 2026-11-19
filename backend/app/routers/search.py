from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.config import PDF_STORAGE_DIR
from app.db import get_session
from app.services.search_index import ensure_index, search

router = APIRouter(prefix='/api/search', tags=['search'])


@router.get('')
def global_search(q: str = Query(default='', max_length=200),
                  type: str = Query(default='all', pattern='^(all|vocabulary|videos|pdfs|notebook)$'),
                  limit: int = Query(default=8, ge=1, le=50), offset: int = Query(default=0, ge=0, le=10000),
                  session: Session = Depends(get_session)):
    query = q.strip()
    if len(query) < 2:
        return {'groups': {'vocabulary': [], 'videos': [], 'pdfs': [], 'notebook': []},
                'has_more': {'vocabulary': False, 'videos': False, 'pdfs': False, 'notebook': False}}
    engine = session.get_bind()
    fts = ensure_index(engine, PDF_STORAGE_DIR)
    return search(engine, query, type, limit, offset, fts)
