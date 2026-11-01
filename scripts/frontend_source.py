"""Select application source separately from the cloud workflow revision."""
import os
from pathlib import Path

SOURCES = {"integration", "feature/frontend-error-handling", "feature/real-csv-upload",
           "feature/insufficient-peer-display"}


def select_source(event, ref, sha, requested="integration", deploy=False, head_ref=""):
    if event == "workflow_dispatch":
        if ref not in {"refs/heads/cloud-config", "refs/heads/main"}:
            raise ValueError("Run the workflow from cloud-config or main")
        if requested not in SOURCES:
            raise ValueError("Select an approved frontend source branch")
        if deploy and requested != "integration":
            raise ValueError("Feature branches are check-only; integrate and retest before publishing")
        return requested
    if ((event == "push" and ref == "refs/heads/cloud-config") or
            (event == "pull_request" and head_ref == "cloud-config")):
        return "integration"
    if event in {"push", "pull_request"}:
        return sha
    raise ValueError("Unsupported frontend workflow event")


def main():
    source = select_source(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"],
        os.environ["GITHUB_SHA"], os.environ.get("FRONTEND_SOURCE_REF", "integration"),
        os.environ.get("PUBLISH_FRONTEND") == "true", os.environ.get("GITHUB_HEAD_REF", ""))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("ref=" + source + "\n")
    print("Frontend source:", source)


if __name__ == "__main__":
    main()
