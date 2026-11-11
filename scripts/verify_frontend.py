"""Check the deployed HTML, every referenced local JS/CSS, and release SHA."""
import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        path = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" else None
        if path and urlsplit(path).path.endswith((".js", ".css")):
            self.paths.append(path)


def verify(base_url, dist, commit):
    if urlsplit(base_url).scheme != "https":
        raise ValueError("Frontend URL must use HTTPS")
    base_url = base_url.rstrip("/") + "/"
    with urlopen(base_url, timeout=30) as response:
        html = response.read()
    if html != (Path(dist) / "index.html").read_bytes():
        raise ValueError("Deployed index.html does not match this build")
    parser = Assets()
    parser.feed(html.decode())
    if not parser.paths:
        raise ValueError("No JS/CSS assets found in deployed HTML")
    for path in parser.paths:
        url = urljoin(base_url, path)
        if urlsplit(url).netloc != urlsplit(base_url).netloc:
            raise ValueError(f"Unexpected external asset: {url}")
        with urlopen(url, timeout=30) as response:
            if "text/html" in response.headers.get("Content-Type", ""):
                raise ValueError(f"Asset returned HTML: {url}")
            if not response.read(1):
                raise ValueError(f"Empty asset: {url}")
    with urlopen(urljoin(base_url, "release.json"), timeout=30) as response:
        if json.load(response).get("commit") != commit:
            raise ValueError("Deployed release SHA does not match")
    print(f"Verified HTML, {len(parser.paths)} assets, and release {commit}: {base_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("commit")
    parser.add_argument("--dist", default="frontend/dist")
    args = parser.parse_args()
    verify(args.url, args.dist, args.commit)
