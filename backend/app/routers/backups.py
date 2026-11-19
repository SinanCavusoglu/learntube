"""Loopback-only backup endpoints. No user-supplied filesystem paths are accepted."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.config import BASE_DIR, PDF_STORAGE_DIR
from app.db import engine
from app.services.backups import BackupError, BackupService, MAX_ARCHIVE_BYTES
from app.services.search_index import ensure_index

router = APIRouter(prefix='/api/backups', tags=['backups'])
service = BackupService(engine, PDF_STORAGE_DIR, BASE_DIR / 'safety-backups', BASE_DIR / '.backup-state')


def _receive(file: UploadFile, destination: Path) -> None:
    size = 0
    with destination.open('wb') as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise BackupError('The backup archive exceeds the size limit.')
            output.write(chunk)


@router.post('/create')
def create_backup():
    directory = Path(tempfile.mkdtemp(prefix='learntube-download-'))
    filename = f'learntube-backup-{datetime.now():%Y-%m-%d-%H%M%S}.zip'
    destination = directory / filename
    try:
        service.create(destination)
        return FileResponse(destination, media_type='application/zip', filename=filename,
                            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True))
    except BackupError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


@router.post('/inspect')
def inspect_backup(file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory(prefix='learntube-inspect-') as temp:
        path = Path(temp) / 'upload.zip'
        try:
            _receive(file, path)
            return service.validate(path, Path(temp) / 'staging')
        except BackupError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post('/restore')
def restore_backup(file: UploadFile = File(...), expected_hash: str = Form(...), confirmation: str = Form(...)):
    if confirmation != 'RESTORE':
        raise HTTPException(400, 'Confirm restoration before replacing current data.')
    with tempfile.TemporaryDirectory(prefix='learntube-upload-') as temp:
        path = Path(temp) / 'upload.zip'
        try:
            _receive(file, path)
            result = service.restore(path, expected_hash)
            try:
                ensure_index(service.engine, service.pdf_dir, retry_failed=True)
            except Exception:
                result['search_index_warning'] = 'Search will rebuild its index when the backend restarts.'
            return result
        except BackupError as exc:
            raise HTTPException(422, str(exc)) from exc
