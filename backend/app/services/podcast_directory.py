"""Apple podcast discovery and public podcast URL resolution."""
import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit

from app.services.podcasts import (MAX_FEED_BYTES, FetchResult, PodcastFetchError, discover_feed_links,
                                   external_url, fetch_public, fetch_public_metadata, parse_feed, plain)

APPLE_API = 'https://itunes.apple.com'
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _apple_json(path: str, params: dict) -> dict:
    url = f'{APPLE_API}/{path}?{urlencode(params)}'
    with _lock:
        cached = _cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]  # type: ignore[return-value]
    data, _, _ = fetch_public(url, 750_000)
    try:
        result = json.loads(data)
    except (UnicodeError, ValueError) as exc:
        raise PodcastFetchError('Podcast discovery returned an invalid response.') from exc
    if not isinstance(result, dict) or not isinstance(result.get('results'), list):
        raise PodcastFetchError('Podcast discovery is temporarily unavailable.')
    with _lock:
        if len(_cache) >= 100:
            _cache.clear()
        _cache[url] = (time.monotonic() + 600, result)
    return result


def search_podcasts(query: str) -> list[dict]:
    data = _apple_json('search', {'term': query, 'media': 'podcast', 'entity': 'podcast', 'limit': 12})
    results = []
    for row in data['results'][:12]:
        if not isinstance(row, dict) or not isinstance(row.get('collectionId'), int):
            continue
        results.append({'id': row['collectionId'], 'title': plain(row.get('collectionName'), 300),
                        'author': plain(row.get('artistName'), 300),
                        'description': plain(row.get('description'), 500),
                        'artwork_url': external_url(row.get('artworkUrl600') or row.get('artworkUrl100')),
                        'store_url': external_url(row.get('collectionViewUrl')),
                        'has_feed': bool(external_url(row.get('feedUrl')))})
    return results


def lookup_feed(directory_id: int) -> str:
    data = _apple_json('lookup', {'id': directory_id, 'entity': 'podcast'})
    row = next((item for item in data['results'] if isinstance(item, dict) and item.get('collectionId') == directory_id), None)
    feed = external_url(row.get('feedUrl')) if row else None
    if not feed:
        raise PodcastFetchError('This directory listing has no usable public RSS feed. Try pasting a feed URL.')
    return feed


def resolve_podcast_url(raw: str) -> tuple[FetchResult, dict, list[dict]]:
    host = (urlsplit(raw).hostname or '').lower()
    if host == 'open.spotify.com':
        raise PodcastFetchError('Spotify does not provide a reliable public RSS URL for this link. Paste the publisher’s RSS feed instead.')
    if host == 'podcasts.apple.com':
        match = re.search(r'/id(\d+)(?:[/?]|$)', urlsplit(raw).path)
        if not match:
            raise PodcastFetchError('This Apple Podcasts link has no podcast ID. Try searching by name or pasting RSS.')
        raw = lookup_feed(int(match.group(1)))
    result = fetch_public_metadata(raw, MAX_FEED_BYTES)
    try:
        feed, entries = parse_feed(result.data)
        return result, feed, entries
    except PodcastFetchError:
        if result.content_type not in {'text/html', 'application/xhtml+xml'} and not result.data[:256].lstrip().lower().startswith((b'<!doctype html', b'<html')):
            raise
    for link in discover_feed_links(result.data, result.url):
        try:
            feed_result = fetch_public_metadata(link, MAX_FEED_BYTES)
            feed, entries = parse_feed(feed_result.data)
            return feed_result, feed, entries
        except PodcastFetchError:
            continue
    raise PodcastFetchError('No public RSS feed was found on this page. Paste the publisher’s RSS feed URL.')
