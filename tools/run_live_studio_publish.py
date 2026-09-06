"""Run one real Studio collection, analysis, draft, and explicitly approved publish.

This is an operator tool.  It never publishes unless ``--publish`` is passed,
and it writes an ignored local report without credentials or unmasked account
identifiers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


def wait_for(service, job_id: str) -> dict:
    while True:
        try:
            service.wait(job_id, timeout=10)
        except TimeoutError:
            continue
        job = service.job(job_id)
        if job["status"] in {"done", "failed", "cancelled", "interrupted"}:
            return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one live Ghost Protocol Studio publish check.")
    parser.add_argument("--gallery", default="universe")
    parser.add_argument("--gallery-type", default="board", choices=("board", "mgallery", "mini"))
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    parser.add_argument("--tone", default="neutral")
    parser.add_argument("--publish", action="store_true", help="Actually submit the generated draft.")
    args = parser.parse_args()

    if not args.publish:
        raise SystemExit("게시 방지: 실제 업로드에는 --publish가 필요합니다.")

    from ghost_protocol.poster import GhostPoster
    from ghost_protocol.studio.service import StudioService

    run_id = datetime.now(timezone.utc).strftime("live-%Y%m%d-%H%M%S")
    report: dict = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gallery": args.gallery,
        "gallery_type": args.gallery_type,
        "model": args.model,
        "tone": args.tone,
        "publish_requested": True,
    }
    report_dir = ROOT / "logs" / "live_runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{run_id}.json"

    def checkpoint() -> None:
        report["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint()

    with tempfile.TemporaryDirectory(prefix="ghost-studio-live-") as directory:
        service = StudioService(directory)
        service.save_settings({"model": args.model, "pages": 1, "max_drafts": 1, "gap": 1.5})
        work = service.create_workspace("실전 업로드 검증", args.gallery, args.gallery_type)

        collect = wait_for(service, service.start(work["id"], "collect", {"pages": 1}))
        work = service.workspace(work["id"])
        source = work["source"]
        report["collection"] = {
            "status": collect["status"],
            "error": collect.get("error", ""),
            "titles": len(source.get("titles", [])),
            "comments": len(source.get("comments", [])),
            "raw_posts": len(source.get("raw_posts", [])),
            "access": source.get("source_access", {}).get("status", ""),
            "reason": source.get("source_access", {}).get("reason", ""),
            "seconds": collect.get("seconds"),
        }
        checkpoint()
        if collect["status"] != "done":
            raise RuntimeError("수집 실패: " + collect.get("error", "알 수 없는 오류"))

        analysis_job = wait_for(service, service.start(work["id"], "analyze", {}))
        work = service.workspace(work["id"])
        report["analysis"] = {
            "status": analysis_job["status"],
            "error": analysis_job.get("error", ""),
            "summary": work["analysis"].get("summary", ""),
            "seconds": analysis_job.get("seconds"),
        }
        checkpoint()
        if analysis_job["status"] != "done":
            raise RuntimeError("분석 실패: " + analysis_job.get("error", "알 수 없는 오류"))

        service.confirm_analysis(work["id"])
        generate_job = wait_for(service, service.start(work["id"], "generate", {"count": 1, "tones": [args.tone]}))
        work = service.workspace(work["id"])
        if not work["drafts"]:
            raise RuntimeError("원고가 생성되지 않았습니다.")
        draft = work["drafts"][-1]
        report["draft"] = {key: draft.get(key) for key in ("title", "content", "tone", "model", "warnings", "failed")}
        report["generation"] = {
            "status": generate_job["status"],
            "error": generate_job.get("error", ""),
            "seconds": generate_job.get("seconds"),
        }
        report["api_calls"] = [
            {key: call.get(key) for key in ("model", "usage", "cost_usd", "seconds", "error")}
            for call in service.calls(work["id"])
        ]
        checkpoint()
        if generate_job["status"] != "done" or draft.get("failed"):
            raise RuntimeError("원고 생성 실패: " + generate_job.get("error", "응답 파싱 오류"))

        poster_logs: list[str] = []
        result = asyncio.run(
            GhostPoster(headless=True, gallery_type=args.gallery_type).auto_post(
                args.gallery,
                draft.get("title", ""),
                draft.get("content", ""),
                log_callback=poster_logs.append,
            )
        )
        # auto_post returns the real account id for internal legacy callers. Never persist it.
        result.pop("account", None)
        report["publish"] = result
        # The legacy logger may include a session filename derived from an account id.
        # Keep only the operation outcome in the durable report.
        report["poster_log_tail"] = [
            "게시 처리 완료 로그는 계정·세션 식별자 보호를 위해 저장하지 않습니다."
        ]
        checkpoint()

    report["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    checkpoint()
    print(json.dumps({"report": str(report_path), "collection": report.get("collection"), "analysis": report.get("analysis"), "draft": report.get("draft"), "publish": report.get("publish"), "api_calls": report.get("api_calls")}, ensure_ascii=False))
    return 0 if report.get("publish", {}).get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
