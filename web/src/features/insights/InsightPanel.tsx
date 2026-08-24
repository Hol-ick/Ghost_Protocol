import { BarChart3, FileText, Sparkles } from "lucide-react";
import type { RunEvent, RunSnapshot } from "../../types";

export function InsightPanel({ run, events }: { run?: RunSnapshot; events: RunEvent[] }) {
  const insight = [...events].reverse().find((event) => event.kind === "insight" || event.kind === "stat");
  const payload = insight?.payload ?? {};
  return (
    <div className="subpanel insight-panel">
      <div className="subpanel-heading"><span className="subpanel-icon blue"><BarChart3 size={14} /></span><div><h3>Signal readout</h3><p>현재 실행의 관측값</p></div></div>
      <div className="readout-grid">
        <div><span>신호</span><strong>{typeof payload.signal_count === "number" ? payload.signal_count : events.filter((event) => event.kind === "insight").length || "—"}</strong></div>
        <div><span>모드</span><strong>{run?.mode ?? "—"}</strong></div>
        <div><span>마지막 seq</span><strong>{run ? String(run.sequence).padStart(4, "0") : "—"}</strong></div>
      </div>
      {insight && <p className="readout-note"><Sparkles size={13} aria-hidden="true" /> {insight.message || "새로운 관측값이 도착했습니다."}</p>}
    </div>
  );
}

export function DraftPreview({ events }: { events: RunEvent[] }) {
  const preview = [...events].reverse().find((event) => event.kind === "preview" || event.kind === "insight");
  return (
    <div className="subpanel draft-panel">
      <div className="subpanel-heading"><span className="subpanel-icon amber"><FileText size={14} /></span><div><h3>검토용 초안</h3><p>사람이 확인한 뒤에만 사용</p></div></div>
      <div className="draft-copy">{preview?.message || (preview?.payload.text as string | undefined) || "실행 결과가 도착하면 검토용 초안이 여기에 표시됩니다."}</div>
      <button type="button" className="text-button" disabled={!preview}>원본 보기 <span aria-hidden="true">↗</span></button>
    </div>
  );
}
