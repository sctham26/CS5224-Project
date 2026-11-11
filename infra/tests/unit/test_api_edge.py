import json
import subprocess
import aws_cdk as cdk
from aws_cdk.assertions import Template
from infra.infra_stack import InfraStack
from infra.api_edge import attach_api


def test_api_behavior_preserves_auth_query_and_body_without_spa_or_cache():
    app = cdk.App()
    stack = InfraStack(app, "Web", env=cdk.Environment(account="825990809862", region="ap-southeast-1"))
    attach_api(stack, "https://example.execute-api.ap-southeast-1.amazonaws.com")
    template = Template.from_stack(stack)
    distribution = next(iter(template.find_resources("AWS::CloudFront::Distribution").values()))["Properties"]["DistributionConfig"]
    routes = distribution["CacheBehaviors"]
    assert all(e["ErrorCachingMinTTL"] == 0 and "ResponsePagePath" not in e
        for e in distribution["CustomErrorResponses"])
    assert {v["PathPattern"] for v in routes} == {"api/*", "api"}
    for route in routes:
        assert route["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
        assert route["OriginRequestPolicyId"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
        assert set(route["AllowedMethods"]) == {"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"}
    function = next(v["Properties"]["FunctionCode"] for v in template.find_resources("AWS::CloudFront::Function").values()
        if "substring(4)" in v["Properties"]["FunctionCode"])
    runner = function + """
for (const [path, expected] of [['/api/health','/health'],['/api/entities','/entities'],['/api/jobs/j1','/jobs/j1'],['/api','/'],['/apix/jobs','/apix/jobs']]) {
 const request={uri:path,querystring:{scope:{value:'asset'}},headers:{authorization:{value:'Bearer test'}},method:'POST'};
 const result=handler({request});
 if(result.uri!==expected || result.headers.authorization.value!=='Bearer test' || result.querystring.scope.value!=='asset' || result.method!=='POST') throw Error(path);
}
"""
    subprocess.run(["node", "-e", runner], check=True)
