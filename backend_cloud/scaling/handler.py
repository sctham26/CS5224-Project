"""Publish queue depth even when SQS native metrics have been dormant."""
import os
import boto3
from botocore.config import Config
config = Config(connect_timeout=3, read_timeout=5, retries={'mode': 'standard', 'total_max_attempts': 2})
sqs = boto3.client('sqs', config=config)
cw = boto3.client('cloudwatch', config=config)
NAMES = ('ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible', 'ApproximateNumberOfMessagesDelayed')
METRICS = ('Visible', 'InFlight', 'Delayed')


def handler(event, context):
    # Missing or failed reads must never publish zero and trigger unsafe scale-in.
    attributes = sqs.get_queue_attributes(QueueUrl=os.environ['QUEUE_URL'], AttributeNames=list(NAMES))['Attributes']
    values = [int(attributes[name]) for name in NAMES]
    cw.put_metric_data(Namespace='SPIP/Scaling', MetricData=[
        {'MetricName': name, 'Dimensions': [{'Name': 'Queue', 'Value': 'backend-jobs'}], 'Value': value, 'Unit': 'Count'}
        for name, value in zip(METRICS, values)])
    return dict(zip(METRICS, values))
