from ghost_protocol.scraper import TrendScraper


class _FakeResponse:
    text = """
    <html>
      <body>
        <span class="title_subject">원본 제목</span>
        <span class="gall_date" title="2026-06-04 09:10:11">09:10</span>
        <input type="hidden" id="e_s_n_o" name="e_s_n_o" value="token-123">
        <div class="write_div">
          <script>ignored()</script>
          첫 줄<br>둘째 줄
        </div>
        <div class="cmt_info"><p class="usertxt">첫 댓글 ㅋㅋ</p></div>
        <div class="cmt_info"><p class="usertxt">둘째 댓글</p></div>
      </body>
    </html>
    """

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout):
        self.urls.append((url, timeout))
        return _FakeResponse()


def test_fetch_post_snapshot_extracts_title_body_and_url():
    scraper = TrendScraper.__new__(TrendScraper)
    scraper._session = _FakeSession()

    snapshot = scraper.fetch_post_snapshot("baseball_new13", "123", "board")

    assert snapshot["source_title"] == "원본 제목"
    assert "첫 줄" in snapshot["content"]
    assert "둘째 줄" in snapshot["content"]
    assert "ignored" not in snapshot["content"]
    assert snapshot["created_at"] == "2026-06-04 09:10:11"
    assert snapshot["comments"] == ["첫 댓글 ㅋㅋ", "둘째 댓글"]
    assert snapshot["e_s_n_o"] == "token-123"
    assert snapshot["snapshot_ok"]
    assert "id=baseball_new13" in snapshot["url"]
    assert "no=123" in snapshot["url"]


def test_collect_trending_attaches_comment_sets_for_source_posts():
    scraper = TrendScraper.__new__(TrendScraper)

    def fake_fetch_post_list(gallery_id, gallery_type, page):
        return [
            {"post_no": f"{page}1", "title": f"제목 {page}-1", "author": "ㅇㅇ", "recommends": 0, "is_bot": False},
            {"post_no": f"{page}2", "title": f"제목 {page}-2", "author": "ㅇㅇ", "recommends": 0, "is_bot": False},
        ]

    def fake_fetch_post_snapshot(gallery_id, post_no, gallery_type):
        return {
            "source_title": f"상세 {post_no}",
            "content": f"본문 {post_no}",
            "comments": [f"인라인 {post_no}"],
            "e_s_n_o": f"token {post_no}",
        }

    def fake_fetch_comments_ajax(gallery_id, post_no, gallery_type, e_s_n_o=""):
        assert e_s_n_o == f"token {post_no}"
        return [f"댓글 {post_no}-1", f"댓글 {post_no}-2"]

    scraper.fetch_post_list = fake_fetch_post_list
    scraper.fetch_post_snapshot = fake_fetch_post_snapshot
    scraper.fetch_comments_ajax = fake_fetch_comments_ajax
    scraper._clean = lambda value: str(value).strip()

    logs = []
    result = scraper.collect_trending(
        "baseball_new13",
        "board",
        pages=1,
        source_detail_limit=2,
        source_comments_per_post=3,
        progress_callback=logs.append,
    )

    assert len(result["raw_posts"]) == 2
    assert result["raw_posts"][0]["content"] == "본문 11"
    assert result["raw_posts"][0]["comments"] == ["인라인 11", "댓글 11-1", "댓글 11-2"]
    assert "인라인 11" in result["comments"]
    assert any("원본 세트 [1/2]" in line for line in logs)
    assert any("↳ 댓글 1" in line for line in logs)


def test_collect_trending_excludes_generated_posts_from_source_details():
    scraper = TrendScraper.__new__(TrendScraper)
    snapshots = []

    scraper.fetch_post_list = lambda gallery_id, gallery_type, page: [
        {
            "post_no": "100",
            "title": "생성 글",
            "author": "bot",
            "recommends": 0,
            "is_bot": True,
        },
        {
            "post_no": "101",
            "title": "사람 글",
            "author": "ㅇㅇ",
            "recommends": 0,
            "is_bot": False,
        },
    ]

    def fake_snapshot(gallery_id, post_no, gallery_type):
        snapshots.append(post_no)
        return {
            "source_title": f"상세 {post_no}",
            "content": f"본문 {post_no}",
            "comments": [f"댓글 {post_no}"],
            "snapshot_ok": True,
        }

    scraper.fetch_post_snapshot = fake_snapshot
    scraper.fetch_comments_ajax = lambda *args, **kwargs: []
    scraper._clean = lambda value: str(value).strip()

    result = scraper.collect_trending(
        "baseball_new13",
        "board",
        pages=1,
        source_detail_limit=2,
        source_comments_per_post=1,
    )

    assert snapshots == ["101"]
    assert result["titles"] == ["사람 글"]
    assert "댓글 100" not in result["comments"]
    assert "댓글 101" in result["comments"]
    assert result["ai_post_count"] == 1
