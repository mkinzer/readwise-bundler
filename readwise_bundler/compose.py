"""Assemble one bundle document, written for the ear.

A spoken intro lists what is coming, a spoken header comes before each
article, and after each one there is real silence and a fixed end line. The
end line never changes, so it becomes a signal rather than content.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Sequence

from .picking import Article, total_minutes

SYNTHETIC_HOST = "https://readwise-bundler.local"

WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]

# Silence. Reader hands a paragraph's visible text to the voice, and its
# Lifelike voices (ElevenLabs, by every sign) honour ElevenLabs' SSML break tag
# when it arrives as text: at most 3 seconds per tag, so longer silences use
# several paragraphs. It must be *visible* text (escaped); written as real markup
# Reader drops it before speaking. Eight listening tests ruled out everything
# else: dashes made the voice breathe oddly, hums and repeated sounds came out as
# sounds of pleasure, and headings, blank lines and rules were too short or did
# nothing. With other voices, such as Unreal Speech's, the tag may be read aloud.
BREAK_SECONDS = 3
_BREAK = "<p>" + html.escape(f'<break time="{BREAK_SECONDS}s" />', quote=False) + "</p>"
SHORT_PAUSE = _BREAK        # 3 seconds
LONG_PAUSE = _BREAK * 2     # 6 seconds, after each article


@dataclass
class Bundle:
    number: int
    articles: List[Article]
    bodies: Dict[str, str]          # article id -> cleaned HTML
    made_on: date
    revision: str = ""              # set when a bundle is remade, so Reader sees a new URL

    @property
    def minutes(self) -> int:
        return total_minutes(self.articles)

    @property
    def title(self) -> str:
        n = len(self.articles)
        return f"Bundle {self.number} · {n} articles · {self.minutes} min"

    @property
    def url(self) -> str:
        digest = hashlib.sha1(",".join(sorted(a.id for a in self.articles)).encode()).hexdigest()[:10]
        suffix = f"-{self.revision}" if self.revision else ""
        return f"{SYNTHETIC_HOST}/bundle/{self.number}-{digest}{suffix}"

    def summary(self) -> str:
        return "; ".join(f"{a.title} ({a.minutes} min)" for a in self.articles)

    def notes(self) -> str:
        """Kept on the bundle in Reader: a readable record, and how the tool finds the originals."""
        lines = ["Bundled by readwise-bundler from:"]
        lines += [f"• {a.title} — {a.reader_url}" for a in self.articles]
        return "\n".join(lines)

    def html(self) -> str:
        n = len(self.articles)
        parts: List[str] = []
        parts.append(_p(f"Bundle {self.number}, bundled on {_spoken_date(self.made_on)}."))
        parts.append(_p(f"This bundle includes {_word(n)} different articles, "
                        f"about {self.minutes} minutes in total. They are:"))
        for i, a in enumerate(self.articles):
            line = f"{ORDINALS[i]}: “{a.title}”{_byline(a, leading=', ')}. About {a.minutes} minutes."
            summary = clean_summary(a.summary)
            if summary:
                line += f" {summary}"
            parts.append(_p(line))
        parts.append(SHORT_PAUSE)
        for i, a in enumerate(self.articles, 1):
            parts.append(f"<h2>{_e(f'Article {i} of {n}: {a.title}')}</h2>")
            byline = _byline(a, leading="").strip(", ")
            parts.append(_p(f"{byline[:1].upper()}{byline[1:]}. About {a.minutes} minutes."
                            if byline else f"About {a.minutes} minutes."))
            parts.append(self.bodies.get(a.id, ""))
            parts.append(LONG_PAUSE)
            parts.append(_p(f"End of article {_word(i)}: “{a.title}”."))
            parts.append(SHORT_PAUSE)
        parts.append(_p(f"End of bundle {self.number}. That was all {_word(n)} articles."))
        return "<div>\n" + "\n".join(p for p in parts if p) + "\n</div>"

    def payload(self) -> Dict:
        return {
            "url": self.url,
            "html": self.html(),
            "should_clean_html": False,
            "title": self.title,
            "author": "readwise-bundler",
            "summary": self.summary(),
            "language": "en",
            "location": "later",
            "category": "article",
            "tags": ["listen-bundle"],
            "notes": self.notes(),
            "saved_using": "readwise-bundler",
        }


# ---------------------------------------------------------------- wording

def _e(text: str) -> str:
    return html.escape(text, quote=False)


def _p(text: str) -> str:
    return f"<p>{_e(text)}</p>"


def _word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _spoken_date(d) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if text[-1:] in ".!?”\"'" else text + "."


# Readwise's summary is often the publisher's page description, which can be
# site boilerplate. Sentences like these are dropped; if nothing is left, the
# intro simply has no summary for that article.
_SUMMARY_JUNK = re.compile(
    r"\.gov website|official government organization|https://|cookies?\b|javascript|"
    r"sign up|subscribe|newsletter|newsroom that investigates|all rights reserved|"
    r"click here|log ?in\b|support our|become a member|donate", re.I)


def clean_summary(summary: str) -> str:
    text = re.sub(r"\s+", " ", summary or "").strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"'])", text)
    kept = [s for s in sentences if not _SUMMARY_JUNK.search(s)]
    return _sentence(" ".join(kept)) if kept else ""


def _byline(a: Article, *, leading: str) -> str:
    """", by Author, from Site, published March 3, 2025" - only the parts that exist."""
    bits = []
    author = a.author
    if author and author.lower() != a.site_name.lower():
        bits.append(f"by {author}")
    if a.site_name:
        bits.append(f"from {a.site_name}")
    if a.published:
        bits.append(f"published {_spoken_date(a.published)}")
    return (leading + ", ".join(bits)) if bits else ""


# ---------------------------------------------------------------- cleaning

DROP_WITH_CONTENT = {
    "script", "style", "noscript", "iframe", "svg", "video", "audio", "object", "embed",
    "canvas", "template", "button", "form", "input", "select", "textarea", "figure",
    "figcaption", "picture", "img", "source", "math",
}
VOID = {"br", "hr", "img", "source", "input", "meta", "link", "wbr", "col", "area", "base", "embed", "param", "track"}
KEEP = {
    "p", "div", "section", "article", "blockquote", "ul", "ol", "li", "a", "em", "strong", "b",
    "i", "u", "s", "sub", "sup", "small", "code", "pre", "br", "hr", "span", "q", "cite", "abbr",
    "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "mark",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
# The article title is an <h2> in the bundle, so the article's own headings sit below it.
HEADING_SHIFT = {"h1": "h3", "h2": "h3", "h3": "h4", "h4": "h5", "h5": "h6", "h6": "h6"}


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self._dropping = 0
        self._text_chars = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self._dropping += 1
            return
        if self._dropping or tag not in KEEP:
            return
        tag = HEADING_SHIFT.get(tag, tag)
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if re.match(r"^(https?:|mailto:)", href, re.I):
                self.out.append(f'<a href="{html.escape(href)}">')
            else:
                self.out.append("<a>")
            return
        self.out.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT or self._dropping or tag not in KEEP:
            return
        self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID and self._dropping:
                self._dropping -= 1
            return
        if self._dropping or tag not in KEEP or tag in VOID:
            return
        self.out.append(f"</{HEADING_SHIFT.get(tag, tag)}>")

    def handle_data(self, data):
        if self._dropping:
            return
        self._text_chars += len(data.strip())
        self.out.append(html.escape(data, quote=False))


@dataclass
class Cleaned:
    html: str
    text_chars: int


def clean_article_html(raw: Optional[str]) -> Cleaned:
    """Strip what reads badly aloud (images, captions, embeds) and demote headings."""
    if not raw or not raw.strip():
        return Cleaned("", 0)
    cleaner = _Cleaner()
    cleaner.feed(raw)
    cleaner.close()
    out = "".join(cleaner.out)
    out = _BLOCK.sub(_drop_boilerplate, out)
    out = re.sub(r"<(p|div|span|li|h[3-6])>\s*</\1>", "", out)  # empty blocks left by removals
    return Cleaned(out, cleaner._text_chars)


# Short standalone lines that are page furniture, not the article. Only whole
# short blocks are removed, so a sentence that merely mentions a newsletter stays.
_BLOCK = re.compile(r"<(p|li|h[3-6])>(.*?)</\1>", re.S)
_FURNITURE_START = re.compile(
    r"^(subscribe|sign up|image credit|image:|image courtesy|photo:|photo credit|photo illustration|"
    r"photograph by|photographs by|illustration by|credit:|read more|click here|advertisement|"
    r"listen to this|share this|follow us|related:|recommended:|copyright ©|©)", re.I)
_CALL_TO_ACTION = re.compile(
    r"\b(subscribe (to|here|now|today)|sign up (for|to|here)|join our|get our)\b", re.I)
# Promotional lines that give themselves away wherever they appear in a short block.
_PROMO = re.compile(
    r"sign up to receive|sign up for our|subscribe to our|support our journalism|"
    r"become a (paid )?(member|subscriber)", re.I)
_MAX_FURNITURE_CHARS = 300


def _drop_boilerplate(match: "re.Match") -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
    if not text or len(text) > _MAX_FURNITURE_CHARS:
        return match.group(0)
    lowered = text.lower()
    if _FURNITURE_START.match(text):
        return ""
    if "newsletter" in lowered and _CALL_TO_ACTION.search(text):
        return ""
    if _PROMO.search(text):
        return ""
    return match.group(0)


def looks_complete(article: Article, cleaned: Cleaned) -> bool:
    """False for paywall stubs: far less text than Readwise's own word count promised."""
    if cleaned.text_chars < 600:
        return False
    expected_chars = article.word_count * 4  # ~5 characters a word, less spaces
    return cleaned.text_chars >= 0.5 * expected_chars
