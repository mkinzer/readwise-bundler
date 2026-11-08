"""Fake Reader documents and a fake API client, so tests never touch the network."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

BASE = datetime(2025, 6, 1, tzinfo=timezone.utc)


def make_doc(i: int, *, minutes: int = 10, days: int = 0, tags=(), category: str = "article",
             location: str = "later", words: Optional[int] = None, published: Optional[str] = None,
             **extra) -> Dict:
    doc_id = f"doc{i:04d}"
    words = words if words is not None else minutes * 238
    doc = {
        "id": doc_id,
        "url": f"https://read.readwise.io/read/{doc_id}",
        "title": f"Article {i}",
        "author": f"Author {i}",
        "site_name": f"Site {i}",
        "category": category,
        "location": location,
        "tags": {t.lower(): {"name": t, "type": "manual", "created": 0} for t in tags},
        "word_count": words,
        "reading_time": f"{minutes} mins",
        "published_date": published,
        "summary": f"Summary of article {i}.",
        "saved_at": (BASE + timedelta(days=days)).isoformat(),
        "parent_id": None,
        "notes": "",
    }
    doc.update(extra)
    return doc


def body_for(doc: Dict) -> str:
    """HTML long enough to pass the empty-save check for the document's word count."""
    words = max(doc.get("word_count") or 0, 200)
    return "<p>" + " ".join(["word"] * words) + "</p>"


class FakeClient:
    def __init__(self, docs: List[Dict]):
        self.docs: Dict[str, Dict] = {d["id"]: copy.deepcopy(d) for d in docs}
        self.saved: List[Dict] = []
        self.updates: List[Dict] = []
        self.html: Dict[str, str] = {}

    def list_documents(self, **params):
        for doc in list(self.docs.values()):
            if "location" in params and doc.get("location") != params["location"]:
                continue
            if "tag" in params and params["tag"] not in doc.get("tags", {}):
                continue
            if "id" in params and doc["id"] != params["id"]:
                continue
            out = copy.deepcopy(doc)
            if params.get("withHtmlContent") == "true":
                out["html_content"] = self.html.get(doc["id"], body_for(doc))
            yield out

    def get_document(self, doc_id, *, with_html=True):
        params = {"id": doc_id}
        if with_html:
            params["withHtmlContent"] = "true"
        return next(self.list_documents(**params), None)

    def save(self, payload):
        self.saved.append(payload)
        doc_id = f"bundle{len(self.saved)}"
        self.docs[doc_id] = {
            "id": doc_id, "url": f"https://read.readwise.io/read/{doc_id}",
            "title": payload["title"], "location": payload["location"], "category": "article",
            "tags": {t: {"name": t} for t in payload["tags"]}, "notes": payload["notes"],
            "parent_id": None, "word_count": 5000, "reading_time": "50 mins",
            "saved_at": BASE.isoformat(),
        }
        return 201, {"id": doc_id, "url": f"https://read.readwise.io/read/{doc_id}"}

    def _apply(self, doc_id, fields):
        self.updates.append({"id": doc_id, **fields})
        doc = self.docs[doc_id]
        if "tags" in fields:
            doc["tags"] = {t.lower(): {"name": t} for t in fields["tags"]}
        if "location" in fields:
            doc["location"] = fields["location"]

    def update(self, doc_id, fields):
        self._apply(doc_id, fields)
        return {"id": doc_id}

    def bulk_update(self, updates):
        for item in updates:
            fields = {k: v for k, v in item.items() if k != "id"}
            self._apply(item["id"], fields)
        return [{"id": u["id"], "success": True} for u in updates]
