"""A small client for the Readwise Reader API (v3).

Reference: https://readwise.io/reader_api

Only the standard library is used, so the scheduled job needs nothing
installed. Requests are paced to stay under each endpoint's published rate
limit, and a 429 is answered by waiting for the number of seconds in its
Retry-After header, as the documentation asks.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

BASE_URL = "https://readwise.io/api/v3"
AUTH_URL = "https://readwise.io/api/v2/auth/"
USER_AGENT = "readwise-bundler"

# Published limits, per access token: LIST, BULK UPDATE and tags 20/minute;
# CREATE and UPDATE 50/minute. The intervals leave a little headroom.
MIN_INTERVAL = {"slow": 3.1, "fast": 1.25}

BULK_LIMIT = 50  # items per bulk_update request


class ReaderError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ReaderClient:
    def __init__(
        self,
        token: str,
        *,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        opener: Optional[Callable[..., Any]] = None,
    ):
        if not token:
            raise ValueError("A Readwise access token is required.")
        self._token = token
        self._max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._open = opener or urllib.request.urlopen
        self._last_call: Dict[str, float] = {}

    # ------------------------------------------------------------------ core

    def _pace(self, bucket: str) -> None:
        interval = MIN_INTERVAL[bucket]
        last = self._last_call.get(bucket)
        if last is not None:
            wait = interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[bucket] = self._clock()

    def _request(
        self,
        method: str,
        url: str,
        *,
        bucket: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(self._max_retries + 1):
            self._pace(bucket)
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", f"Token {self._token}")
            req.add_header("User-Agent", USER_AGENT)
            if data is not None:
                req.add_header("Content-Type", "application/json")
            try:
                with self._open(req, timeout=60) as resp:
                    raw = resp.read()
                    status = resp.status
            except urllib.error.HTTPError as err:
                status = err.code
                raw = err.read() or b""
                if status == 429 and attempt < self._max_retries:
                    self._sleep(_retry_after(err.headers.get("Retry-After")))
                    continue
                if status >= 500 and attempt < self._max_retries:
                    self._sleep(min(60, 2 ** attempt * 2))
                    continue
                detail = raw.decode("utf-8", "replace")[:500]
                raise ReaderError(status, f"{method} {url} failed with {status}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt < self._max_retries:
                    self._sleep(min(60, 2 ** attempt * 2))
                    continue
                raise ReaderError(0, f"{method} {url} failed: {err}") from None
            if not raw:
                return status, None
            return status, json.loads(raw.decode("utf-8"))
        raise ReaderError(429, f"{method} {url} kept being rate limited")  # pragma: no cover

    # --------------------------------------------------------------- reading

    def check_auth(self) -> bool:
        status, _ = self._request("GET", AUTH_URL, bucket="slow")
        return status == 204

    def list_documents(self, **params: Any) -> Iterator[Dict[str, Any]]:
        """Every document matching the LIST parameters, across all pages."""
        query = {k: _param(v) for k, v in params.items() if v is not None}
        cursor: Optional[str] = None
        while True:
            if cursor:
                query["pageCursor"] = cursor
            url = f"{BASE_URL}/list/?{urllib.parse.urlencode(query)}"
            _, page = self._request("GET", url, bucket="slow")
            for doc in page.get("results", []):
                yield doc
            cursor = page.get("nextPageCursor")
            if not cursor:
                return

    def get_document(self, doc_id: str, *, with_html: bool = True) -> Optional[Dict[str, Any]]:
        params = {"id": doc_id}
        if with_html:
            params["withHtmlContent"] = "true"
        for doc in self.list_documents(**params):
            return doc
        return None

    # --------------------------------------------------------------- writing

    def save(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Create a document. Returns (status, body): 201 created, 200 already existed."""
        status, body = self._request("POST", f"{BASE_URL}/save/", bucket="fast", body=payload)
        return status, body or {}

    def update(self, doc_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        path = urllib.parse.quote(doc_id, safe="")
        _, body = self._request("PATCH", f"{BASE_URL}/update/{path}/", bucket="fast", body=fields)
        return body or {}

    def delete(self, doc_id: str) -> None:
        """Permanently delete a document (and its highlights)."""
        path = urllib.parse.quote(doc_id, safe="")
        self._request("DELETE", f"{BASE_URL}/delete/{path}/", bucket="slow")

    def bulk_update(self, updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply per-document updates, 50 at a time. Raises if any item fails."""
        results: List[Dict[str, Any]] = []
        for start in range(0, len(updates), BULK_LIMIT):
            chunk = updates[start:start + BULK_LIMIT]
            _, body = self._request("PATCH", f"{BASE_URL}/bulk_update/", bucket="slow",
                                    body={"updates": chunk})
            chunk_results = (body or {}).get("results", [])
            failed = [r for r in chunk_results if not r.get("success")]
            if failed:
                raise ReaderError(207, f"bulk update failed for {len(failed)} document(s): {failed}")
            results.extend(chunk_results)
        return results


def _param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _retry_after(header: Optional[str]) -> float:
    try:
        seconds = float(header) if header is not None else 5.0
    except ValueError:
        seconds = 5.0
    return max(1.0, seconds) + 0.5
