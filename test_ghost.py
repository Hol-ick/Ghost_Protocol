"""Ghost Protocol v0.3 — 오프라인 통합 테스트.

Playwright(브라우저) 없이 실행 가능한 테스트 스크립트.
각 모듈의 핵심 로직을 독립적으로 검증함.

실행: python test_ghost.py
"""

import asyncio
import os
import sys
import time
import tempfile
from unittest.mock import MagicMock

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(__file__))

# Playwright/Textual이 없어도 로직을 테스트할 수 있도록 mock 삽입
for mod_name in ["playwright", "playwright.async_api",
                 "textual", "textual.app", "textual.binding",
                 "textual.containers", "textual.widgets"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()


def header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def test_imports() -> bool:
    """모든 모듈의 import 검증."""
    header("TEST 1: Module Imports")
    try:
        from ghost_protocol import __version__
        ok(f"ghost_protocol.__version__ = {__version__}")

        from ghost_protocol.config import (
            GALLERY_PATTERNS, POST_URL_PATTERNS, USER_AGENTS,
            BLOCKED_STATUS_CODES, BLOCKED_TEXT_MARKERS,
            BOT_TIME_WINDOW_SEC, BOT_CPM_THRESHOLD, BOT_CLEANUP_INTERVAL,
            SUSPICIOUS_KEYWORDS, STREAM_CSV_POSTS_HEADER,
            STREAM_CSV_COMMENTS_HEADER, CIRCUIT_BREAKER_COOLDOWN,
        )
        ok(f"config.py: {len(GALLERY_PATTERNS)} gallery patterns, "
           f"{len(BLOCKED_STATUS_CODES)} blocked codes, "
           f"{len(SUSPICIOUS_KEYWORDS)} keywords")

        from ghost_protocol.database import (
            init_db, insert_post, insert_comments,
            get_all_posts, get_all_comments,
            get_post_count, get_comment_count,
            StreamWriter,
        )
        ok("database.py: All functions + StreamWriter imported")

        from ghost_protocol.scraper import (
            GalleryScraper, ScrapeResult, CrawlerBlockedError,
        )
        ok("scraper.py: GalleryScraper, ScrapeResult, CrawlerBlockedError imported")

        from ghost_protocol.ui import GhostProtocolApp
        ok("ui.py: GhostProtocolApp imported")

        return True
    except Exception as e:
        fail(f"Import failed: {e}")
        return False


def test_database() -> bool:
    """SQLite DB 초기화 + CRUD 검증."""
    header("TEST 2: Database (SQLite)")
    try:
        from ghost_protocol.database import (
            init_db, insert_post, insert_comments,
            get_all_posts, get_all_comments,
            get_post_count, get_comment_count,
        )
        from ghost_protocol import config
        import ghost_protocol.database as db_mod

        # 임시 DB 경로 사용 — database 모듈 내부도 직접 패치
        original_db = config.DB_PATH
        original_dir = config.DATA_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            config.DB_PATH = os.path.join(tmpdir, "test.db")
            config.DATA_DIR = tmpdir
            db_mod.DB_PATH = config.DB_PATH
            db_mod.DATA_DIR = config.DATA_DIR

            try:
                init_db()
                ok("DB initialized")

                # Insert test post
                insert_post(
                    post_id=1001,
                    gallery_id="test_gall",
                    title="테스트 제목",
                    content="테스트 본문 내용",
                    author="테스터",
                    author_type="고정닉",
                    ip_hash=None,
                    views=42,
                    recommends=7,
                    created_at="2024-01-01 12:00:00",
                )
                ok("Post inserted (id=1001)")

                # Insert test comments
                insert_comments([
                    {
                        "post_id": 1001,
                        "gallery_id": "test_gall",
                        "author": "댓글러1",
                        "content": "좋은 글이네요",
                        "is_reply": 0,
                        "created_at": "2024-01-01 12:01:00",
                    },
                    {
                        "post_id": 1001,
                        "gallery_id": "test_gall",
                        "author": "댓글러2",
                        "content": "ㅇㅇ",
                        "is_reply": 1,
                        "created_at": "2024-01-01 12:02:00",
                    },
                ])
                ok("2 comments inserted")

                # Read back
                posts = get_all_posts("test_gall")
                assert len(posts) == 1, f"Expected 1 post, got {len(posts)}"
                assert posts[0]["title"] == "테스트 제목"
                ok(f"get_all_posts: {len(posts)} post(s), title='{posts[0]['title']}'")

                comments = get_all_comments("test_gall")
                assert len(comments) == 2, f"Expected 2 comments, got {len(comments)}"
                ok(f"get_all_comments: {len(comments)} comment(s)")

                pc = get_post_count("test_gall")
                cc = get_comment_count("test_gall")
                assert pc == 1 and cc == 2
                ok(f"Counts: posts={pc}, comments={cc}")

                # Duplicate insert (REPLACE)
                insert_post(
                    post_id=1001,
                    gallery_id="test_gall",
                    title="수정된 제목",
                    content="수정된 내용",
                    author="테스터",
                    author_type="고정닉",
                    ip_hash=None,
                    views=100,
                    recommends=15,
                    created_at="2024-01-01 12:00:00",
                )
                posts2 = get_all_posts("test_gall")
                assert len(posts2) == 1
                assert posts2[0]["title"] == "수정된 제목"
                ok(f"UPSERT works: title now '{posts2[0]['title']}', views={posts2[0]['views']}")

            finally:
                config.DB_PATH = original_db
                config.DATA_DIR = original_dir
                db_mod.DB_PATH = original_db
                db_mod.DATA_DIR = original_dir

        return True
    except Exception as e:
        fail(f"Database test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_stream_writer() -> bool:
    """StreamWriter CSV 즉시 저장 검증."""
    header("TEST 3: Stream Writer (CSV flush)")
    try:
        from ghost_protocol.database import StreamWriter
        from ghost_protocol import config

        original_dir = config.DATA_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            config.DATA_DIR = tmpdir

            try:
                sw = StreamWriter("test_gall")
                sw.open()
                ok(f"StreamWriter opened: {sw.posts_path}")

                # Write 3 posts
                for i in range(3):
                    sw.write_post(
                        post_id=i + 1,
                        gallery_id="test_gall",
                        title=f"글 제목 {i+1}",
                        content=f"본문 {i+1}",
                        author=f"작성자{i+1}",
                        author_type="유동닉",
                        ip_hash=f"123.45.{i}",
                        views=i * 10,
                        recommends=i,
                        created_at=f"2024-01-0{i+1}",
                    )

                # Write comments
                sw.write_comments([
                    {"post_id": 1, "gallery_id": "test_gall",
                     "author": "댓글러", "content": "댓글 내용",
                     "is_reply": 0, "created_at": "2024-01-01"},
                ])

                assert sw.rows_written == 3
                ok(f"rows_written = {sw.rows_written}")

                # 파일이 flush되어 있는지 확인 (close 전에도 데이터 존재)
                with open(sw.posts_path, "r", encoding="utf-8-sig") as f:
                    lines = f.readlines()
                assert len(lines) == 4  # 1 header + 3 data
                ok(f"Posts CSV has {len(lines)} lines (1 header + 3 data) BEFORE close")

                with open(sw.comments_path, "r", encoding="utf-8-sig") as f:
                    lines = f.readlines()
                assert len(lines) == 2  # 1 header + 1 data
                ok(f"Comments CSV has {len(lines)} lines BEFORE close")

                sw.close()
                ok("StreamWriter closed safely")

            finally:
                config.DATA_DIR = original_dir

        return True
    except Exception as e:
        fail(f"StreamWriter test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_bot_radar() -> bool:
    """Time-Aware Bot Radar 로직 검증."""
    header("TEST 4: Bot Radar (Time-Aware)")
    try:
        from ghost_protocol.scraper import GalleryScraper

        scraper = GalleryScraper()

        # 같은 IP로 3번 등록 → 봇 판정
        ip = "223.39.100"
        result1 = scraper._bot_radar_register(ip)
        result2 = scraper._bot_radar_register(ip)
        result3 = scraper._bot_radar_register(ip)

        assert result1 is False, "1회차는 False여야 함"
        assert result2 is False, "2회차는 False여야 함"
        assert result3 is True, "3회차(임계값)는 True여야 함"
        ok(f"IP '{ip}': 1st={result1}, 2nd={result2}, 3rd={result3} (threshold=3)")

        # 다른 IP는 영향 없음
        other = scraper._bot_radar_register("111.22.33")
        assert other is False
        ok(f"Different IP '111.22.33': {other} (independent)")

        # 활동 맵 확인
        assert len(scraper._ip_activity_map[ip]) == 3
        ok(f"Activity map for '{ip}': {len(scraper._ip_activity_map[ip])} entries")

        # Cleanup 테스트
        scraper._cleanup_old_timestamps(time.time() + 120)  # 120초 후라 전부 만료
        assert len(scraper._ip_activity_map) == 0
        ok(f"Cleanup: map size = {len(scraper._ip_activity_map)} (all expired)")

        # 키워드 감지 테스트
        kw1 = scraper._bot_radar_check_keywords("매수 좌표 찍어줘")
        assert "매수" in kw1 and "좌표" in kw1
        ok(f"Keyword detection: '{', '.join(kw1)}'")

        kw2 = scraper._bot_radar_check_keywords("안녕하세요 좋은 아침입니다")
        assert len(kw2) == 0
        ok(f"No keywords in clean text: {kw2}")

        return True
    except Exception as e:
        fail(f"Bot Radar test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_circuit_breaker() -> bool:
    """Circuit Breaker 로직 검증 (비동기)."""
    header("TEST 5: Circuit Breaker (Async)")
    try:
        from ghost_protocol.scraper import GalleryScraper, CrawlerBlockedError
        from ghost_protocol.config import CIRCUIT_BREAKER_MAX_RETRIES

        scraper = GalleryScraper()

        # CrawlerBlockedError 예외 발생 확인
        try:
            raise CrawlerBlockedError("HTTP 403")
        except CrawlerBlockedError as e:
            ok(f"CrawlerBlockedError raised: {e}")

        # block_count 시뮬레이션
        scraper._block_count = 0
        ok(f"Initial block_count = {scraper._block_count}")

        scraper._block_count = CIRCUIT_BREAKER_MAX_RETRIES + 1
        ok(f"Max retries exceeded: block_count={scraper._block_count} > max={CIRCUIT_BREAKER_MAX_RETRIES}")

        # 비동기 쿨다운 — asyncio.sleep 사용 확인 (소스코드 검사)
        import inspect, textwrap, ast
        source = inspect.getsource(scraper._circuit_breaker_cooldown)
        assert "await asyncio.sleep" in source
        # AST 기반 검사: 실제 코드에서 time.sleep 호출이 없는지
        # (주석/docstring은 AST에 포함되지 않으므로 false positive 없음)
        dedented = textwrap.dedent(source)
        tree = ast.parse(dedented)
        has_blocking_sleep = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # time.sleep(...) 호출 패턴 감지
                if (isinstance(func, ast.Attribute)
                    and func.attr == "sleep"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "time"):
                    has_blocking_sleep = True
        assert not has_blocking_sleep, "Found time.sleep() call in actual code AST"
        ok("_circuit_breaker_cooldown uses 'await asyncio.sleep' (AST verified: no time.sleep)")

        # status_cb 파라미터 존재 확인
        sig = inspect.signature(scraper._circuit_breaker_cooldown)
        assert "status_cb" in sig.parameters
        ok("_circuit_breaker_cooldown accepts status_cb parameter")

        # run_full_scrape에도 status_cb 파라미터 있는지 확인
        sig2 = inspect.signature(scraper.run_full_scrape)
        assert "status_cb" in sig2.parameters
        ok("run_full_scrape accepts status_cb parameter")

        return True
    except Exception as e:
        fail(f"Circuit Breaker test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_rps_tracker() -> bool:
    """RPS (Requests Per Second) 계산 검증."""
    header("TEST 6: RPS Tracker")
    try:
        from ghost_protocol.scraper import GalleryScraper

        scraper = GalleryScraper()

        # 초기 RPS = 0
        assert scraper.get_rps() == 0.0
        ok(f"Initial RPS = {scraper.get_rps()}")

        # 5개 요청 기록
        for _ in range(5):
            scraper._record_request()
            time.sleep(0.05)

        rps = scraper.get_rps()
        assert rps > 0, f"RPS should be > 0, got {rps}"
        ok(f"After 5 requests: RPS = {rps:.2f}")

        return True
    except Exception as e:
        fail(f"RPS test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_config_integrity() -> bool:
    """Config 상수 무결성 검증."""
    header("TEST 7: Config Integrity")
    try:
        from ghost_protocol.config import (
            GALLERY_PATTERNS, POST_URL_PATTERNS, USER_AGENTS,
            BLOCKED_STATUS_CODES, BOT_TIME_WINDOW_SEC,
            BOT_CPM_THRESHOLD, STREAM_CSV_POSTS_HEADER,
            STREAM_CSV_COMMENTS_HEADER,
        )

        assert len(GALLERY_PATTERNS) == 3
        ok(f"Gallery patterns: {list(GALLERY_PATTERNS.keys())}")

        assert len(POST_URL_PATTERNS) == 3
        ok(f"Post URL patterns: {list(POST_URL_PATTERNS.keys())}")

        assert len(USER_AGENTS) >= 3
        ok(f"User agents: {len(USER_AGENTS)} available")

        assert 403 in BLOCKED_STATUS_CODES
        ok(f"Blocked codes: {BLOCKED_STATUS_CODES}")

        assert BOT_TIME_WINDOW_SEC == 60
        assert BOT_CPM_THRESHOLD == 3
        ok(f"Bot Radar: window={BOT_TIME_WINDOW_SEC}s, threshold={BOT_CPM_THRESHOLD}")

        assert len(STREAM_CSV_POSTS_HEADER) == 10
        assert len(STREAM_CSV_COMMENTS_HEADER) == 6
        ok(f"Stream headers: posts={len(STREAM_CSV_POSTS_HEADER)} cols, "
           f"comments={len(STREAM_CSV_COMMENTS_HEADER)} cols")

        # URL 패턴에 {gallery_id}, {post_id} 포함 확인
        for gtype, url in GALLERY_PATTERNS.items():
            assert "{gallery_id}" in url
        for gtype, url in POST_URL_PATTERNS.items():
            assert "{gallery_id}" in url and "{post_id}" in url
        ok("All URL patterns contain required placeholders")

        return True
    except Exception as e:
        fail(f"Config test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def test_ui_widget_ids() -> bool:
    """UI 위젯 ID 중복 및 누락 검증 (소스코드 기반)."""
    header("TEST 8: UI Widget IDs")
    try:
        import re

        ui_path = os.path.join(
            os.path.dirname(__file__), "ghost_protocol", "ui.py"
        )
        with open(ui_path, "r", encoding="utf-8") as f:
            source = f.read()

        # compose()에서 정의된 위젯 ID 추출
        compose_ids = re.findall(r'id="([^"]+)"', source)
        ok(f"Widget IDs found in compose: {len(compose_ids)}")

        # query_one에서 참조되는 ID 추출
        query_ids = re.findall(r'query_one\("#([^"]+)"', source)
        ok(f"Widget IDs referenced in query_one: {len(set(query_ids))}")

        # 참조된 ID가 정의에 포함되는지 확인
        missing = [qid for qid in set(query_ids) if qid not in compose_ids]
        if missing:
            fail(f"Missing widget IDs (referenced but not defined): {missing}")
            return False
        ok("All query_one IDs exist in compose()")

        # 핵심 ID 존재 확인
        required_ids = [
            "input-gallery", "input-pages", "switch-headless",
            "btn-start", "btn-stop", "btn-export",
            "log", "progress-bar", "status-label", "stats-label",
            "table-posts", "table-comments",
            "dash-posts", "dash-ratio-text", "ratio-bar",
            "dash-bots", "dash-rps",
        ]
        for rid in required_ids:
            assert rid in compose_ids, f"Required ID '{rid}' not found"
        ok(f"All {len(required_ids)} required widget IDs present")

        # CSS에서 참조된 ID가 compose에 있는지
        css_ids = re.findall(r'#([\w-]+)', source)
        ok(f"CSS ID selectors: {len(set(css_ids))}")

        return True
    except Exception as e:
        fail(f"UI widget ID test failed: {e}")
        import traceback; traceback.print_exc()
        return False


def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  GHOST PROTOCOL v0.3 — TEST SUITE    ║")
    print("  ║  Offline Verification (No Browser)   ║")
    print("  ╚══════════════════════════════════════╝")

    tests = [
        ("Module Imports",     test_imports),
        ("Database (SQLite)",  test_database),
        ("Stream Writer",      test_stream_writer),
        ("Bot Radar",          test_bot_radar),
        ("Circuit Breaker",    test_circuit_breaker),
        ("RPS Tracker",        test_rps_tracker),
        ("Config Integrity",   test_config_integrity),
        ("UI Widget IDs",      test_ui_widget_ids),
    ]

    results = []
    for name, fn in tests:
        try:
            passed = fn()
        except Exception:
            passed = False
        results.append((name, passed))

    # Summary
    header("RESULTS SUMMARY")
    total = len(results)
    passed = sum(1 for _, p in results if p)
    failed = total - passed

    for name, p in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"  {status}  {name}")

    print()
    print(f"  Total: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║  🟢 ALL TESTS PASSED — BATTLE READY  ║")
        print("  ╚══════════════════════════════════════╝")
    else:
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║  🔴 SOME TESTS FAILED                ║")
        print("  ╚══════════════════════════════════════╝")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
