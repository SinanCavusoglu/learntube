import json
import unittest
from unittest.mock import patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.dictionary import router


class FakeResponse:
    def __init__(self, status=200, payload=None, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, chunk_size):
        yield self.raw


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_definitions_examples_and_fixed_encoded_url(self):
        payload = [{'meanings': [{'partOfSpeech': 'verb', 'definitions': [
            {'definition': 'To consider something.', 'example': 'Take this into account.'},
            {'definition': 'To include in a calculation.', 'example': 'Take this into account.'},
            {'definition': 'To consider something.', 'example': 'We took the cost into account.'},
            {'definition': 'A third meaning.', 'example': 'Their plan takes risks into account.'},
            {'definition': 'A fourth meaning.', 'example': 'A fourth example.'}]}]}]
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(payload=payload)) as get:
            response = self.client.get('/api/dictionary/lookup', params={'word': '  take   into account  '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['word'], 'take into account')
        self.assertEqual(len(response.json()['definitions']), 4)
        self.assertEqual(response.json()['examples'], ['Take this into account.', 'We took the cost into account.', 'Their plan takes risks into account.'])
        self.assertEqual(get.call_args.args[0], 'https://api.dictionaryapi.dev/api/v2/entries/en/take%20into%20account')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_no_examples_unknown_word_and_invalid_response(self):
        payload = [{'meanings': [{'definitions': [{'definition': 'A useful meaning.'}]}]}]
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(payload=payload)):
            self.assertEqual(self.client.get('/api/dictionary/lookup?word=sample').json()['examples'], [])
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(status=404)):
            missing = self.client.get('/api/dictionary/lookup?word=unknownphrase')
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()['detail'], 'No dictionary definition found.')
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(payload=[{'meanings': []}])):
            self.assertEqual(self.client.get('/api/dictionary/lookup?word=sample').status_code, 404)
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(raw=b'not json')):
            self.assertEqual(self.client.get('/api/dictionary/lookup?word=sample').status_code, 502)

    def test_network_rate_limit_and_input_validation(self):
        with patch('app.services.dictionary.requests.get', side_effect=requests.Timeout):
            self.assertEqual(self.client.get('/api/dictionary/lookup?word=sample').status_code, 503)
        with patch('app.services.dictionary.requests.get', return_value=FakeResponse(status=429)):
            self.assertEqual(self.client.get('/api/dictionary/lookup?word=sample').status_code, 429)
        self.assertEqual(self.client.get('/api/dictionary/lookup', params={'word': 'x' * 101}).status_code, 422)
