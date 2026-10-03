"""Produce docs/cache.json locally, matching .github/workflows/update-cache.yml.

The workflow builds this with jq; this exists so the file is present in the
repository on the first commit rather than only after CI has run. Both write the
same shape, so whichever runs last simply refreshes it.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "agniveshtm/flux"
HEADERS = {"User-Agent": "flux-cache", "Accept": "application/vnd.github+json"}


def get(path: str):
    url = f"https://api.github.com/repos/{REPO}{path}"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def flatten(body: str) -> str:
    """The same HTML -> text reduction the jq `text` filter applies."""
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body or "", flags=re.S | re.I)
    body = re.sub(r"<[^>]*>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n[ \t]+", "\n", body)
    return body.strip()


releases = []
for item in get("/releases?per_page=25"):
    tag = item.get("tag_name") or ""
    if item.get("draft") or not re.match(r"^v?\d", tag):
        continue
    releases.append(
        {
            "tag": tag,
            "version": tag[1:] if tag.startswith("v") else tag,
            "name": item.get("name") or "",
            "published": item.get("published_at") or "",
            "url": item.get("html_url") or "",
            "prerelease": bool(item.get("prerelease")),
            "body": flatten(item.get("body") or ""),
        }
    )

commits = [
    {
        "sha": item["sha"][:7],
        "subject": (item.get("commit", {}).get("message") or "").split("\n")[0],
        "date": (item.get("commit", {}).get("author") or {}).get("date") or "",
        "url": item.get("html_url") or "",
    }
    for item in get("/commits?per_page=20")
]

data = {
    "source": "rest",
    "repo": REPO,
    "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "latest": releases[0]["version"] if releases else "",
    "releases": releases,
    "commits": commits,
}

out = Path("docs/cache.json")
out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {out}: {len(releases)} release(s), {len(commits)} commit(s), latest {data['latest'] or 'none'}")
for r in releases:
    print(f"  {r['tag']}  {r['published'][:10]}  body={len(r['body'])} chars")
