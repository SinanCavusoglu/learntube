import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.routers import ai, writing
from google.genai import errors


class AITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(ai, 'engine', self.engine)
        self.engine_patch.start()
        self.cors_patch = patch.object(ai, 'CORS_ORIGINS', ['http://localhost:5173', 'http://127.0.0.1:5173'])
        self.cors_patch.start()
        self.environment = patch.dict(os.environ, {'AI_ENABLED': 'true', 'GEMINI_API_KEY': 'test-only-key',
                                                   'GEMINI_MODEL': 'gemini-2.5-flash-lite', 'AI_DAILY_REQUEST_LIMIT': '2',
                                                   'TAILSCALE_AI_LOGIN': '', 'TAILSCALE_AI_ORIGIN': ''})
        self.environment.start()
        app = FastAPI()
        app.include_router(ai.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()
        self.engine_patch.stop()
        self.cors_patch.stop()
        self.engine.dispose()

    def test_missing_key_and_remote_access_fail_closed(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            response = self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'address'})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('test-only-key', response.text)
            self.assertFalse(self.client.get('/api/ai/status').json()['enabled'])
        remote = Request({'type': 'http', 'method': 'POST', 'path': '/api/ai/explain-vocabulary',
                          'headers': [(b'host', b'localhost:8001')], 'client': ('192.168.1.50', 1234), 'server': ('0.0.0.0', 8001)})
        with self.assertRaises(HTTPException) as error:
            ai._guard(remote)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.client.post('/api/ai/explain-vocabulary', headers={'X-Forwarded-For': '192.168.1.50'}, json={'request_id': str(uuid4()), 'text': 'word'}).status_code, 403)
        self.assertEqual(self.client.post('/api/ai/explain-vocabulary', headers={'Origin': 'https://untrusted.example'}, json={'request_id': str(uuid4()), 'text': 'word'}).status_code, 403)
        with patch.dict(os.environ, {'GEMINI_MODEL': 'unknown-model'}):
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'word'}).status_code, 503)

    def test_minimal_output_no_context_daily_limit_and_duplicate_request(self):
        result = ai.VocabularyExplanation(definition='To deal with a problem.', examples=['Address the issue.', 'The report addresses safety.'])
        first_id = str(uuid4())
        with patch.object(ai, '_generate', return_value=result) as generate:
            first = self.client.post('/api/ai/explain-vocabulary', json={'request_id': first_id, 'text': 'address'})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(set(first.json()), {'definition', 'examples'})
            self.assertIn('address', generate.call_args.args[1])
            self.assertNotIn('context', generate.call_args.args[1])
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': first_id, 'text': 'address'}).status_code, 409)
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'another'}).status_code, 200)
            self.assertEqual(self.client.get('/api/ai/status').json()['used_today'], 2)
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'third'}).status_code, 429)
            self.assertEqual(generate.call_count, 2)
        self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'x', 'context': 'No context'}).status_code, 422)
        self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'x'*501}).status_code, 422)
        self.assertEqual(self.client.post('/api/ai/explain-text', json={'request_id': str(uuid4()), 'text': 'x'}).status_code, 404)

    def test_tailscale_serve_requires_identity_origin_and_private_source(self):
        origin = 'https://desktop.example.ts.net'
        headers = {'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.75.58.47',
                   'Origin': origin, 'Host': '127.0.0.1:8001'}
        with patch.dict(os.environ, {'TAILSCALE_AI_LOGIN': 'owner@example.com', 'TAILSCALE_AI_ORIGIN': origin}):
            self.assertTrue(self.client.get('/api/ai/status', headers=headers).json()['enabled'])
            result = ai.VocabularyExplanation(definition='A simple meaning.', examples=['Example one.', 'Example two.'])
            with patch.object(ai, '_generate', return_value=result):
                response = self.client.post('/api/ai/explain-vocabulary', headers=headers,
                                            json={'request_id': str(uuid4()), 'text': 'word'})
                self.assertEqual(response.status_code, 200, response.text)
            for bad in ({'Tailscale-User-Login': 'other@example.com'}, {'Origin': 'https://evil.example'},
                        {'X-Forwarded-For': '192.168.1.50'}, {'X-Forwarded-For': ''},
                        {'Tailscale-User-Login': ''}):
                self.assertEqual(self.client.post('/api/ai/explain-vocabulary', headers={**headers, **bad},
                                                  json={'request_id': str(uuid4()), 'text': 'word'}).status_code, 403)

    def test_local_pc_accepts_both_loopback_browser_origins(self):
        answer = ai.VocabularyExplanation(definition='A simple meaning.', examples=['Example one.', 'Example two.'])
        with patch.object(ai, '_generate', return_value=answer):
            for origin in ('http://localhost:5173', 'http://127.0.0.1:5173'):
                response = self.client.post('/api/ai/explain-vocabulary', headers={'Origin': origin},
                                            json={'request_id': str(uuid4()), 'text': 'word'})
                self.assertEqual(response.status_code, 200, response.text)

    def test_writing_feedback_is_independent_of_essay(self):
        app = FastAPI()
        app.include_router(writing.router)
        with patch.object(writing, 'engine', self.engine), TestClient(app) as client:
            item = client.post('/api/writing', json={'task_type': 2, 'question': 'Discuss pollution.', 'timer_duration_seconds': 2400}).json()
            essay = 'Pollution is a serious problem.\n\nWe should act.'
            client.patch(f"/api/writing/{item['id']}", json={'expected_revision': 0, 'question': item['question'], 'essay_content': essay, 'notes': 'Plan'}).raise_for_status()
            finished = client.post(f"/api/writing/{item['id']}/finish", json={'expected_revision': 1, 'question': item['question'], 'essay_content': essay, 'notes': 'Plan'})
            self.assertEqual(finished.status_code, 200, finished.text)
            saved = client.put(f"/api/writing/{item['id']}/feedback", json={'content': 'Improve coherence.', 'expected_revision': 0})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()['question'], 'Discuss pollution.')
            self.assertEqual(saved.json()['essay_content'], essay)
            self.assertEqual(saved.json()['notes'], 'Plan')
            self.assertEqual(saved.json()['status'], 'completed')
            self.assertEqual(client.get(f"/api/writing/{item['id']}").json()['chatgpt_feedback'], 'Improve coherence.')
            self.assertEqual(client.put(f"/api/writing/{item['id']}/feedback", json={'content': 'Edited feedback.', 'expected_revision': 0}).status_code, 409)
            self.assertEqual(client.put(f"/api/writing/{item['id']}/feedback", json={'content': 'Edited feedback.', 'expected_revision': 1}).json()['chatgpt_feedback'], 'Edited feedback.')
            self.assertEqual(client.get(f"/api/writing/{item['id']}").json()['essay_content'], essay)

    def test_failed_provider_call_does_not_consume_local_allowance(self):
        request_id = str(uuid4())
        payload = {'request_id': request_id, 'text': 'resilient'}
        with patch.object(ai, '_generate', side_effect=HTTPException(503, 'Gemini is overloaded')):
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json=payload).status_code, 503)
        self.assertEqual(self.client.get('/api/ai/status').json()['used_today'], 0)
        answer = ai.VocabularyExplanation(definition='Able to recover quickly.', examples=['She stayed resilient.', 'A resilient team adapts.'])
        with patch.object(ai, '_generate', return_value=answer):
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json=payload).status_code, 200)
        self.assertEqual(self.client.get('/api/ai/status').json()['used_today'], 1)

    def test_minute_limit_provider_quota_and_non_english_output(self):
        result = ai.VocabularyExplanation(definition='Clear English.', examples=['Example one.', 'Example two.'])
        with patch.dict(os.environ, {'AI_DAILY_REQUEST_LIMIT': '100'}), patch.object(ai, '_generate', return_value=result):
            for _ in range(5):
                self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'A phrase'}).status_code, 200)
            self.assertEqual(self.client.post('/api/ai/explain-vocabulary', json={'request_id': str(uuid4()), 'text': 'A phrase'}).status_code, 429)
        with patch('google.genai.Client') as client:
            call = client.return_value.__enter__.return_value.models.generate_content
            call.side_effect = errors.APIError(429, {'message': 'private provider details'})
            with self.assertRaises(HTTPException) as quota:
                ai._generate('gemini-2.5-flash-lite', 'sample', ai.VocabularyExplanation)
            self.assertEqual(quota.exception.status_code, 429)
            self.assertNotIn('private provider details', quota.exception.detail)
            call.side_effect = errors.APIError(503, {'message': 'provider internal details'})
            with self.assertRaises(HTTPException) as overloaded:
                ai._generate('gemini-3.5-flash-lite', 'sample', ai.VocabularyExplanation)
            self.assertEqual(overloaded.exception.status_code, 503)
            self.assertNotIn('provider internal details', overloaded.exception.detail)
            call.side_effect = None
            call.return_value.text = '{"definition":"Non-English \u00e7","examples":["One.","Two."]}'
            with self.assertRaises(HTTPException) as language:
                ai._generate('gemini-2.5-flash-lite', 'sample', ai.VocabularyExplanation)
            self.assertEqual(language.exception.status_code, 502)


if __name__ == '__main__':
    unittest.main()
