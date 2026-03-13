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
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO posts
           (post_id, gallery_id, title, content, author, author_type,
            ip_hash, views, recommends, created_at, style_tags,
            has_image, is_winner, image_url, is_ai)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (post_id, gallery_id, title, content, author, author_type,
         ip_hash, views, recommends, created_at, style_tags,
         int(has_image), int(is_winner), image_url, int(is_ai)),
    )
    conn.commit()
    conn.close()


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
