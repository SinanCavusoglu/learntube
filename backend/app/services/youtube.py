import re
from urllib.parse import urlparse, parse_qs
import requests

VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')

def fallback_title(video_id: str) -> str:
    return f'YouTube video · {video_id}'

def fetch_title(video_id: str) -> str | None:
    """Use YouTube oEmbed metadata without an API key; failure never blocks saving."""
    if not VIDEO_ID.fullmatch(video_id):
        return None
    try:
        response = requests.get(
            'https://www.youtube.com/oembed',
            params={'url': f'https://www.youtube.com/watch?v={video_id}', 'format': 'json'},
            timeout=4,
        )
        response.raise_for_status()
        title = response.json().get('title')
        return title.strip()[:500] if isinstance(title, str) and title.strip() else None
    except (requests.RequestException, ValueError):
        return None
def extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower().removeprefix('www.')
        if host == 'youtu.be': candidate = parsed.path.strip('/').split('/')[0]
        elif host in {'youtube.com', 'm.youtube.com', 'music.youtube.com'}:
            candidate = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else parsed.path.split('/')[2] if parsed.path.startswith('/shorts/') or parsed.path.startswith('/embed/') else ''
        else: return None
        return candidate if VIDEO_ID.fullmatch(candidate) else None
    except Exception: return None
