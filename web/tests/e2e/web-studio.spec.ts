import { expect, test, type Page, type Route } from "@playwright/test";

type MockRun = {
  run_id: string;
  mode: string;
  state: string;
  sequence: number;
  progress: number;
  total: number;
  headline: string;
  started_at: string;
};

function mockControlPlane(page: Page) {
  const state: { run?: MockRun; stopRequested: boolean } = { stopRequested: false };
  const events = [
    { sequence: 1, run_id: "run-fixture-001", kind: "started", timestamp: "2026-08-24T12:00:01.000Z", message: "로컬 워커가 시작되었습니다.", payload: {} },
    { sequence: 2, run_id: "run-fixture-001", kind: "progress", timestamp: "2026-08-24T12:00:02.000Z", message: "소스 1개를 읽었습니다.", payload: { wave: 1, total: 2 } },
    { sequence: 3, run_id: "run-fixture-001", kind: "insight", timestamp: "2026-08-24T12:00:03.000Z", message: "반응 신호 2건을 검토 대기열에 넣었습니다.", payload: { signal_count: 2 } },
  ];
  const newRun = (mode = "sample"): MockRun => ({ run_id: "run-fixture-001", mode, state: "running", sequence: 3, progress: 50, total: 2, headline: "Fixture signal sweep", started_at: "2026-08-24T12:00:00.000Z" });

  return page.route("**/*", async (route: Route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, worker: "local-fixture", capabilities: ["sample", "rehearsal"] }) });
      return;
    }
    if (url.pathname === "/v1/runs" && route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: state.run ? [state.run] : [] }) });
      return;
    }
    if (url.pathname === "/v1/runs" && route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { mode?: string };
      state.run = newRun(body.mode ?? "sample");
      state.stopRequested = false;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(state.run) });
      return;
    }
    if (url.pathname === "/v1/runs/run-fixture-001" && route.request().method() === "GET") {
      if (state.run && state.stopRequested) state.run = { ...state.run, state: "stopped", sequence: 4, progress: 50 };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state.run ?? newRun()) });
      return;
    }
    if (url.pathname === "/v1/runs/run-fixture-001/events") {
      const after = Number(url.searchParams.get("after") ?? 0);
      const values = after >= 3 ? [] : events.filter((event) => event.sequence > after);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ events: values, next_sequence: values.at(-1)?.sequence ?? after }) });
      return;
    }
    if (url.pathname === "/v1/runs/run-fixture-001/stop" && route.request().method() === "POST") {
      state.stopRequested = true;
      state.run = { ...(state.run ?? newRun()), state: "stopping", sequence: 4 };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state.run) });
      return;
    }
    await route.continue();
  });
}

test.beforeEach(async ({ page }) => {
  await mockControlPlane(page);
});

test("shows run and stop controls after worker becomes available", async ({ page }) => {
  await page.goto("/studio");
  await expect(page.getByText("LOCAL SIGNAL ROOM")).toBeVisible();
  await expect(page.getByRole("status")).toContainText("로컬 워커 연결됨");
  await expect(page.getByRole("button", { name: "시작" })).toBeEnabled();
});

test("starts a fixture run, deduplicates the cursor events, and stops it", async ({ page }) => {
  await page.goto("/studio");
  await page.getByRole("button", { name: "시작" }).click();
  await expect(page.getByText("Fixture signal sweep")).toBeVisible();
  await expect(page.getByText("반응 신호 2건을 검토 대기열에 넣었습니다.").first()).toBeVisible();
  await expect(page.getByText("3 events")).toBeVisible();
  await expect(page.locator('[aria-label="실행 이벤트 타임라인"] .timeline-item')).toHaveCount(3);
  await page.getByRole("button", { name: "중단" }).click();
  await expect(page.getByText("중단 중")).toBeVisible();
  await expect(page.getByText("중단됨")).toBeVisible({ timeout: 3_000 });
  await expect(page.getByRole("button", { name: "중단" })).toBeDisabled();
});

test("keeps the layout usable on a narrow viewport and exposes keyboard focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/studio");
  await expect(page.locator(".studio-grid")).toHaveCSS("display", "flex");
  await page.getByRole("button", { name: "시작" }).focus();
  await expect(page.getByRole("button", { name: "시작" })).toBeFocused();
  await expect(page.getByText("외부 게시·자동 전송은 이 화면에 연결되지 않습니다.")).toBeVisible();
});
