"""FastAPI entrypoint for the Ghost Protocol API facade."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ghost_protocol import database
from ghost_protocol.api import API_VERSION
from ghost_protocol.api import services
from ghost_protocol.api import local_control
from ghost_protocol.application.local_worker_models import (
    ActiveRunError,
    RunNotFoundError,
    RunSpec,
)
from ghost_protocol.api.schemas import (
    CommunityAnalyzeRequest,
    CommunityScanRequest,
    CommunitySignalResponse,
    CommunitySnapshotResponse,
    HealthResponse,
    LocalOverviewResponse,
    PostDraftRequest,
    PostDraftResponse,
    ReplyDraftRequest,
    ReplyDraftResponse,
    ThreadAnalysisResponse,
    ThreadAnalyzeRequest,
    RunCreateRequest,
    RunEventResponse,
    RunEventsResponse,
    RunListResponse,
    RunSnapshotResponse,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    yield


def _snapshot_response(snapshot) -> RunSnapshotResponse:
    return RunSnapshotResponse(**snapshot.to_dict())


def create_app(*, runtime=None) -> FastAPI:
    app = FastAPI(
        title="Ghost Protocol Community Signal API",
        version=API_VERSION,
        description=(
            "Read-only community signal analysis and human-review draft API. "
            "Posting automation is intentionally not exposed."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
        allow_credentials=False,
    )

    def active_runtime():
        return runtime or local_control.get_runtime()

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return services.health()

    @app.post("/v1/runs", response_model=RunSnapshotResponse, status_code=202)
    def start_run(request: RunCreateRequest) -> RunSnapshotResponse:
        try:
            snapshot = active_runtime().start(
                RunSpec(mode=request.mode, params=request.params)
            )
        except ActiveRunError as exc:
            raise HTTPException(status_code=409, detail="active_run") from exc
        return _snapshot_response(snapshot)

    @app.get("/v1/runs", response_model=RunListResponse)
    def list_runs() -> RunListResponse:
        return RunListResponse(
            runs=[_snapshot_response(item) for item in active_runtime().snapshots()]
        )

    @app.get("/v1/runs/{run_id}", response_model=RunSnapshotResponse)
    def get_run(run_id: str) -> RunSnapshotResponse:
        try:
            return _snapshot_response(active_runtime().snapshot(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run_not_found") from exc

    @app.get("/v1/runs/{run_id}/events", response_model=RunEventsResponse)
    def get_run_events(
        run_id: str,
        after: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=200),
    ) -> RunEventsResponse:
        try:
            runtime_instance = active_runtime()
            snapshot = runtime_instance.snapshot(run_id)
            events = runtime_instance.events_after(run_id, after=after, limit=limit)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run_not_found") from exc
        last = events[-1].sequence if events else None
        return RunEventsResponse(
            **snapshot.to_dict(),
            events=[RunEventResponse(**event.to_dict()) for event in events],
            next_sequence=last,
            has_more=bool(last is not None and last < snapshot.last_event_sequence),
        )

    @app.post("/v1/runs/{run_id}/stop", response_model=RunSnapshotResponse)
    def stop_run(run_id: str) -> RunSnapshotResponse:
        try:
            return _snapshot_response(active_runtime().stop(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run_not_found") from exc

    @app.post("/v1/communities/scan", response_model=CommunitySnapshotResponse)
    async def scan_community(
        request: CommunityScanRequest,
    ) -> CommunitySnapshotResponse:
        try:
            return await run_in_threadpool(services.collect_community_snapshot, request)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/communities/analyze", response_model=CommunitySignalResponse)
    async def analyze_community(
        request: CommunityAnalyzeRequest,
    ) -> CommunitySignalResponse:
        try:
            return await run_in_threadpool(services.analyze_community_signal, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get(
        "/v1/communities/{community_id}/overview",
        response_model=LocalOverviewResponse,
    )
    async def local_overview(
        community_id: str,
        limit: int = 20,
    ) -> LocalOverviewResponse:
        return await run_in_threadpool(
            services.get_local_overview,
            community_id,
            limit=max(1, min(100, limit)),
        )

    @app.get("/v1/communities/{community_id}/exports/posts.csv")
    async def export_posts(community_id: str) -> Response:
        content, _count = await run_in_threadpool(
            database.build_posts_csv_bytes,
            community_id,
        )
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{community_id}_posts.csv"'
            },
        )

    @app.get("/v1/communities/{community_id}/exports/comments.csv")
    async def export_comments(community_id: str) -> Response:
        content, _count = await run_in_threadpool(
            database.build_comments_csv_bytes,
            community_id,
        )
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{community_id}_comments.csv"'
            },
        )

    @app.post("/v1/drafts/posts", response_model=PostDraftResponse)
    async def post_draft(request: PostDraftRequest) -> PostDraftResponse:
        try:
            return await run_in_threadpool(services.build_post_draft, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/threads/analyze", response_model=ThreadAnalysisResponse)
    async def thread_analyze(
        request: ThreadAnalyzeRequest,
    ) -> ThreadAnalysisResponse:
        try:
            return await run_in_threadpool(services.analyze_thread, request)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/drafts/replies", response_model=ReplyDraftResponse)
    async def reply_draft(request: ReplyDraftRequest) -> ReplyDraftResponse:
        try:
            return await run_in_threadpool(services.build_reply_draft, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    studio_index = web_dist / "index.html"
    if studio_index.is_file():
        assets_dir = web_dist / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="studio-assets",
            )

        @app.get("/studio", include_in_schema=False)
        def studio_home() -> FileResponse:
            return FileResponse(studio_index)

        @app.get("/studio/{asset_path:path}", include_in_schema=False)
        def studio_spa(asset_path: str) -> FileResponse:
            candidate = (web_dist / asset_path).resolve()
            try:
                candidate.relative_to(web_dist.resolve())
            except ValueError:
                return FileResponse(studio_index)
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(studio_index)

    return app


app = create_app()
