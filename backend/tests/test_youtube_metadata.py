import unittest
from unittest.mock import patch
from app.services.youtube import fallback_title, fetch_title

class MetadataTests(unittest.TestCase):
    @patch('app.services.youtube.requests.get')
    def test_title_from_oembed(self, get):
        get.return_value.json.return_value = {'title': '  BBC Learning English  '}
        self.assertEqual(fetch_title('mdrSqiyNXO4'), 'BBC Learning English')
        self.assertEqual(get.call_args.kwargs['params']['url'], 'https://www.youtube.com/watch?v=mdrSqiyNXO4')

    @patch('app.services.youtube.requests.get')
    def test_unavailable_metadata_keeps_fallback(self, get):
        get.return_value.json.return_value = {}
        self.assertIsNone(fetch_title('mdrSqiyNXO4'))
        self.assertEqual(fallback_title('mdrSqiyNXO4'), 'YouTube video · mdrSqiyNXO4')
