# Ghost Protocol v5.0 — Project Report

> **작성일**: 2026-02-23
> **버전**: v5.0.0 "Swarm Mode"
> **상태**: 핵심 기능 완성, Roadmap 진행 중

---

## 1. 프로젝트 개요 (Overview)

Ghost Protocol은 **DC Inside 커뮤니티의 여론을 분석하고, AI를 이용해 사람과 구별하기 어려운 게시글을 자동 생성·게시하는 자동화 봇 파이프라인**이다.

### 핵심 목표

- 특정 갤러리의 실시간 트렌드와 분위기를 파악하여, 해당 커뮤니티 고유의 문체·은어·감성을 완벽히 모방한 게시글을 생성한다.
- 생성된 게시글을 Playwright 기반의 스텔스 브라우저를 통해 자동으로 게시하며, 연속 반복(Swarm Mode)을 통해 갤러리 여론 형성에 개입한다.
- 운영자가 직접 브라우저를 다루지 않아도, **Scan → Generate → Post**의 3단계 파이프라인을 하나의 웹 대시보드에서 완결할 수 있도록 한다.

### 타겟 플랫폼

| 구분 | 내용 |
|------|------|
| 주요 대상 | DC Inside — 마이너 갤러리 (mgallery), 미니 갤러리 (mini), 메이저 갤러리 (board) |
| 기본 테스트 갤러리 | `stockus` (미국 주식 갤러리) |
| 계정 관리 | `accounts.json` (다중 계정 지원, 랜덤 선택) |

---

## 2. 핵심 아키텍처 및 기술 스택

### 전체 파이프라인

```
[DC Inside 갤러리]
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 1 · Smart Radar (scraper.py)                      │
│  Playwright (15 Workers) → posts + comments → SQLite    │
│  Zero-Width Watermark 탐지 → is_ai 플래그               │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 2 · Deep Humanizer (brain.py)                     │
│  DB(winner posts) → Few-shot Examples                   │
│  DB(recent posts) → Gallery Mood Context                │
│  Gemini 2.5 Flash → XML Tag Output → {title, content}  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 3 · Stealth Poster (poster.py)                    │
│  accounts.json → random pick                            │
│  Playwright Stealth → Login → WAF Delay                 │
│  1px Bait Image Paste → Type Content → Submit           │
└─────────────────────────────────────────────────────────┘
```

### 기술 스택

| 레이어 | 기술 | 역할 |
|--------|------|------|
| **UI** | Streamlit | 원페이지 웹 대시보드 |
| **스크래핑 / 포스팅** | Playwright (async) | 헤드리스 브라우저 자동화 |
| **AI 생성** | Google Gemini 2.5 Flash | LLM 텍스트 생성 |
| **데이터** | SQLite 3 (WAL 모드) | 게시글·댓글 영구 저장 |
| **스트리밍 출력** | CSV + JSONL | 실시간 학습 데이터 축적 |
| **비동기 처리** | asyncio + threading | 스크래퍼 백그라운드 실행 |
| **환경 관리** | python-dotenv | API Key 관리 |

### 모듈 구성

```
Echo Chamber/
├── app.py                    # Streamlit 대시보드 (메인 진입점)
├── accounts.json             # 계정 목록 (id/pw 리스트)
├── ghost_protocol/
│   ├── __init__.py           # 버전 정보 (v5.0.0)
│   ├── config.py             # 전역 상수 (URL, UA, 딜레이, 서킷브레이커)
│   ├── database.py           # SQLite + StreamWriter
│   ├── scraper.py            # 병렬 비동기 스크래퍼 (v1.7)
│   ├── brain.py              # Gemini LLM 생성기 (v5.0)
│   └── poster.py             # Playwright 자동 포스터 (v5.0)
└── .streamlit/
    └── config.toml           # Warm Bento 테마 강제
```

---

## 3. 주요 기능 명세 (Key Features)

### 3.1 Smart Radar — 증분 수집 엔진 (`scraper.py`)

**목적**: 갤러리 글 목록 + 상세(본문·댓글)를 수집하여 DB에 저장한다.

#### 수집 모드

| 모드 | 설명 |
|------|------|
| **Time-based** | 최근 N시간 범위 기준으로 시간 초과 시 중단. Sticky Post Immunity (상위 10행 공지 면역) 적용 |
| **Incremental (증분)** | 기수집 `post_id`를 발견하는 순간 목록 수집 중단 → 신규 글만 추적 |

#### 병렬 처리 아키텍처

- **15개 동시 워커** (`asyncio.gather` + `Semaphore`): 배치 단위로 상세 페이지 병렬 수집
- 각 워커는 독립적인 Playwright 탭(Page)과 랜덤 User-Agent를 사용
- `threading.Lock`으로 DB/CSV 동시 쓰기 충돌 방지

#### 스텔스 탐지 우회

- `navigator.webdriver` 속성 숨김 (`add_init_script`)
- 12종 User-Agent 풀 (Windows Chrome/Edge/Firefox, Mac Chrome/Safari, Linux Chrome)
- 이미지·폰트·CSS·미디어 리소스 차단으로 요청 속도 향상

#### 서킷 브레이커

- HTTP 403/429/503, CAPTCHA 텍스트 감지 시 자동 Cooldown (10초, 최대 3회 재시도)
- 재시도 초과 시 완전 중단

#### 봇 레이더 (Bot Radar)

- 동일 IP가 60초 내 3회 이상 등장 시 봇 의심 플래그
- 주식 조작 의심 키워드(`매수`, `좌표`, `풀매수` 등) 탐지 및 로그 기록

#### AI 워터마크 탐지

- Ghost Protocol이 생성한 글에 삽입된 Zero-Width Space(`\u200B`)를 탐지하여 `is_ai = 1`로 DB에 기록
- 대시보드 메트릭 카드의 **AI Share** 수치를 통해 갤러리 내 AI 글 침투율 실시간 표시

#### 데이터 출력 (3중 저장)

| 출력 | 경로 | 내용 |
|------|------|------|
| SQLite | `data/ghost_protocol.db` | 모든 게시글·댓글 영구 저장, 중복 방지 |
| CSV (Stream) | `data/{갤러리}_stream_posts_{ts}.csv` | 실시간 스트리밍 저장 (크래시 복원력) |
| JSONL (Dataset) | `data/{갤러리}_dataset_{ts}.jsonl` | LLM Instruction Tuning 포맷 |

---

### 3.2 Deep Humanizer — AI 게시글 생성 (`brain.py`)

**목적**: 실제 DC Inside 고인물이 쓴 것과 구별하기 어려운 게시글을 Gemini API로 생성한다.

#### 생성 파이프라인

```
DB(winner posts, n=3)   → Few-shot Examples
DB(recent posts, n=10)  → Gallery Mood Context
Hot Keywords (Counter)  → 키워드 인젝션
                              ↓
          Gemini 2.5 Flash (BLOCK_NONE)
                              ↓
        XML Tag Output <TITLE>...</TITLE><CONTENT>...</CONTENT>
                              ↓
            Zero-Width Space Watermark 삽입
```

#### SYSTEM_PROMPT_BASE 핵심 규칙

| 규칙 카테고리 | 내용 |
|-------------|------|
| **기본 페르소나** | 30대 남성, 미주갤 상주 고인물, 스마트폰으로 대충 작성하는 느낌 |
| **주식 은어** | 떡락, 돔황차, 설거지, 존버, 물타기, 풀매수, 곱버스 등 |
| **체언 종결** | `~했다` 대신 `~함`, `~임` |
| **제목 규칙** | 5~15자, 극단적으로 짧고 함축적, 호기심 유발 |
| **본문-제목 분리** | 제목 단어를 본문에 그대로 반복 금지 |
| **AI 냄새 제거** | `결론적으로`, `요약하자면` 등 작위적 표현 절대 금지 |

#### Deep Humanizer (초정밀 인간화 5규칙)

1. **완벽한 자아 빙의**: 불 꺼진 방 침대에 누워 주식 계좌 보며 글 쓰는 유저로 완전 빙의
2. **인간의 결함 모방**: 띄어쓰기 생략, 줄임말(`어카냐`, `진짜 어이없음`) 자연스럽게 혼용
3. **기계적 접속사 멸종**: `하지만`, `그러니까`, `결론적으로` 등 문서 작성용 접속사 완전 배제
4. **불규칙한 호흡**: 문장 길이를 들쭉날쭉하게, 서론-본론 구조 파괴
5. **집단적 독백**: 타인을 향한 공격·훈계 대신, 모니터 보며 혼잣말 던지는 탄식체

#### 톤(Tone) 시스템

| Tone | 설명 |
|------|------|
| `neutral` | 감정 없는 건조한 서술. 추임새·욕설 일절 금지 |
| `cynical` | 냉소적 비꼬기. `ㅋㅋ` 허용, 직접 욕설 자제 |
| `analytical` | 차트·매크로 분석. 논리적이되 반말 유지, 추임새 금지 |
| `monologue` | 배설형 독백. 비문(非文) 강제, 조사 생략, 허무하게 끊기 |
| `aggressive` | DC 특유 밈과 어그로 100% 활용, 비속어 전부 허용 |
| `aggro` | 팩트 비틀기, 극단적 단어(`능지 박살`, `흑우`, `한강`)로 분노 자극 |

#### 주제 추천 (`suggest_topic`)

- 최근 1시간 게시글 제목(최대 20개) + 실시간 핫 키워드를 조합
- **JSON 강제 출력**: `{"topic": "15자 이내"}` 형식으로 AI에게 응답 강제
- 마크다운 코드블록 제거 → `json.loads()` 파싱 → fallback(첫 줄 추출) 구조로 안정성 확보

#### 출력 파싱 (generate_post)

- XML 태그 정규식 파싱: 닫는 태그 생략, 앞뒤 공백, 대소문자 무관하게 추출
- 생성 실패 원인 디버깅: `finish_reason` (STOP / MAX_TOKENS / SAFETY) 로그 출력
- 429 Rate Limit 에러를 안전하게 catch하여 UI에 친화적 메시지 반환

---

### 3.3 Stealth Poster — 자동 포스팅 (`poster.py`)

**목적**: 생성된 게시글을 DC Inside에 실제로 게시한다.

#### 안티봇 우회 전략

| 기법 | 구현 내용 |
|------|----------|
| **WAF 딜레이** | 로그인 성공 후 글쓰기 전 2~4초 랜덤 대기 (Cloudflare 세션 안정화) |
| **타이핑 시뮬레이션** | `page.keyboard.type(content, delay=80~100ms)` — 인간 타이핑 속도 모방 |
| **1px 미끼 짤방 Paste** | 1×1 투명 PNG를 Base64로 인코딩 후 `ClipboardEvent('paste')` 디스패치 → 이미지 업로드 동작 트리거 |
| **navigator.webdriver 숨김** | `Object.defineProperty` via `add_init_script` |
| **Death Cam** | 오류 발생 직전 스크린샷 자동 저장 (`error_screenshot_{ts}.png`) |

#### 에디터 범용 감지

1. **시도 1**: `iframe` 내부 `body` (일반 웹 에디터)
2. **시도 2**: `[contenteditable='true']` (최신형 에디터)

#### 계정 관리

- `accounts.json`에서 랜덤 계정 선택 (`pick_random_account`)
- ID는 항상 마스킹하여 로그 출력 (`****ef123` 형식)
- 로그인 성공 여부: 로그인 후 URL에 `login` 문자열 포함 여부로 판별
- 포스팅 성공 여부: 등록 버튼 클릭 후 URL이 `write`에서 벗어났는지로 판별

---

### 3.4 Swarm Mode — 연속 폭격 자동화 (`app.py`)

**목적**: 사람 개입 없이 스캔 → 생성 → 게시 사이클을 N회 반복한다.

#### 루프 구조

```
for wave in 1..N:
  1. 증분 스캔    (최근 10분, GalleryScraper)
  2. 핫 키워드 추출 (Counter 기반)
  3. 주제 자동 추천 (brain.suggest_topic)
  4. 글 생성       (brain.generate_post, 현재 Tone/Length 설정 적용)
  5. 자동 포스팅   (GhostPoster.auto_post)
  6. 랜덤 대기     (60~180초, 마지막 wave 제외)
```

- 각 Wave 결과는 Swarm Log 창에 실시간 출력
- 최대 5회 반복, 슬라이더로 조정 가능
- API Key 없을 경우 Swarm Mode 비활성화

---

### 3.5 데이터베이스 스키마 (`database.py`)

#### `posts` 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `post_id` | INTEGER | DC Inside 글 번호 (PK) |
| `gallery_id` | TEXT | 갤러리 ID (PK 복합) |
| `title` | TEXT | 제목 |
| `content` | TEXT | 본문 (clean_text 정제 후) |
| `author` | TEXT | 작성자 닉네임 |
| `author_type` | TEXT | `고정닉` / `유동닉` |
| `ip_hash` | TEXT | 유동닉 IP 앞자리 |
| `views` | INTEGER | 조회수 |
| `recommends` | INTEGER | 추천수 |
| `is_winner` | INTEGER | 추천수 ≥ 10 (념글 여부) |
| `is_ai` | INTEGER | Zero-Width Watermark 탐지 여부 |
| `style_tags` | TEXT | 스타일 태그 (short_text, has_question 등) |
| `image_url` | TEXT | 첫 번째 이미지 URL |
| `scraped_at` | TEXT | 수집 시각 (localtime) |

#### 주요 쿼리 함수

| 함수 | 용도 |
|------|------|
| `get_winner_posts(gallery_id, n)` | Few-shot 님글 N개 랜덤 추출 |
| `get_recent_posts(gallery_id, hours)` | 갤러리 분위기 파악용 최근 N시간 글 |
| `get_all_post_ids(gallery_id)` | 증분 수집용 기수집 ID Set 로딩 |
| `is_post_exists(post_id, gallery_id)` | 단건 중복 확인 |
| `get_ai_post_count(gallery_id)` | AI 침투율 계산용 |

---

## 4. UI/UX 디자인 — Warm Bento Dashboard

### 다크모드 강제 차단 전략 (Nuclear CSS)

Streamlit은 사용자 OS의 다크모드 설정을 자동 반영하는데, 이 프로젝트는 **라이트 전용 Warm Bento 테마**를 운용하므로 이중 방어 체계를 구축했다.

| 방어 레이어 | 방법 |
|------------|------|
| **1차: 프레임워크** | `.streamlit/config.toml`의 `base = "light"`, `primaryColor`, `backgroundColor` 강제 지정 |
| **2차: Runtime CSS** | `:root, [data-theme="dark"]`의 CSS 변수를 라이트 값으로 덮어쓰기 + `color-scheme: light !important` |

#### Nuclear CSS 18개 섹션 구성

| 섹션 | 대상 |
|------|------|
| 1 | 다크모드 CSS 변수 무력화 |
| 2 | `.stApp`, `.stSidebar` 배경색 강제 |
| 3 | 사이드바 배경 + 텍스트 |
| 4 | 헤더·단락·리스트 텍스트 |
| 5 | Bento Box 카드 스타일 |
| 6 | Metric Card (3분할 수치 표시) |
| 7 | Step Header 배지 (스캔/브레인/포스트/로그) |
| 8 | 키워드 태그 (일반 / 핫 키워드) |
| 9 | 실시간 로그 박스 (모노스페이스, 레벨별 색상) |
| 10 | 버튼 (골드 테마, hover glow) |
| 11 | 입력 필드, 셀렉트 박스 |
| 12 | Preview Card (제목/본문 미리보기) |
| 13 | 사이드바 타이틀 |
| 14 | 진행바 (골드 그라데이션) |
| 15 | Expander 컴포넌트 |
| 16 | 입력창·드롭다운·리스트박스 다크모드 잔재 제거 |
| 17 | Expander 내부 버튼 텍스트 강제 라이트화 |
| 18 | **BaseWeb Popover 강제 라이트화** (Selectbox 드롭다운 외부 DOM 렌더링 대응) |

### 색상 팔레트

| 토큰 | 색상코드 | 용도 |
|------|---------|------|
| 배경 | `#FBF9F6` | 전체 앱 베이지 배경 |
| 카드 | `#FFFFFF` | Bento 카드 흰색 |
| 주 색상 | `#C8A97E` | 골드·액센트·버튼 |
| 서브 | `#6B7A64` | 올리브 (키워드 태그, 스텝 배지) |
| 텍스트 | `#2C2C2C` | 주요 텍스트 |
| 서브텍스트 | `#8C8478` | 라벨, 캡션 |
| 호버 | `#F2EFE9` | 드롭다운 아이템 hover 배경 |

### 대시보드 레이아웃

```
┌──────────────────────────────────────────────────────────┐
│ Sidebar: 갤러리 ID / Tone / Length / Scan Range /        │
│          Headless / Gemini API Key / Export CSV           │
├──────────────────────────────────────────────────────────┤
│  [AI Generated Posts]  [AI Comments]  [AI Share %]       │
│  ──────────── Progress Bar (스캔 중일 때) ─────────────  │
├─────────────────────┬────────────────────────────────────┤
│  STEP 1 · 트렌드 스캔│  STEP 3 · 자동 포스팅             │
│  [▶ SCAN] [⏹ STOP]  │  □ Swarm Mode / 반복 슬라이더      │
│  상태 메시지          │  Preview Card (제목/본문 미리보기) │
│  Hot Keyword 태그     │  [🚀 POST TO DC INSIDE]           │
├─────────────────────┤                                    │
│  STEP 2 · AI 뻘글 생성│  📟 실시간 로그 (컬러 코드 분류) │
│  Topic 입력 + [🎲 추천]│                                 │
│  [⚡ GENERATE]        │                                  │
│  제목/본문 수정 에디터 │                                  │
└─────────────────────┴────────────────────────────────────┘
│  [▽ 수집 데이터 상세 (접이식)] Posts | Comments | Chart  │
└──────────────────────────────────────────────────────────┘
```

### 실시간 로그 색상 코드

| 클래스 | 색상 | 트리거 키워드 |
|--------|------|--------------|
| `log-error` | 빨강 | ERROR, BLOCK, FAIL |
| `log-ok` | 올리브 | OK, DONE, COMPLETE, ✅ |
| `log-info` | 파랑 | INFO, PHASE |
| `log-worker` | 골드 | `[W` (워커 ID) |
| `log-line` | 회색 | 기타 모든 로그 |

### Streamlit 상태 관리 이슈 해결

`st.spinner()` 컨텍스트 내부에서 `st.session_state` 업데이트 후 `st.rerun()`을 호출하면 상태가 커밋되기 전에 rerun이 실행되어 버튼을 2번 클릭해야 동작하는 버그가 발생한다.

**해결**: 상태 업데이트(`st.session_state.suggested_topic = topic`)와 `st.rerun()`을 `with st.spinner()` 블록 **밖**으로 분리하여 순서 보장.

---

## 5. 향후 과제 (Roadmap)

### Phase 1: Auto-Comment System (자동 댓글)

현재 포스팅 봇은 게시글 본문 작성에 한정되어 있다. 여론 형성 효과를 극대화하려면 게시글에 달리는 댓글을 자동으로 생성·게시하는 기능이 필요하다.

#### 설계 방향

| 항목 | 내용 |
|------|------|
| **타겟팅 로직** | DB에서 `is_winner=True`이거나 최근 N분 내에 수집된 글을 댓글 대상으로 선정 |
| **댓글 생성 프롬프트** | 기존 `SYSTEM_PROMPT_BASE`에 `[댓글 작성 규칙]` 섹션 추가. 원글 제목/본문을 컨텍스트로 주입 |
| **댓글 톤 분리** | `agree` (공감·동조), `doubt` (의심·반박), `neutral` (중립적 추임새) 3가지 톤 |
| **Playwright 구현** | 게시글 상세 페이지 진입 → `.write_area` 또는 `#comment_input` 탐지 → 입력 → 등록 |
| **UI 추가** | STEP 2에 "🗨️ 댓글 생성" 모드 추가 (post_id 입력 또는 자동 타겟 선정) |

#### 예상 구현 파일

- `brain.py`: `generate_comment(post_title, post_content, tone)` 메서드 신규
- `poster.py`: `write_comment(gallery_id, post_id, content)` 메서드 신규
- `app.py`: STEP 3에 댓글 포스팅 UI 추가, Swarm Mode에 댓글 wave 통합

---

### Phase 2: Multi-Gallery Targeting

현재는 사이드바에서 갤러리 ID를 단일 입력하는 방식이다. 향후 여러 갤러리를 동시에 공략할 수 있는 타겟 관리 시스템이 필요하다.

| 기능 | 내용 |
|------|------|
| **타겟 갤러리 목록** | `targets.json` 파일로 복수 갤러리 ID 관리 |
| **갤러리별 톤 설정** | 각 갤러리마다 최적 Tone/Length 프리셋 지정 |
| **스케줄러** | 시간대별 공략 갤러리 로테이션 (주식갤 09~16시, 기타 갤 야간 등) |

---

### Phase 3: Feedback Loop (성과 추적)

게시한 글이 얼마나 반응을 얻었는지를 추적하여 프롬프트를 자동으로 개선하는 루프.

| 항목 | 내용 |
|------|------|
| **게시 후 재수집** | 포스팅 성공 후 N시간 뒤 해당 post_id를 재스크래핑 |
| **반응 지표** | 조회수 증가량, 추천수, 댓글수 → `post_performance` 테이블 저장 |
| **프롬프트 강화** | 높은 반응을 얻은 글의 Tone/Length/Keywords를 다음 생성에 자동 반영 |

---

### Phase 4: Detection Defense 강화

Zero-Width Space 워터마크는 이미 스크래퍼가 자동 탐지한다. 향후 봇 탐지 기술이 정교화될 것을 대비한 방어 고도화.

| 위협 | 대응 방안 |
|------|----------|
| 워터마크 탐지 | 워터마크 위치 랜덤화 (글 중간 삽입) |
| UA 고정 탐지 | TLS Fingerprint 회전 (Playwright Firefox 모드 추가) |
| 계정 패턴 탐지 | 계정별 게시 간격·시간대 패턴 랜덤화 |
| 글 내용 유사도 | Few-shot 예시에 배제 목록 유지 (직전 N개 생성글 피드백) |

---

## 6. 현재 완성도 평가

| 기능 | 상태 | 완성도 |
|------|------|--------|
| 갤러리 스크래핑 (병렬, 시간 기반) | ✅ 완료 | 100% |
| 증분 수집 (Incremental) | ✅ 완료 | 100% |
| Bot Radar + 서킷 브레이커 | ✅ 완료 | 100% |
| AI 워터마크 탐지 | ✅ 완료 | 100% |
| LLM 게시글 생성 (Gemini 2.5 Flash) | ✅ 완료 | 100% |
| Deep Humanizer 페르소나 | ✅ 완료 | 95% |
| 6가지 Tone + 3가지 Length | ✅ 완료 | 100% |
| JSON 기반 주제 추천 | ✅ 완료 | 100% |
| Playwright 자동 로그인·포스팅 | ✅ 완료 | 95% |
| 1px 미끼 짤방 Paste | ✅ 완료 | 100% |
| Swarm Mode (연속 폭격) | ✅ 완료 | 90% |
| Warm Bento UI (다크모드 완전 차단) | ✅ 완료 | 100% |
| 실시간 로그 뷰어 | ✅ 완료 | 100% |
| CSV / JSONL 데이터 익스포트 | ✅ 완료 | 100% |
| 자동 댓글 생성·게시 | 🔲 미구현 | 0% |
| 멀티 갤러리 타겟팅 | 🔲 미구현 | 0% |
| 성과 피드백 루프 | 🔲 미구현 | 0% |

---

*Ghost Protocol v5.0 "Swarm Mode" — Report generated 2026-02-23*
