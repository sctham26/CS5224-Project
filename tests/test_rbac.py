"""Role boundaries, tenant isolation and protected administration contracts."""
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
import api
from auth import Authenticator, InvalidToken, Principal, StaticMembershipStore
from datastore import CsvDataSource
from admin_access import CognitoDirectory, MembershipAdministration, AdminUnavailable, ProtectedAdministrator
from rbac import role_for

SUBJECT = '11111111-1111-4111-8111-111111111111'
TARGET = '22222222-2222-4222-8222-222222222222'
client = TestClient(api.app)

class Validator:
    def __init__(self, groups): self.groups = groups
    def verify(self, token):
        if token != 'verified': raise InvalidToken('bad token')
        return {'sub': SUBJECT, 'scope': 'spip/access', 'cognito:groups': self.groups}

def sign_in(monkeypatch, group):
    monkeypatch.setattr(api, '_authenticator', Authenticator(validator=Validator([group]),
        memberships=StaticMembershipStore({SUBJECT:'tenant_a'}), enabled=True))
    monkeypatch.setattr(api, '_datasource', CsvDataSource('tests/fixtures_tenants.csv'))
    return {'Authorization':'Bearer verified'}

@pytest.mark.parametrize('group,role', [('spip-admin','admin'),('spip-backend','backend'),('spip-tester','tester'),('spip-customer','customer')])
def test_verified_group_and_identity(monkeypatch, group, role):
    headers=sign_in(monkeypatch,group)
    response=client.get('/auth/me',headers=headers)
    assert response.status_code==200
    assert response.json()['role']==role and response.json()['tenant_id']=='tenant_a'
    assert response.headers['cache-control']=='no-store'

@pytest.mark.parametrize('groups', ['spip-admin', {'spip-admin':True}, [1]])
def test_malformed_groups_fail_closed(groups):
    auth=Authenticator(validator=Validator(groups),memberships=StaticMembershipStore({SUBJECT:'a'}))
    with pytest.raises(InvalidToken): auth.authenticate('Bearer verified')

def test_multiple_groups_use_explicit_precedence():
    assert role_for(('spip-tester','spip-admin','spip-backend'))=='admin'
    assert role_for(('arbitrary-admin-name',))=='customer'

@pytest.mark.parametrize('group', ['spip-admin','spip-backend','spip-tester','spip-customer'])
def test_all_roles_keep_existing_cross_tenant_data_isolation(monkeypatch,group):
    headers=sign_in(monkeypatch,group)
    assert client.get('/analysis/BETA_BUILD',headers=headers).status_code==404
    assert client.get('/analysis/ALPHA_BUILD',headers=headers).status_code==200

@pytest.mark.parametrize('group,expected', [('spip-admin',200),('spip-backend',200),('spip-tester',403),('spip-customer',403)])
def test_operations_roles_are_enforced(monkeypatch,group,expected):
    headers=sign_in(monkeypatch,group)
    assert client.get('/ops/status',headers=headers).status_code==expected
    assert client.post('/ops/cache/invalidate',headers=headers).status_code==expected

@pytest.mark.parametrize('path,method,body', [('/admin/users','GET',None),
    (f'/admin/users/{TARGET}/role','PUT',{'role':'backend'}),
    (f'/admin/memberships/{TARGET}','PUT',{'tenant_id':'a','active':True})])
@pytest.mark.parametrize('group',['spip-backend','spip-tester','spip-customer'])
def test_non_admin_cannot_invoke_adapters(monkeypatch,path,method,body,group):
    directory,store=Mock(),Mock()
    monkeypatch.setattr(api,'_directory',directory);monkeypatch.setattr(api,'_membership_administration',store)
    headers=sign_in(monkeypatch,group)
    assert client.request(method,path,headers=headers,json=body).status_code==403
    assert not directory.mock_calls and not store.mock_calls

def test_headers_and_body_cannot_grant_admin(monkeypatch):
    headers=sign_in(monkeypatch,'spip-tester')
    headers.update({'X-Role':'admin','X-Tenant-ID':'tenant_b'})
    assert client.get('/admin/users',headers=headers).status_code==403
    assert client.get('/auth/me',headers=headers).json()['tenant_id']=='tenant_a'

@pytest.mark.parametrize('path,body', [(f'/admin/users/{SUBJECT}/role',{'role':'tester'}),
    (f'/admin/memberships/{SUBJECT}',{'tenant_id':'a','active':False})])
def test_admin_cannot_demote_or_deactivate_self(monkeypatch,path,body):
    headers=sign_in(monkeypatch,'spip-admin')
    assert client.put(path,headers=headers,json=body).status_code==409

def test_admin_membership_calls_separate_store(monkeypatch):
    headers=sign_in(monkeypatch,'spip-admin');store=Mock()
    store.set_membership.return_value={'subject':TARGET,'tenant_id':'b','active':True}
    monkeypatch.setattr(api,'_membership_administration',store)
    response=client.put(f'/admin/memberships/{TARGET}',headers=headers,json={'tenant_id':'b','active':True})
    assert response.status_code==200
    store.set_membership.assert_called_once_with(TARGET,'b',True)

def test_missing_admin_credentials_fail_closed():
    with pytest.raises(AdminUnavailable): MembershipAdministration(url='').set_membership(TARGET,'a',True)

def test_cache_invalidation_is_tenant_and_process_scoped(monkeypatch):
    headers=sign_in(monkeypatch,'spip-backend')
    source=api._datasource;source.load('tenant_a');other=source.load('tenant_b')
    monkeypatch.setattr(api,'_analysis_cache',{})
    api._analysis_cache.update({(1,'tenant_a','asset','a',2024):(1,None,{}),
        (2,'tenant_b','asset','b',2024):(1,None,{})})
    response=client.post('/ops/cache/invalidate',headers=headers)
    assert response.json()['cache_scope']=='current_api_process'
    assert response.json()['analysis_entries_removed']==1
    assert len(api._analysis_cache)==1 and source.load('tenant_b') is other

def test_cognito_admin_groups_cannot_be_granted_or_removed_by_api():
    aws=Mock();directory=CognitoDirectory('pool',aws)
    with pytest.raises(ProtectedAdministrator):directory.set_role(TARGET,'admin')
    assert not aws.mock_calls
    aws.admin_list_groups_for_user.return_value={'Groups':[{'GroupName':'spip-admin'}]}
    with pytest.raises(ProtectedAdministrator):directory.set_role(TARGET,'tester')
    aws.admin_remove_user_from_group.assert_not_called()
    aws.admin_add_user_to_group.assert_not_called()

def test_role_demotion_removes_old_privilege_before_granting_new_group():
    aws=Mock();directory=CognitoDirectory('pool',aws)
    aws.admin_list_groups_for_user.side_effect=[{'Groups':[{'GroupName':'spip-backend'}]}, {'Groups':[{'GroupName':'spip-tester'}]}]
    directory.set_role(TARGET,'tester')
    calls=[c[0] for c in aws.mock_calls]
    assert calls.index('admin_remove_user_from_group')<calls.index('admin_add_user_to_group')

def test_provider_failure_does_not_expose_secrets(monkeypatch):
    headers=sign_in(monkeypatch,'spip-admin');store=Mock()
    store.set_membership.side_effect=RuntimeError('postgres://SECRET')
    monkeypatch.setattr(api,'_membership_administration',store)
    response=client.put(f'/admin/memberships/{TARGET}',headers=headers,json={'tenant_id':'a','active':True})
    assert response.status_code==503 and 'SECRET' not in response.text

def test_privileged_routes_require_authentication(monkeypatch):
    sign_in(monkeypatch,'spip-admin')
    assert client.get('/auth/me').status_code==401
    assert client.get('/ops/status').status_code==401
    assert client.get('/admin/users').status_code==401
