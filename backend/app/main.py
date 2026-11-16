from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import CORS_ORIGINS
from app.db import create_db_and_tables
from app.routers.videos import router as videos_router
from app.routers.vocabulary import router as vocabulary_router
from app.routers.writing import router as writing_router
from app.routers.dashboard import router as dashboard_router
from app.routers.pdfs import router as pdfs_router
from app.routers.ai import router as ai_router
from app.routers.notebooks import router as notebooks_router
from app.routers.dictionary import router as dictionary_router
@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield
app = FastAPI(title='LearnTube API', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=['*'], allow_headers=['*'], expose_headers=['Accept-Ranges', 'Content-Range', 'Content-Length'])
app.include_router(videos_router)
app.include_router(vocabulary_router)
app.include_router(writing_router)
app.include_router(dashboard_router)
app.include_router(pdfs_router)
app.include_router(ai_router)
app.include_router(notebooks_router)
app.include_router(dictionary_router)
@app.get('/api/health', tags=['health'])
async def health_check() -> dict[str, str]: return {'status': 'ok'}
