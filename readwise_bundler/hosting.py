"""Somewhere public for thumbnails to live, because Reader takes a cover only as a URL.

Reader rejects images packed into a data: URL, and it does not use a picture in
the document's text as its cover, so each thumbnail is committed to the
``thumbnails`` branch of this repository and Reader is given its
raw.githubusercontent.com address. That address is public only while the
repository is public.

In GitHub Actions the job's own token (``GITHUB_TOKEN``, with ``contents: write``)
does the uploading; nothing else is needed.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional


class GitHubBranchHost:
    API = "https://api.github.com"

    def __init__(self, repo: str, token: str, *, branch: str = "thumbnails", opener=None):
        self.repo = repo
        self.token = token
        self.branch = branch
        self._open = opener or urllib.request.urlopen

    @classmethod
    def from_env(cls) -> Optional["GitHubBranchHost"]:
        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not repo or not token:
            return None
        return cls(repo, token, branch=os.environ.get("BUNDLER_THUMBNAIL_BRANCH", "thumbnails"))

    def url_for(self, path: str) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.branch}/{path}"

    def put(self, path: str, data: bytes, message: str) -> str:
        """Create or replace the file at ``path`` on the branch, and return its public URL."""
        body = {"message": message, "branch": self.branch,
                "content": base64.b64encode(data).decode("ascii")}
        existing = self._sha(path)
        if existing:
            body["sha"] = existing
        self._call("PUT", f"/repos/{self.repo}/contents/{path}", body)
        return self.url_for(path)

    def _sha(self, path: str) -> Optional[str]:
        try:
            found = self._call("GET", f"/repos/{self.repo}/contents/{path}?ref={self.branch}")
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            raise
        return (found or {}).get("sha")

    def _call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.API}{path}", data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "readwise-bundler")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with self._open(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw) if raw else None
