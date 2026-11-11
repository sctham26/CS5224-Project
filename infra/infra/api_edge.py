"""CloudFront API routing shared by the real runtime and routing tests."""
from aws_cdk import Fn, aws_cloudfront as cloudfront, aws_cloudfront_origins as origins


def attach_api(frontend, endpoint):
    # Error bodies may be tenant-specific too. Preserve status/body, but never
    # let CloudFront's separate error-cache TTL retain a 403/404/5xx response.
    frontend.distribution.node.default_child.add_property_override(
        "DistributionConfig.CustomErrorResponses",
        [{"ErrorCode": code, "ErrorCachingMinTTL": 0} for code in (403, 404, 500, 502, 503, 504)])
    rewrite = cloudfront.Function(frontend, "ApiPrefixRouting",
        code=cloudfront.FunctionCode.from_inline("""
function handler(event) {
    var r = event.request;
    if (r.uri === '/api') { r.uri = '/'; }
    else if (r.uri.indexOf('/api/') === 0) { r.uri = r.uri.substring(4); }
    return r;
}
"""))
    origin = origins.HttpOrigin(Fn.select(2, Fn.split("/", endpoint)),
        protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY)
    for path in ("api/*", "api"):
        frontend.distribution.add_behavior(path, origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            function_associations=[cloudfront.FunctionAssociation(function=rewrite,
                event_type=cloudfront.FunctionEventType.VIEWER_REQUEST)])
