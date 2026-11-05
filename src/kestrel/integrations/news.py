"""Optional news headlines for the daily report. Context only, never a signal in v1.

To add another source: implement :class:`NewsSource` (one method) and register it in
:func:`build_news_source`. Under 50 lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from kestrel.config import NewsConfig, Secrets
from kestrel.logsetup import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Headline:
    """One headline."""

    title: str
    source: str
    url: str


class NewsSource(Protocol):
    """Fetch recent headlines for a query."""

    name: str

    def headlines(self, query: str, limit: int) -> list[Headline]:
        """Return up to ``limit`` headlines."""
        ...


class NewsApiSource:
    """newsapi.org ``/v2/everything`` (free developer tier, 100 requests/day)."""

    name = "newsapi"

    def __init__(self, api_key: str, *, http: httpx.Client | None = None) -> None:
        """Create a source; ``http`` can be injected for tests."""
        self._key = api_key
        self._http = http or httpx.Client(timeout=30)

    def headlines(self, query: str, limit: int) -> list[Headline]:
        """Fetch headlines; on any failure return an empty list with one warning."""
        try:
            r = self._http.get("https://newsapi.org/v2/everything", params={"q": query, "pageSize": limit, "sortBy": "publishedAt", "language": "en"}, headers={"X-Api-Key": self._key})
            r.raise_for_status()
            arts = r.json().get("articles", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("news_failed", error=str(exc))
            return []
        return [Headline(a.get("title", ""), (a.get("source") or {}).get("name", ""), a.get("url", "")) for a in arts[:limit]]


def build_news_source(cfg: NewsConfig, secrets: Secrets) -> NewsSource | None:
    """Return a source when enabled and keyed, else ``None``."""
    if not cfg.enabled or not secrets.has("kestrel_news_api_key") or secrets.kestrel_news_api_key is None:
        return None
    return NewsApiSource(secrets.kestrel_news_api_key.get_secret_value())
