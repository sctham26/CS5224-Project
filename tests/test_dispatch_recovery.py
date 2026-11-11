from unittest.mock import Mock
import pytest
from fastapi import HTTPException
import api
from auth import Principal
from jobs import InMemoryJobStore

def test_failed_send_is_retried_with_same_job(monkeypatch):
    store = InMemoryJobStore()
    queue = Mock()
    queue.send.side_effect = [RuntimeError('temporary outage'), None]
    monkeypatch.setattr(api, '_job_store', store)
    monkeypatch.setattr(api, '_job_queue', queue)
    monkeypatch.setattr(api, '_uploader', Mock())
    payload = api.JobRequest(upload_key='tenants/test/uploads/a.csv', entity_id='TEST', reporting_year=2025, scope='asset')
    principal = Principal(subject='test', tenant_id='test')
    with pytest.raises(HTTPException) as error:
        api.post_jobs(payload, principal, 'stable-key')
    assert error.value.status_code == 503
    response = api.post_jobs(payload, principal, 'stable-key')
    assert response.status_code == 202
    assert queue.send.call_count == 2
    assert queue.send.call_args_list[0] == queue.send.call_args_list[1]
