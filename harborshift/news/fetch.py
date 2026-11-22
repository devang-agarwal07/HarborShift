"""Fetch bounded RSS/Atom feeds on demand, with an in-memory advisory cache."""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
import re
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML

from harborshift.models import Port
from .extract import Candidate, extract_candidate


FEEDS = (
    ("UK Maritime and Coastguard Agency",
     "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=maritime-and-coastguard-agency"),
    ("NOAA National Hurricane Center · Atlantic",
     "https://www.nhc.noaa.gov/index-at.xml"),
)
MAX_BYTES = 1_000_000
CACHE_SECONDS = 600
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    published: str | None
    source: str
    candidate: Candidate


@dataclass(frozen=True)
class AdvisoryReport:
    articles: tuple[Article, ...]
    errors: tuple[str, ...]


def normalize_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
    except ValueError:
        return None
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), ""))


def timestamp(value: str) -> str | None:
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            return parse(value).isoformat()
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def parse_feed(data: bytes, source: str, ports: list[Port]) -> list[Article]:
    if len(data) > MAX_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsupported or oversized XML feed")
    root = XML.fromstring(data)
    if root.tag not in {"rss", f"{ATOM}feed"}:
        raise ValueError("Expected an RSS or Atom feed")
    articles = []
    for entry in (root.findall("channel/item") + root.findall(f"{ATOM}entry"))[:100]:
        rss = entry.tag == "item"
        prefix = "" if rss else ATOM
        title = (entry.findtext(prefix + "title") or "").strip()
        if rss:
            link = entry.findtext("link", "")
            summary = entry.findtext("description", "")
            published = entry.findtext("pubDate", "")
        else:
            link = next((item.get("href", "") for item in entry.findall(prefix + "link")
                         if item.get("rel", "alternate") == "alternate"), "")
            summary = entry.findtext(prefix + "summary", "")
            published = entry.findtext(prefix + "published", "") or entry.findtext(prefix + "updated", "")
        url = normalize_url(link)
        description = unescape(re.sub(r"<[^>]*>", " ", summary))
        candidate = extract_candidate(f"{title} {description}", ports)
        if title and url and candidate:
            articles.append(Article(title, url, timestamp(published), source, candidate))
    return articles


def fetch_feed(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "HarborShift/1.0 (public advisory reader)"})
    with urlopen(request, timeout=5) as response:
        return response.read(MAX_BYTES + 1)


def collect(ports: list[Port], feeds=FEEDS, fetch=fetch_feed) -> AdvisoryReport:
    articles = []
    urls, hashes, errors = set(), set(), []
    for source, url in feeds:
        try:
            items = parse_feed(fetch(url), source, ports)
        except (OSError, ValueError, XML.ParseError):
            errors.append(f"{source} feed unavailable.")
            continue
        for article in items:
            title = " ".join(article.title.casefold().split())
            digest = sha256(f"{title}|{article.published or ''}".encode()).hexdigest()
            if article.url not in urls and digest not in hashes:
                articles.append(article)
                urls.add(article.url)
                hashes.add(digest)
    return AdvisoryReport(tuple(articles), tuple(errors))


class AdvisoryCache:
    def __init__(self):
        self._lock = Lock()
        self._expires = 0.0
        self._report = AdvisoryReport((), ())

    def get(self, ports: list[Port]) -> AdvisoryReport:
        with self._lock:
            if monotonic() >= self._expires:
                self._report = collect(ports)
                self._expires = monotonic() + CACHE_SECONDS
            return self._report
