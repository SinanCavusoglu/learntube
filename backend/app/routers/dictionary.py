from fastapi import APIRouter, Query

from app.services.dictionary import lookup

router = APIRouter(prefix='/api/dictionary', tags=['dictionary'])


@router.get('/lookup')
def dictionary_lookup(word: str = Query(min_length=1, max_length=500)):
    return lookup(word)
