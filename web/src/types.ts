export const RUN_STATES = [
  "idle",
  "queued",
  "running",
  "stopping",
  "succeeded",
  "failed",
  "stopped",
  "disconnected",
] as const;

export type RunState = (typeof RUN_STATES)[number];
export type RunMode = "sample" | "rehearsal" | "intel";

export interface RunSpec {
  mode: RunMode;
  params: Record<string, unknown>;
}

export interface RunSnapshot {
  runId: string;
  mode: RunMode;
  state: RunState;
  sequence: number;
  progress: number;
  total?: number;
  headline?: string;
  startedAt?: string;
  endedAt?: string;
  stopReason?: string;
  error?: string;
  latestEvent?: RunEvent;
}

export type RunEventKind =
  | "started"
  | "progress"
  | "log"
  | "preview"
  | "stat"
  | "insight"
  | "warning"
  | "succeeded"
  | "failed"
  | "stopped"
  | "batch_progress";

export interface RunEvent {
  sequence: number;
  runId: string;
  kind: RunEventKind | string;
  timestamp: string;
  message?: string;
  payload: Record<string, unknown>;
}

export interface HealthSnapshot {
  ok: boolean;
  worker?: string;
  version?: string;
  activeRuns?: number;
  capabilities?: string[];
}

export interface EventPage {
  events: RunEvent[];
  nextSequence?: number;
  hasMore?: boolean;
}

export function normalizeRunSnapshot(input: Record<string, unknown>): RunSnapshot {
  const latest = input.latest_event ?? input.latestEvent;
  const progressRecord = isRecord(input.progress) ? input.progress : {};
  const completed = numberValueOptional(progressRecord.completed ?? progressRecord.current);
  const total = numberValueOptional(input.total ?? progressRecord.total);
  const explicitProgress = numberValueOptional(input.progress);
  const progress = explicitProgress ?? (completed !== undefined && total ? (completed / total) * 100 : 0);
  return {
    runId: String(input.run_id ?? input.runId ?? ""),
    mode: asMode(input.mode),
    state: asState(input.state),
    sequence: numberValue(input.sequence ?? input.last_sequence ?? input.last_event_sequence, 0),
    progress,
    total,
    headline: stringOptional(input.headline ?? input.title ?? progressRecord.headline ?? progressRecord.title),
    startedAt: stringOptional(input.started_at ?? input.startedAt ?? input.created_at),
    endedAt: stringOptional(input.ended_at ?? input.endedAt ?? input.updated_at),
    stopReason: stringOptional(input.stop_reason ?? input.stopReason),
    error: stringOptional(input.error),
    latestEvent: isRecord(latest) ? normalizeRunEvent(latest) : undefined,
  };
}

export function normalizeRunEvent(input: Record<string, unknown>): RunEvent {
  return {
    sequence: numberValue(input.sequence ?? input.seq, 0),
    runId: String(input.run_id ?? input.runId ?? ""),
    kind: String(input.kind ?? input.type ?? "log"),
    timestamp: String(input.timestamp ?? input.created_at ?? new Date().toISOString()),
    message: stringOptional(input.message ?? input.text),
    payload: isRecord(input.payload) ? input.payload : input,
  };
}

function asMode(value: unknown): RunMode {
  return value === "intel" || value === "rehearsal" ? value : "sample";
}

function asState(value: unknown): RunState {
  return RUN_STATES.includes(value as RunState) ? (value as RunState) : "idle";
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function numberValueOptional(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringOptional(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
