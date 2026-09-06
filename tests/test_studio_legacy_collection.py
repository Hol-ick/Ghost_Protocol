from ghost_protocol.scraper import ScrapeResult
import asyncio

from ghost_protocol.studio.legacy_collection import collect_legacy_board, run_legacy_collection_loop


def test_legacy_collection_uses_proactor_loop_on_windows(monkeypatch):
    calls = []

    class Loop:
        def run_until_complete(self, coroutine):
            calls.append('run')
            return asyncio.run(coroutine)

        def close(self):
            calls.append('close')

    monkeypatch.setattr(asyncio, 'ProactorEventLoop', lambda: Loop())

    async def value():
        return 'ok'

    assert run_legacy_collection_loop(value()) == 'ok'
    assert calls == ['run', 'close']


def test_studio_uses_original_list_and_detail_collector_without_db_writes():
    calls = []

    class LegacyFixture:
        def __init__(self, *, headless):
            assert headless is True
            self.gallery_id = None
            self.gallery_type = None
            self._semaphore = None

        async def start_browser(self):
            calls.append('start')

        async def close(self):
            calls.append('close')

        async def scrape_post_list(self, page_no, log):
            calls.append(('list', page_no, self.gallery_id, self.gallery_type))
            await log('legacy list complete')
            return [
                {'post_id': 1, 'title': '달 경계가 선명함', 'author': '관측자'},
                {'post_id': 2, 'title': '광고 쿠폰 판매', 'author': '제외'},
            ]

        async def _scrape_single_post(self, post, worker_id, log):
            calls.append(('detail', post['post_id'], worker_id))
            await log('legacy detail complete')
            return ScrapeResult(
                post_id=post['post_id'],
                title=post['title'],
                content='원래 수집기의 본문',
                comments=[{'content': '댓글 하나'}, {'content': '광고 쿠폰'}],
            )

    logs = []
    source = collect_legacy_board(
        gallery_id='universe',
        gallery_type='board',
        pages=1,
        log=logs.append,
        scraper_factory=LegacyFixture,
    )

    assert calls == [
        'start', ('list', 1, 'universe', 'board'), ('detail', 1, 0), ('detail', 2, 0), 'close'
    ]
    assert source['source_access']['status'] == 'ok'
    assert source['titles'] == ['달 경계가 선명함']
    assert source['comments'] == ['댓글 하나']
    assert source['raw_posts'][0]['content'] == '원래 수집기의 본문'
    assert logs == ['목록 수집 중... (1/1 페이지)', 'legacy list complete', 'legacy detail complete', '원본 세트 [1/2] #1', 'legacy detail complete', '원본 세트 [2/2] #2']
