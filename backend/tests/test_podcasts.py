import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.routers import dashboard, podcasts, vocabulary
from app.services.podcasts import FetchResult, PodcastFetchError, discover_feed_links, fetch_public, parse_feed, parse_transcript, public_url


RSS = b'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel><title>IELTS Talks</title><description>Study conversations</description>
<item><guid>episode-one</guid><title>Listening skills</title><description>Practice careful listening</description>
<pubDate>Sun, 15 Nov 2026 12:00:00 GMT</pubDate><itunes:duration>2:30</itunes:duration>
<enclosure url="https://media.example.org/episode.mp3" type="audio/mpeg" length="1234"/>
<podcast:transcript url="https://media.example.org/episode.vtt" type="text/vtt"/>
</item></channel></rss>'''
VTT = b'WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nA useful expression.\n\n00:00:04.000 --> 00:00:06.000\nPractice listening.\n'


class PodcastTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(podcasts.router)
        app.include_router(vocabulary.router)
        app.include_router(dashboard.router)
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def fake_fetch(self, url, limit):
        if url.endswith('.vtt'):
            return VTT, url, 'text/vtt'
        return RSS, 'https://podcasts.example.org/feed.xml', 'application/rss+xml'

    def fake_metadata(self, url, limit, *args):
        return FetchResult(RSS, 'https://podcasts.example.org/feed.xml', 'application/rss+xml', '"feed-v1"', 'Sun, 15 Nov 2026 12:00:00 GMT')

    def test_podcast_learning_flow_and_existing_vocabulary_queue(self):
        with patch('app.services.podcast_directory.fetch_public_metadata', side_effect=self.fake_metadata), patch('app.routers.podcasts.fetch_public', side_effect=self.fake_fetch), patch('app.routers.podcasts.fetch_public_metadata', side_effect=self.fake_metadata):
            added = self.client.post('/api/podcasts', json={'feed_url': 'https://podcasts.example.org/feed.xml'})
            self.assertEqual(added.status_code, 201, added.text)
            podcast_id = added.json()['id']
            self.assertEqual(self.client.post('/api/podcasts', json={'feed_url': 'https://podcasts.example.org/feed.xml'}).status_code, 409)
            self.assertEqual(self.client.get('/api/podcasts').json()[0]['episode_count'], 1)
            episodes = self.client.get(f'/api/podcasts/{podcast_id}/episodes').json()
            self.assertEqual(len(episodes), 1)
            episode_id = episodes[0]['id']
            self.assertEqual(episodes[0]['duration_seconds'], 150)
            self.assertEqual(self.client.get('/api/podcasts/episodes/search?q=Listening').json()[0]['id'], episode_id)
            self.assertEqual(self.client.get(f'/api/podcasts/{podcast_id}/episodes?q=missing').json(), [])
            transcript = self.client.get(f'/api/podcasts/episodes/{episode_id}/transcript')
            self.assertEqual(transcript.status_code, 200)
            self.assertEqual([row['start'] for row in transcript.json()], [1, 4])
            self.assertEqual(len(self.client.get(f'/api/podcasts/episodes/{episode_id}/transcript').json()), 2)
            manual = self.client.put(f'/api/podcasts/episodes/{episode_id}/transcript/manual', json={'text': 'First line\nSecond line'})
            self.assertEqual(manual.status_code, 200)
            self.assertTrue(manual.json()[0]['is_manual'])
            self.assertEqual(len(self.client.get(f'/api/podcasts/episodes/{episode_id}/transcript').json()), 2)
            refreshed = self.client.post(f'/api/podcasts/{podcast_id}/refresh')
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(refreshed.json()['new_episodes'], 0)
            self.assertTrue(self.client.get(f'/api/podcasts/episodes/{episode_id}/transcript').json()[0]['is_manual'])

        progress = self.client.patch(f'/api/podcasts/episodes/{episode_id}/progress', json={'position_seconds': 25, 'duration_seconds': 150, 'playback_speed': 1.25})
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(self.client.get(f'/api/podcasts/episodes/{episode_id}').json()['progress']['position_seconds'], 25)
        self.assertEqual(self.client.patch(f'/api/podcasts/episodes/{episode_id}/progress', json={'position_seconds': 1, 'playback_speed': 3}).status_code, 422)
        note = self.client.put(f'/api/podcasts/episodes/{episode_id}/notes', json={'content': 'Remember this phrase'})
        self.assertEqual(note.status_code, 200)
        self.assertEqual(self.client.get(f'/api/podcasts/episodes/{episode_id}/notes').json()['content'], 'Remember this phrase')
        word = self.client.post('/api/vocabulary', json={'text': 'useful expression', 'meaning': 'a helpful phrase', 'source_episode_id': episode_id, 'source_episode_timestamp': 1})
        self.assertEqual(word.status_code, 201, word.text)
        self.assertEqual(word.json()['source_podcast_title'], 'IELTS Talks')
        self.assertEqual(len(self.client.get('/api/vocabulary/review/due').json()), 1)
        self.assertEqual(len(self.client.get(f'/api/vocabulary?episode_id={episode_id}').json()), 1)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'useful expression', 'source_episode_id': episode_id}).status_code, 409)
        self.assertEqual(self.client.post('/api/vocabulary', json={'text': 'bad', 'source_episode_timestamp': 5}).status_code, 422)
        activity = {'event_key': str(uuid4()), 'client_session_id': str(uuid4()), 'activity_type': 'podcast', 'source_id': episode_id,
                    'ended_at': datetime.now(timezone.utc).isoformat(), 'duration_seconds': 5}
        self.assertEqual(self.client.post('/api/dashboard/activity', json=activity).status_code, 200)
        stats = self.client.get('/api/dashboard?timezone_name=UTC').json()
        self.assertEqual(stats['podcasts']['subscriptions'], 1)
        self.assertAlmostEqual(stats['podcasts']['active_seconds'], 5)
        self.assertAlmostEqual(stats['daily'][-1]['podcast'], 5)
        manual_listen = self.client.post(f'/api/podcasts/episodes/{episode_id}/listened', json={'duration_seconds': 600})
        self.assertEqual(manual_listen.status_code, 201)
        self.assertTrue(self.client.get(f'/api/podcasts/episodes/{episode_id}').json()['progress']['completed'])
        self.assertEqual(self.client.get('/api/dashboard?timezone_name=UTC').json()['total_seconds'], 5)
        self.assertEqual(self.client.delete(f'/api/podcasts/{podcast_id}').status_code, 204)
        self.assertEqual(self.client.get(f'/api/podcasts/episodes/{episode_id}').status_code, 404)
        saved = self.client.get('/api/vocabulary').json()[0]
        self.assertIsNone(saved['source_episode_id'])
        self.assertEqual(saved['source_episode_title'], 'Listening skills')
        self.assertEqual(len(self.client.get('/api/vocabulary/review/due').json()), 1)

    def test_url_and_transcript_parsing_reject_unsafe_sources(self):
        for url in ('file:///etc/passwd', 'http://127.0.0.1/feed', 'http://[::1]/feed', 'http://169.254.169.254/latest/meta-data', 'https://localhost/feed', 'https://example.org:9000/feed'):
            with self.subTest(url=url), self.assertRaises(PodcastFetchError):
                public_url(url)
        self.assertEqual(self.client.post('/api/podcasts', json={'feed_url': 'http://127.0.0.1/feed'}).status_code, 422)
        self.assertEqual(self.client.post('/api/podcasts', json={'feed_url': 'https://open.spotify.com/show/abc'}).status_code, 422)
        with patch('app.services.podcasts.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('10.0.0.5', 443))]):
            with self.assertRaises(PodcastFetchError):
                public_url('https://example.org/feed')
        feed, episodes = parse_feed(RSS)
        self.assertEqual(feed['title'], 'IELTS Talks')
        self.assertEqual(episodes[0]['transcript_type'], 'text/vtt')
        self.assertEqual(parse_transcript(VTT, 'text/vtt')[0]['duration'], 3)
        self.assertEqual(parse_transcript(b'1\n00:00:01,000 --> 00:00:02,000\nHello\n', 'application/srt')[0]['text'], 'Hello')
        self.assertEqual(parse_transcript(b'{"segments":[{"startTime":2,"endTime":3,"body":"Hello"}]}', 'application/json')[0]['start'], 2)
        with self.assertRaises(PodcastFetchError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>')

    def test_search_directory_add_website_discovery_and_conditional_refresh(self):
        directory = {'results': [{'collectionId': 123, 'collectionName': 'IELTS Talks', 'artistName': 'Study Studio',
                                  'artworkUrl100': 'https://art.example.org/a.jpg', 'feedUrl': 'https://podcasts.example.org/feed.xml'}]}
        with patch('app.services.podcast_directory._apple_json', return_value=directory), patch('app.services.podcast_directory.fetch_public_metadata', side_effect=self.fake_metadata):
            results = self.client.get('/api/podcasts/search?q=IELTS')
            self.assertEqual(results.status_code, 200)
            self.assertEqual(results.json()[0]['title'], 'IELTS Talks')
            added = self.client.post('/api/podcasts/from-directory', json={'directory_id': 123})
            self.assertEqual(added.status_code, 201, added.text)
            self.assertEqual(added.json()['external_directory_id'], 123)
            podcast_id = added.json()['id']
            self.assertEqual(self.client.post('/api/podcasts/from-directory', json={'directory_id': 123}).status_code, 409)
        episode_id = self.client.get(f'/api/podcasts/{podcast_id}/episodes').json()[0]['id']
        self.client.put(f'/api/podcasts/episodes/{episode_id}/notes', json={'content': 'keep'})
        self.client.patch(f'/api/podcasts/episodes/{episode_id}/progress', json={'position_seconds': 22})
        self.client.put(f'/api/podcasts/episodes/{episode_id}/transcript/manual', json={'text': 'keep transcript'})
        self.client.post('/api/vocabulary', json={'text': 'keep word', 'source_episode_id': episode_id})
        with patch('app.routers.podcasts.fetch_public_metadata', return_value=FetchResult(b'', 'https://podcasts.example.org/feed.xml', '', '"feed-v1"', None, True)) as mocked:
            refresh = self.client.post(f'/api/podcasts/{podcast_id}/refresh')
            self.assertEqual(refresh.status_code, 200, refresh.text)
            self.assertTrue(refresh.json()['not_modified'])
            self.assertEqual(refresh.json()['new_episodes'], 0)
            self.assertEqual(mocked.call_args.args[2], '"feed-v1"')
        self.assertEqual(self.client.get(f'/api/podcasts/episodes/{episode_id}/notes').json()['content'], 'keep')
        self.assertEqual(self.client.get(f'/api/podcasts/episodes/{episode_id}').json()['progress']['position_seconds'], 22)
        self.assertTrue(self.client.get(f'/api/podcasts/episodes/{episode_id}/transcript').json()[0]['is_manual'])
        self.assertEqual(self.client.get(f'/api/vocabulary?episode_id={episode_id}').json()[0]['text'], 'keep word')
        self.assertEqual(len(self.client.get(f'/api/podcasts/{podcast_id}/episodes').json()), 1)

        html = b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
        with patch('app.services.podcasts.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 443))]):
            self.assertEqual(discover_feed_links(html, 'https://example.org/show')[0], 'https://example.org/feed.xml')
            self.assertEqual(discover_feed_links(b'<link rel="alternate" type="application/rss+xml" href="http://127.0.0.1/private">', 'https://example.org'), [])

    def test_paste_website_apple_link_and_new_episode_refresh(self):
        html = b'<html><link rel="alternate" type="application/rss+xml" href="/feed.xml"></html>'
        next_rss = RSS.replace(b'</channel>', b'<item><guid>episode-two</guid><title>New lesson</title><enclosure url="https://media.example.org/two.mp3" type="audio/mpeg"/></item></channel>')
        def website_fetch(url, limit):
            if url.endswith('/feed.xml'):
                return FetchResult(RSS, 'https://podcasts.example.org/feed.xml', 'application/rss+xml')
            return FetchResult(html, 'https://example.org/show', 'text/html')
        with patch('app.services.podcast_directory.fetch_public_metadata', side_effect=website_fetch), patch('app.services.podcasts.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 443))]):
            added = self.client.post('/api/podcasts', json={'feed_url': 'https://example.org/show'})
            self.assertEqual(added.status_code, 201, added.text)
            podcast_id = added.json()['id']
        with patch('app.routers.podcasts.fetch_public_metadata', return_value=FetchResult(next_rss, 'https://podcasts.example.org/feed.xml', 'application/rss+xml')):
            first = self.client.post(f'/api/podcasts/{podcast_id}/refresh')
            second = self.client.post(f'/api/podcasts/{podcast_id}/refresh')
        self.assertEqual(first.json()['new_episodes'], 1)
        self.assertEqual(second.json()['new_episodes'], 0)
        self.assertEqual(len(self.client.get(f'/api/podcasts/{podcast_id}/episodes').json()), 2)
        with patch('app.services.podcast_directory.lookup_feed', return_value='https://podcasts.example.org/feed.xml'), patch('app.services.podcast_directory.fetch_public_metadata', side_effect=self.fake_metadata):
            self.assertEqual(self.client.post('/api/podcasts', json={'feed_url': 'https://podcasts.apple.com/us/podcast/show/id123'}).status_code, 409)
        self.assertIn('Spotify', self.client.post('/api/podcasts', json={'feed_url': 'https://open.spotify.com/show/abc'}).json()['detail'])

    def test_unsafe_redirect_and_oversized_feed_are_rejected(self):
        class Response:
            def __init__(self, status, headers):
                self.status = status
                self.headers = headers
            def getheader(self, name):
                return self.headers.get(name)
            def read1(self, amount):
                return b'x' * amount
        class Connection:
            sock = None
            def __init__(self, response):
                self.response = response
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return self.response
            def close(self):
                pass
        public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 443))]
        with patch('app.services.podcasts.socket.getaddrinfo', return_value=public_dns):
            with patch('app.services.podcasts.http.client.HTTPSConnection', return_value=Connection(Response(302, {'Location': 'http://127.0.0.1/admin'}))):
                with self.assertRaises(PodcastFetchError):
                    fetch_public('https://example.org/feed', 10)
            with patch('app.services.podcasts.http.client.HTTPSConnection', return_value=Connection(Response(200, {'Content-Length': '999'}))):
                with self.assertRaises(PodcastFetchError):
                    fetch_public('https://example.org/feed', 10)


if __name__ == '__main__':
    unittest.main()
