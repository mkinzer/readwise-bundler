"""Which articles may be bundled, and which ones go together.

The rule, as agreed:

* Only documents in Later, and only articles, newsletters and feed articles.
* Never anything tagged ``interactive``, anything already bundled, or a bundle.
* Anything Readwise labels at 40 minutes or more stands on its own.
* A bundle holds 2-4 articles adding up to 40-80 minutes, by Readwise's own
  reading-time label.
* Articles in a bundle were saved within 30 days of one another: pick one
  article at random, then choose its companions from what was saved within 30
  days either side of it. Picking an *article* rather than a date lands most
  often where the library is densest.
"""
from __future__ import annotations

import math
import random
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ELIGIBLE_CATEGORIES = {"article", "email", "rss"}

TAG_BUNDLE = "listen-bundle"   # on the bundles themselves
TAG_BUNDLED = "bundled"        # on an original once it is in a bundle
TAG_HEARD = "bundle-heard"     # on a bundle and its originals once the bundle is archived
TAG_TEST = "listen-bundle-test"
TAG_SKIP = "interactive"       # never bundle these
EXCLUDED_TAGS = {TAG_BUNDLE, TAG_BUNDLED, TAG_HEARD, TAG_TEST, TAG_SKIP}

STANDALONE_MINUTES = 40   # this long or longer is listened to on its own
MIN_WORDS = 150           # below this it is a teaser or an empty save
FALLBACK_WPM = 238        # only used when Readwise gives no reading time


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    author: str
    site_name: str
    minutes: int
    saved_at: datetime
    published: Optional[datetime]
    summary: str
    word_count: int
    category: str
    reader_url: str
    tag_names: Tuple[str, ...] = field(default_factory=tuple)


@dataclass
class Rule:
    min_minutes: int = 40
    max_minutes: int = 80
    min_items: int = 2
    max_items: int = 4
    window_days: int = 30
    anchor_tries: int = 300
    combo_tries: int = 300


# ------------------------------------------------------------------ parsing

_TIME_PART = re.compile(r"(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b", re.I)


def parse_minutes(reading_time: Optional[str], word_count: Optional[int]) -> Optional[int]:
    """Minutes from Readwise's label ("12 mins", "1 hr 5 mins"), else from the word count."""
    if isinstance(reading_time, (int, float)):
        return int(reading_time)
    if isinstance(reading_time, str) and reading_time.strip():
        total = 0
        found = False
        for amount, unit in _TIME_PART.findall(reading_time):
            found = True
            total += int(amount) * (60 if unit.lower().startswith("h") else 1)
        if found:
            return total
    if word_count:
        return max(1, math.ceil(word_count / FALLBACK_WPM))
    return None


def parse_when(value) -> Optional[datetime]:
    """A UTC datetime from an ISO string, a bare date, or epoch milliseconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def tag_keys(doc: Dict) -> List[str]:
    tags = doc.get("tags") or {}
    if isinstance(tags, dict):
        return [str(k).lower() for k in tags]
    return [str(t).lower() for t in tags]


def tag_names(doc: Dict) -> List[str]:
    """Display names, which is what the API expects back when tags are rewritten."""
    tags = doc.get("tags") or {}
    if isinstance(tags, dict):
        return [str((v or {}).get("name") or k) for k, v in tags.items()]
    return [str(t) for t in tags]


_SEPARATOR = re.compile(r"\s+[|\-–—]\s+")


def _bare(name: str) -> str:
    name = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    return name[4:] if name.startswith("the ") else name


def tidy_title(title: str, site_name: str = "") -> str:
    """Drop a trailing " - The New York Times" when it repeats the site, and calm ALL-CAPS titles."""
    title = re.sub(r"\s+", " ", title or "").strip() or "Untitled"
    parts = _SEPARATOR.split(title)
    if len(parts) > 1 and site_name and _bare(parts[-1]) == _bare(site_name):
        title = title[: title.rfind(parts[-1])].rstrip(" |-–—")
    letters = [c for c in title if c.isalpha()]
    if len(letters) > 10 and all(c.isupper() for c in letters):
        title = " ".join(w[:1].upper() + w[1:].lower() for w in title.split(" "))
    return title


def tidy_author(author: str) -> str:
    """"Name, Name, Name" read as a list; drop prefixes, links and junk."""
    author = re.sub(r"\s+", " ", author or "").strip()
    profile = re.match(r"https?://(?:www\.)?nytimes\.com/by/([a-z0-9-]+)", author)
    if profile:
        return " ".join(w.capitalize() for w in profile.group(1).split("-"))
    if author.lower().startswith("by "):
        author = author[3:].strip()
    if not author or "://" in author or "@" in author or "|" in author or len(author) > 80:
        return ""
    names = [n.strip() for n in author.split(",") if n.strip()]
    if len(names) > 3:
        return f"{names[0]}, {names[1]} and others"
    if len(names) > 1 and " and " not in author:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return author


def to_article(doc: Dict) -> Optional[Article]:
    minutes = parse_minutes(doc.get("reading_time"), doc.get("word_count"))
    saved = parse_when(doc.get("saved_at") or doc.get("created_at"))
    if minutes is None or saved is None:
        return None
    site_name = (doc.get("site_name") or "").strip()
    return Article(
        id=doc["id"],
        title=tidy_title(doc.get("title") or "", site_name),
        author=tidy_author(doc.get("author") or ""),
        site_name=site_name,
        minutes=minutes,
        saved_at=saved,
        published=parse_when(doc.get("published_date")),
        summary=(doc.get("summary") or "").strip(),
        word_count=int(doc.get("word_count") or 0),
        category=doc.get("category") or "",
        reader_url=doc.get("url") or f"https://read.readwise.io/read/{doc['id']}",
        tag_names=tuple(tag_names(doc)),
    )


# -------------------------------------------------------------- eligibility

def eligible(docs: Iterable[Dict], *, exclude_ids: Iterable[str] = ()) -> Tuple[List[Article], Dict[str, int]]:
    """Articles that may go into a bundle, and a count of why the rest may not."""
    excluded = set(exclude_ids)
    pool: List[Article] = []
    skipped: Dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for doc in docs:
        if doc.get("parent_id"):
            skip("highlight or note")
            continue
        if doc.get("location") not in (None, "later"):
            skip("not in Later")
            continue
        if doc.get("category") not in ELIGIBLE_CATEGORIES:
            skip(f"category: {doc.get('category')}")
            continue
        keys = set(tag_keys(doc))
        hit = keys & EXCLUDED_TAGS
        if hit:
            skip(f"tagged {sorted(hit)[0]}")
            continue
        if doc.get("id") in excluded:
            skip("already in a bundle")
            continue
        if (doc.get("word_count") or 0) < MIN_WORDS:
            skip(f"under {MIN_WORDS} words")
            continue
        article = to_article(doc)
        if article is None:
            skip("no length or date")
            continue
        if article.minutes >= STANDALONE_MINUTES:
            skip(f"{STANDALONE_MINUTES}+ minutes")
            continue
        pool.append(article)
    return pool, skipped


# ------------------------------------------------------------------ picking

class Picker:
    """Draws bundles from a pool without ever reusing an article."""

    def __init__(self, pool: Sequence[Article], rule: Rule = Rule(), rng: Optional[random.Random] = None):
        self.rule = rule
        self.rng = rng or random.Random()
        self._articles = sorted(pool, key=lambda a: a.saved_at)
        self._times = [a.saved_at for a in self._articles]
        self._used: set = set()

    @property
    def remaining(self) -> int:
        return len(self._articles) - len(self._used)

    def exclude(self, ids: Iterable[str]) -> None:
        self._used.update(ids)

    def release(self, ids: Iterable[str]) -> None:
        """Put articles back, e.g. the good ones from a bundle that had to be abandoned."""
        self._used.difference_update(ids)

    def _window(self, anchor: Article) -> List[Article]:
        span = timedelta(days=self.rule.window_days)
        lo = bisect_left(self._times, anchor.saved_at - span)
        hi = bisect_right(self._times, anchor.saved_at + span)
        return [a for a in self._articles[lo:hi] if a.id != anchor.id and a.id not in self._used]

    def pick(self) -> Optional[List[Article]]:
        r = self.rule
        available = [a for a in self._articles if a.id not in self._used and a.minutes < r.max_minutes]
        if not available:
            return None
        for _ in range(r.anchor_tries):
            anchor = self.rng.choice(available)
            neighbours = self._window(anchor)
            combo = self._combo(anchor, neighbours)
            if combo:
                self._used.update(a.id for a in combo)
                return order(combo)
        return None

    def _combo(self, anchor: Article, neighbours: List[Article]) -> Optional[List[Article]]:
        r = self.rule
        sizes = [k for k in range(r.min_items, r.max_items + 1) if k - 1 <= len(neighbours)]
        if not sizes:
            return None
        for _ in range(r.combo_tries):
            k = self.rng.choice(sizes)
            others = self.rng.sample(neighbours, k - 1)
            total = anchor.minutes + sum(a.minutes for a in others)
            if r.min_minutes <= total <= r.max_minutes:
                return [anchor] + others
        return None


def order(articles: Sequence[Article]) -> List[Article]:
    """Oldest publication first; articles with no publication date go by when they were saved."""
    return sorted(articles, key=lambda a: (a.published or a.saved_at, a.saved_at))


def total_minutes(articles: Sequence[Article]) -> int:
    return sum(a.minutes for a in articles)
