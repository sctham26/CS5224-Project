#!/usr/bin/env python3
import json
from dataclasses import replace
import os
from pathlib import Path
import aws_cdk as cdk
from infra.api_edge import attach_api
from infra.infra_stack import InfraStack
from infra.backend_config import BackendConfig
from infra.backend_data_stack import BackendDataStack
from infra.backend_runtime_stack import BackendRuntimeStack
from infra.auth_stack import AuthStack
from infra.backend_operations_stack import BackendOperationsStack
from infra.backend_release_stack import BackendReleaseStack


def enabled(value):
    if value in (None, False, "false"):
        return False
    if value in (True, "true"):
        return True
    raise ValueError("Feature flags must be true or false")


app = cdk.App()
env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"),
                      region=os.getenv("CDK_DEFAULT_REGION", "ap-southeast-1"))
frontend = InfraStack(app, "InfraStack", env=env)
identity = None
if enabled(app.node.try_get_context("enable_auth")):
    identity = AuthStack(app, "AuthStack", env=env, termination_protection=True,
        frontend_origin=app.node.try_get_context("auth_frontend_origin") or "https://d10rc41o4pb0h.cloudfront.net",
        local_origin=app.node.try_get_context("auth_local_origin"))
if enabled(app.node.try_get_context("enable_backend")):
    path = app.node.try_get_context("backend_config")
    if not path:
        raise ValueError("Provide -c backend_config=<reviewed JSON file>")
    config = BackendConfig.from_dict(json.loads(Path(path).read_text()))
    data = BackendDataStack(app, "BackendDataStack", config=config, env=env, termination_protection=True)
    if enabled(app.node.try_get_context("enable_backend_operations")):
        BackendOperationsStack(app, "BackendOperationsStack", data=data, config=config, env=env)
    if enabled(app.node.try_get_context("enable_backend_runtime")):
        if identity:
            config = replace(config, jwt_issuer=identity.issuer,
                jwt_audience=(identity.client.user_pool_client_id,), authorization_scopes=("spip/access",))
        runtime = BackendRuntimeStack(app, "BackendRuntimeStack", data=data, config=config, env=env)
        attach_api(frontend, runtime.api.api_endpoint)
        if enabled(app.node.try_get_context("enable_backend_release")):
            BackendReleaseStack(app, "BackendReleaseStack", data=data, runtime=runtime, env=env)
else:
    if enabled(app.node.try_get_context("enable_backend_runtime")):
        raise ValueError("enable_backend_runtime requires enable_backend=true")
app.synth()
