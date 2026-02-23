"""Ghost Protocol v1.6 "Context Awareness" - Configuration constants."""

import os

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "ghost_protocol.db")

# ──────────────────────────────────────────────
# DC Inside URL patterns
# ──────────────────────────────────────────────
GALLERY_PATTERNS = {
    "board": "https://gall.dcinside.com/board/lists/?id={gallery_id}",
    "mgallery": "https://gall.dcinside.com/mgallery/board/lists/?id={gallery_id}",
    "mini": "https://gall.dcinside.com/mini/board/lists/?id={gallery_id}",
}

POST_URL_PATTERNS = {
    "board": "https://gall.dcinside.com/board/view/?id={gallery_id}&no={post_id}",
    "mgallery": "https://gall.dcinside.com/mgallery/board/view/?id={gallery_id}&no={post_id}",
    "mini": "https://gall.dcinside.com/mini/board/view/?id={gallery_id}&no={post_id}",
}

# Redirect-based gallery detection: 메이저 갤러리 URL로 접속 후 리다이렉트 확인
GALLERY_DETECT_URL = "https://gall.dcinside.com/board/lists/?id={gallery_id}"
# DC Inside 메인 페이지 (갤러리 없으면 여기로 튕김)
DC_MAIN_URL = "https://gall.dcinside.com"

# ──────────────────────────────────────────────
# Anti-crawling & Stealth
# ──────────────────────────────────────────────
USER_AGENTS = [
    # 2025 최신 Windows Chrome (메인 — DC 접속 비율 최다)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    # 2025 Windows Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # 2025 Windows Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Mac Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Mac Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    # Linux Chrome
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# ──────────────────────────────────────────────
# Nitro Boost: Parallel Crawling (v1.5)
# ──────────────────────────────────────────────
PARALLEL_WORKERS = 15               # 동시 탭 수 (Semaphore) — v1.0: 5 → v1.5: 15
PARALLEL_DELAY_MIN = 0.1            # Smart Jitter: 최소 (초)
PARALLEL_DELAY_MAX = 0.3            # Smart Jitter: 최대 (초) — 기계적 패턴 분산
BATCH_COOLDOWN_MIN = 0.5            # 배치 간 쿨다운 (초) — v1.0: 1.0 → 0.5
BATCH_COOLDOWN_MAX = 1.0            # v1.0: 2.0 → 1.0

# Fail-Fast: 타임아웃 (ms)
PAGE_TIMEOUT = 10000                # 10초 — v1.0: 15s → v1.5: 10s
LIST_TIMEOUT = 10000                # 리스트 페이지도 10초
DETECT_TIMEOUT = 8000               # 갤러리 탐지는 8초

# Resource blocking: 차단할 리소스 타입
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}

# 기존 Sequential 모드용 (리스트 수집 등)
MIN_DELAY = 0.5                     # v1.0: 0.8 → 0.5
MAX_DELAY = 1.0                     # v1.0: 1.5 → 1.0
PAGE_DELAY_MIN = 0.5                # v1.0: 1.0 → 0.5
PAGE_DELAY_MAX = 1.0                # v1.0: 2.0 → 1.0

# ──────────────────────────────────────────────
# Circuit Breaker
# ──────────────────────────────────────────────
CIRCUIT_BREAKER_COOLDOWN = 10
CIRCUIT_BREAKER_MAX_RETRIES = 3
BLOCKED_STATUS_CODES = {403, 429, 503}
BLOCKED_TEXT_MARKERS = [
    "captcha",
    "보안 문자",
    "접근이 차단",
    "비정상적인 접근",
    "잠시 후 다시",
]

# ──────────────────────────────────────────────
# Bot Radar (v2: Time-Aware)
# ──────────────────────────────────────────────
BOT_TIME_WINDOW_SEC = 60
BOT_CPM_THRESHOLD = 3
BOT_CLEANUP_INTERVAL = 30
SUSPICIOUS_KEYWORDS = [
    "매수", "좌표", "풀매수", "올인", "존버",
    "떡상", "급등", "단타", "물타기", "손절",
]

# ──────────────────────────────────────────────
# Stream Save & Data Prep
# ──────────────────────────────────────────────
STREAM_CSV_POSTS_HEADER = [
    "post_id", "gallery_id", "title", "content", "author",
    "author_type", "ip_hash", "views", "recommends", "created_at",
    "style_tags", "has_image", "is_winner", "image_url",
]
STREAM_CSV_COMMENTS_HEADER = [
    "post_id", "gallery_id", "author", "content", "is_reply", "created_at",
]

# Clean Text: 제거할 패턴
CLEAN_TEXT_PATTERNS = [
    r"- dc official App",
    r"- dc App",
    r"ㅇㅇ \(\d{1,3}\.\d{1,3}\)",           # IP 유동닉 패턴
    r"https?://\S+",                          # URL 제거
    r"<[^>]+>",                               # HTML 태그 제거
    r"\[.*?\]",                               # 대괄호 태그 [이미지], [동영상] 등
]

# ──────────────────────────────────────────────
# Keyword Radar: 불용어 (Hot Keywords 추출 시 제외)
# ──────────────────────────────────────────────
KEYWORD_STOPWORDS = {
    # 한글 불용어
    "이", "그", "저", "것", "수", "등", "및", "더", "좀", "안",
    "잘", "못", "왜", "뭐", "걍", "진짜", "ㅋㅋ", "ㅎㅎ", "ㄷㄷ",
    "ㅠㅠ", "ㅜㅜ", "ㅇㅇ", "ㄴㄴ", "ㅈㄱ", "ㅂㅂ", "ㄱㄱ",
    "는", "은", "를", "을", "에", "의", "로", "가", "도", "로",
    "에서", "으로", "하고", "이다", "있다", "없다", "하다", "되다",
    "거", "때", "나", "내", "너", "니", "다", "들", "만", "분",
    "씨", "아", "어", "에", "예", "오", "자", "중", "한", "함",
    # dc 관련
    "갤러리", "게시글", "댓글", "ㅇㅂ", "글", "놈", "년",
    "dc", "app", "official",
}
