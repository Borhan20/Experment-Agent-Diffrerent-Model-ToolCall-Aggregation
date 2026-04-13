"""Demo news tool handlers — mock articles, no external API required."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, List


_SOURCES = [
    "Reuters", "BBC News", "The Guardian", "AP News",
    "Bloomberg", "CNN", "Al Jazeera", "The Times",
]

_ARTICLE_TEMPLATES = [
    "{query}: Latest developments as experts weigh in",
    "Breaking: Major update in {query} situation",
    "{query} — what you need to know today",
    "Analysis: The future of {query} according to insiders",
    "World reacts to new findings on {query}",
]


def _query_hash(query: str) -> int:
    digest = hashlib.md5(query.lower().strip().encode()).hexdigest()
    return int(digest[:8], 16)


async def search_news(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Return mock news articles for a search query.

    Args:
        query: Search terms.
        max_results: Maximum number of articles (default 5).

    Returns:
        Dict with query and list of article dicts.
    """
    await asyncio.sleep(0.8)  # Simulate API latency

    h = _query_hash(query)
    articles: List[Dict[str, Any]] = []

    for i in range(max_results):
        idx_h = (h + i * 13) & 0xFFFFFFFF
        template = _ARTICLE_TEMPLATES[idx_h % len(_ARTICLE_TEMPLATES)]
        title = template.format(query=query.title())
        source = _SOURCES[idx_h % len(_SOURCES)]
        day = 1 + (idx_h % 28)
        articles.append({
            "title": title,
            "source": source,
            "published_at": f"2026-04-{day:02d}",
            "snippet": (
                f"In a significant development related to {query}, {source} reports that "
                f"new information has emerged that could change the current understanding. "
                f"Experts are divided on the implications."
            ),
            "url": f"https://example.com/news/{idx_h:08x}",
        })

    return {
        "query": query,
        "articles": articles,
    }


async def summarize_articles(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construct a bullet-point summary from a list of news articles.

    Args:
        articles: List of article dicts from search_news.

    Returns:
        Dict with summary string and article_count.
    """
    await asyncio.sleep(0.2)  # Simulate processing latency

    if not articles:
        return {"summary": "No articles found.", "article_count": 0}

    bullet_points: List[str] = []
    for article in articles:
        title = article.get("title", "Unknown")
        source = article.get("source", "Unknown source")
        date = article.get("published_at", "recent")
        bullet_points.append(f"• {title} ({source}, {date})")

    summary = "Key findings from recent news:\n" + "\n".join(bullet_points)
    return {
        "summary": summary,
        "article_count": len(articles),
    }
