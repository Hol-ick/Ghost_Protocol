"""Ghost Protocol - Textual TUI Application (Refined v0.3).

비동기 통신 흐름 요약:
  ┌──────────┐     log callback      ┌──────────┐
  │ Scraper  │ ──────────────────────→│  RichLog │  실시간 로그
  │ (worker) │     progress callback  │          │
  │          │ ──────────────────────→│ Progress │  진행률 바
  └──────────┘                        └──────────┘
       │  CrawlerBlockedError 발생
       ▼
  ┌──────────────────┐
  │ Circuit Breaker  │  10초 카운트다운 → 상태바 RED 점멸
  │ (scraper 내부)   │  → UA 교체 → 동일 인덱스 재시도
  └──────────────────┘
       │  매 글 수집 시
       ▼
  ┌──────────────────┐
  │  Bot Radar       │  IP 빈도 + 키워드 → [🤖] 태그 로그
  │  (scraper 내부)  │
  └──────────────────┘

  set_interval(1초) → Dashboard 통계 위젯 갱신 (posts/ratio/RPS)
"""

import os
from datetime import datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from . import database
from .scraper import GalleryScraper

# ══════════════════════════════════════════════
# CSS Theme: Cyberpunk / Matrix (Battle-Ready)
# ══════════════════════════════════════════════
CSS = """
Screen {
    background: #0a0a0a;
}

Header {
    background: #0d0d0d;
    color: #00ff41;
    text-style: bold;
}

Footer {
    background: #0d0d0d;
    color: #00ff41;
}

/* ── Layout ── */
#app-grid {
    layout: horizontal;
    height: 100%;
}

#sidebar {
    width: 34;
    min-width: 30;
    background: #0d1117;
    border-right: thick #00ff41 30%;
    padding: 1 2;
    overflow-y: auto;
}

#main-area {
    width: 1fr;
}

/* ── Sidebar elements ── */
.sidebar-title {
    color: #00ff41;
    text-style: bold;
    text-align: center;
    padding: 1 0;
}

.field-label {
    color: #00cc33;
    margin-top: 1;
    text-style: bold;
}

.section-divider {
    color: #00ff41 30%;
    margin-top: 1;
}

Input {
    background: #111a11;
    color: #00ff41;
    border: tall #00ff41 30%;
    margin-bottom: 1;
}

Input:focus {
    border: tall #00ff41;
}

Button {
    width: 100%;
    margin-top: 1;
}

#btn-start {
    background: #003300;
    color: #00ff41;
    border: tall #00ff41;
}
#btn-start:hover {
    background: #005500;
}

#btn-stop {
    background: #330000;
    color: #ff4444;
    border: tall #ff4444;
}
#btn-stop:hover {
    background: #550000;
}

#btn-export {
    background: #1a1a00;
    color: #ffcc00;
    border: tall #ffcc00;
}
#btn-export:hover {
    background: #333300;
}

/* ── Headless Toggle (Module 3) ── */
#headless-row {
    height: 3;
    margin-top: 1;
}

#headless-row Label {
    color: #00cc33;
    padding: 0 1;
}

Switch {
    background: #1a1a1a;
}

Switch.-on > .switch--slider {
    color: #00ff41;
}

/* ── Dashboard Stats Panel (Module 4) ── */
#dashboard-panel {
    margin-top: 1;
    padding: 1;
    background: #0a100a;
    border: tall #00ff41 30%;
    height: auto;
}

.dash-title {
    color: #00ff41;
    text-style: bold;
    text-align: center;
}

.dash-row {
    height: 1;
    margin-top: 0;
}

.dash-key {
    color: #00cc33;
    width: 1fr;
}

.dash-val {
    color: #00ff41;
    text-style: bold;
    width: auto;
    text-align: right;
}

#ratio-bar {
    margin-top: 0;
}

#ratio-bar Bar {
    color: #d600ff;
    background: #1a1a1a;
}

#ratio-bar PercentageStatus {
    color: #d600ff;
}

/* ── Main Area ── */
#status-box {
    height: 3;
    background: #0d1117;
    color: #00ff41;
    padding: 0 1;
    border-bottom: hkey #00ff41 30%;
}

#status-label {
    color: #00cc33;
}

/* Circuit Breaker: alert class → red blink */
#status-label.alert {
    color: #ff0055;
    text-style: bold blink;
}

#progress-bar {
    margin: 0 1;
}

ProgressBar Bar {
    color: #00ff41;
    background: #1a1a1a;
}

ProgressBar PercentageStatus {
    color: #00ff41;
}

RichLog {
    background: #0a0f0a;
    color: #00dd33;
    border: tall #00ff41 20%;
    scrollbar-color: #00ff41;
    scrollbar-color-hover: #00ff88;
    scrollbar-background: #111;
}

TabbedContent {
    background: #0a0a0a;
}

ContentSwitcher {
    background: #0a0a0a;
}

TabPane {
    background: #0a0a0a;
    padding: 0;
}

Tabs {
    background: #0d1117;
}

Tab {
    color: #00cc33;
    background: #0d1117;
}

Tab.-active {
    color: #00ff41;
    background: #001a00;
    text-style: bold;
}

DataTable {
    background: #0a0a0a;
    color: #00dd33;
    scrollbar-color: #00ff41;
    scrollbar-color-hover: #00ff88;
}

DataTable > .datatable--header {
    background: #0d1117;
    color: #00ff41;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #003300;
    color: #00ff41;
}

#stats-panel {
    height: 3;
    background: #0d1117;
    color: #00ff41;
    padding: 0 2;
    border-top: hkey #00ff41 30%;
}
"""

BANNER = r"""
  ╔══════════════════════════════╗
  ║   [bright_green]G H O S T[/]                  ║
  ║       [bright_green]P R O T O C O L[/]        ║
  ║                              ║
  ║  [dim green]Dead Internet Theory[/]         ║
  ║  [dim green]Analysis Tool v0.3[/]           ║
  ╚══════════════════════════════╝
"""


class GhostProtocolApp(App):
    TITLE = "GHOST PROTOCOL"
    SUB_TITLE = "DC Inside Opinion Analyzer"
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+s", "start_scrape", "Start", show=True),
        Binding("ctrl+x", "stop_scrape", "Stop", show=True),
        Binding("ctrl+e", "export_csv", "Export", show=True),
    ]

    def __init__(self):
        super().__init__()
        self._scraper: GalleryScraper | None = None
        self._is_scraping = False
        self._stats_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="app-grid"):
            # ══════════════════════════════
            # SIDEBAR
            # ══════════════════════════════
            with VerticalScroll(id="sidebar"):
                yield Static(BANNER, classes="sidebar-title", markup=True)

                yield Label("GALLERY ID", classes="field-label")
                yield Input(placeholder="예: stockus", id="input-gallery")
                yield Label("PAGES", classes="field-label")
                yield Input(placeholder="1", id="input-pages", type="integer")

                # ── Module 3: Headless Toggle ──
                yield Static("─" * 28, classes="section-divider")
                with Horizontal(id="headless-row"):
                    yield Label("HEADLESS")
                    yield Switch(value=True, id="switch-headless")

                yield Button("▶  INITIATE SCAN", id="btn-start", variant="success")
                yield Button("■  ABORT", id="btn-stop", variant="error")
                yield Button("⬇  EXPORT CSV", id="btn-export", variant="warning")

                # ── Module 4: Dashboard Stats ──
                yield Static("─" * 28, classes="section-divider")
                with Vertical(id="dashboard-panel"):
                    yield Static("[ DASHBOARD ]", classes="dash-title")

                    with Horizontal(classes="dash-row"):
                        yield Label("Total Posts:", classes="dash-key")
                        yield Label("0", id="dash-posts", classes="dash-val")

                    with Horizontal(classes="dash-row"):
                        yield Label("Fixed/Anon:", classes="dash-key")
                        yield Label("0 / 0", id="dash-ratio-text", classes="dash-val")

                    yield Label("Bot Ratio (Anon%):", classes="dash-key")
                    yield ProgressBar(
                        total=100, show_eta=False, id="ratio-bar"
                    )

                    with Horizontal(classes="dash-row"):
                        yield Label("Bot Suspects:", classes="dash-key")
                        yield Label("0", id="dash-bots", classes="dash-val")

                    with Horizontal(classes="dash-row"):
                        yield Label("RPS:", classes="dash-key")
                        yield Label("0.00", id="dash-rps", classes="dash-val")

            # ══════════════════════════════
            # MAIN AREA
            # ══════════════════════════════
            with Vertical(id="main-area"):
                with Horizontal(id="status-box"):
                    yield Label("STATUS: IDLE", id="status-label")
                yield ProgressBar(total=100, show_eta=False, id="progress-bar")
                with TabbedContent():
                    with TabPane("LIVE LOG", id="tab-log"):
                        yield RichLog(
                            highlight=True,
                            markup=True,
                            wrap=True,
                            id="log",
                        )
                    with TabPane("POSTS", id="tab-posts"):
                        yield DataTable(id="table-posts")
                    with TabPane("COMMENTS", id="tab-comments"):
                        yield DataTable(id="table-comments")
                with Horizontal(id="stats-panel"):
                    yield Label("POSTS: 0 | COMMENTS: 0", id="stats-label")
        yield Footer()

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────
    def on_mount(self) -> None:
        database.init_db()
        log_widget = self.query_one("#log", RichLog)
        log_widget.write("[bold bright_green]> GHOST PROTOCOL v0.3 INITIALIZED[/]")
        log_widget.write("[dim green]> Patches: Non-blocking CB | Stream Save | Time-Aware Bot Radar[/]")
        log_widget.write("[dim green]> Awaiting target designation...[/]")

        # Setup data tables
        posts_table = self.query_one("#table-posts", DataTable)
        posts_table.add_columns(
            "ID", "제목", "작성자", "타입", "IP", "조회", "추천", "작성일"
        )

        comments_table = self.query_one("#table-comments", DataTable)
        comments_table.add_columns(
            "ID", "글번호", "작성자", "내용", "대댓글", "작성일"
        )

        # Module 4: 1초 간격 통계 갱신 타이머
        self._stats_timer = self.set_interval(1.0, self._refresh_dashboard)

    # ──────────────────────────────────────────
    # Log / Progress / Status helpers
    # ──────────────────────────────────────────
    async def _log(self, message: str) -> None:
        log_widget = self.query_one("#log", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_widget.write(f"[dim]{timestamp}[/] {message}")

    async def _update_progress(self, current: int, total: int) -> None:
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.update(total=total, progress=current)

    def _update_status(self, text: str, alert: bool = False) -> None:
        """상태바 업데이트. alert=True면 붉은색 점멸 (Circuit Breaker 시각 피드백)."""
        label = self.query_one("#status-label", Label)
        label.update(f"STATUS: {text}")
        if alert:
            label.add_class("alert")
        else:
            label.remove_class("alert")

    async def _status_callback(self, text: str, is_alert: bool) -> None:
        """[Patch 1] scraper의 Circuit Breaker가 호출하는 상태 콜백.

        쿨다운 중 매초 호출되어 UI 상태바를 실시간 업데이트.
        await asyncio.sleep(1) 사이사이에 호출되므로 UI는 멈추지 않음.
        """
        self._update_status(text, alert=is_alert)

    # ──────────────────────────────────────────
    # Module 4: Dashboard 실시간 갱신
    # ──────────────────────────────────────────
    def _refresh_dashboard(self) -> None:
        """set_interval(1초)에 의해 호출. scraper의 통계를 읽어 위젯 갱신."""
        if not self._scraper:
            return

        s = self._scraper

        # Total posts
        dash_posts = self.query_one("#dash-posts", Label)
        dash_posts.update(str(s.stats_posts_scraped))

        # Fixed / Anon ratio
        dash_ratio_text = self.query_one("#dash-ratio-text", Label)
        dash_ratio_text.update(f"{s.stats_fixed_nick} / {s.stats_anon_nick}")

        # Anon % progress bar (= bot suspicion ratio)
        ratio_bar = self.query_one("#ratio-bar", ProgressBar)
        total_authors = s.stats_fixed_nick + s.stats_anon_nick
        if total_authors > 0:
            anon_pct = int((s.stats_anon_nick / total_authors) * 100)
        else:
            anon_pct = 0
        ratio_bar.update(total=100, progress=anon_pct)

        # Bot suspects
        dash_bots = self.query_one("#dash-bots", Label)
        dash_bots.update(str(s.stats_bot_suspects))

        # RPS
        dash_rps = self.query_one("#dash-rps", Label)
        dash_rps.update(f"{s.get_rps():.2f}")

    # ──────────────────────────────────────────
    # Data tables refresh
    # ──────────────────────────────────────────
    def _refresh_tables(self, gallery_id: str) -> None:
        posts_table = self.query_one("#table-posts", DataTable)
        posts_table.clear()
        posts = database.get_all_posts(gallery_id)
        for p in posts:
            posts_table.add_row(
                str(p["post_id"]),
                (p["title"] or "")[:40],
                p["author"] or "",
                p["author_type"] or "",
                p["ip_hash"] or "",
                str(p["views"]),
                str(p["recommends"]),
                p["created_at"] or "",
            )

        comments_table = self.query_one("#table-comments", DataTable)
        comments_table.clear()
        comments = database.get_all_comments(gallery_id)
        for c in comments:
            comments_table.add_row(
                str(c["comment_id"]),
                str(c["post_id"]),
                c["author"] or "",
                (c["content"] or "")[:50],
                "Y" if c["is_reply"] else "N",
                c["created_at"] or "",
            )

        # Bottom stats
        pc = database.get_post_count(gallery_id)
        cc = database.get_comment_count(gallery_id)
        stats = self.query_one("#stats-label", Label)
        stats.update(f"POSTS: {pc} | COMMENTS: {cc}")

    # ──────────────────────────────────────────
    # Button handlers
    # ──────────────────────────────────────────
    @on(Button.Pressed, "#btn-start")
    def handle_start(self) -> None:
        self.action_start_scrape()

    @on(Button.Pressed, "#btn-stop")
    def handle_stop(self) -> None:
        self.action_stop_scrape()

    @on(Button.Pressed, "#btn-export")
    def handle_export(self) -> None:
        self.action_export_csv()

    # ──────────────────────────────────────────
    # Scrape actions
    # ──────────────────────────────────────────
    def action_start_scrape(self) -> None:
        if self._is_scraping:
            return
        gallery_id = self.query_one("#input-gallery", Input).value.strip()
        pages_str = self.query_one("#input-pages", Input).value.strip()

        if not gallery_id:
            self.call_later(self._log, "[bold red]> ERROR: Gallery ID required[/]")
            return

        num_pages = int(pages_str) if pages_str.isdigit() and int(pages_str) > 0 else 1

        # Module 3: read headless switch before launch
        headless = self.query_one("#switch-headless", Switch).value

        self._run_scrape(gallery_id, num_pages, headless)

    @work(exclusive=True, thread=False)
    async def _run_scrape(
        self, gallery_id: str, num_pages: int, headless: bool
    ) -> None:
        """Background worker: scraper를 실행하고 UI를 실시간 업데이트.

        흐름:
          1. GalleryScraper(headless=...) 생성
          2. run_full_scrape() 호출 — 내부에서 Circuit Breaker + Bot Radar 작동
          3. log/progress callback이 UI를 갱신
          4. set_interval이 Dashboard를 1초마다 갱신
          5. 완료 시 DataTable 리프레시
        """
        self._is_scraping = True
        self._scraper = GalleryScraper(headless=headless)
        self._update_status("SCANNING...", alert=False)

        mode_str = "HEADLESS" if headless else "VISIBLE BROWSER"
        await self._log(f"[bold bright_green]> TARGET ACQUIRED: {gallery_id}[/]")
        await self._log(f"[green]> Mode: {mode_str} | Scanning {num_pages} page(s)...[/]")

        try:
            total = await self._scraper.run_full_scrape(
                gallery_id=gallery_id,
                num_pages=num_pages,
                log=self._log,
                progress=self._update_progress,
                status_cb=self._status_callback,  # [Patch 1] 쿨다운 상태 콜백
            )
            self._refresh_tables(gallery_id)
            await self._log(
                f"[bold bright_green]> MISSION COMPLETE: {total} posts secured[/]"
            )
            self._update_status("COMPLETE", alert=False)
        except Exception as e:
            await self._log(f"[bold red]> CRITICAL ERROR: {e}[/]")
            self._update_status("ERROR", alert=True)
        finally:
            self._is_scraping = False

    def action_stop_scrape(self) -> None:
        if self._is_scraping and self._scraper:
            self._scraper.request_stop()
            self._update_status("ABORTING...", alert=True)
            self.call_later(self._log, "[bold yellow]> ABORT SIGNAL SENT[/]")

    def action_export_csv(self) -> None:
        gallery_id = self.query_one("#input-gallery", Input).value.strip()
        if not gallery_id:
            self.call_later(self._log, "[bold red]> ERROR: Gallery ID required for export[/]")
            return

        from .config import DATA_DIR

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        posts_path = os.path.join(DATA_DIR, f"{gallery_id}_posts_{ts}.csv")
        comments_path = os.path.join(DATA_DIR, f"{gallery_id}_comments_{ts}.csv")

        pc = database.export_posts_csv(gallery_id, posts_path)
        cc = database.export_comments_csv(gallery_id, comments_path)

        self.call_later(
            self._log,
            f"[bold bright_green]> EXPORTED: {pc} posts, {cc} comments[/]",
        )
        self.call_later(
            self._log,
            f"[dim green]> Files saved to {DATA_DIR}[/]",
        )
