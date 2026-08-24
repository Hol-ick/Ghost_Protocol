import {
  type EventPage,
  type HealthSnapshot,
  type RunEvent,
  type RunSnapshot,
  type RunSpec,
  normalizeRunEvent,
  normalizeRunSnapshot,
} from "../types";
import { DEFAULT_CONTROL_PLANE_ORIGIN } from "./runtime";

export class StudioApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "StudioApiError";
    this.status = status;
  }
}

type RequestInitWithBody = Omit<RequestInit, "body"> & { body?: unknown };

/** The browser client intentionally has no API-key or credential parameter. */
function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === "string" && configured.trim()) return configured.replace(/\/$/, "");
  return import.meta.env.PROD ? DEFAULT_CONTROL_PLANE_ORIGIN : "";
}

async function request<T>(path: string, init: RequestInitWithBody = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    headers,
  });
  if (!response.ok) {
    let detail = `Local control plane returned ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string; message?: string };
      detail = body.detail ?? body.message ?? detail;
    } catch {
      // Keep the status-derived message when the server response is not JSON.
    }
    throw new StudioApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export async function getHealth(): Promise<HealthSnapshot> {
  const body = await request<Record<string, unknown>>("/health");
  return {
    ok: body.ok === true || body.status === "ok" || body.healthy === true,
    worker: typeof body.worker === "string" ? body.worker : undefined,
    version: typeof body.version === "string" ? body.version : undefined,
    activeRuns: typeof body.active_runs === "number" ? body.active_runs : undefined,
    capabilities: Array.isArray(body.capabilities)
      ? body.capabilities.filter((item): item is string => typeof item === "string")
      : undefined,
  };
}

export async function startRun(spec: RunSpec): Promise<RunSnapshot> {
  const body = await request<Record<string, unknown>>("/v1/runs", {
    method: "POST",
    body: { mode: spec.mode, params: spec.params },
  });
  return normalizeRunSnapshot(body);
}

export async function getRuns(): Promise<RunSnapshot[]> {
  const body = await request<unknown>("/v1/runs");
  const values = Array.isArray(body)
    ? body
    : typeof body === "object" && body !== null && Array.isArray((body as { runs?: unknown[] }).runs)
      ? (body as { runs: unknown[] }).runs
      : [];
  return values.filter(isRecord).map(normalizeRunSnapshot);
}

export async function getRun(runId: string): Promise<RunSnapshot> {
  return normalizeRunSnapshot(await request<Record<string, unknown>>(`/v1/runs/${encodeURIComponent(runId)}`));
}

export async function getEvents(runId: string, after = 0, limit = 200): Promise<EventPage> {
  const body = await request<unknown>(
    `/v1/runs/${encodeURIComponent(runId)}/events?after=${Math.max(0, after)}&limit=${Math.min(200, Math.max(1, limit))}`,
  );
  const values =
    Array.isArray(body) ? body : typeof body === "object" && body !== null && Array.isArray((body as { events?: unknown[] }).events) ? (body as { events: unknown[] }).events : [];
  const events = values.filter(isRecord).map((event) => normalizeRunEvent({ ...event, run_id: event.run_id ?? runId }));
  const record = isRecord(body) ? body : {};
  return {
    events,
    nextSequence: typeof record.next_sequence === "number" ? record.next_sequence : events.at(-1)?.sequence,
    hasMore: record.has_more === true,
  };
}

export async function stopRun(runId: string): Promise<RunSnapshot> {
  return normalizeRunSnapshot(
    await request<Record<string, unknown>>(`/v1/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type { EventPage, HealthSnapshot, RunEvent, RunSnapshot, RunSpec };
