import { Check, CircleAlert, CircleStop, LoaderCircle, Radio, Sparkles } from "lucide-react";
import type { RunEvent, RunSnapshot } from "../../types";

interface RunTimelineProps {
  run?: RunSnapshot;
  events: RunEvent[];
}

const eventIcon = (kind: string) => {
  if (kind === "succeeded") return <Check size={13} aria-hidden="true" />;
  if (kind === "failed" || kind === "warning") return <CircleAlert size={13} aria-hidden="true" />;
  if (kind === "stopped") return <CircleStop size={13} aria-hidden="true" />;
  if (kind === "insight" || kind === "preview") return <Sparkles size={13} aria-hidden="true" />;
  return <Radio size={13} aria-hidden="true" />;
};

function eventMessage(event: RunEvent): string {
  if (event.message) return event.message;
  const payload = event.payload;
  if (typeof payload.message === "string") return payload.message;
  if (typeof payload.headline === "string") return payload.headline;
  if (typeof payload.wave === "number" && typeof payload.total === "number") return `웨이브 ${payload.wave} / ${payload.total}`;
  return event.kind.replaceAll("_", " ");
}

export function RunTimeline({ run, events }: RunTimelineProps) {
  const progress = run?.progress ?? 0;
  const state = run?.state ?? "idle";
  return (
    <section className="panel signal-canvas" aria-labelledby="signal-title">
      <div className="canvas-topline">
        <div className="panel-kicker">SIGNAL CANVAS <span>02</span></div>
        <span className={`state-pill state-${state}`}><span className="state-dot" />{stateLabel(state)}</span>
      </div>
      <div className="canvas-title-row">
        <div>
          <h2 id="signal-title">{run ? run.headline || `${run.mode} 실행` : "신호를 기다리는 중"}</h2>
          <p className="run-id">{run ? run.runId : "RUN — — — —"}</p>
        </div>
        <div className="heartbeat" aria-label={state === "running" ? "워커 heartbeat 활성" : "워커 heartbeat 대기"}>
          <span className={`heartbeat-pulse ${state === "running" ? "active" : ""}`} />
          <span>WORKER HEARTBEAT</span>
        </div>
      </div>
      <div className="progress-area" aria-label={`진행률 ${Math.round(progress)}%`}>
        <div className="progress-label"><span>작업 진행</span><strong>{Math.round(progress)}%</strong></div>
        <div className="progress-track"><span style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} /></div>
        <div className="progress-meta"><span>{run?.total ? `${run.total} items` : "대기 중"}</span><span>SEQ {String(run?.sequence ?? 0).padStart(4, "0")}</span></div>
      </div>
      <div className="timeline-heading"><h3>Run timeline</h3><span>{events.length} events</span></div>
      {events.length === 0 ? (
        <div className="timeline-empty"><LoaderCircle size={17} aria-hidden="true" /><span>아직 기록된 이벤트가 없습니다.</span></div>
      ) : (
        <ol className="timeline" aria-label="실행 이벤트 타임라인">
          {events.slice(-12).map((event) => (
            <li key={`${event.runId}-${event.sequence}`} className={`timeline-item event-${event.kind}`}>
              <span className="event-icon">{eventIcon(event.kind)}</span>
              <div className="event-body"><div className="event-line"><strong>{eventMessage(event)}</strong><time>{formatTime(event.timestamp)}</time></div><span className="event-kind">{event.kind} · seq {event.sequence}</span></div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function stateLabel(state: string): string {
  return ({ idle: "대기", queued: "대기열", running: "실행 중", stopping: "중단 중", succeeded: "완료", failed: "실패", stopped: "중단됨", disconnected: "연결 끊김" } as Record<string, string>)[state] ?? state;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "--:--" : date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
