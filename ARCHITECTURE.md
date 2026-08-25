# Ghost Protocol v4.3 — Architecture Document

## Overview

Ghost Protocol은 DC Inside 갤러리의 여론 흐름을 분석하고, AI 기반 게시글을 자동 생성·등록하는 파이프라인 시스템이다.

**3-Step Pipeline**: `SCAN → GENERATE → POST`

| Step | Module | 역할 |
|------|--------|------|
| 1. Scan | `scraper.py` | DC Inside 갤러리 병렬 크롤링 + 데이터 수집 |
| 2. Generate | `brain.py` | 로컬 Ollama/Qwen 기반 게시글 생성 |
| 3. Post | `poster.py` | Playwright 기반 자동 로그인 + 글쓰기 |

**Dashboard**: Streamlit Warm Bento UI (`app.py`)

---

## Directory Structure

```
Echo Chamber/
├── app.py                      # Streamlit 대시보드 (메인 엔트리포인트)
├── accounts.json               # DC Inside 계정 목록 (gitignore 대상)
├── .env                        # OLLAMA_* / LLM_* (gitignore 대상)
├── ARCHITECTURE.md             # 이 문서
│
├── .streamlit/
│   └── config.toml             # Streamlit 네이티브 테마 (Warm Bento 강제)
│
├── ghost_protocol/             # 코어 패키지
│   ├── __init__.py             # __version__ = "4.3.0"
│   ├── config.py               # 상수, URL 패턴, 타이밍, 불용어
│   ├── scraper.py              # 병렬 비동기 크롤러 (Playwright)
│   ├── brain.py                # Ollama/Qwen AI 글 생성기
│   ├── poster.py               # 자동 포스터 (Playwright)
│   └── database.py             # SQLite + CSV/JSONL 스트림 저장
│
├── data/                       # 수집 데이터 (런타임 생성)
│   ├── ghost_protocol.db       # SQLite DB
│   ├── *_stream_posts_*.csv    # 실시간 CSV
│   ├── *_stream_comments_*.csv
│   ├── *_dataset_*.jsonl       # LLM 학습용 JSONL
│   └── debug/                  # HTML 스냅샷 (디버깅)
│
└── dist/                       # 배포용 사본
    └── ghost_protocol/         # 코어 패키지 미러
```

---

## Core Modules

### 1. `scraper.py` — Parallel Async Crawler (v1.7)

DC Inside 갤러리를 병렬 비동기로 크롤링하는 엔진.

**핵심 구조**:
- **Phase 0**: DB에서 기수집 `post_id` 로딩 (Memory Dedup)
- **Phase 1**: 글 목록 수집 (Sequential) — 시간 기반 cutoff + Sticky Post Immunity
- **Phase 2**: 글 상세 수집 (Parallel) — `asyncio.gather` + `Semaphore(15)`

**주요 기능**:
- 15 Workers 병렬 크롤링 (`PARALLEL_WORKERS`)
- 갤러리 타입 자동 감지 (Smart Redirect: board / mgallery / mini)
- Circuit Breaker (403/429/503 자동 쿨다운)
- Bot Radar (IP 빈도 + 키워드 탐지)
- Zero-Width Space 워터마크 탐지 (`\u200B` → `is_ai = True`)
- Resource Blocking (이미지/폰트/CSS 차단으로 속도 최적화)
- StreamWriter (CSV + JSONL 실시간 저장)

```
BrowserContext (1) ─── 15 Workers ─── asyncio.gather()
                                          ↓
                           DB + CSV + JSONL (thread-safe)
```

### 2. `brain.py` — Local Ollama/Qwen Post Generator

로컬 Ollama의 Qwen 모델을 이용한 DC 스타일 게시글 생성기.

**Model**: `OLLAMA_MODEL` (기본 `qwen2.5:3b`, 선택적 로컬 fallback `qwen2.5:7b`)
**Runtime**: `http://127.0.0.1:11434` loopback Ollama only
**Output**: Native JSON mode with schema validation

**프롬프트 구조**:
1. System Prompt (`SYSTEM_PROMPT_BASE`): 톤별 규칙, 제목 규칙, AI 냄새 제거, 비문 강제
2. Few-shot: DB에서 념글(`is_winner=True`) 예시 N개 (content ≤ 300자)
3. Context: 최근 N시간 글 제목 (갤러리 분위기)
4. User Prompt: 주제 + 톤 지시 + 길이 조건 + XML 출력 강제

**톤 시스템**:
| 톤 | 설명 |
|----|------|
| `neutral` | 감정 제거, 건조한 마침표 종결 |
| `cynical` | 냉소·비꼬기, 자조 섞인 한탄 |
| `analytical` | 차트·매크로 분석, 진지한 투자자 |
| `monologue` | 배설형 독백, 비문 강제, 허무·우울 |
| `aggressive` | 거친 디시 밈, 비속어 전개 |
| `aggro` | 어그로 극대화, 팩트 비틀기 |

**길이 시스템**:
- 아주 짧게 (1문장) / 짧게 (1~2문장) / 보통 (3~4문장)

**워터마크**: 생성된 본문 끝에 Zero-Width Space (`\u200B`) 자동 삽입

### 3. `poster.py` — Auto-Poster (v4.3)

Playwright 기반 DC Inside 자동 로그인 + 글쓰기 모듈.

**파이프라인**:
```
accounts.json → 랜덤 계정 선택
    → 브라우저 시작 (Anti-Detection)
    → DC 로그인 (visible selector + fill)
    → WAF 딜레이 (2~4초)
    → 글쓰기 페이지 이동
    → 제목 입력 (#subject)
    → 에디터 탐색 (iframe → contenteditable fallback)
    → 미끼 짤방 (1x1 PNG paste event)
    → 본문 타이핑
    → 등록 버튼 클릭
    → 결과 확인 (URL 변경 체크)
```

**Anti-Detection**:
- `navigator.webdriver` 숨기기
- 랜덤 User-Agent 로테이션
- `--disable-blink-features=AutomationControlled`

**에러 처리**: 모든 실패 지점에서 Death Cam 스크린샷 자동 저장

### 4. `database.py` — Data Layer (v1.0)

SQLite + CSV + JSONL 3중 저장 시스템.

**SQLite 스키마**:
- `posts`: post_id(PK), gallery_id(PK), title, content, author, author_type, views, recommends, is_winner, is_ai, ...
- `comments`: comment_id(PK), post_id(FK), gallery_id(FK), author, content, is_reply, ...

**StreamWriter**:
- 실시간 CSV (posts + comments)
- JSONL (Instruction Tuning 포맷: instruction=제목+본문, output=상위 댓글)
- 크래시 방지: 행 단위 `flush()`

### 5. `config.py` — Configuration Constants (v1.6)

| 카테고리 | 주요 상수 |
|----------|-----------|
| Parallel | `PARALLEL_WORKERS=15`, Jitter 0.1~0.3s |
| Timeout | `PAGE_TIMEOUT=10s`, `LIST_TIMEOUT=10s` |
| Circuit Breaker | `MAX_RETRIES=3`, `COOLDOWN=10s` |
| Bot Radar | `CPM_THRESHOLD=3`, `TIME_WINDOW=60s` |
| Resource Block | image, media, font, stylesheet |
| Keyword | `KEYWORD_STOPWORDS` (한글 불용어 + DC 관련) |

### 6. `app.py` — Streamlit Dashboard (v4.3)

Warm Bento UI 대시보드. `.streamlit/config.toml` + Nuclear CSS 이중 방어로 다크 모드 완전 차단.

**레이아웃**:
```
┌─────────────────────────────────────────┐
│  📝 AI Posts  │  💬 AI Comments  │  🤖 AI Share  │  ← Metric Cards
├──────────────────┬──────────────────────┤
│  STEP 1: Scan    │  STEP 3: Post        │
│  (Hot Keywords)  │  (Preview + Submit)  │
│──────────────────│──────────────────────│
│  STEP 2: Brain   │  📟 실시간 로그       │
│  (Generate)      │                      │
├──────────────────┴──────────────────────┤
│  📊 수집 데이터 상세 (Posts/Comments/Chart) │
└─────────────────────────────────────────┘
```

**사이드바**: Gallery ID, Tone, Length, Scan Range, Headless, API Key, Export CSV

---

## Data Pipeline Flow

```
[User: Dashboard]
       │
       ▼
   ┌───────────┐     ┌───────────┐     ┌───────────┐
   │  STEP 1   │     │  STEP 2   │     │  STEP 3   │
   │   SCAN    │────▶│  GENERATE │────▶│   POST    │
   │ scraper   │     │  brain    │     │  poster   │
   └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
         │                 │                 │
         ▼                 ▼                 ▼
   ┌───────────┐     ┌───────────┐     ┌───────────┐
   │  SQLite   │     │  Ollama  │     │ DC Inside │
   │  CSV/JSONL│     │ 2.5 Flash │     │  (Write)  │
   └───────────┘     └───────────┘     └───────────┘
```

1. **SCAN**: Playwright로 DC Inside 크롤링 → SQLite + CSV + JSONL 저장
2. **GENERATE**: 수집 데이터 기반 핫 키워드 추출 → Ollama/Qwen으로 게시글 생성 (JSON 파싱) → 워터마크 삽입
3. **POST**: 랜덤 계정 선택 → 자동 로그인 → WAF 우회 → 글 등록 → 결과 확인

---

## Theme System

**Warm Bento** 컬러 팔레트:

| 용도 | 색상 | Hex |
|------|------|-----|
| Primary (Gold) | 골드 액센트 | `#C8A97E` |
| Background | 크림 | `#FBF9F6` |
| Secondary BG | 화이트 | `#FFFFFF` |
| Text | 다크 차콜 | `#2C2C2C` |
| Olive (Step/Tags) | 올리브 | `#6B7A64` |
| Muted Text | 웜 그레이 | `#8C8478` |

**다크 모드 방어**: `.streamlit/config.toml` (프레임워크 레벨) + Nuclear CSS `:root, [data-theme="dark"]` 변수 재정의 + `color-scheme: light !important` (런타임 레벨)
