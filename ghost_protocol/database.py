"""Ghost Protocol v1.0 - SQLite + Stream CSV + JSONL writer.

Data pipeline:
  Scraper ──┬──→ SQLite (insert + commit per row)
            ├──→ CSV    (writerow + flush per row)
            └──→ JSONL  (json.dumps + flush per row)  ← NEW in v1.0

All three outputs are crash-resilient via immediate flush.
"""

import csv
import json
import sqlite3
import os
from datetime import datetime
from typing import Optional, IO

from .config import (
    DB_PATH,
    DATA_DIR,
    STREAM_CSV_POSTS_HEADER,
    STREAM_CSV_COMMENTS_HEADER,
)


# ══════════════════════════════════════════════
# SQLite layer
# ══════════════════════════════════════════════

def get_connection() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            post_id     INTEGER NOT NULL,
            gallery_id  TEXT    NOT NULL,
            title       TEXT,
            content     TEXT,
            author      TEXT,
            author_type TEXT CHECK(author_type IN ('고정닉', '유동닉')),
            ip_hash     TEXT,
            views       INTEGER DEFAULT 0,
            recommends  INTEGER DEFAULT 0,
            created_at  TEXT,
            style_tags  TEXT DEFAULT '',
            has_image   INTEGER DEFAULT 0,
            is_winner   INTEGER DEFAULT 0,
            image_url   TEXT DEFAULT NULL,
            scraped_at  TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (post_id, gallery_id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            comment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id     INTEGER NOT NULL,
            gallery_id  TEXT    NOT NULL,
            author      TEXT,
            content     TEXT,
            is_reply    INTEGER DEFAULT 0,
            created_at  TEXT,
            scraped_at  TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (post_id, gallery_id) REFERENCES posts(post_id, gallery_id)
        );

        CREATE INDEX IF NOT EXISTS idx_posts_gallery ON posts(gallery_id);
        CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, gallery_id);

        CREATE TABLE IF NOT EXISTS ai_post_comments (
            comment_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id          TEXT    NOT NULL,
            gallery_id       TEXT    NOT NULL,
            author           TEXT    DEFAULT '',
            content          TEXT    NOT NULL,
            created_at       TEXT    DEFAULT '',
            scraped_at       TEXT    DEFAULT (datetime('now','localtime')),
            marker_feedback  INTEGER DEFAULT 0,
            feedback_reason  TEXT    DEFAULT '',
            UNIQUE(post_id, gallery_id, author, content, created_at)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_post_comments_gallery
            ON ai_post_comments(gallery_id, post_id);

        CREATE TABLE IF NOT EXISTS actor_briefings (
            gallery_id      TEXT PRIMARY KEY,
            briefing_json   TEXT NOT NULL,
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS actor_profiles (
            gallery_id       TEXT NOT NULL,
            actor_key        TEXT NOT NULL,
            display_label    TEXT DEFAULT '',
            identity_type    TEXT DEFAULT '',
            post_count       INTEGER DEFAULT 0,
            comment_count    INTEGER DEFAULT 0,
            total_count      INTEGER DEFAULT 0,
            resident_score   REAL DEFAULT 0,
            activity_score   REAL DEFAULT 0,
            top_terms_json   TEXT DEFAULT '[]',
            style_json       TEXT DEFAULT '{}',
            summary_json     TEXT DEFAULT '{}',
            updated_at       TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (gallery_id, actor_key)
        );

        CREATE TABLE IF NOT EXISTS actor_observations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            gallery_id    TEXT NOT NULL,
            actor_key     TEXT NOT NULL,
            kind          TEXT DEFAULT '',
            post_no       TEXT DEFAULT '',
            comment_id    TEXT DEFAULT '',
            title         TEXT DEFAULT '',
            excerpt       TEXT DEFAULT '',
            observed_at   TEXT DEFAULT '',
            scraped_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(gallery_id, actor_key, kind, post_no, comment_id, excerpt)
        );

        CREATE INDEX IF NOT EXISTS idx_actor_profiles_gallery
            ON actor_profiles(gallery_id, total_count DESC);
        CREATE INDEX IF NOT EXISTS idx_actor_observations_actor
            ON actor_observations(gallery_id, actor_key);
    """)

    # v1.0 migration: 신규 컬럼 추가 (기존 DB 호환)
    for col, typedef in [
        ("style_tags", "TEXT DEFAULT ''"),
        ("has_image", "INTEGER DEFAULT 0"),
        ("is_winner", "INTEGER DEFAULT 0"),
        ("image_url", "TEXT DEFAULT NULL"),
        ("is_ai", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"SELECT {col} FROM posts LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {typedef}")

    conn.commit()
    conn.close()


def truncate_posts() -> int:
    """게시글·댓글 테이블 전체 삭제 (Context Poisoning 방지용 DB 초기화).

    이전 테스트 사이클에서 스크래퍼가 읽어오는 찌꺼기 데이터를 완전히 제거한다.
    반환값: 삭제된 총 행 수 (posts + comments).
    """
    conn = get_connection()
    n_comments = conn.execute("DELETE FROM comments").rowcount
    n_posts    = conn.execute("DELETE FROM posts").rowcount
    conn.commit()
    conn.close()
    return n_posts + n_comments


def insert_post(
    post_id: int,
    gallery_id: str,
    title: str,
    content: str,
    author: str,
    author_type: str,
    ip_hash: Optional[str],
    views: int,
    recommends: int,
    created_at: str,
    style_tags: str = "",
    has_image: bool = False,
    is_winner: bool = False,
    image_url: Optional[str] = None,
    is_ai: bool = False,
) -> None:
    """게시글 1건 저장. 충돌 시 UPSERT — is_ai는 절대 1→0으로 퇴행하지 않음.

    스크래퍼가 is_ai=False로 덮어쓰더라도 poster가 mark_ai_post()로 먼저
    is_ai=1을 기록한 경우 MAX(posts.is_ai, excluded.is_ai)로 보존된다.
    """
    conn = get_connection()
    conn.execute(
        """INSERT INTO posts
               (post_id, gallery_id, title, content, author, author_type,
                ip_hash, views, recommends, created_at, style_tags,
                has_image, is_winner, image_url, is_ai)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(post_id, gallery_id) DO UPDATE SET
               title       = excluded.title,
               content     = excluded.content,
               author      = excluded.author,
               author_type = excluded.author_type,
               ip_hash     = excluded.ip_hash,
               views       = excluded.views,
               recommends  = excluded.recommends,
               created_at  = excluded.created_at,
               style_tags  = excluded.style_tags,
               has_image   = excluded.has_image,
               is_winner   = excluded.is_winner,
               image_url   = excluded.image_url,
               is_ai       = MAX(posts.is_ai, excluded.is_ai)""",
        (post_id, gallery_id, title, content, author, author_type,
         ip_hash, views, recommends, created_at, style_tags,
         int(has_image), int(is_winner), image_url, int(is_ai)),
    )
    conn.commit()
    conn.close()


def mark_ai_post(post_id: str, gallery_id: str, title: str = "", content: str = "") -> None:
    """Bot이 직접 게시한 글을 즉시 is_ai=1로 DB에 스탬프.

    - 신규 게시글: 최소 메타데이터(title, content)로 INSERT → is_ai=1
    - 이미 스크래핑된 게시글: is_ai=1로 UPDATE (퇴행 없음)
    - author_type=NULL → SQLite CHECK(NULL) 결과 NULL(≠FALSE) → 제약 통과
    - 이후 스크래퍼가 insert_post()를 호출해도 MAX(is_ai) 로직으로 is_ai=1 유지
    """
    conn = get_connection()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO posts
               (post_id, gallery_id, title, content, author, author_type,
                ip_hash, views, recommends, created_at, style_tags,
                has_image, is_winner, image_url, is_ai)
           VALUES (?, ?, ?, ?, '', NULL, NULL, 0, 0, ?, '', 0, 0, NULL, 1)
           ON CONFLICT(post_id, gallery_id) DO UPDATE SET is_ai = 1""",
        (str(post_id), gallery_id, title, content, now),
    )
    conn.commit()
    conn.close()


def get_ai_post_nos(gallery_id: str) -> set[str]:
    """is_ai=1인 게시글 번호(str) 집합 반환. Intel 패널 봇 컬럼 조회에 사용."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT post_id FROM posts WHERE gallery_id = ? AND is_ai = 1",
        (gallery_id,),
    ).fetchall()
    conn.close()
    return {str(r[0]) for r in rows}


def get_ai_posts(gallery_id: str, limit: int = 50) -> list[dict]:
    """Return recent AI-marked posts for comment monitoring."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT post_id, gallery_id, title, content, created_at, scraped_at
           FROM posts
           WHERE gallery_id = ? AND is_ai = 1
           ORDER BY CAST(post_id AS INTEGER) DESC
           LIMIT ?""",
        (gallery_id, max(1, int(limit or 50))),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_ai_post_comments(comments: list[dict]) -> int:
    """Persist comments attached to AI-marked posts.

    Returns the number of rows newly inserted. Repeated crawls are ignored by
    the UNIQUE constraint.
    """
    if not comments:
        return 0

    conn = get_connection()
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO ai_post_comments
           (post_id, gallery_id, author, content, created_at, marker_feedback, feedback_reason)
           VALUES (:post_id, :gallery_id, :author, :content, :created_at,
                   :marker_feedback, :feedback_reason)""",
        comments,
    )
    conn.commit()
    inserted = conn.total_changes - before
    conn.close()
    return int(inserted)


def get_ai_post_comments(gallery_id: str, limit: int = 120) -> list[dict]:
    """Return recently observed comments on AI-marked posts."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT post_id, gallery_id, author, content, created_at,
                  scraped_at, marker_feedback, feedback_reason
           FROM ai_post_comments
           WHERE gallery_id = ?
           ORDER BY comment_id DESC
           LIMIT ?""",
        (gallery_id, max(1, int(limit or 120))),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_actor_briefing(gallery_id: str, analysis: dict) -> None:
    """Persist the latest public-identity actor briefing for a gallery."""
    if not gallery_id or not isinstance(analysis, dict):
        return

    conn = get_connection()
    now = datetime.now().isoformat()
    payload = json.dumps(analysis, ensure_ascii=False)
    conn.execute(
        """INSERT INTO actor_briefings (gallery_id, briefing_json, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(gallery_id) DO UPDATE SET
               briefing_json = excluded.briefing_json,
               updated_at = excluded.updated_at""",
        (gallery_id, payload, now),
    )
    conn.execute("DELETE FROM actor_profiles WHERE gallery_id = ?", (gallery_id,))

    for actor in list(analysis.get("actors") or []):
        if not isinstance(actor, dict) or not actor.get("actor_key"):
            continue
        scores = dict(actor.get("scores") or {})
        summary = {
            "active_hours": actor.get("active_hours", []),
            "observed_total": actor.get("total_count", 0),
        }
        conn.execute(
            """INSERT INTO actor_profiles
               (gallery_id, actor_key, display_label, identity_type,
                post_count, comment_count, total_count, resident_score,
                activity_score, top_terms_json, style_json, summary_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(gallery_id, actor_key) DO UPDATE SET
                   display_label = excluded.display_label,
                   identity_type = excluded.identity_type,
                   post_count = excluded.post_count,
                   comment_count = excluded.comment_count,
                   total_count = excluded.total_count,
                   resident_score = excluded.resident_score,
                   activity_score = excluded.activity_score,
                   top_terms_json = excluded.top_terms_json,
                   style_json = excluded.style_json,
                   summary_json = excluded.summary_json,
                   updated_at = excluded.updated_at""",
            (
                gallery_id,
                actor.get("actor_key"),
                actor.get("display_label", ""),
                actor.get("identity_type", ""),
                int(actor.get("post_count") or 0),
                int(actor.get("comment_count") or 0),
                int(actor.get("total_count") or 0),
                float(scores.get("resident_score") or 0),
                float(scores.get("activity_score") or 0),
                json.dumps(actor.get("top_terms", []), ensure_ascii=False),
                json.dumps(actor.get("style", {}), ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                now,
            ),
        )
        for obs in list(actor.get("observations") or []):
            if not isinstance(obs, dict):
                continue
            conn.execute(
                """INSERT OR IGNORE INTO actor_observations
                   (gallery_id, actor_key, kind, post_no, comment_id,
                    title, excerpt, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    gallery_id,
                    actor.get("actor_key"),
                    obs.get("kind", ""),
                    str(obs.get("post_no") or ""),
                    str(obs.get("comment_id") or ""),
                    obs.get("title", ""),
                    obs.get("excerpt", ""),
                    obs.get("created_at", ""),
                ),
            )

    conn.commit()
    conn.close()


def get_actor_briefing(gallery_id: str) -> dict:
    """Return the latest actor briefing JSON for a gallery."""
    conn = get_connection()
    row = conn.execute(
        "SELECT briefing_json FROM actor_briefings WHERE gallery_id = ?",
        (gallery_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return json.loads(row["briefing_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def get_actor_profiles(gallery_id: str, limit: int = 12) -> list[dict]:
    """Return stored actor profile rows for a gallery."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM actor_profiles
           WHERE gallery_id = ?
           ORDER BY total_count DESC, resident_score DESC
           LIMIT ?""",
        (gallery_id, max(1, int(limit or 12))),
    ).fetchall()
    conn.close()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("top_terms_json", "style_json", "summary_json"):
            try:
                item[key[:-5]] = json.loads(item.get(key) or "[]")
            except json.JSONDecodeError:
                item[key[:-5]] = [] if key == "top_terms_json" else {}
        result.append(item)
    return result


def insert_comments(comments: list[dict]) -> None:
    if not comments:
        return
    conn = get_connection()
    conn.executemany(
        """INSERT INTO comments
           (post_id, gallery_id, author, content, is_reply, created_at)
           VALUES (:post_id, :gallery_id, :author, :content, :is_reply, :created_at)""",
        comments,
    )
    conn.commit()
    conn.close()


def get_all_posts(gallery_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM posts WHERE gallery_id = ? ORDER BY post_id DESC",
        (gallery_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_comments(gallery_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM comments WHERE gallery_id = ? ORDER BY comment_id DESC",
        (gallery_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_post_count(gallery_id: str) -> int:
    conn = get_connection()
    result = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE gallery_id = ?", (gallery_id,)
    ).fetchone()
    conn.close()
    return result[0]


def is_post_exists(post_id: int, gallery_id: str) -> bool:
    """특정 post_id가 DB에 이미 존재하는지 확인 (증분 수집용)."""
    conn = get_connection()
    result = conn.execute(
        "SELECT 1 FROM posts WHERE post_id = ? AND gallery_id = ? LIMIT 1",
        (post_id, gallery_id),
    ).fetchone()
    conn.close()
    return result is not None


def get_all_post_ids(gallery_id: str) -> set[int]:
    """해당 갤러리의 수집 완료된 모든 post_id를 Set으로 반환 (중복 방지용)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT post_id FROM posts WHERE gallery_id = ?", (gallery_id,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def get_comment_count(gallery_id: str) -> int:
    conn = get_connection()
    result = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE gallery_id = ?", (gallery_id,)
    ).fetchone()
    conn.close()
    return result[0]


def get_ai_post_count(gallery_id: str) -> int:
    """워터마크(is_ai=1)가 감지된 글 수를 반환."""
    conn = get_connection()
    result = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE gallery_id = ? AND is_ai = 1",
        (gallery_id,),
    ).fetchone()
    conn.close()
    return result[0]


def get_bot_titles(gallery_id: str, limit: int = 200) -> list[str]:
    """최근 봇 게시글 제목 리스트 반환 (스크래핑 데이터 오염 필터용).

    is_ai=1인 게시글의 제목을 최근 순으로 최대 limit개 반환.
    collect_trending()에서 ledger에 안 잡힌 봇 글을 유사도 비교로 추가 필터링할 때 사용.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT title FROM posts WHERE gallery_id = ? AND is_ai = 1 "
        "ORDER BY rowid DESC LIMIT ?",
        (gallery_id, limit),
    ).fetchall()
    conn.close()
    return [r["title"] for r in rows]


def get_winner_posts(gallery_id: str, limit: int = 3) -> list[dict]:
    """is_winner=True 게시글 중 랜덤 N개 반환 (Few-shot 프롬프트용).

    is_ai=1(봇 생성) 글은 의도적으로 제외한다.
    봇 글이 few-shot으로 재주입되면 극단적 패턴이 자기강화(파멸 루프)되므로
    사람이 쓴 실제 게시글만 스타일 레퍼런스로 허용한다.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM posts WHERE gallery_id = ? AND is_winner = 1 AND is_ai = 0 "
        "ORDER BY RANDOM() LIMIT ?",
        (gallery_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_posts(gallery_id: str, hours: int = 1) -> list[dict]:
    """최근 N시간 이내 수집된 게시글 반환 (갤러리 분위기 파악용)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM posts WHERE gallery_id = ? "
        "AND scraped_at >= datetime('now', 'localtime', ? || ' hours') "
        "ORDER BY post_id DESC",
        (gallery_id, f"-{hours}"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def export_posts_csv(gallery_id: str, filepath: str) -> int:
    posts = get_all_posts(gallery_id)
    if not posts:
        return 0
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=posts[0].keys())
        writer.writeheader()
        writer.writerows(posts)
    return len(posts)


def export_comments_csv(gallery_id: str, filepath: str) -> int:
    comments = get_all_comments(gallery_id)
    if not comments:
        return 0
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=comments[0].keys())
        writer.writeheader()
        writer.writerows(comments)
    return len(comments)


# ── 대용량 CSV 브라우저 다운로드용 빌더 ──────────────────────────────────────
_EXPORT_HARD_LIMIT = 50_000   # OOM 방어 상한선 (행)
_EXPORT_CHUNK_SIZE = 5_000    # SQLite cursor.fetchmany() 단위


def _build_csv_bytes_chunked(query: str, params: tuple) -> tuple[bytes, int]:
    """SQLite 커서를 _EXPORT_CHUNK_SIZE 단위로 순회하며 CSV bytes를 생성한다.

    전체를 한 번에 fetchall()하지 않으므로 수만 행 규모에서도 OOM이 발생하지 않는다.
    Returns:
        (csv_bytes, row_count) — csv_bytes는 UTF-8 BOM 포함 (Excel 한글 호환).
    """
    import io
    buf = io.StringIO()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)

    writer = None
    total = 0
    while True:
        rows = cur.fetchmany(_EXPORT_CHUNK_SIZE)
        if not rows:
            break
        if writer is None:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
        writer.writerows([dict(r) for r in rows])
        total += len(rows)

    conn.close()
    return buf.getvalue().encode("utf-8-sig"), total


def build_posts_csv_bytes(gallery_id: str, limit: int = _EXPORT_HARD_LIMIT) -> tuple[bytes, int]:
    """갤러리 게시글 전체를 CSV bytes로 반환. 최대 limit행 (기본 50,000)."""
    return _build_csv_bytes_chunked(
        "SELECT * FROM posts WHERE gallery_id = ? ORDER BY post_id DESC LIMIT ?",
        (gallery_id, limit),
    )


def build_comments_csv_bytes(gallery_id: str, limit: int = _EXPORT_HARD_LIMIT) -> tuple[bytes, int]:
    """갤러리 댓글 전체를 CSV bytes로 반환. 최대 limit행 (기본 50,000)."""
    return _build_csv_bytes_chunked(
        "SELECT * FROM comments WHERE gallery_id = ? ORDER BY comment_id DESC LIMIT ?",
        (gallery_id, limit),
    )


# ══════════════════════════════════════════════
# Stream Writer (CSV + JSONL)
# ══════════════════════════════════════════════

class StreamWriter:
    """실시간 CSV + JSONL 스트림 저장기 (v1.0).

    v0.3 대비 변경:
      - write_post()에 style_tags 파라미터 추가
      - JSONL 파일 출력 추가 (LLM 학습 데이터용)
      - write_jsonl() 메서드 신규
    """

    def __init__(self, gallery_id: str):
        self.gallery_id = gallery_id
        self._posts_file: Optional[IO] = None
        self._comments_file: Optional[IO] = None
        self._jsonl_file: Optional[IO] = None
        self._posts_writer: Optional[csv.writer] = None
        self._comments_writer: Optional[csv.writer] = None
        self.posts_path: str = ""
        self.comments_path: str = ""
        self.jsonl_path: str = ""
        self.rows_written: int = 0

    def open(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.posts_path = os.path.join(
            DATA_DIR, f"{self.gallery_id}_stream_posts_{ts}.csv"
        )
        self.comments_path = os.path.join(
            DATA_DIR, f"{self.gallery_id}_stream_comments_{ts}.csv"
        )
        self.jsonl_path = os.path.join(
            DATA_DIR, f"{self.gallery_id}_dataset_{ts}.jsonl"
        )

        # Posts CSV
        self._posts_file = open(
            self.posts_path, "w", newline="", encoding="utf-8-sig"
        )
        self._posts_writer = csv.writer(self._posts_file)
        self._posts_writer.writerow(STREAM_CSV_POSTS_HEADER)
        self._posts_file.flush()

        # Comments CSV
        self._comments_file = open(
            self.comments_path, "w", newline="", encoding="utf-8-sig"
        )
        self._comments_writer = csv.writer(self._comments_file)
        self._comments_writer.writerow(STREAM_CSV_COMMENTS_HEADER)
        self._comments_file.flush()

        # JSONL (LLM dataset)
        self._jsonl_file = open(
            self.jsonl_path, "w", encoding="utf-8"
        )

    def write_post(
        self,
        post_id: int,
        gallery_id: str,
        title: str,
        content: str,
        author: str,
        author_type: str,
        ip_hash: Optional[str],
        views: int,
        recommends: int,
        created_at: str,
        style_tags: str = "",
        has_image: bool = False,
        is_winner: bool = False,
        image_url: Optional[str] = None,
    ) -> None:
        if not self._posts_writer or not self._posts_file:
            return
        self._posts_writer.writerow([
            post_id, gallery_id, title, content, author,
            author_type, ip_hash or "", views, recommends, created_at,
            style_tags, int(has_image), int(is_winner), image_url or "",
        ])
        self._posts_file.flush()
        self.rows_written += 1

    def write_comments(self, comments: list[dict]) -> None:
        if not self._comments_writer or not self._comments_file:
            return
        for c in comments:
            self._comments_writer.writerow([
                c.get("post_id", ""),
                c.get("gallery_id", ""),
                c.get("author", ""),
                c.get("content", ""),
                c.get("is_reply", 0),
                c.get("created_at", ""),
            ])
        self._comments_file.flush()

    def write_jsonl(
        self,
        title: str,
        content: str,
        comments: list[dict],
        is_winner: bool = False,
        has_image: bool = False,
        style_tags: str = "",
        post_id: int = 0,
        gallery_id: str = "",
        image_url: Optional[str] = None,
    ) -> None:
        """Instruction Tuning 포맷 JSONL 저장.

        Output format:
          {
            "instruction": "제목\n본문",
            "output": "댓글1 | 댓글2 | 댓글3",
            "metadata": { "post_id", "is_winner", "has_image", "image_url", ... }
          }
        """
        if not self._jsonl_file:
            return

        # instruction = 제목 + 본문 결합
        instruction = f"{title}\n{content}".strip()

        # output = 상위 3개 댓글 (대댓글 제외, 빈 내용 제외)
        top_comments = [
            c["content"]
            for c in comments
            if c.get("content", "").strip() and not c.get("is_reply", 0)
        ][:3]
        output = " | ".join(top_comments) if top_comments else ""

        record = {
            "instruction": instruction,
            "output": output,
            "metadata": {
                "post_id": post_id,
                "gallery_id": gallery_id,
                "is_winner": is_winner,
                "has_image": has_image,
                "image_url": image_url,
                "style_tags": style_tags,
                "comment_count": len(comments),
            },
        }
        line = json.dumps(record, ensure_ascii=False)
        self._jsonl_file.write(line + "\n")
        self._jsonl_file.flush()

    def close(self) -> None:
        for f in (self._posts_file, self._comments_file, self._jsonl_file):
            if f:
                try:
                    f.close()
                except Exception:
                    pass
        self._posts_file = None
        self._posts_writer = None
        self._comments_file = None
        self._comments_writer = None
        self._jsonl_file = None
