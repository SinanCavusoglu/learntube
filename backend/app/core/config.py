import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///{(BASE_DIR / 'learntube.db').as_posix()}")
CORS_ORIGINS = [origin.strip() for origin in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',') if origin.strip()]
PDF_STORAGE_DIR = Path(os.getenv('PDF_STORAGE_DIR', str(BASE_DIR / 'uploads' / 'pdfs'))).resolve()
MAX_PDF_SIZE_MB = int(os.getenv('MAX_PDF_SIZE_MB', '50'))
