import unittest
from unittest.mock import patch, MagicMock
from scripts.load_test import request, summary
import io

class LoadTestTests(unittest.TestCase):
    def test_failed_samples_are_not_success_latency(self):
        result = summary([{'success': True, 'seconds': 2}, {'success': False, 'seconds': 100}, {'success': True, 'seconds': 4}])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['p95_seconds'], 4)
        self.assertIsNone(summary([])['p95_seconds'])

    def test_s3_put_streams_without_authorization(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b''
        stream = io.BytesIO(b'csv')
        with patch('scripts.load_test.urlopen', return_value=response) as call:
            request('https://example.s3.amazonaws.com/file', payload=stream, method='PUT', headers={'Content-Length': '3'})
        sent = call.call_args.args[0]
        self.assertIs(sent.data, stream)
        self.assertNotIn('Authorization', sent.headers)
