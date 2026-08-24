import { Play, Square } from "lucide-react";
import type { RunMode, RunSnapshot } from "../../types";

interface RunControlPanelProps {
  connected: boolean;
  mode: RunMode;
  onModeChange: (mode: RunMode) => void;
  onStart: () => void;
  onStop: () => void;
  run?: RunSnapshot;
  busy: boolean;
}

const modeCopy: Record<RunMode, { title: string; detail: string }> = {
  sample: { title: "소스 샘플", detail: "작은 범위로 신호를 확인합니다" },
  rehearsal: { title: "리허설", detail: "비용 없는 실행 흐름을 점검합니다" },
  intel: { title: "인텔리전스", detail: "로컬 워커에서 분석을 실행합니다" },
};

export function RunControlPanel({ connected, mode, onModeChange, onStart, onStop, run, busy }: RunControlPanelProps) {
  const active = run && ["queued", "running", "stopping"].includes(run.state);
  return (
    <section className="panel run-control" aria-labelledby="run-control-title">
      <div className="panel-kicker">CONTROL DECK <span>01</span></div>
      <div className="panel-heading">
        <div>
          <h2 id="run-control-title">Run Control</h2>
          <p>로컬 워커에 다음 작업을 전달합니다.</p>
        </div>
        <span className="local-only-label">LOCAL ONLY</span>
      </div>
      <fieldset className="mode-list" disabled={Boolean(active) || busy}>
        <legend>실행 모드</legend>
        {(Object.keys(modeCopy) as RunMode[]).map((item) => (
          <label key={item} className={`mode-option ${mode === item ? "selected" : ""}`}>
            <input type="radio" name="run-mode" value={item} checked={mode === item} onChange={() => onModeChange(item)} />
            <span className="radio-mark" aria-hidden="true" />
            <span className="mode-text"><strong>{modeCopy[item].title}</strong><small>{modeCopy[item].detail}</small></span>
            <span className="mode-code">{item}</span>
          </label>
        ))}
      </fieldset>
      <div className="control-actions">
        <button type="button" className="primary-button" onClick={onStart} disabled={!connected || Boolean(active) || busy}>
          <Play size={16} fill="currentColor" aria-hidden="true" /> {busy ? "준비 중" : "시작"}
        </button>
        <button type="button" className="danger-button" onClick={onStop} disabled={!run || !active || busy}>
          <Square size={15} fill="currentColor" aria-hidden="true" /> 중단
        </button>
      </div>
      <p className="control-hint"><span className="hint-dot" /> 외부 게시·자동 전송은 이 화면에 연결되지 않습니다.</p>
    </section>
  );
}
