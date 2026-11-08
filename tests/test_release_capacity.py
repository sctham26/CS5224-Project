import unittest
from scripts.release_backend import verify_services

class CapacityTests(unittest.TestCase):
    def test_scaled_services(self):
        outputs = dict(ApiServiceArn="api", ApiTaskDefinitionArn="api:1", WorkerServiceArn="worker", WorkerTaskDefinitionArn="worker:1")
        services = [dict(serviceArn=s, taskDefinition=s+":1", desiredCount=3, runningCount=3, pendingCount=0, deployments=[dict(rolloutState="COMPLETED")]) for s in ("api", "worker")]
        verify_services(dict(services=services), outputs)
        services[0]["runningCount"] = 2
        with self.assertRaises(ValueError):
            verify_services(dict(services=services), outputs)
