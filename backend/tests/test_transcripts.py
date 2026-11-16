import unittest
from unittest.mock import patch
from app.services.transcripts import fetch_english

class Track:
    def __init__(self, language_code, is_generated):
        self.language_code = language_code
        self.is_generated = is_generated

    def fetch(self):
        return [type('Line', (), {'text': self.language_code, 'start': 2.0, 'duration': 1.5})()]

class TranscriptSelectionTests(unittest.TestCase):
    @patch('app.services.transcripts.YouTubeTranscriptApi')
    def test_regional_english_and_manual_priority(self, api):
        api.return_value.list.return_value = [Track('en-US', True), Track('en-GB', False), Track('de', False)]
        self.assertEqual(fetch_english('mdrSqiyNXO4')[0]['text'], 'en-GB')

    @patch('app.services.transcripts.YouTubeTranscriptApi')
    def test_missing_english(self, api):
        api.return_value.list.return_value = [Track('de', False)]
        with self.assertRaisesRegex(ValueError, 'No English captions'):
            fetch_english('mdrSqiyNXO4')
