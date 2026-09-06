"""Studio adapter for the original Ghost Protocol browser collection path."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Callable

from ghost_protocol.content_filter import classify_noise_text
from ghost_protocol.scraper import CrawlerBlockedError, GalleryScraper


def run_legacy_collection_loop(coroutine):
    """Run Playwright collection in a subprocess-capable loop on Windows.

    Streamlit/Tornado selects ``WindowsSelectorEventLoopPolicy``.  That loop
    cannot create the Playwright driver subprocess and raises
    ``NotImplementedError`` before the collector can log a request.
    """
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def collect_legacy_board(
    *,
    gallery_id: str,
    gallery_type: str,
    pages: int,
    log: Callable[[str], None],
    scraper_factory=GalleryScraper,
) -> dict:
    """Run the original browser list/detail collector without its DB writers."""
    return run_legacy_collection_loop(
        _collect(
            gallery_id=gallery_id,
            gallery_type=gallery_type,
            pages=max(1, min(int(pages or 1), 3)),
            log=log,
            scraper_factory=scraper_factory,
        )
    )


async def _collect(*, gallery_id, gallery_type, pages, log, scraper_factory) -> dict:
    scraper = scraper_factory(headless=True)
    events: list[dict] = []
    raw_posts: list[dict] = []
    titles: list[str] = []
    comments: list[str] = []
    authors: list[str] = []
    reason = ''

    async def legacy_log(message: str) -> None:
        log(str(message))

    try:
        await scraper.start_browser()
        scraper.gallery_id = gallery_id
        scraper.gallery_type = gallery_type
        scraper._semaphore = asyncio.Semaphore(1)

        for page_no in range(1, pages + 1):
            log(f'목록 수집 중... ({page_no}/{pages} 페이지)')
            try:
                page_posts = await scraper.scrape_post_list(page_no, legacy_log)
            except CrawlerBlockedError as exc:
                reason = 'legacy_blocked'
                events.append({'kind': 'list', 'reason': reason, 'detail': type(exc).__name__})
                break
            except Exception as exc:
                reason = 'legacy_list_error'
                events.append({'kind': 'list', 'reason': reason, 'detail': type(exc).__name__})
                break
            for post in page_posts:
                post['page'] = page_no
                raw_posts.append(post)

        for index, post in enumerate(raw_posts[:6], start=1):
            try:
                result = await scraper._scrape_single_post(post, 0, legacy_log)
            except CrawlerBlockedError as exc:
                reason = 'legacy_blocked'
                events.append({'kind': 'detail', 'reason': reason, 'detail': type(exc).__name__})
                break
            except Exception as exc:
                reason = 'legacy_detail_error'
                events.append({'kind': 'detail', 'reason': reason, 'detail': type(exc).__name__})
                break
            if result is None:
                continue
            post.update(
                content=str(result.content or ''),
                comments=[str(item.get('content') or '') for item in result.comments],
                source_title=str(result.title or post.get('title') or ''),
            )
            log(f'원본 세트 [{index}/{min(6, len(raw_posts))}] #{post.get("post_id", "?")}')

        for post in raw_posts:
            title = str(post.get('title') or '').strip()
            if title and not classify_noise_text(title).is_noise:
                titles.append(title)
            author = str(post.get('author') or '').strip()
            if author:
                authors.append(author)
            for comment in post.get('comments') or []:
                text = str(comment or '').strip()
                if text and text not in comments and not classify_noise_text(text).is_noise:
                    comments.append(text[:80])
        if not reason and not titles:
            reason = 'legacy_empty_list'
    finally:
        await scraper.close()

    return {
        'titles': titles[:120],
        'comments': comments[:18],
        'authors': authors[:120],
        'gallery_id': gallery_id,
        'gallery_type': gallery_type,
        'collected_at': datetime.now().isoformat(),
        'raw_posts': raw_posts,
        'source_access': {
            'status': 'ok' if not reason else 'blocked',
            'reason': reason,
            'request_count': len(events),
            'request_budget': 0,
            'purpose': 'studio_legacy_read',
            'events': events,
        },
    }
