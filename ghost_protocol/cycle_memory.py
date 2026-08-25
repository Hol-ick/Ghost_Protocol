"""cycle_memory — 무한 사이클 간 상태 지속 메모리.

저장 위치: {project_root}/cycle_memory.json
갱신 시점: _batch_gen_worker 시작/종료 시 (app.py).

추적 항목:
  topic_ttl      : hot_topic 키워드별 연속 등장 횟수.
                   TOPIC_TTL_BAN 이상 → 금지 목록 → topic에 주입.
  sentiment_hist : 최근 MAX_HIST 사이클 감성 점수 배열.
                   합산 ≤ DRIFT_THRESHOLD → lineup HOT 상한 절반, mutant 최대.
  vocab_window   : 최근 MAX_VOCAB 개 본문의 첫 어절 배열.
                   특정 어절이 VOCAB_BAN_RATIO 초과 → 자동 금지어 → topic에 주입.
  cycle_count    : 총 누적 사이클 수 (외부 자극 강제 주입 주기 계산에 사용).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# ── 저장 경로 ─────────────────────────────────────────────────────────────────
_MEMORY_PATH = Path(__file__).parent.parent / "cycle_memory.json"

# ── 튜닝 파라미터 ─────────────────────────────────────────────────────────────
TOPIC_TTL_BAN    = 3     # N사이클 연속 등장 → 금지 목록 추가 (2→3: 요요 방지)
TOPIC_COOLDOWN   = 2     # 금지 해제 후 N사이클간 쿨다운 (재등장 시 즉시 재금지)
MAX_HIST         = 5     # 감성 기록 보존 최대 사이클 수
DRIFT_THRESHOLD  = -4    # sentiment 합산 이 값 이하 → 진자 보정 발동 (-2→-4: 과민 억제)
DRIFT_RECOVERY_AFTER = 3 # DRIFT 연속 N사이클 후 강제 리셋 (고착 방지)
DRIFT_BONUS      = 1     # DRIFT 발동 중 감성 점수에 가산할 보정값
MAX_VOCAB        = 30    # first_word 추적 슬라이딩 윈도우 크기
VOCAB_BAN_RATIO  = 0.15  # 특정 first_word가 윈도우 내 이 비율 초과 → 자동 금지 (0.20→0.15)
MAX_TITLE_VOCAB  = 40    # 제목 첫 토큰 슬라이딩 윈도우 크기
TITLE_BAN_RATIO  = 0.20  # 제목 첫 토큰이 윈도우 내 이 비율 초과 → 자동 금지

# ── 감성 문자열 → 수치 매핑 ──────────────────────────────────────────────────
# 값이 높을수록 긍정, 낮을수록 부정.
# 키워드 포함 여부로 매칭 (순서대로 첫 매칭).
# 냉소/조롱/혼란은 갤러리 기본 감성이므로 0(중립)으로 처리 — 실제 분노·패닉만 음수.
_SENTIMENT_TABLE: list[tuple[str, int]] = [
    ("우호적",  2),
    ("긍정",    1),
    ("중립",    0),
    ("보통",    0),
    ("냉소",    0),   # 갤러리 기본 상태 → 중립으로 처리
    ("조롱",    0),   # 갤러리 기본 상태 → 중립으로 처리
    ("피로",   -1),   # "피로감/조롱" — 모델 빈출 감성
    ("회의",   -1),   # "회의적/조롱" — 모델 빈출 감성
    ("의아",   -1),   # "의아함" — 모델 빈출 감성
    ("짜증",   -1),
    ("혼란",   -1),
    ("의문",   -1),
    ("분노",   -2),
    ("적대적", -2),
    ("의심",   -1),   # "의심/피로" — 모델 빈출 감성
    ("패닉",   -3),
    ("공황",   -3),
]


# ── 기본 구조 ─────────────────────────────────────────────────────────────────
def _default() -> dict:
    return {
        "topic_ttl":          {},   # {keyword: consecutive_count}
        "topic_first_seen":   {},   # {keyword: cycle_count} — 화제 생명주기 추적용
        "topic_cooldown":     {},   # {keyword: remaining_cooldown_cycles} — 금지 해제 후 쿨다운
        "sentiment_hist":     [],   # [int, ...]  최근 MAX_HIST개
        "vocab_window":       [],   # [str, ...]  최근 MAX_VOCAB개 first_words (본문 첫 어절)
        "title_vocab_window": [],   # [str, ...]  최근 MAX_TITLE_VOCAB개 (제목 첫 토큰)
        "cycle_count":        0,
        "drift_streak":       0,    # DRIFT 연속 발동 사이클 수 (고착 방지용)
        "galleries":          {},   # {gallery_id: cycle_memory_scope}
    }


def _default_scope() -> dict:
    data = _default()
    data.pop("galleries", None)
    return data


def get_gallery_memory(mem: dict, gallery_id: str) -> dict:
    """Return the mutable cycle-memory scope for a single gallery.

    Topic bans and vocabulary convergence are only meaningful inside the same
    community. Keeping them scoped prevents one gallery's old meme from
    suppressing another gallery's live topic.
    """

    gid = str(gallery_id or "").strip()
    if not gid:
        return mem

    galleries = mem.get("galleries")
    if not isinstance(galleries, dict):
        galleries = {}
        mem["galleries"] = galleries
    scope = galleries.get(gid)
    if not isinstance(scope, dict):
        scope = {}

    base = _default_scope()
    base.update(scope)
    galleries[gid] = base
    return base


# ── IO ────────────────────────────────────────────────────────────────────────
def load() -> dict:
    """cycle_memory.json 로드. 파일 없거나 파손 시 기본값 반환."""
    try:
        data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default()
        base = _default()
        base.update(data)   # 새 키가 추가돼도 안전하게 병합
        return base
    except Exception:
        return _default()


def save(mem: dict) -> None:
    """cycle_memory.json 저장. 실패 시 무시 (UX 차단 방지)."""
    try:
        _MEMORY_PATH.write_text(
            json.dumps(mem, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── 사이클 카운터 ─────────────────────────────────────────────────────────────
def increment_cycle(mem: dict) -> int:
    """cycle_count 1 증가 후 반환."""
    mem["cycle_count"] = mem.get("cycle_count", 0) + 1
    return mem["cycle_count"]


# ── 1. 화제 반감기 (Topic TTL) ────────────────────────────────────────────────
def update_topic_ttl(mem: dict, hot_topics: list[str]) -> list[str]:
    """hot_topics의 등장 카운트를 갱신하고 금지 키워드 목록을 반환.

    이번 사이클에 등장한 키워드: 카운트 +1 + 생명주기 가속 페널티.
      → 오래된 화제일수록 빠르게 금지 임계값에 도달 (자연스러운 화제 전환).
    미등장 키워드: 즉시 리셋 대신 카운트 -1 (서서히 쿨다운).
    쿨다운: 금지 해제 후 TOPIC_COOLDOWN 사이클 동안 재등장 시 즉시 재금지 (요요 방지).
    Returns: TOPIC_TTL_BAN 이상 카운트인 키워드 목록.
    """
    old_ttl: dict = mem.get("topic_ttl", {})
    first_seen: dict = mem.get("topic_first_seen", {})
    cooldown: dict = mem.get("topic_cooldown", {})
    cycle = mem.get("cycle_count", 0)
    new_ttl: dict = {}
    current: set[str] = {t.strip() for t in hot_topics if t.strip()}

    # 쿨다운 감소 (매 사이클 1씩)
    expired_cd = []
    for key in list(cooldown.keys()):
        cooldown[key] -= 1
        if cooldown[key] <= 0:
            expired_cd.append(key)
    for key in expired_cd:
        del cooldown[key]

    # 등장 키워드: 카운트 증가 + 생명주기 가속 + 쿨다운 페널티
    for key in current:
        # 첫 등장 사이클 기록
        if key not in first_seen:
            first_seen[key] = cycle
        age = cycle - first_seen[key]  # 이 화제가 존재한 사이클 수
        # 가속 페널티: 5사이클 이상 장기 화제 → +1 추가 (총 +2/사이클)
        accel = 1 if age >= 5 else 0
        base = old_ttl.get(key, 0) + 1 + accel
        # 쿨다운 페널티: 최근 금지 해제된 화제가 다시 등장하면 즉시 재금지
        if key in cooldown:
            base = max(base, TOPIC_TTL_BAN)  # 즉시 임계값 도달
        new_ttl[key] = base

    # 미등장 키워드: 즉시 삭제 대신 1 감소 (쿨다운)
    for key, count in old_ttl.items():
        if key not in current and key not in new_ttl:
            # 금지 상태에서 미등장으로 전환 → 쿨다운 시작
            if count >= TOPIC_TTL_BAN and key not in cooldown:
                cooldown[key] = TOPIC_COOLDOWN
            decayed = count - 1
            if decayed > 0:
                new_ttl[key] = decayed
            else:
                # 카운트 0 이하로 쿨다운 완료 → first_seen도 정리
                first_seen.pop(key, None)

    mem["topic_ttl"] = new_ttl
    mem["topic_first_seen"] = first_seen
    mem["topic_cooldown"] = cooldown
    return [k for k, v in new_ttl.items() if v >= TOPIC_TTL_BAN]


MAX_BANNED_TOPICS = 3    # 동시 금지 화제 최대 수 — 초과 시 가장 오래된 것부터 해제

def get_banned_topics(mem: dict) -> list[str]:
    """현재 TTL 임계값 초과 금지 키워드 목록 반환.

    최대 MAX_BANNED_TOPICS개까지만 반환. 금지가 너무 많으면 LLM이 쓸 소재가
    없어져 실패율이 급증하므로, TTL이 높은(오래 반복된) 순으로 우선 차단.
    """
    banned = {k: v for k, v in mem.get("topic_ttl", {}).items() if v >= TOPIC_TTL_BAN}
    if len(banned) <= MAX_BANNED_TOPICS:
        return list(banned.keys())
    # TTL 높은 순 정렬 → 상위 MAX_BANNED_TOPICS만
    sorted_banned = sorted(banned.items(), key=lambda x: -x[1])
    return [k for k, _ in sorted_banned[:MAX_BANNED_TOPICS]]


def get_topic_ages(mem: dict) -> dict[str, int]:
    """각 화제의 나이(사이클 수) 반환. 생명주기 모니터링용."""
    cycle = mem.get("cycle_count", 0)
    first_seen = mem.get("topic_first_seen", {})
    return {k: cycle - v for k, v in first_seen.items()}


# ── 2. 감성 진자 (Sentiment Drift) ───────────────────────────────────────────
def _score_sentiment(sentiment: str) -> int:
    """sentiment 문자열을 수치로 변환 — 복합 감성은 최소(가장 부정적) 점수 사용.

    "조롱/의심/피로" 같은 복합 감성에서 "조롱"(0점)이 먼저 매칭되어
    실제 부정 신호를 0으로 씹는 문제를 해결.
    모든 매칭 키워드의 점수 중 최소값(가장 부정적)을 반환.
    """
    scores = [val for keyword, val in _SENTIMENT_TABLE if keyword in sentiment]
    return min(scores) if scores else 0


def update_sentiment(mem: dict, sentiment: str) -> int:
    """sentiment 기록 추가. 최근 MAX_HIST개 유지. 현재 누적 점수 반환.

    DRIFT 고착 방지:
    - DRIFT 발동 중이면 점수에 DRIFT_BONUS(+1) 가산 → 자연 회복 유도.
    - DRIFT가 DRIFT_RECOVERY_AFTER(3) 사이클 연속이면 hist를 [0]*MAX_HIST로 리셋.
    """
    score = _score_sentiment(sentiment)

    # ── DRIFT 고착 방지 ─────────────────────────────────────────────
    was_drifted = is_drift_active(mem)
    streak = mem.get("drift_streak", 0)

    if was_drifted:
        streak += 1
        if streak >= DRIFT_RECOVERY_AFTER:
            # 연속 DRIFT N사이클 → 강제 리셋 (중립 상태로 복귀)
            mem["sentiment_hist"] = [0] * MAX_HIST
            mem["drift_streak"] = 0
            return 0
        # DRIFT 발동 중: 보정 가산 → 회복 가능하게
        score = min(score + DRIFT_BONUS, 1)  # 최대 +1(긍정)까지만
    else:
        streak = 0

    mem["drift_streak"] = streak

    hist: list = mem.get("sentiment_hist", [])
    hist.append(score)
    mem["sentiment_hist"] = hist[-MAX_HIST:]
    return sum(mem["sentiment_hist"])


def get_sentiment_score(mem: dict) -> int:
    """최근 MAX_HIST 사이클 감성 점수 합계 반환."""
    return sum(mem.get("sentiment_hist", []))


def is_drift_active(mem: dict) -> bool:
    """감성 drift 보정(진자) 발동 여부. score ≤ DRIFT_THRESHOLD이면 True."""
    return get_sentiment_score(mem) <= DRIFT_THRESHOLD


# ── 3. 어휘 엔트로피 모니터링 ────────────────────────────────────────────────
def update_vocab(mem: dict, first_words: list[str]) -> list[str]:
    """first_words 배치를 vocab 슬라이딩 윈도우에 추가하고 금지어 목록을 반환.

    Returns: VOCAB_BAN_RATIO 초과 어절 목록.
    """
    window: list = mem.get("vocab_window", [])
    window.extend(w.strip() for w in first_words if w.strip())
    window = window[-MAX_VOCAB:]
    mem["vocab_window"] = window
    if not window:
        return []
    counter = Counter(window)
    total = len(window)
    return [w for w, cnt in counter.items() if cnt / total >= VOCAB_BAN_RATIO]


MAX_BANNED_STARTS = 3    # 동시 금지 서두어 최대 수

def get_banned_starts(mem: dict) -> list[str]:
    """현재 어휘 윈도우에서 VOCAB_BAN_RATIO 초과 어절 목록 반환. 최대 3개."""
    window = mem.get("vocab_window", [])
    if not window:
        return []
    counter = Counter(window)
    total = len(window)
    banned = [(w, cnt) for w, cnt in counter.items() if cnt / total >= VOCAB_BAN_RATIO]
    banned.sort(key=lambda x: -x[1])
    return [w for w, _ in banned[:MAX_BANNED_STARTS]]


# ── 4. 제목 키워드 엔트로피 모니터링 ─────────────────────────────────────────
def _extract_title_tokens(title: str) -> list[str]:
    """제목에서 의미 있는 토큰 추출 (2자 이상, 구두점 제거).

    첫 3 토큰만 수집 — 제목 앞부분이 화제를 가장 잘 대표.
    예: '세미라미스 얘기 언제까지 하는 거냐' → ['세미라미스', '얘기', '언제까지']
    """
    stripped = [
        w.strip("?!.~ㅋㅠ.,ㅡ()[]{}\"'")
        for w in title.split()
    ]
    return [w for w in stripped if len(w) >= 2][:3]


def update_title_vocab(mem: dict, titles: list[str]) -> list[str]:
    """생성된 제목들의 앞 토큰을 title_vocab_window에 추가, 금지 키워드 반환.

    여러 배치에 걸쳐 동일 소재 제목이 반복 생성되는 것을 감지.
    Returns: TITLE_BAN_RATIO 초과 토큰 목록.
    """
    tokens: list[str] = []
    for t in titles:
        tokens.extend(_extract_title_tokens(t))

    window: list = mem.get("title_vocab_window", [])
    window.extend(tokens)
    window = window[-MAX_TITLE_VOCAB:]
    mem["title_vocab_window"] = window
    if not window:
        return []
    counter = Counter(window)
    total = len(window)
    return [w for w, cnt in counter.items() if cnt / total >= TITLE_BAN_RATIO]


MAX_BANNED_TITLE_KWS = 3  # 동시 금지 제목 키워드 최대 수

def get_banned_title_keywords(mem: dict) -> list[str]:
    """현재 title_vocab_window에서 TITLE_BAN_RATIO 초과 토큰 목록 반환. 최대 3개."""
    window = mem.get("title_vocab_window", [])
    if not window:
        return []
    counter = Counter(window)
    total = len(window)
    banned = [(w, cnt) for w, cnt in counter.items() if cnt / total >= TITLE_BAN_RATIO]
    banned.sort(key=lambda x: -x[1])
    return [w for w, _ in banned[:MAX_BANNED_TITLE_KWS]]
