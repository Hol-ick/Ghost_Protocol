"""Pydantic contracts for the Ghost Protocol API facade.

The API intentionally exposes analysis and human-review draft workflows only.
It does not expose browser posting, account rotation, or stealth automation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


GalleryType = Literal["board", "mgallery", "mini"]
SourceName = Literal["dcinside"]
RunMode = Literal["sample", "intel", "rehearsal"]
DraftIntent = Literal[
    "information",
    "clarification",
    "neutral_summary",
    "logical_rebuttal",
    "question_answer",
]
DraftTone = Literal["calm", "neutral", "firm", "polite", "concise"]
DraftLength = Literal["short", "normal", "long"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafetyContract(ApiModel):
    requires_human_review: bool = True
    posting_supported: bool = False
    disallowed_actions: list[str] = Field(
        default_factory=lambda: [
            "automatic_posting",
            "account_rotation",
            "stealth_evasion",
            "impersonation",
        ]
    )
    note: str = (
        "This API returns analysis and drafts only. A human operator must review "
        "and approve any external communication."
    )


class HealthResponse(ApiModel):
    status: str
    app_version: str
    api_version: str
    safety: SafetyContract = Field(default_factory=SafetyContract)


class RunCreateRequest(ApiModel):
    """Browser-safe input for a local worker run.

    Credentials and local session material are intentionally rejected rather
    than silently ignored, so a caller cannot mistake the browser for a
    credential boundary.
    """

    mode: RunMode
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def reject_local_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {
            "api_key",
            "gemini_api_key",
            "account_file",
            "cookie",
            "cookies",
            "session",
            "session_file",
        }
        for key in value:
            normalized = str(key).strip().casefold()
            if normalized in forbidden or normalized.startswith("gemini_api_key"):
                raise ValueError(f"local credential field is not accepted: {key}")
        return dict(value)


class RunSnapshotResponse(ApiModel):
    run_id: str
    state: str
    created_at: str
    updated_at: str
    mode: str
    progress: dict[str, Any] = Field(default_factory=dict)
    last_event_sequence: int = 0
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class RunListResponse(ApiModel):
    runs: list[RunSnapshotResponse] = Field(default_factory=list)


class RunEventResponse(ApiModel):
    sequence: int
    kind: str
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class RunEventsResponse(ApiModel):
    run_id: str
    state: str
    created_at: str
    updated_at: str
    mode: str
    progress: dict[str, Any] = Field(default_factory=dict)
    last_event_sequence: int = 0
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    events: list[RunEventResponse] = Field(default_factory=list)
    next_sequence: int | None = None
    has_more: bool = False


class CommunityScanRequest(ApiModel):
    source: SourceName = "dcinside"
    community_id: str = Field(..., min_length=1, max_length=120)
    community_type: GalleryType = "mgallery"
    pages: int = Field(1, ge=1, le=20)
    max_comments_per_post: int = Field(5, ge=0, le=30)
    top_posts_per_page: int = Field(5, ge=0, le=30)
    source_detail_limit: int = Field(0, ge=0, le=50)
    source_comments_per_post: int = Field(5, ge=0, le=30)


class CommunitySnapshotResponse(ApiModel):
    source: SourceName
    community_id: str
    community_type: GalleryType
    collected_at: str
    titles: list[str]
    comments: list[str]
    authors: list[str]
    raw_posts: list[dict[str, Any]]
    stats: dict[str, Any]
    noise_filter: dict[str, Any] = Field(default_factory=dict)
    posting_rhythm: dict[str, Any] = Field(default_factory=dict)
    safety: SafetyContract = Field(default_factory=SafetyContract)


class CommunityAnalyzeRequest(CommunityScanRequest):
    api_key: str | None = Field(default=None, repr=False)
    top_k: int = Field(30, ge=3, le=80)
    use_llm: bool = True
    snapshot: dict[str, Any] | None = None


class CommunitySignalResponse(ApiModel):
    source: SourceName
    community_id: str
    community_type: GalleryType
    analysis: dict[str, Any]
    snapshot_stats: dict[str, Any]
    safety: SafetyContract = Field(default_factory=SafetyContract)


class LocalOverviewResponse(ApiModel):
    community_id: str
    post_count: int
    comment_count: int
    ai_post_count: int
    top_keywords: list[str]
    recent_posts: list[dict[str, Any]]
    safety: SafetyContract = Field(default_factory=SafetyContract)


class PostDraftRequest(ApiModel):
    topic: str = Field(..., min_length=2, max_length=500)
    community_id: str = Field("", max_length=120)
    tone: DraftTone = "neutral"
    length: DraftLength = "short"
    api_key: str | None = Field(default=None, repr=False)
    context_hours: int = Field(0, ge=0, le=24)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class PostDraftResponse(ApiModel):
    title: str
    content: str
    risk_flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = True
    posting_supported: bool = False
    raw_model_metadata: dict[str, Any] = Field(default_factory=dict)
    safety: SafetyContract = Field(default_factory=SafetyContract)


class ThreadAnalyzeRequest(ApiModel):
    source: SourceName = "dcinside"
    post_url: str | None = Field(default=None, max_length=1000)
    community_id: str | None = Field(default=None, max_length=120)
    community_type: GalleryType = "mgallery"
    post_no: str | None = Field(default=None, max_length=80)
    title: str = Field("", max_length=500)
    content: str = Field("", max_length=10000)
    comments: list[str] = Field(default_factory=list, max_length=500)
    fetch_live: bool = True

    @field_validator("comments")
    @classmethod
    def trim_comments(cls, value: list[str]) -> list[str]:
        return [str(item).strip()[:1000] for item in value if str(item).strip()]


class CommentCluster(ApiModel):
    label: str
    count: int
    samples: list[str] = Field(default_factory=list)


class ThreadAnalysisResponse(ApiModel):
    source: SourceName
    community_id: str
    community_type: GalleryType
    post_no: str
    post_url: str
    title: str
    content_excerpt: str
    post_summary: str
    main_claims: list[str]
    comment_clusters: list[CommentCluster]
    key_counterpoints: list[str]
    risk_flags: list[str] = Field(default_factory=list)
    fetched_live: bool = False
    safety: SafetyContract = Field(default_factory=SafetyContract)


class ReplyDraftRequest(ApiModel):
    thread: ThreadAnalyzeRequest | None = None
    analysis: ThreadAnalysisResponse | None = None
    intent: DraftIntent = "logical_rebuttal"
    tone: DraftTone = "calm"
    length: DraftLength = "short"
    must_include_evidence: bool = True

    @model_validator(mode="after")
    def require_thread_or_analysis(self) -> "ReplyDraftRequest":
        if self.analysis is None and self.thread is None:
            raise ValueError("Either thread or analysis is required")
        return self


class ReplyDraftResponse(ApiModel):
    draft: str
    intent: DraftIntent
    tone: DraftTone
    length: DraftLength
    used_counterpoints: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = True
    posting_supported: bool = False
    safety: SafetyContract = Field(default_factory=SafetyContract)
