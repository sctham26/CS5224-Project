"""Copy non-secret CDK stack outputs into GitHub repository Actions variables."""
import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("outputs", type=Path)
parser.add_argument("--repo", default="sctham26/CS5224-Project")
args = parser.parse_args()
outputs = json.loads(args.outputs.read_text())["InfraStack"]
variables = {
    "FRONTEND_BUCKET_NAME": outputs["FrontendBucketName"],
    "CLOUDFRONT_DISTRIBUTION_ID": outputs["DistributionId"],
    "FRONTEND_URL": outputs["FrontendUrl"],
    "FRONTEND_DEPLOY_ROLE_ARN": outputs["FrontendDeployRoleArn"],
}
for name, value in variables.items():
    subprocess.run(["gh", "variable", "set", name, "--repo", args.repo, "--body", value], check=True)
    print(f"Set {name}")
