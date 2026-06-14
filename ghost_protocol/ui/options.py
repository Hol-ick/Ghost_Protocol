"""Stable dashboard option labels and value mappings."""

from __future__ import annotations


DEFAULT_GALLERY_TYPE_LABEL = "마이너 게시판"
DEFAULT_TONE_LABEL = "냉소적"
DEFAULT_LENGTH_LABEL = "보통 (3~4문장)"

GALLERY_TYPE_OPTIONS: list[str] = [
    DEFAULT_GALLERY_TYPE_LABEL,
    "정규 게시판",
    "미니 게시판",
]

TYPE_MAP: dict[str, str] = {
    DEFAULT_GALLERY_TYPE_LABEL: "mgallery",
    "정규 게시판": "board",
    "미니 게시판": "mini",
    # Backward-compatible aliases for existing session/cache/history values.
    "마이너 (mgallery)": "mgallery",
    "정규 (board)": "board",
    "미니 (mini)": "mini",
    "mgallery": "mgallery",
    "board": "board",
    "mini": "mini",
}

TONE_OPTIONS: list[str] = [
    DEFAULT_TONE_LABEL,
    "중립",
    "분석적",
    "독백",
    "공격적",
    "어그로성",
    "하소연형",
    "메타 관전자",
    "체념형",
    "소신발언",
    "훈수꾼",
    "희망회로",
    "질문형",
    "비틱",
    "음모론자",
    "자학형",
    "집결형",
    "실황형",
    "화제전환형",
]

TONE_MAP: dict[str, str] = {
    DEFAULT_TONE_LABEL: "cynical",
    "중립": "neutral",
    "분석적": "analytical",
    "독백": "monologue",
    "공격적": "aggressive",
    "어그로성": "aggro",
    "하소연형": "ventilator",
    "메타 관전자": "meta_observer",
    "체념형": "doomer",
    "소신발언": "conviction_defender",
    "훈수꾼": "solution_proposer",
    "희망회로": "hopium",
    "질문형": "lazy_questioner",
    "비틱": "humblebragger",
    "음모론자": "paranoid",
    "자학형": "self_deprecator",
    "집결형": "rally_crier",
    "실황형": "score_reporter",
    "화제전환형": "topic_diverger",
    # Backward-compatible aliases for existing session values.
    "🧊 냉소적 (Cynical)": "cynical",
    "😐 중립 (Neutral)": "neutral",
    "📊 분석적 (Analytical)": "analytical",
    "🗣️ 독백 (Monologue)": "monologue",
    "🔥 공격적 (Aggressive)": "aggressive",
    "💀 어그로성 (Aggro)": "aggro",
    "😤 하소연형 (Ventilator)": "ventilator",
    "🔭 메타 관전자 (Meta)": "meta_observer",
    "☠️ 체념형 (Doomer)": "doomer",
    "🛡️ 소신발언 (Defender)": "conviction_defender",
    "🔧 훈수꾼 (Solution)": "solution_proposer",
    "🚀 희망회로 (Hopium)": "hopium",
    "❓ 질문충 (Lazy Q)": "lazy_questioner",
    "😏 비틱 (Humblebragger)": "humblebragger",
    "🕵️ 음모론자 (Paranoid)": "paranoid",
    "😭 자학형 (Self-deprecator)": "self_deprecator",
    "📣 집결형 (Rally Crier)": "rally_crier",
    "📡 실황형 (Score Reporter)": "score_reporter",
    "🔄 화제전환형 (Diverger)": "topic_diverger",
    "cynical": "cynical",
    "neutral": "neutral",
    "analytical": "analytical",
    "monologue": "monologue",
    "aggressive": "aggressive",
    "aggro": "aggro",
    "ventilator": "ventilator",
    "meta_observer": "meta_observer",
    "doomer": "doomer",
    "conviction_defender": "conviction_defender",
    "solution_proposer": "solution_proposer",
    "hopium": "hopium",
    "lazy_questioner": "lazy_questioner",
    "humblebragger": "humblebragger",
    "paranoid": "paranoid",
    "self_deprecator": "self_deprecator",
    "rally_crier": "rally_crier",
    "score_reporter": "score_reporter",
    "topic_diverger": "topic_diverger",
}

LENGTH_OPTIONS: list[str] = [
    "아주 짧게 (1문장)",
    "짧게 (1~2문장)",
    DEFAULT_LENGTH_LABEL,
]


def gallery_type_for_label(label: str) -> str:
    """Resolve a UI gallery type label to the scraper/poster value."""
    return TYPE_MAP.get(label, TYPE_MAP[DEFAULT_GALLERY_TYPE_LABEL])


def normalize_gallery_type_label(label: str) -> str:
    """Return the preferred display label for a gallery type label or value."""
    value = gallery_type_for_label(label)
    return {
        "mgallery": DEFAULT_GALLERY_TYPE_LABEL,
        "board": "정규 게시판",
        "mini": "미니 게시판",
    }.get(value, DEFAULT_GALLERY_TYPE_LABEL)


def tone_for_label(label: str) -> str:
    """Resolve a UI tone label to the generation tone key."""
    return TONE_MAP.get(label, TONE_MAP[DEFAULT_TONE_LABEL])


def normalize_tone_label(label: str) -> str:
    """Return the preferred display label for a tone label or internal key."""
    value = tone_for_label(label)
    for option in TONE_OPTIONS:
        if TONE_MAP[option] == value:
            return option
    return DEFAULT_TONE_LABEL
