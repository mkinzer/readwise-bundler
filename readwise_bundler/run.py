"""One daily run: settle finished bundles, then top the shelf back up to five.

All state lives in Reader itself, so there is no database to lose:

* a bundle is any document tagged ``listen-bundle``;
* its note lists the Reader links of the originals inside it;
* originals carry ``bundled`` once used, and ``bundle-heard`` once their bundle
  has been archived (the bundle gets ``bundle-heard`` too, so it is settled once).

Every step can be re-run safely. If a run dies between saving a bundle and
tagging its originals, the next run sees the originals listed in that bundle's
note, never reuses them, and adds the missing tags.
"""
from __future__ import annotations

import os
import random
import re
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

from .api import ReaderClient
from .compose import Bundle, clean_article_html, looks_complete
from .picking import (
    TAG_BUNDLE, TAG_BUNDLED, TAG_HEARD, Article, Picker, Rule, eligible, tag_keys, tag_names,
)

TARGET_OPEN = 5
_ORIGINAL_LINK = re.compile(r"read\.readwise\.io/(?:[a-z]+/)?read/([0-9a-z]+)", re.I)
_BUNDLE_NUMBER = re.compile(r"^\s*Bundle\s+(\d+)\b", re.I)


def original_ids(notes: Optional[str]) -> List[str]:
    return _ORIGINAL_LINK.findall(notes or "")


def bundle_number(title: Optional[str]) -> int:
    match = _BUNDLE_NUMBER.match(title or "")
    return int(match.group(1)) if match else 0


def today_local() -> date:
    tz = os.environ.get("BUNDLER_TZ", "America/New_York")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:  # no tz database: fall back to the machine's date
        return date.today()


class Run:
    def __init__(
        self,
        client: ReaderClient,
        *,
        target: int = TARGET_OPEN,
        dry_run: bool = False,
        rng: Optional[random.Random] = None,
        rule: Rule = Rule(),
        made_on: Optional[date] = None,
        preview_dir: Optional[Path] = None,
        log: Callable[[str], None] = print,
    ):
        self.client = client
        self.target = target
        self.dry_run = dry_run
        self.rng = rng or random.Random()
        self.rule = rule
        self.made_on = made_on or today_local()
        self.preview_dir = preview_dir
        self.log = log
        self.created: List[Bundle] = []

    # ------------------------------------------------------------- the run

    def go(self) -> List[Bundle]:
        prefix = "[dry run] " if self.dry_run else ""
        bundles = [b for b in self.client.list_documents(tag=TAG_BUNDLE) if not b.get("parent_id")]
        open_bundles = [b for b in bundles if b.get("location") != "archive"]
        settled_needed = [b for b in bundles
                          if b.get("location") == "archive" and TAG_HEARD not in tag_keys(b)]
        used: Set[str] = {i for b in bundles for i in original_ids(b.get("notes"))}
        number = max((bundle_number(b.get("title")) for b in bundles), default=0)
        self.log(f"{prefix}{len(bundles)} bundles exist: {len(open_bundles)} waiting, "
                 f"{len(settled_needed)} newly finished.")

        later = list(self.client.list_documents(location="later"))
        by_id = {d["id"]: d for d in later}
        self.log(f"{prefix}{len(later)} documents in Later.")

        self._settle_finished(settled_needed, by_id)
        self._repair_bundled_tags(used, by_id)

        wanted = max(0, self.target - len(open_bundles))
        if not wanted:
            self.log(f"{prefix}The shelf already has {len(open_bundles)} bundles; nothing to make.")
            return []

        pool, skipped = eligible(later, exclude_ids=used)
        reasons = ", ".join(f"{n} {why}" for why, n in sorted(skipped.items(), key=lambda x: -x[1]))
        self.log(f"{prefix}{len(pool)} articles can be bundled (skipped: {reasons or 'none'}).")
        picker = Picker(pool, self.rule, self.rng)

        for _ in range(wanted):
            number += 1
            bundle = self._build(picker, number)
            if bundle is None:
                self.log(f"{prefix}Could not find another set of articles that fits the rules.")
                break
            self._deliver(bundle, by_id)
        return self.created

    # ------------------------------------------------------- finished bundles

    def _settle_finished(self, finished: List[Dict], by_id: Dict[str, Dict]) -> None:
        for bundle in finished:
            ids = original_ids(bundle.get("notes"))
            updates = []
            for doc_id in ids:
                doc = by_id.get(doc_id) or self.client.get_document(doc_id, with_html=False)
                if doc is None:
                    continue  # deleted since
                tags = _with_tag(doc, TAG_HEARD)
                if tags is not None:
                    updates.append({"id": doc_id, "tags": tags})
            title = bundle.get("title")
            if self.dry_run:
                self.log(f"[dry run] Would mark {title!r} and {len(updates)} originals as {TAG_HEARD}.")
                continue
            if updates:
                self.client.bulk_update(updates)
            self.client.update(bundle["id"], {"tags": _with_tag(bundle, TAG_HEARD) or tag_names(bundle)})
            self.log(f"Marked {title!r} and {len(updates)} originals as {TAG_HEARD}.")

    def _repair_bundled_tags(self, used: Set[str], by_id: Dict[str, Dict]) -> None:
        """Originals listed in a bundle's note but missing the tag: an earlier run was interrupted."""
        updates = []
        for doc_id in used:
            doc = by_id.get(doc_id)
            if doc is not None:
                tags = _with_tag(doc, TAG_BUNDLED)
                if tags is not None:
                    updates.append({"id": doc_id, "tags": tags})
        if not updates:
            return
        if self.dry_run:
            self.log(f"[dry run] Would add the missing {TAG_BUNDLED} tag to {len(updates)} originals.")
            return
        self.client.bulk_update(updates)
        self.log(f"Added the missing {TAG_BUNDLED} tag to {len(updates)} originals.")

    # ------------------------------------------------------------ new bundles

    def _build(self, picker: Picker, number: int) -> Optional[Bundle]:
        """Pick articles, fetch their text, and swap out any that turn out to be empty saves."""
        for _ in range(10):
            articles = picker.pick()
            if not articles:
                return None
            bodies: Dict[str, str] = {}
            stubs: List[Article] = []
            for article in articles:
                doc = self.client.get_document(article.id, with_html=True) or {}
                cleaned = clean_article_html(doc.get("html_content"))
                if looks_complete(article, cleaned):
                    bodies[article.id] = cleaned.html
                else:
                    stubs.append(article)
            if not stubs:
                return Bundle(number=number, articles=articles, bodies=bodies, made_on=self.made_on)
            for stub in stubs:
                self.log(f"Skipping {stub.title!r}: Reader has little or none of its text.")
            picker.release(a.id for a in articles if a not in stubs)
        return None

    def _deliver(self, bundle: Bundle, by_id: Dict[str, Dict]) -> None:
        listing = "; ".join(f"{a.title} ({a.minutes} min, saved {a.saved_at.date()})"
                            for a in bundle.articles)
        if self.preview_dir is not None:
            self.preview_dir.mkdir(parents=True, exist_ok=True)
            path = self.preview_dir / f"bundle-{bundle.number}.html"
            path.write_text(_preview_page(bundle), encoding="utf-8")
        if self.dry_run:
            self.log(f"[dry run] Would save {bundle.title!r}: {listing}")
            self.created.append(bundle)
            return
        status, body = self.client.save(bundle.payload())
        updates = []
        for article in bundle.articles:
            doc = by_id.get(article.id)
            tags = _with_tag(doc, TAG_BUNDLED) if doc else None
            if tags is not None:
                updates.append({"id": article.id, "tags": tags})
        if updates:
            self.client.bulk_update(updates)
        verb = "Saved" if status == 201 else "Already had"
        self.log(f"{verb} {bundle.title!r} ({body.get('url', '')}): {listing}")
        self.created.append(bundle)


def _with_tag(doc: Dict, tag: str) -> Optional[List[str]]:
    """The document's full tag list plus ``tag``, or None if it already has it.

    The API replaces the whole tag list on update, so every existing tag has to
    be sent back or it would be removed.
    """
    if tag in tag_keys(doc):
        return None
    return tag_names(doc) + [tag]


def _preview_page(bundle: Bundle) -> str:
    return (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{bundle.title}</title>"
        "<style>body{max-width:42rem;margin:2rem auto;padding:0 1rem;font:17px/1.6 Georgia,serif}"
        "h2{margin-top:2.5rem}</style>"
        f"<h1>{bundle.title}</h1>{bundle.html()}"
    )
