import os
import runpy
import unittest
from unittest.mock import Mock, patch

class QueueSamplerTests(unittest.TestCase):
    def test_missing_queue_attribute_never_publishes_zero(self):
        sqs, cw = Mock(), Mock()
        sdk = Mock()
        sdk.client.side_effect = [sqs, cw]
        with patch.dict('sys.modules', {'boto3': sdk, 'botocore.config': Mock()}), patch.dict(os.environ, {'QUEUE_URL': 'q'}):
            module = runpy.run_path('backend_cloud/scaling/handler.py')
            sqs.get_queue_attributes.return_value = {'Attributes': {}}
            with self.assertRaises(KeyError):
                module['handler']({}, None)
            cw.put_metric_data.assert_not_called()
            sqs.get_queue_attributes.return_value = {'Attributes': dict(zip(module['NAMES'], ['1','2','3']))}
            self.assertEqual(module['handler']({}, None), {'Visible':1,'InFlight':2,'Delayed':3})
            self.assertEqual([m['Value'] for m in cw.put_metric_data.call_args.kwargs['MetricData']], [1,2,3])
