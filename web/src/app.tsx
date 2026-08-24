import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Clock3, Command, RefreshCw, WifiOff } from "lucide-react";
import { getEvents, getHealth, getRun, getRuns, startRun, stopRun, StudioApiError } from "./api/client";
import type { ConnectionStatus } from "./features/connection/ConnectionBadge";
import { ConnectionBadge } from "./features/connection/ConnectionBadge";
import { InsightPanel, DraftPreview } from "./features/insights/InsightPanel";
import { StudioEmptyState } from "./features/empty/StudioEmptyState";
import { ResourceGuard } from "./features/ops/ResourceGuard";
import { ReviewQueue } from "./features/review/ReviewQueue";
import { RunControlPanel } from "./features/run-control/RunControlPanel";
import { RunTimeline } from "./features/run-monitor/RunTimeline";
import type { RunEvent, RunMode, RunSnapshot } from "./types";

const ACTIVE_STATES = new Set(["queued", "running", "stopping"]);

export function App() {
  const [connection, setConnection] = useState<ConnectionStatus>("checking");
  const [run, setRun] = useState<RunSnapshot>();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [mode, setMode] = useState<RunMode>("sample");
  const [busy, setBusy] = useState(false);
  const [lastError, setLastError] = useState<string>();
  const cursorRef = useRef(0);

  const markDisconnected = useCallback((error: unknown) => {
    setConnection("disconnected");
    if (error instanceof StudioApiError && error.status === 409) setLastError("이미 실행 중인 Run이 있습니다.");
    else if (error instanceof Error) setLastError(error.message);
    else setLastError("로컬 제어면에 연결할 수 없습니다.");
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const health = await getHealth();
      if (!health.ok) throw new Error("워커가 준비되지 않았습니다.");
      setConnection("connected");
      setLastError(undefined);
      return true;
    } catch (error) {
      markDisconnected(error);
      return false;
    }
  }, [markDisconnected]);

  const refreshRuns = useCallback(async () => {
    try {
      const runs = await getRuns();
      const latest = runs[0];
      if (latest) {
        setRun(latest);
        cursorRef.current = latest.sequence;
      }
      return latest;
    } catch (error) {
      markDisconnected(error);
      return undefined;
    }
  }, [markDisconnected]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const connected = await refreshHealth();
      if (connected && alive) await refreshRuns();
    })();
    const timer = window.setInterval(() => { void refreshHealth(); }, 8_000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [refreshHealth, refreshRuns]);

  const pollRun = useCallback(async () => {
    const current = run;
    if (!current) return;
    try {
      const [snapshot, page] = await Promise.all([getRun(current.runId), getEvents(current.runId, cursorRef.current)]);
      setConnection("connected");
      setLastError(undefined);
      setRun(snapshot);
      if (page.events.length) {
        setEvents((existing) => mergeEvents(existing, page.events));
        cursorRef.current = Math.max(cursorRef.current, ...page.events.map((event) => event.sequence));
      }
      if (snapshot.sequence > cursorRef.current) cursorRef.current = snapshot.sequence;
    } catch (error) {
      markDisconnected(error);
    }
  }, [markDisconnected, run]);

  useEffect(() => {
    if (!run) return;
    void pollRun();
    const timer = window.setInterval(() => { void pollRun(); }, 1_000);
    return () => window.clearInterval(timer);
  }, [pollRun, run?.runId]); // Reconnect to the same run without resetting its cursor.

  const handleStart = async () => {
    setBusy(true);
    setLastError(undefined);
    try {
      const next = await startRun({ mode, params: { pages: 1, use_llm: false } });
      setConnection("connected");
      setRun(next);
      setEvents([]);
      cursorRef.current = 0;
      await pollRunFor(next.runId);
    } catch (error) {
      markDisconnected(error);
    } finally {
      setBusy(false);
    }
  };

  const pollRunFor = async (runId: string) => {
    try {
      const page = await getEvents(runId, 0);
      if (page.events.length) {
        setEvents(mergeEvents([], page.events));
        cursorRef.current = Math.max(...page.events.map((event) => event.sequence));
      }
    } catch (error) {
      markDisconnected(error);
    }
  };

  const handleStop = async () => {
    if (!run) return;
    setBusy(true);
    try {
      const snapshot = await stopRun(run.runId);
      setRun(snapshot);
      setConnection("connected");
    } catch (error) {
      markDisconnected(error);
    } finally {
      setBusy(false);
    }
  };

  const handleReconnect = async () => {
    setConnection("checking");
    const connected = await refreshHealth();
    if (connected) await refreshRuns();
  };

  const effectiveRun = useMemo(() => {
    if (!run || connection !== "disconnected") return run;
    return { ...run, state: "disconnected" as const };
  }, [connection, run]);
  const active = Boolean(run && ACTIVE_STATES.has(run.state));

  return (
    <div className="studio-shell">
      <header className="topbar">
        <a className="brand" href="/studio" aria-label="Local Signal Room 홈"><span className="brand-mark"><span /></span><span><strong>LOCAL SIGNAL ROOM</strong><small>GHOST PROTOCOL / WEB STUDIO</small></span></a>
        <div className="topbar-meta"><div className="clock"><Clock3 size={14} aria-hidden="true" /><span>LOCAL SESSION</span></div><ConnectionBadge status={connection} onReconnect={handleReconnect} /></div>
      </header>
      <main className="studio-main">
        <div className="intro-row"><div><p className="eyebrow"><Activity size={13} aria-hidden="true" /> OBSERVATION DECK <span>/</span> {active ? "LIVE RUN" : "STANDBY"}</p><h1>신호를 읽고, <em>판단을 남깁니다.</em></h1></div><div className="intro-note"><Command size={15} aria-hidden="true" /><span>브라우저는 로컬 워커를 조작하는<br />가벼운 창구로만 동작합니다.</span></div></div>
        {lastError && <div className="notice error-notice" role="alert"><WifiOff size={15} aria-hidden="true" /><span>{lastError}</span><button type="button" className="notice-action" onClick={handleReconnect}><RefreshCw size={13} /> 재시도</button></div>}
        <div className="studio-grid">
          <RunControlPanel connected={connection === "connected"} mode={mode} onModeChange={setMode} onStart={handleStart} onStop={handleStop} run={run} busy={busy} />
          {effectiveRun ? <RunTimeline run={effectiveRun} events={events} /> : <section className="panel signal-canvas"><StudioEmptyState /></section>}
          <aside className="event-rail"><div className="rail-heading"><div><div className="panel-kicker">EVENT RAIL <span>03</span></div><h2>Operational trace</h2></div><span className="rail-live"><i /> LIVE</span></div><InsightPanel run={effectiveRun} events={events} /><DraftPreview events={events} /><ReviewQueue events={events} /><ResourceGuard connected={connection === "connected"} /></aside>
        </div>
      </main>
      <footer className="footer"><span>GHOST PROTOCOL</span><span className="footer-separator" /><span>LOCAL WORKER CONTROL PLANE</span><span className="footer-spacer" /><span className="footer-safe">NO AUTO-PUBLISH</span></footer>
    </div>
  );
}

function mergeEvents(existing: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const bySequence = new Map(existing.map((event) => [event.sequence, event]));
  for (const event of incoming) bySequence.set(event.sequence, event);
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}
