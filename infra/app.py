#!/usr/bin/env python3
import json
import os
from pathlib import Path
import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront, aws_cloudfront_origins as origins
from infra.infra_stack import InfraStack
from infra.backend_config import BackendConfig
from infra.backend_data_stack import BackendDataStack
from infra.backend_runtime_stack import BackendRuntimeStack


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
if enabled(app.node.try_get_context("enable_backend")):
    path = app.node.try_get_context("backend_config")
    if not path:
        raise ValueError("Provide -c backend_config=<reviewed JSON file>")
    config = BackendConfig.from_dict(json.loads(Path(path).read_text()))
    data = BackendDataStack(app, "BackendDataStack", config=config, env=env, termination_protection=True)
    if enabled(app.node.try_get_context("enable_backend_runtime")):
        runtime = BackendRuntimeStack(app, "BackendRuntimeStack", data=data, config=config, env=env)
        # The API Gateway has unprefixed routes. Rewrite /api/jobs to /jobs.
        rewrite = cloudfront.Function(frontend, "ApiPrefixRouting", code=cloudfront.FunctionCode.from_inline(
            "function handler(event) { var r = event.request; r.uri = r.uri.substring(4); return r; }"
        ))
        frontend.distribution.add_behavior(
            "api/*", origins.HttpOrigin(cdk.Fn.select(2, cdk.Fn.split("/", runtime.api.api_endpoint))),
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            function_associations=[cloudfront.FunctionAssociation(
                function=rewrite, event_type=cloudfront.FunctionEventType.VIEWER_REQUEST)],
        )
else:
    if enabled(app.node.try_get_context("enable_backend_runtime")):
        raise ValueError("enable_backend_runtime requires enable_backend=true")
app.synth()
