"""Podcast RSS and transcript handling. Network requests never follow unvalidated DNS or redirects."""
import calendar
import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser

MAX_FEED_BYTES = 10_000_000
MAX_TRANSCRIPT_BYTES = 1_000_000
MAX_EPISODES = 150
TRANSCRIPT_TYPES = {'text/vtt', 'application/vtt', 'application/x-subrip', 'application/srt', 'text/srt', 'application/json', 'text/plain', 'text/html'}


class PodcastFetchError(ValueError):
    pass


def public_url(raw: str) -> tuple[str, str, int]:
    if not raw or len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        raise PodcastFetchError('Enter a valid public RSS URL.')
    try:
        parsed = urlsplit(raw.strip())
    except ValueError as exc:
        raise PodcastFetchError('Enter a valid public RSS URL.') from exc
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise PodcastFetchError('Only public HTTP or HTTPS URLs are supported.')
    try:
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError as exc:
        raise PodcastFetchError('Invalid URL port.') from exc
    if port not in {80, 443}:
        raise PodcastFetchError('Only standard HTTP and HTTPS ports are supported.')
    host = parsed.hostname.rstrip('.').lower()
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.internal', '.localhost')):
        raise PodcastFetchError('Private network addresses are not allowed.')
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise PodcastFetchError('Private network addresses are not allowed.')
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PodcastFetchError('The feed host could not be resolved.') from exc
    ips = {item[4][0] for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise PodcastFetchError('Private network addresses are not allowed.')
    clean = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))
    return clean, next(iter(sorted(ips))), port


def external_url(raw: str | None) -> str | None:
    """Validate stored browser media URLs; the server never fetches audio or artwork."""
    if not isinstance(raw, str) or not raw or len(raw) > 2048:
        return None
    try:
        parsed = urlsplit(raw.strip())
    except ValueError:
        return None
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in (None, 80, 443):
        return None
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            return None
    else:
        if parsed.hostname.lower() in {'localhost', 'localhost.localdomain'} or parsed.hostname.lower().endswith(('.local', '.internal', '.localhost')):
            return None
    return raw.strip()


@dataclass
class FetchResult:
    data: bytes
    url: str
    content_type: str
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


def fetch_public_metadata(raw: str, limit: int, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
    current = raw
    for _ in range(4):
        url, ip, port = public_url(current)
        parsed = urlsplit(url)
        path = (parsed.path or '/') + (f'?{parsed.query}' if parsed.query else '')
        if parsed.scheme == 'https':
            connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=7, context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=7)
        def pinned_connect(_address, timeout, source_address=None):
            sock = socket.create_connection((ip, port), timeout, source_address)
            try:
                if sock.getpeername()[0] != ip or not ipaddress.ip_address(sock.getpeername()[0]).is_global:
                    raise PodcastFetchError('The connection reached an unsafe address.')
                return sock
            except Exception:
                sock.close()
                raise
        connection._create_connection = pinned_connect
        try:
            headers = {'Accept': 'application/rss+xml, application/atom+xml, text/xml, text/vtt, application/json, text/plain, text/html', 'Accept-Encoding': 'identity', 'User-Agent': 'LearnTube/1.0'}
            if current == raw:
                if etag and '\r' not in etag and '\n' not in etag:
                    headers['If-None-Match'] = etag
                if last_modified and '\r' not in last_modified and '\n' not in last_modified:
                    headers['If-Modified-Since'] = last_modified
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location:
                    raise PodcastFetchError('The feed redirect has no destination.')
                current = urljoin(url, location)
                continue
            if response.status == 304 and (etag or last_modified):
                return FetchResult(b'', url, '', etag, last_modified, True)
            if response.status != 200:
                raise PodcastFetchError(f'The source returned HTTP {response.status}.')
            length = response.getheader('Content-Length')
            if length and length.isdecimal() and int(length) > limit:
                raise PodcastFetchError(f'The RSS page or transcript exceeds the {limit / 1_000_000:g} MB download limit.')
            deadline = time.monotonic() + 20
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PodcastFetchError('The source timed out.')
                if connection.sock:
                    connection.sock.settimeout(min(7, remaining))
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise PodcastFetchError(f'The RSS page or transcript exceeds the {limit / 1_000_000:g} MB download limit.')
            content = b''.join(chunks)
            return FetchResult(content, url, (response.getheader('Content-Type') or '').split(';')[0].strip().lower(),
                               (response.getheader('ETag') or '')[:500] or None,
                               (response.getheader('Last-Modified') or '')[:500] or None)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise PodcastFetchError('The source could not be downloaded safely.') from exc
        finally:
            connection.close()
    raise PodcastFetchError('The source redirected too many times.')


def fetch_public(raw: str, limit: int) -> tuple[bytes, str, str]:
    result = fetch_public_metadata(raw, limit)
    return result.data, result.url, result.content_type


class _FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() != 'link':
            return
        values = dict(attrs)
        if 'alternate' in (values.get('rel') or '').lower().split() and (values.get('type') or '').lower().split(';')[0] in {'application/rss+xml', 'application/atom+xml'} and values.get('href'):
            self.links.append(values['href'])


def discover_feed_links(data: bytes, page_url: str) -> list[str]:
    parser = _FeedLinks()
    parser.feed(data.decode('utf-8-sig', errors='replace'))
    links = []
    for href in parser.links[:10]:
        candidate = urljoin(page_url, href)
        try:
            public_url(candidate)
        except PodcastFetchError:
            continue
        if candidate not in links:
            links.append(candidate)
    return links[:3]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
    def handle_data(self, data: str):
        self.parts.append(data)


def plain(value: str | None, limit: int = 4000) -> str:
    parser = _Text()
    parser.feed(value or '')
    return re.sub(r'\s+', ' ', html.unescape(' '.join(parser.parts))).strip()[:limit]


def duration_seconds(value: str | int | None) -> float | None:
    if value is None:
        return None
    parts = str(value).strip().split(':')
    try:
        result = 0.0
        for part in parts:
            result = result * 60 + float(part)
        return result if 0 < result < 24 * 3600 * 7 else None
    except ValueError:
        return None


def parse_feed(data: bytes) -> tuple[dict, list[dict]]:
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise PodcastFetchError('Feeds with DTD declarations are not supported.')
    parsed = feedparser.parse(data)
    if not parsed.version or not parsed.feed.get('title'):
        raise PodcastFetchError('This URL does not contain a podcast RSS feed.')
    feed = {'title': plain(parsed.feed.get('title'), 300), 'description': plain(parsed.feed.get('summary') or parsed.feed.get('description')),
            'publisher': plain(parsed.feed.get('itunes_author') or parsed.feed.get('author') or '', 300),
            'image_url': external_url((parsed.feed.get('image') or {}).get('href') or parsed.feed.get('itunes_image'))}
    episodes = []
    for entry in parsed.entries[:MAX_EPISODES]:
        enclosures = entry.get('enclosures') or []
        audio = next((external_url(enclosure.get('href')) for enclosure in enclosures if (enclosure.get('type') or '').lower().startswith('audio/') and external_url(enclosure.get('href'))), None)
        if not audio:
            audio = next((external_url(enclosure.get('href')) for enclosure in enclosures if re.search(r'\.(mp3|m4a|ogg|opus|wav)(?:\?|$)', enclosure.get('href') or '', re.I) and external_url(enclosure.get('href'))), None)
        if not audio:
            continue
        source_id = entry.get('id') or entry.get('guid')
        stable_audio = urlunsplit((*urlsplit(audio)[:3], '', ''))
        fallback = '|'.join((str(entry.get('link') or ''), plain(entry.get('title'), 300), str(entry.get('published') or ''), stable_audio))
        guid = str(source_id)[:1000] if source_id else 'fallback:' + hashlib.sha256(fallback.encode()).hexdigest()
        stamp = entry.get('published_parsed') or entry.get('updated_parsed')
        try:
            published = datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc) if stamp else None
        except (OverflowError, ValueError):
            published = None
        transcript = entry.get('podcast_transcript')
        if isinstance(transcript, list):
            transcript = next((item for item in transcript if isinstance(item, dict) and item.get('type', '').split(';')[0].lower() in TRANSCRIPT_TYPES), None)
        transcript_kind = transcript.get('type', '').split(';')[0].lower() if isinstance(transcript, dict) else ''
        transcript_url = external_url(transcript.get('url')) if isinstance(transcript, dict) else None
        episodes.append({'guid': guid, 'title': plain(entry.get('title') or 'Untitled episode', 300),
                         'description': plain(entry.get('summary') or entry.get('description')),
                         'audio_url': audio, 'image_url': external_url((entry.get('image') or {}).get('href') or entry.get('itunes_image')),
                         'published_at': published, 'duration_seconds': duration_seconds(entry.get('itunes_duration')),
                         'transcript_url': transcript_url if transcript_kind in TRANSCRIPT_TYPES else None,
                         'transcript_type': transcript_kind if transcript_url and transcript_kind in TRANSCRIPT_TYPES else None})
    if not episodes:
        raise PodcastFetchError('This feed has no playable audio episodes.')
    return feed, episodes


_TIMING = re.compile(r'(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})')


def _seconds(value: str) -> float | None:
    match = _TIMING.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, '0')) / 1000


def parse_transcript(data: bytes, kind: str) -> list[dict]:
    text = data.decode('utf-8-sig', errors='replace')
    rows: list[dict] = []
    if kind == 'application/json':
        try:
            source = json.loads(text)
            segments = source.get('segments', []) if isinstance(source, dict) else []
        except (ValueError, TypeError) as exc:
            raise PodcastFetchError('The transcript JSON is invalid.') from exc
        for segment in segments[:5000]:
            if not isinstance(segment, dict):
                continue
            body = plain(str(segment.get('body') or segment.get('text') or ''))
            start = segment.get('startTime', segment.get('start'))
            end = segment.get('endTime', segment.get('end'))
            try:
                start = max(0.0, float(start)) if start is not None else None
                duration = max(0.0, float(end) - start) if end is not None and start is not None else None
            except (TypeError, ValueError):
                start = duration = None
            if body:
                rows.append({'text': body, 'start': start, 'duration': duration})
    elif kind in {'text/vtt', 'application/vtt', 'application/x-subrip', 'application/srt', 'text/srt'}:
        for block in re.split(r'\r?\n\s*\r?\n', text.replace('\r\n', '\n'))[:5000]:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            timing = next((index for index, line in enumerate(lines) if '-->' in line), None)
            if timing is None:
                continue
            points = lines[timing].split('-->', 1)
            start = _seconds(points[0])
            end = _seconds(points[1].split()[0])
            body = plain(' '.join(lines[timing + 1:]))
            if body:
                rows.append({'text': body, 'start': start, 'duration': max(0, end-start) if start is not None and end is not None else None})
    else:
        for line in text.splitlines()[:5000]:
            body = plain(line)
            if body:
                rows.append({'text': body, 'start': None, 'duration': None})
    if not rows:
        raise PodcastFetchError('The transcript has no readable text.')
    return rows
