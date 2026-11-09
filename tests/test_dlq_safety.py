from unittest.mock import Mock
import json
from worker import reconcile_dlq
from jobs import RUNNING, SUCCEEDED

def test_dlq_does_not_fail_an_active_job():
    store = Mock()
    store.get.return_value.status = RUNNING
    client = Mock()
    client.receive_message.side_effect = [{"Messages": [{"Body": json.dumps(dict(job_id="j", tenant_id="t", upload_key="tenants/t/uploads/x.csv", entity_id="e")), "ReceiptHandle": "r"}]}, {}]
    assert reconcile_dlq("q", store, client) == 0
    store.finish.assert_not_called()
    client.delete_message.assert_not_called()

def test_terminal_duplicate_can_be_removed():
    store = Mock()
    store.get.return_value.status = SUCCEEDED
    client = Mock()
    client.receive_message.side_effect = [{"Messages": [{"Body": json.dumps(dict(job_id="j", tenant_id="t", upload_key="tenants/t/uploads/x.csv", entity_id="e")), "ReceiptHandle": "r"}]}, {}]
    assert reconcile_dlq("q", store, client) == 1
    store.finish.assert_not_called()
    client.delete_message.assert_called_once()
