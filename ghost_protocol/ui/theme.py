"""Corporate Trust theme for Ghost Protocol."""

from __future__ import annotations


def launchpad_css() -> str:
    return """
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable.css");
@import url("https://cdn.jsdelivr.net/gh/sunn-us/SUIT/fonts/variable/woff2/SUIT-Variable.css");
@import url("https://fonts.googleapis.com/css2?family=Gowun+Dodum&family=Noto+Sans+KR:wght@500;600;700;800;900&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap");

:root {
    --gp-bg: #F8FAFC;
    --gp-paper: #FFFFFF;
    --gp-sheet: #FFFFFF;
    --gp-ink: #0F172A;
    --gp-soft: #334155;
    --gp-muted: #64748B;
    --gp-line: #E2E8F0;
    --gp-strong-line: #CBD5E1;
    --gp-blue: #4F46E5;
    --gp-violet: #7C3AED;
    --gp-cyan: #06B6D4;
    --gp-green: #10B981;
    --gp-red: #EF4444;
    --gp-amber: #F59E0B;
    --gp-accent: #4F46E5;
    --gp-accent-2: #7C3AED;
    --gp-font: "Pretendard Variable", "SUIT Variable", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    --gp-mono: "SUIT Variable", "Pretendard Variable", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    --gp-shadow: 0 4px 20px -2px rgba(79, 70, 229, 0.10);
    --gp-shadow-hover: 0 10px 25px -5px rgba(79, 70, 229, 0.15), 0 8px 10px -6px rgba(79, 70, 229, 0.10);
    --gp-shadow-strong: 0 18px 44px -14px rgba(79, 70, 229, 0.34);
    --gp-gradient: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
}

html,
body,
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background:
        radial-gradient(circle at 12% 8%, rgba(79, 70, 229, 0.18), transparent 29rem),
        radial-gradient(circle at 88% 4%, rgba(124, 58, 237, 0.20), transparent 30rem),
        radial-gradient(circle at 55% 100%, rgba(6, 182, 212, 0.10), transparent 34rem),
        linear-gradient(180deg, #F8FAFC 0%, #EEF2FF 100%) !important;
    color: var(--gp-ink) !important;
    font-family: var(--gp-font) !important;
}

.stApp::before,
.stApp::after {
    content: "" !important;
    position: fixed !important;
    pointer-events: none !important;
    z-index: 0 !important;
    border-radius: 999px !important;
    filter: blur(54px) !important;
    opacity: 0.46 !important;
}

.stApp::before {
    width: 440px !important;
    height: 440px !important;
    top: 80px !important;
    left: -160px !important;
    background: linear-gradient(135deg, rgba(79, 70, 229, 0.18), rgba(124, 58, 237, 0.12)) !important;
}

.stApp::after {
    width: 520px !important;
    height: 520px !important;
    right: -190px !important;
    bottom: -220px !important;
    background: linear-gradient(135deg, rgba(124, 58, 237, 0.14), rgba(6, 182, 212, 0.11)) !important;
}

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="collapsedControl"],
section[data-testid="stSidebar"] {
    display: none !important;
}

.stMainBlockContainer {
    width: min(1760px, calc(100vw - 24px)) !important;
    max-width: none !important;
    padding: 0.15rem 0 1.5rem !important;
    position: relative !important;
    z-index: 1 !important;
}

.block-container {
    padding-top: 0.2rem !important;
}

* {
    box-sizing: border-box !important;
    transition-duration: 0s !important;
    animation-duration: 0s !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
}

.stApp *,
.stApp button,
.stApp input,
.stApp textarea,
.stApp select {
    font-family: var(--gp-font) !important;
}

.stApp pre,
.stApp code,
.stApp kbd,
.stApp samp,
[data-testid="stCodeBlock"],
[data-testid="stCodeBlock"] *,
[data-testid="stMarkdownContainer"] pre,
[data-testid="stMarkdownContainer"] code {
    font-family: var(--gp-font) !important;
    letter-spacing: -0.02em !important;
}

.minimal-topbar {
    min-height: 30px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 16px !important;
    margin: 0 0 12px !important;
    padding: 0 2px 10px !important;
    border-bottom: 1px solid rgba(148, 163, 184, 0.35) !important;
    color: var(--gp-ink) !important;
    font: 800 0.66rem/1 var(--gp-mono) !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
}

.minimal-topbar-main {
    display: inline-flex !important;
    align-items: center !important;
    gap: 10px !important;
}

.minimal-topbar small {
    color: var(--gp-muted) !important;
    font: 800 0.62rem/1 var(--gp-mono) !important;
    letter-spacing: 0.13em !important;
}

.topbar-dot {
    width: 10px !important;
    height: 10px !important;
    border-radius: 999px !important;
    display: inline-block !important;
    background: var(--gp-gradient) !important;
    box-shadow: 0 0 20px rgba(79, 70, 229, 0.48) !important;
}

.mission-title {
    position: relative !important;
    overflow: hidden !important;
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    margin: 0 0 12px !important;
    padding: 14px 24px 16px !important;
    border: 1px solid rgba(226, 232, 240, 0.92) !important;
    border-radius: 22px !important;
    background:
        radial-gradient(circle at 88% 18%, rgba(124, 58, 237, 0.18), transparent 17rem),
        linear-gradient(135deg, rgba(255,255,255,0.96), rgba(238,242,255,0.88)) !important;
    box-shadow: var(--gp-shadow-strong) !important;
}

.mission-title::after {
    content: "" !important;
    position: absolute !important;
    width: 148px !important;
    height: 148px !important;
    right: 44px !important;
    top: -74px !important;
    border-radius: 28px !important;
    background: linear-gradient(135deg, rgba(79,70,229,0.16), rgba(124,58,237,0.10)) !important;
    transform: rotate(12deg) skewY(-6deg) !important;
}

.mission-title span,
.mission-title b {
    position: relative !important;
    z-index: 1 !important;
}

.mission-title span {
    display: block !important;
    margin-bottom: 6px !important;
    color: var(--gp-blue) !important;
    font: 800 0.66rem/1 var(--gp-mono) !important;
    letter-spacing: 0.2em !important;
}

.mission-title b {
    display: block !important;
    max-width: none !important;
    color: var(--gp-ink) !important;
    font: 800 clamp(2rem, 3.55vw, 4.15rem)/1.02 var(--gp-font) !important;
    letter-spacing: -0.05em !important;
    word-break: keep-all !important;
    text-wrap: balance !important;
}

.mission-title b::first-letter {
    background: var(--gp-gradient) !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    color: transparent !important;
}

[data-testid="stHorizontalBlock"]:has(.stack-panel-marker):has(.active-panel-marker):has(.log-panel-marker) {
    align-items: stretch !important;
    padding: 22px !important;
    border: 1px solid rgba(203, 213, 225, 0.92) !important;
    border-radius: 30px !important;
    background:
        radial-gradient(circle at 48% 110%, rgba(6, 182, 212, 0.10), transparent 28rem),
        radial-gradient(circle at 100% 0%, rgba(124, 58, 237, 0.08), transparent 24rem),
        rgba(255, 255, 255, 0.96) !important;
    box-shadow: var(--gp-shadow-strong) !important;
}

[data-testid="stColumn"]:has(.stage-panel-marker),
[data-testid="stColumn"]:has(.topic-panel-marker),
[data-testid="stColumn"]:has(.run-panel-marker),
[data-testid="stColumn"]:has(.stack-panel-marker),
[data-testid="stColumn"]:has(.active-panel-marker),
[data-testid="stColumn"]:has(.log-panel-marker) {
    min-height: 0 !important;
    padding: 0 16px !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    transition: none !important;
}

[data-testid="stColumn"]:has(.stage-panel-marker):hover,
[data-testid="stColumn"]:has(.topic-panel-marker):hover,
[data-testid="stColumn"]:has(.run-panel-marker):hover,
[data-testid="stColumn"]:has(.stack-panel-marker):hover,
[data-testid="stColumn"]:has(.active-panel-marker):hover,
[data-testid="stColumn"]:has(.log-panel-marker):hover {
    transform: none !important;
    box-shadow: none !important;
    border-color: transparent !important;
}

[data-testid="stColumn"]:has(.active-panel-marker) {
    min-height: clamp(460px, calc(100vh - 250px), 680px) !important;
    align-self: flex-start !important;
}

[data-testid="stColumn"]:has(.log-panel-marker) {
    min-height: clamp(640px, calc(100vh - 120px), 920px) !important;
}

[data-testid="stColumn"]:has(.stack-panel-marker) {
    align-self: flex-start !important;
    padding-left: 0 !important;
    padding-right: 18px !important;
    border-right: 1px solid rgba(226, 232, 240, 0.95) !important;
}

[data-testid="stColumn"]:has(.log-panel-marker) {
    padding-left: 18px !important;
    padding-right: 0 !important;
    border-left: 1px solid rgba(226, 232, 240, 0.95) !important;
}

[data-testid="stColumn"]:has(.active-stage-review) {
    min-height: clamp(520px, calc(100vh - 190px), 820px) !important;
}

[data-testid="stColumn"]:has(.active-stage-read) {
    min-height: 0 !important;
}

[data-testid="stColumn"]:has(.active-stage-intel) {
    min-height: 0 !important;
    align-self: flex-start !important;
}

[data-testid="stColumn"]:has(.active-panel-marker) {
    background: transparent !important;
}

[data-testid="stColumn"]:has(.log-panel-marker) {
    background: transparent !important;
}

[data-testid="stColumn"]:has(.topic-panel-marker) {
    background: transparent !important;
}

[data-testid="stColumn"]:has(.run-panel-marker) {
    background: transparent !important;
}

[data-testid="stColumn"]:has(.stage-panel-marker) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.topic-panel-marker) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.run-panel-marker) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.stack-panel-marker) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.active-panel-marker) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.log-panel-marker) [data-testid="stVerticalBlock"] {
    gap: 0.7rem !important;
}

.panel-heading,
.command-heading {
    display: grid !important;
    grid-template-columns: auto minmax(0, 1fr) !important;
    align-items: center !important;
    gap: 11px !important;
    margin: 0 0 14px !important;
    padding: 0 0 12px !important;
    border-bottom: 1px solid rgba(226, 232, 240, 0.92) !important;
}

.panel-heading span,
.command-heading span {
    display: inline-grid !important;
    place-items: center !important;
    min-width: 32px !important;
    height: 32px !important;
    border-radius: 12px !important;
    background: var(--gp-gradient) !important;
    color: #FFFFFF !important;
    box-shadow: 0 0 20px rgba(79, 70, 229, 0.30) !important;
    font: 800 0.7rem/1 var(--gp-mono) !important;
    letter-spacing: 0.08em !important;
}

.panel-heading b,
.command-heading b {
    color: var(--gp-ink) !important;
    font: 800 1.2rem/1.12 var(--gp-font) !important;
    letter-spacing: -0.035em !important;
}

.process-rail {
    position: static !important;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 8px !important;
    padding: 0 !important;
    margin-bottom: 8px !important;
}

.process-rail p {
    grid-column: 1 / -1 !important;
    margin: 0 0 2px !important;
    color: var(--gp-muted) !important;
    font: 800 0.62rem/1 var(--gp-mono) !important;
    letter-spacing: 0.16em !important;
}

.rail-item {
    display: grid !important;
    grid-template-columns: 28px minmax(0, 1fr) !important;
    align-items: center !important;
    min-height: 38px !important;
    margin: 0 !important;
    padding: 0 10px !important;
    border: 1px solid rgba(226, 232, 240, 0.98) !important;
    border-radius: 13px !important;
    background: #FFFFFF !important;
    box-shadow: none !important;
}

.rail-item span {
    color: var(--gp-blue) !important;
    font: 800 0.68rem/1 var(--gp-mono) !important;
}

.rail-item b {
    color: var(--gp-ink) !important;
    font: 700 0.86rem/1.12 var(--gp-font) !important;
    letter-spacing: -0.02em !important;
}

.stage-summary-list {
    display: grid !important;
    gap: 7px !important;
    margin: 0 0 10px !important;
}

.stage-summary-list.is-minimal {
    margin-top: 8px !important;
}

.stage-summary {
    display: grid !important;
    grid-template-columns: 28px minmax(0, 1fr) !important;
    gap: 2px 7px !important;
    align-items: center !important;
    min-height: 44px !important;
    padding: 8px 10px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    background: #FFFFFF !important;
}

.stage-summary span {
    grid-row: 1 / span 2 !important;
    width: 24px !important;
    height: 24px !important;
    display: grid !important;
    place-items: center !important;
    border-radius: 9px !important;
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
    font: 800 0.62rem/1 var(--gp-mono) !important;
}

.stage-summary b {
    color: var(--gp-ink) !important;
    font: 800 0.8rem/1.1 var(--gp-font) !important;
}

.stage-summary em {
    min-width: 0 !important;
    color: var(--gp-muted) !important;
    font: 600 0.72rem/1.16 var(--gp-font) !important;
    font-style: normal !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

.stage-summary.is-active {
    border-color: #C7D2FE !important;
    background: linear-gradient(135deg, #EEF2FF, #F5F3FF) !important;
}

.stage-summary.is-done span {
    background: #ECFDF5 !important;
    color: var(--gp-green) !important;
}

.compact-artifact,
.focus-note,
.read-digest,
.run-context-card,
.utility-empty {
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: #FFFFFF !important;
    box-shadow: var(--gp-shadow) !important;
}

.run-context-card {
    display: grid !important;
    gap: 13px !important;
    padding: 18px !important;
}

.run-context-card.is-empty {
    min-height: 64px !important;
    align-content: center !important;
    border-style: dashed !important;
    background: rgba(248, 250, 252, 0.72) !important;
    box-shadow: none !important;
}

.run-context-card.is-empty .run-context-kicker {
    color: #94A3B8 !important;
}

.run-context-kicker {
    color: var(--gp-blue) !important;
    font: 800 0.74rem/1.2 var(--gp-font) !important;
    letter-spacing: 0.04em !important;
}

.run-context-card h3 {
    margin: 0 !important;
    color: var(--gp-ink) !important;
    font: 850 1.22rem/1.24 var(--gp-font) !important;
    letter-spacing: -0.015em !important;
    word-break: keep-all !important;
    overflow-wrap: break-word !important;
}

.run-context-grid {
    display: grid !important;
    grid-template-columns: 4.25rem minmax(0, 1fr) !important;
    gap: 9px 12px !important;
    padding: 11px 0 !important;
    border-top: 1px solid var(--gp-line) !important;
    border-bottom: 1px solid var(--gp-line) !important;
}

.run-context-grid span {
    color: var(--gp-muted) !important;
    font: 750 0.78rem/1.35 var(--gp-font) !important;
}

.run-context-grid b {
    min-width: 0 !important;
    color: var(--gp-soft) !important;
    font: 780 0.92rem/1.42 var(--gp-font) !important;
    letter-spacing: -0.005em !important;
    word-break: keep-all !important;
    overflow-wrap: anywhere !important;
    white-space: normal !important;
}

.run-context-card p {
    margin: 0 !important;
    color: var(--gp-ink) !important;
    font: 780 0.98rem/1.58 var(--gp-font) !important;
    letter-spacing: -0.005em !important;
    word-break: keep-all !important;
    overflow-wrap: break-word !important;
}

.run-context-brief {
    border-top: 1px solid var(--gp-line) !important;
    padding-top: 8px !important;
}

.run-context-brief summary {
    cursor: pointer !important;
    list-style: none !important;
    min-height: 36px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 10px !important;
    padding: 0 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    background: #F8FAFC !important;
    color: var(--gp-blue) !important;
    font: 850 0.82rem/1.2 var(--gp-font) !important;
}

.run-context-brief summary::-webkit-details-marker {
    display: none !important;
}

.run-context-brief summary::after {
    content: "펼치기" !important;
    color: var(--gp-muted) !important;
    font: 800 0.72rem/1 var(--gp-font) !important;
}

.run-context-brief[open] summary::after {
    content: "접기" !important;
}

.run-context-brief p {
    max-height: 220px !important;
    overflow: auto !important;
    margin-top: 10px !important;
    padding: 11px 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    background: #FFFFFF !important;
    font: 720 0.9rem/1.72 var(--gp-font) !important;
}

.read-digest {
    display: grid !important;
    gap: 5px !important;
    padding: 13px !important;
}

.read-digest span {
    color: var(--gp-blue) !important;
    font: 900 0.64rem/1 var(--gp-mono) !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
}

.read-digest b {
    color: var(--gp-ink) !important;
    font: 800 1.02rem/1.28 var(--gp-font) !important;
    letter-spacing: -0.015em !important;
    word-break: break-word !important;
}

.read-digest em {
    color: var(--gp-blue) !important;
    font: 800 0.78rem/1.2 var(--gp-font) !important;
    font-style: normal !important;
}

.read-digest p {
    margin: 6px 0 0 !important;
    padding-top: 8px !important;
    border-top: 1px solid var(--gp-line) !important;
    color: var(--gp-ink) !important;
    font: 700 0.9rem/1.62 var(--gp-font) !important;
    letter-spacing: -0.01em !important;
    word-break: keep-all !important;
    overflow-wrap: anywhere !important;
}

.compact-artifact {
    display: grid !important;
    gap: 7px !important;
    margin-top: 10px !important;
    padding: 12px !important;
}

.compact-artifact span,
.focus-note span,
.utility-panel-title span,
.utility-section-title {
    color: var(--gp-blue) !important;
    font: 800 0.66rem/1 var(--gp-mono) !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
}

.compact-artifact b {
    color: var(--gp-ink) !important;
    font: 800 0.92rem/1.45 var(--gp-font) !important;
    word-break: keep-all !important;
}

.compact-artifact em {
    color: var(--gp-muted) !important;
    font: 700 0.74rem/1.25 var(--gp-font) !important;
    font-style: normal !important;
}

.focus-note {
    display: grid !important;
    gap: 12px !important;
    min-height: 210px !important;
    align-content: start !important;
    margin-top: 8px !important;
    padding: 22px !important;
    background:
        radial-gradient(circle at 92% 0%, rgba(79,70,229,0.10), transparent 16rem),
        #FFFFFF !important;
}

.focus-note b {
    max-width: 760px !important;
    color: var(--gp-ink) !important;
    font: 800 clamp(1.35rem, 2.2vw, 2rem)/1.18 var(--gp-font) !important;
    letter-spacing: -0.045em !important;
}

.focus-note p {
    max-width: 720px !important;
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 600 0.98rem/1.58 var(--gp-font) !important;
}

.prompt-snapshot {
    display: grid !important;
    gap: 12px !important;
    margin-top: 12px !important;
}

.prompt-snapshot-block {
    display: grid !important;
    gap: 8px !important;
    padding: 13px 14px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: #FFFFFF !important;
}

.prompt-snapshot-block span {
    color: var(--gp-blue) !important;
    font: 850 0.72rem/1 var(--gp-font) !important;
}

.prompt-snapshot-block p {
    max-height: 180px !important;
    overflow: auto !important;
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 650 0.94rem/1.72 var(--gp-font) !important;
    white-space: pre-wrap !important;
    word-break: keep-all !important;
    overflow-wrap: anywhere !important;
}

.prompt-snapshot-block.is-muted {
    background: #F8FAFC !important;
}

.prompt-snapshot-block.is-muted p {
    color: #94A3B8 !important;
}

.utility-panel-title {
    display: grid !important;
    gap: 5px !important;
    margin: 10px 0 10px !important;
    padding-top: 12px !important;
    border-top: 1px solid var(--gp-line) !important;
}

.utility-panel-title b {
    color: var(--gp-ink) !important;
    font: 800 1rem/1.2 var(--gp-font) !important;
}

.utility-section-title {
    margin: 14px 0 8px !important;
    padding-top: 12px !important;
    border-top: 1px solid var(--gp-line) !important;
}

.utility-empty {
    padding: 14px !important;
    color: var(--gp-muted) !important;
    font: 700 0.86rem/1.45 var(--gp-font) !important;
}

.rail-item.is-active {
    border-color: rgba(79, 70, 229, 0.32) !important;
    background: linear-gradient(135deg, rgba(238, 242, 255, 0.98), rgba(245, 243, 255, 0.94)) !important;
}

.rail-item.is-active span,
.rail-item.is-active b {
    color: var(--gp-blue) !important;
}

.rail-item.is-done span,
.rail-item.is-done b {
    color: var(--gp-green) !important;
}

.rail-state {
    margin: 8px 0 !important;
    padding: 11px 12px !important;
    border: 1px solid rgba(226, 232, 240, 0.96) !important;
    border-radius: 14px !important;
    background: #FFFFFF !important;
    color: var(--gp-ink) !important;
    font: 800 0.86rem/1.15 var(--gp-font) !important;
    letter-spacing: 0.02em !important;
}

.rail-state.is-ready {
    border-color: rgba(79, 70, 229, 0.22) !important;
    background: linear-gradient(135deg, rgba(238,242,255,0.96), rgba(245,243,255,0.88)) !important;
    color: var(--gp-blue) !important;
}

.rail-state.is-waiting {
    background: #F8FAFC !important;
    color: var(--gp-muted) !important;
}

.rail-state.is-blocked {
    background: #FFF7ED !important;
    color: #C2410C !important;
    border-color: #FED7AA !important;
}

.run-controls-compact .rail-state {
    margin: 0 0 8px !important;
    padding: 8px 12px !important;
    min-height: 34px !important;
    display: flex !important;
    align-items: center !important;
}

.st-key-main_execution_modes {
    margin: 4px 0 2px !important;
    padding: 8px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    background: #F8FAFC !important;
}

.st-key-main_execution_modes [data-testid="stVerticalBlock"] {
    gap: 6px !important;
}

.st-key-main_execution_modes [data-testid="stHorizontalBlock"] {
    gap: 6px !important;
}

.st-key-main_execution_modes [data-testid="stColumn"] {
    min-width: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
}

.st-key-main_execution_modes .stButton {
    margin: 0 !important;
}

.st-key-main_execution_modes .stButton > button {
    min-height: 48px !important;
    padding: 9px 8px !important;
    border-radius: 11px !important;
    font: 850 0.78rem/1.2 var(--gp-font) !important;
    white-space: normal !important;
    transition: none !important;
}

.st-key-main_execution_modes .stButton > button:hover {
    transform: none !important;
}

.st-key-toggle_infinite_mode_card button[kind="primary"],
.st-key-toggle_rehearsal_mode_card button[kind="primary"] {
    border-color: transparent !important;
    background: var(--gp-gradient) !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 16px rgba(79, 70, 229, 0.24) !important;
}

.st-key-toggle_infinite_mode_card button[kind="primary"]:hover,
.st-key-toggle_rehearsal_mode_card button[kind="primary"]:hover {
    border-color: transparent !important;
    background: var(--gp-gradient) !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 16px rgba(79, 70, 229, 0.24) !important;
}

.st-key-toggle_infinite_mode_card button[kind="primary"] *,
.st-key-toggle_rehearsal_mode_card button[kind="primary"] *,
.st-key-toggle_infinite_mode_card button[kind="primary"] p,
.st-key-toggle_rehearsal_mode_card button[kind="primary"] p {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
}

.st-key-toggle_infinite_mode_card button[kind="secondary"],
.st-key-toggle_rehearsal_mode_card button[kind="secondary"] {
    border-color: var(--gp-line) !important;
    background: #FFFFFF !important;
    color: var(--gp-soft) !important;
    box-shadow: none !important;
}

.st-key-toggle_infinite_mode_card button[kind="secondary"] *,
.st-key-toggle_rehearsal_mode_card button[kind="secondary"] *,
.st-key-toggle_infinite_mode_card button[kind="secondary"] p,
.st-key-toggle_rehearsal_mode_card button[kind="secondary"] p {
    color: #334155 !important;
    -webkit-text-fill-color: #334155 !important;
    opacity: 1 !important;
}

.st-key-main_execution_modes [data-testid="stCaptionContainer"] {
    margin: 0 !important;
    text-align: center !important;
}

.st-key-main_execution_modes [data-testid="stCaptionContainer"] p {
    color: var(--gp-muted) !important;
    font-size: 0.72rem !important;
    line-height: 1.25 !important;
    white-space: nowrap !important;
}

[data-testid="stColumn"]:has(.command-canvas-marker) {
    padding: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
}

.sheet-button-offset,
.sheet-button-offset.is-tall {
    height: 0 !important;
}

label p,
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] *,
[data-testid="stColumn"]:has(.stage-panel-marker) label p,
[data-testid="stColumn"]:has(.topic-panel-marker) label p,
[data-testid="stColumn"]:has(.run-panel-marker) label p,
[data-testid="stColumn"]:has(.stack-panel-marker) label p,
[data-testid="stColumn"]:has(.active-panel-marker) label p,
[data-testid="stColumn"]:has(.log-panel-marker) label p,
.stCheckbox label p,
.stToggle label p {
    color: var(--gp-soft) !important;
    font: 700 0.86rem/1.15 var(--gp-font) !important;
    letter-spacing: -0.01em !important;
}

[data-testid="stTooltipIcon"],
[data-testid="stTooltipHoverTarget"],
[data-testid="stTooltipIcon"] *,
[data-testid="stTooltipHoverTarget"] * {
    color: var(--gp-muted) !important;
}

div[data-baseweb="input"],
div[data-baseweb="select"] > div,
div[data-baseweb="textarea"],
.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
[data-testid="stNumberInputContainer"] {
    min-height: 44px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 12px !important;
    background: #FFFFFF !important;
    color: var(--gp-ink) !important;
    box-shadow: none !important;
    font-family: var(--gp-font) !important;
}

.stTextArea textarea {
    min-height: 210px !important;
    color: var(--gp-ink) !important;
    font: 600 1rem/1.6 var(--gp-font) !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #94A3B8 !important;
    opacity: 1 !important;
}

div[data-baseweb="input"]:focus-within,
div[data-baseweb="select"] > div:focus-within,
div[data-baseweb="textarea"]:focus-within {
    border-color: var(--gp-blue) !important;
    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.16) !important;
}

.stSlider [data-baseweb="slider"] {
    min-height: 24px !important;
    padding: 2px 6px 0 !important;
    box-sizing: border-box !important;
}

.stSlider [data-baseweb="slider"] > div {
    border-radius: 999px !important;
}

.stSlider [data-baseweb="slider"] [role="slider"] {
    width: 14px !important;
    height: 14px !important;
    min-width: 14px !important;
    min-height: 14px !important;
    padding: 0 !important;
    border: 3px solid #FFFFFF !important;
    border-radius: 999px !important;
    background: var(--gp-blue) !important;
    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.14) !important;
}

.stSlider [data-baseweb="slider"] [data-testid="stTickBar"],
.stSlider [data-baseweb="slider"] [data-testid="stSliderTickBar"] {
    color: var(--gp-muted) !important;
    background: transparent !important;
}

.stSlider [data-baseweb="slider"] [data-testid="stThumbValue"],
.stSlider [data-baseweb="slider"] [data-testid="stSliderThumbValue"] {
    display: none !important;
    opacity: 0 !important;
    visibility: hidden !important;
    pointer-events: none !important;
}

.stSlider [data-baseweb="slider"] [data-testid="stMarkdownContainer"],
.stSlider [data-baseweb="slider"] p {
    color: var(--gp-muted) !important;
    background: transparent !important;
}

.slider-readout {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    min-height: 34px !important;
    margin: 0 0 8px !important;
    padding: 7px 10px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    box-sizing: border-box !important;
    background: #F8FAFC !important;
}

.slider-readout span {
    color: var(--gp-muted) !important;
    font: 800 0.66rem/1 var(--gp-mono) !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
}

.slider-readout b {
    color: var(--gp-blue) !important;
    font: 800 0.88rem/1 var(--gp-font) !important;
}

.stNumberInput button,
[data-testid="stNumberInput"] button {
    min-width: 38px !important;
    min-height: 44px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 10px !important;
    background: #FFFFFF !important;
    color: var(--gp-blue) !important;
    box-shadow: none !important;
}

div.stButton > button,
button,
button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primary"],
button[data-testid="stPopoverButton"],
button[kind="secondary"],
button[kind="primary"] {
    min-height: 42px !important;
    height: auto !important;
    padding: 10px 16px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    background: #FFFFFF !important;
    color: #334155 !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08) !important;
    font: 850 0.84rem/1.1 var(--gp-font) !important;
    letter-spacing: -0.01em !important;
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    transition: none !important;
}

div.stButton > button:hover,
button[data-testid="stPopoverButton"]:hover {
    transform: none !important;
    border-color: #C7D2FE !important;
    background: #F8FAFC !important;
    color: var(--gp-blue) !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08) !important;
}

.st-key-toggle_infinite_mode_card .stTooltipHoverTarget > button[kind="primary"],
.st-key-toggle_rehearsal_mode_card .stTooltipHoverTarget > button[kind="primary"],
.st-key-toggle_infinite_mode_card > div button[kind="primary"],
.st-key-toggle_rehearsal_mode_card > div button[kind="primary"] {
    border-color: transparent !important;
    background: var(--gp-gradient) !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 16px rgba(79, 70, 229, 0.24) !important;
}

.st-key-toggle_infinite_mode_card .stTooltipHoverTarget > button[kind="primary"] *,
.st-key-toggle_rehearsal_mode_card .stTooltipHoverTarget > button[kind="primary"] *,
.st-key-toggle_infinite_mode_card > div button[kind="primary"] *,
.st-key-toggle_rehearsal_mode_card > div button[kind="primary"] * {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
}

.st-key-toggle_infinite_mode_card .stTooltipHoverTarget > button[kind="secondary"],
.st-key-toggle_rehearsal_mode_card .stTooltipHoverTarget > button[kind="secondary"],
.st-key-toggle_infinite_mode_card > div button[kind="secondary"],
.st-key-toggle_rehearsal_mode_card > div button[kind="secondary"] {
    border-color: var(--gp-line) !important;
    background: #FFFFFF !important;
    color: var(--gp-soft) !important;
    box-shadow: none !important;
}

.st-key-toggle_infinite_mode_card .stTooltipHoverTarget > button[kind="secondary"] *,
.st-key-toggle_rehearsal_mode_card .stTooltipHoverTarget > button[kind="secondary"] *,
.st-key-toggle_infinite_mode_card > div button[kind="secondary"] *,
.st-key-toggle_rehearsal_mode_card > div button[kind="secondary"] * {
    color: #334155 !important;
    -webkit-text-fill-color: #334155 !important;
    opacity: 1 !important;
}

.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[data-testid="stBaseButton-primary"],
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[data-testid="stBaseButton-primary"],
.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[kind="primary"],
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[kind="primary"] {
    background: linear-gradient(135deg, #2563EB 0%, #4F46E5 52%, #7C3AED 100%) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 900 !important;
    text-shadow: 0 1px 1px rgba(15, 23, 42, 0.28) !important;
}

.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[data-testid="stBaseButton-primary"] *,
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[data-testid="stBaseButton-primary"] *,
.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[kind="primary"] *,
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[kind="primary"] * {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 900 !important;
    text-shadow: 0 1px 1px rgba(15, 23, 42, 0.28) !important;
    opacity: 1 !important;
}

.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[data-testid="stBaseButton-secondary"],
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[data-testid="stBaseButton-secondary"],
.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[kind="secondary"],
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[kind="secondary"] {
    background: #FFFFFF !important;
    border-color: #CBD5E1 !important;
    color: #0F172A !important;
    -webkit-text-fill-color: #0F172A !important;
    font-weight: 850 !important;
    text-shadow: none !important;
}

.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[data-testid="stBaseButton-secondary"] *,
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[data-testid="stBaseButton-secondary"] *,
.st-key-main_execution_modes .st-key-toggle_infinite_mode_card button[kind="secondary"] *,
.st-key-main_execution_modes .st-key-toggle_rehearsal_mode_card button[kind="secondary"] * {
    color: #0F172A !important;
    -webkit-text-fill-color: #0F172A !important;
    font-weight: 850 !important;
    opacity: 1 !important;
}

div.stButton > button:focus-visible,
button:focus-visible,
input:focus-visible,
textarea:focus-visible {
    outline: 2px solid rgba(79, 70, 229, 0.82) !important;
    outline-offset: 2px !important;
}

.st-key-make_drafts_btn button,
.st-key-confirm_publish_btn button,
.st-key-stack_confirm_publish_btn button {
    background: var(--gp-gradient) !important;
    color: #FFFFFF !important;
    border-color: transparent !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.30) !important;
}

.st-key-make_drafts_btn button:hover,
.st-key-confirm_publish_btn button:hover,
.st-key-stack_confirm_publish_btn button:hover {
    transform: none !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.30) !important;
}

.st-key-intel_fire_btn button,
.st-key-use_as_topic_btn button {
    border-color: rgba(199, 210, 254, 0.95) !important;
    color: var(--gp-blue) !important;
    background: #EEF2FF !important;
}

div.stButton > button:disabled,
button:disabled,
.st-key-make_drafts_btn button:disabled,
.st-key-intel_fire_btn button:disabled {
    border-color: var(--gp-line) !important;
    background: #F1F5F9 !important;
    color: #94A3B8 !important;
    box-shadow: none !important;
    transform: none !important;
}

.st-key-intel_fire_btn button:not(:disabled) {
    background: linear-gradient(135deg, #2563EB, #4F46E5) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px -10px rgba(37, 99, 235, 0.62) !important;
}

.st-key-intel_fire_btn button:not(:disabled):hover {
    background: linear-gradient(135deg, #2563EB, #4F46E5) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
}

.st-key-make_drafts_btn button:not(:disabled) {
    background: var(--gp-gradient) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px -10px rgba(79, 70, 229, 0.62) !important;
}

.st-key-confirm_publish_btn button:not(:disabled) {
    background: linear-gradient(135deg, #059669, #10B981) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px -10px rgba(16, 185, 129, 0.62) !important;
}

.st-key-stack_confirm_publish_btn button:not(:disabled) {
    background: linear-gradient(135deg, #059669, #10B981) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px -10px rgba(16, 185, 129, 0.62) !important;
}

.st-key-stop_batch_btn_top button,
.st-key-stop_publish_btn_top button,
.st-key-review_discard_btn button,
.st-key-review_discard_only_btn button,
.st-key-stack_review_discard_btn button {
    border-color: #FECACA !important;
    background: #FEF2F2 !important;
    color: #B91C1C !important;
}

.st-key-use_as_topic_btn button:not(:disabled),
.st-key-intel_raw_toggle_btn button,
.st-key-stack_use_as_topic_btn button:not(:disabled),
.st-key-stack_intel_raw_toggle_btn button {
    border-color: #C7D2FE !important;
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
}

.stack-intel-actions-marker {
    height: 8px !important;
}

.st-key-stack_use_as_topic_btn button,
.st-key-stack_intel_raw_toggle_btn button,
.st-key-stack_confirm_publish_btn button,
.st-key-stack_review_discard_btn button {
    width: 100% !important;
    min-height: 42px !important;
    margin-top: 6px !important;
    border-radius: 14px !important;
    font: 850 0.82rem/1.15 var(--gp-font) !important;
}

.st-key-stack_use_as_topic_btn button:not(:disabled) {
    background: linear-gradient(135deg, #2563EB, #4F46E5) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 18px -12px rgba(79, 70, 229, 0.60) !important;
}

.stack-review-actions {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) auto !important;
    gap: 4px 8px !important;
    align-items: center !important;
    margin: 10px 0 4px !important;
    padding: 11px 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    background: linear-gradient(135deg, #FFFFFF, #F8FAFC) !important;
}

.stack-review-actions span {
    grid-column: 1 / -1 !important;
    color: var(--gp-blue) !important;
    font: 850 0.68rem/1 var(--gp-font) !important;
}

.stack-review-actions b {
    color: var(--gp-ink) !important;
    font: 900 1rem/1.15 var(--gp-font) !important;
}

.stack-review-actions em {
    justify-self: end !important;
    color: var(--gp-muted) !important;
    font: 800 0.72rem/1 var(--gp-font) !important;
    font-style: normal !important;
}

.stack-package-actions {
    display: grid !important;
    gap: 4px !important;
    margin: 12px 0 6px !important;
    padding: 10px 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    background: rgba(255, 255, 255, 0.72) !important;
}

.stack-package-actions span {
    color: var(--gp-blue) !important;
    font: 900 0.68rem/1 var(--gp-font) !important;
    letter-spacing: -0.01em !important;
}

.stack-package-actions em {
    color: var(--gp-muted) !important;
    font: 760 0.72rem/1.35 var(--gp-font) !important;
    font-style: normal !important;
    word-break: keep-all !important;
}

.st-key-recent_manage_toggle_btn button,
.st-key-advanced_manage_toggle_btn button {
    min-height: 38px !important;
    background: #FFFFFF !important;
    color: var(--gp-soft) !important;
    box-shadow: none !important;
}

[class*="st-key-quick_pick_"] button {
    min-height: 36px !important;
    padding: 0 10px !important;
    font: 800 0.78rem/1 var(--gp-font) !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

button[aria-label^="Help for"],
[data-testid="stTooltipIcon"] button {
    width: 18px !important;
    min-width: 18px !important;
    height: 18px !important;
    min-height: 18px !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: 999px !important;
    background: transparent !important;
    color: var(--gp-muted) !important;
    box-shadow: none !important;
}

[data-testid="stTooltipHoverTarget"] > button[aria-label^="Help for"],
[data-testid="stTooltipHoverTarget"] > [data-testid="stTooltipIcon"] button {
    width: 18px !important;
    min-width: 18px !important;
    height: 18px !important;
    min-height: 18px !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: 999px !important;
    background: transparent !important;
    color: var(--gp-muted) !important;
    box-shadow: none !important;
}

[data-testid="stTooltipHoverTarget"] > button[data-testid^="stBaseButton"] {
    width: 100% !important;
    min-width: 0 !important;
    min-height: 44px !important;
    padding: 0.55rem 1rem !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 999px !important;
    background: #FFFFFF !important;
    color: var(--gp-soft) !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08) !important;
}

button[data-testid="stPopoverButton"] {
    width: 100% !important;
}

div[data-baseweb="popover"],
[data-testid="stPopover"],
[data-testid="stPopover"] > div,
ul[role="listbox"],
div[role="listbox"],
div[data-baseweb="menu"],
[data-testid="stSelectboxVirtualDropdown"],
[data-testid="stSelectboxVirtualDropdown"] > div {
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: #FFFFFF !important;
    color: var(--gp-ink) !important;
    box-shadow: 0 18px 44px -18px rgba(15, 23, 42, 0.20), 0 10px 25px -10px rgba(79, 70, 229, 0.16) !important;
}

div[data-baseweb="popover"] div,
[data-testid="stPopover"] [data-testid="stExpander"],
[data-testid="stPopover"] [data-testid="stExpander"] details,
[data-testid="stPopover"] [data-testid="stExpander"] summary,
[data-testid="stPopover"] [data-testid="stExpanderDetails"],
[data-testid="stPopover"] [data-testid="stVerticalBlock"],
[data-testid="stPopover"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stPopover"] [data-testid="stVerticalBlockBorderWrapper"] > div,
[data-testid="stPopover"] [data-testid="stElementContainer"] {
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
}

div[data-baseweb="popover"] > div,
[data-testid="stPopover"] {
    border: 1px solid var(--gp-line) !important;
    border-radius: 22px !important;
    background: rgba(255, 255, 255, 0.98) !important;
    box-shadow: 0 18px 44px -18px rgba(15, 23, 42, 0.22), 0 10px 25px -10px rgba(79, 70, 229, 0.18) !important;
}

[data-testid="stPopover"] *,
div[data-baseweb="popover"] * {
    color: var(--gp-ink) !important;
}

li[role="option"],
div[role="option"],
[data-baseweb="menu"] li,
[data-baseweb="menu"] div,
[data-testid="stSelectboxVirtualDropdown"] li,
[data-testid="stSelectboxVirtualDropdown"] div {
    color: var(--gp-ink) !important;
    background: #FFFFFF !important;
    border: 0 !important;
    box-shadow: none !important;
}

li[role="option"]:hover,
div[role="option"]:hover,
li[role="option"][aria-selected="true"],
div[role="option"][aria-selected="true"],
[data-testid="stSelectboxVirtualDropdown"] li:hover,
[data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"] {
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
}

[data-testid="stExpander"] {
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: rgba(255, 255, 255, 0.96) !important;
    box-shadow: var(--gp-shadow) !important;
}

[data-testid="stExpander"] summary {
    color: var(--gp-ink) !important;
    font: 800 0.86rem/1 var(--gp-font) !important;
}

[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    background: #FFFFFF !important;
    color: var(--gp-ink) !important;
}

.result-title {
    margin: 22px 0 12px !important;
    padding-top: 16px !important;
    border-top: 1px solid rgba(226, 232, 240, 0.95) !important;
}

.result-title b {
    color: var(--gp-ink) !important;
    font: 800 clamp(1.45rem, 2.25vw, 2.5rem)/1.05 var(--gp-font) !important;
    letter-spacing: -0.04em !important;
}

.workflow-divider {
    height: 1px !important;
    margin: 22px 0 !important;
    background: var(--gp-line) !important;
}

.activity-panel,
.studio-intel-card,
.studio-preview-card,
.publish-draft-stack,
.publish-draft-card,
.studio-stat,
.pd-empty,
.status-bento {
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: #FFFFFF !important;
    box-shadow: var(--gp-shadow) !important;
}

.activity-panel {
    overflow: hidden !important;
    padding: 16px !important;
    display: grid !important;
    grid-template-rows: auto minmax(0, 1fr) !important;
}

.activity-head {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 12px !important;
    padding-bottom: 8px !important;
    border-bottom: 1px solid var(--gp-line) !important;
}

.activity-head b {
    color: var(--gp-ink) !important;
    font: 800 1rem/1 var(--gp-font) !important;
}

.activity-head small {
    color: var(--gp-muted) !important;
    font: 800 0.62rem/1 var(--gp-mono) !important;
}

.activity-body {
    min-height: 0 !important;
    overflow: auto !important;
    padding-top: 9px !important;
}

.activity-line {
    display: grid !important;
    grid-template-columns: 9px minmax(0, 1fr) !important;
    gap: 12px !important;
    align-items: start !important;
    padding: 6px 0 !important;
}

.activity-line span {
    width: 7px !important;
    height: 7px !important;
    margin-top: 7px !important;
    border-radius: 999px !important;
    background: var(--gp-blue) !important;
}

.activity-line p {
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 760 1rem/1.62 var(--gp-font) !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    overflow-wrap: anywhere !important;
}

.publish-draft-stack {
    min-height: 0 !important;
    overflow: auto !important;
    display: grid !important;
    align-content: start !important;
    gap: 10px !important;
    padding: 12px !important;
    background:
        radial-gradient(circle at 96% 0%, rgba(124, 58, 237, 0.07), transparent 18rem),
        #FFFFFF !important;
}

.publish-draft-card {
    padding: 14px 16px !important;
    box-shadow: none !important;
    border-color: #D8E0F0 !important;
}

.publish-draft-card.is-current {
    border-color: #A5B4FC !important;
    background: #F5F7FF !important;
}

.publish-draft-card.is-done {
    background: #FBFDFF !important;
}

.publish-draft-card header {
    display: grid !important;
    grid-template-columns: auto minmax(0, 1fr) !important;
    gap: 8px !important;
    align-items: center !important;
    margin-bottom: 9px !important;
}

.publish-draft-card header span {
    color: var(--gp-blue) !important;
    font: 900 0.72rem/1 var(--gp-font) !important;
}

.publish-draft-card header em {
    min-width: 0 !important;
    color: var(--gp-muted) !important;
    font: 800 0.72rem/1.25 var(--gp-font) !important;
    font-style: normal !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}

.publish-draft-card h3 {
    margin: 0 0 8px !important;
    color: var(--gp-ink) !important;
    font: 850 1.06rem/1.32 var(--gp-font) !important;
    letter-spacing: -0.025em !important;
}

.publish-draft-card p {
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 700 0.94rem/1.55 var(--gp-font) !important;
    white-space: pre-wrap !important;
    overflow-wrap: anywhere !important;
}

.draft-comment-list {
    display: grid !important;
    gap: 8px !important;
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 8px 10px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 12px !important;
    background: #FAFBFF !important;
}

.draft-comment-list > header {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 6px !important;
    color: var(--gp-muted) !important;
    font: 850 0.74rem/1.25 var(--gp-font) !important;
}

.draft-comment-list > header b {
    min-width: 38px !important;
    padding: 2px 6px !important;
    border-radius: 999px !important;
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
    text-align: center !important;
}

.draft-comment-list ul {
    display: grid !important;
    gap: 6px !important;
    margin: 0 !important;
    padding: 0 !important;
    list-style: none !important;
}

.draft-comment-list li {
    display: grid !important;
    grid-template-columns: auto minmax(0, 1fr) !important;
    gap: 8px !important;
    align-items: start !important;
    width: 100% !important;
    max-width: 100% !important;
    padding: 5px 7px !important;
    border-radius: 8px !important;
    background: #FFFFFF !important;
}

.draft-comment-empty {
    margin: 0 !important;
    color: var(--gp-muted) !important;
    font: 700 0.8rem/1.4 var(--gp-font) !important;
}

.draft-comment-list li b {
    color: var(--gp-blue) !important;
    font: 850 0.72rem/1.45 var(--gp-font) !important;
}

.draft-comment-list li span {
    min-width: 0 !important;
    color: var(--gp-soft) !important;
    font: 700 0.82rem/1.45 var(--gp-font) !important;
    white-space: pre-wrap !important;
    overflow-wrap: anywhere !important;
}

@media (max-width: 760px) {
    .draft-comment-list {
        display: grid !important;
        width: 100% !important;
        max-width: 100% !important;
    }
}

.st-key-swarm_infinite {
    margin: 10px 0 0 !important;
    padding: 10px 12px 8px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 14px !important;
    background: #F8FAFF !important;
}

.st-key-swarm_infinite label {
    color: var(--gp-ink) !important;
    font: 850 0.88rem/1.3 var(--gp-font) !important;
}

.publish-draft-stack.is-empty {
    display: grid !important;
    place-items: center !important;
}

.publish-draft-empty {
    color: var(--gp-muted) !important;
    font: 850 0.95rem/1.4 var(--gp-font) !important;
}

.activity-line.is-ok span { background: var(--gp-green) !important; }
.activity-line.is-warn span { background: var(--gp-amber) !important; }
.activity-line.is-error span { background: var(--gp-red) !important; }

.source-collection {
    display: grid !important;
    gap: 12px !important;
    margin-top: 12px !important;
    padding: 14px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 20px !important;
    background: rgba(255, 255, 255, 0.96) !important;
    box-shadow: var(--gp-shadow) !important;
}

.source-collection-head {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 12px !important;
    padding-bottom: 8px !important;
    border-bottom: 1px solid var(--gp-line) !important;
}

.source-collection-head b {
    color: var(--gp-ink) !important;
    font: 900 1rem/1 var(--gp-font) !important;
}

.source-collection-head span {
    color: var(--gp-muted) !important;
    font: 850 0.72rem/1 var(--gp-font) !important;
}

.source-post-grid {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 10px !important;
    max-height: 560px !important;
    overflow: auto !important;
    padding-right: 4px !important;
}

.source-post-card {
    min-width: 0 !important;
    padding: 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    background: #FFFFFF !important;
    box-shadow: none !important;
}

.source-post-card header {
    display: flex !important;
    align-items: center !important;
    gap: 7px !important;
    margin-bottom: 7px !important;
    color: var(--gp-muted) !important;
    font: 850 0.68rem/1.2 var(--gp-font) !important;
}

.source-post-card header span {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    min-width: 28px !important;
    height: 24px !important;
    border-radius: 999px !important;
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
}

.source-post-card header em {
    font-style: normal !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}

.source-post-card header .is-ai {
    margin-left: auto !important;
    color: var(--gp-amber) !important;
    font: 900 0.66rem/1 var(--gp-font) !important;
}

.source-post-card h4 {
    margin: 0 0 7px !important;
    color: var(--gp-ink) !important;
    font: 900 0.95rem/1.35 var(--gp-font) !important;
    letter-spacing: -0.03em !important;
    overflow-wrap: anywhere !important;
}

.source-post-card p {
    margin: 0 0 8px !important;
    color: var(--gp-soft) !important;
    font: 760 0.82rem/1.55 var(--gp-font) !important;
    overflow-wrap: anywhere !important;
}

.source-post-card ul {
    display: grid !important;
    gap: 5px !important;
    margin: 0 !important;
    padding: 8px 0 0 !important;
    border-top: 1px solid var(--gp-line) !important;
    list-style: none !important;
}

.source-post-card li {
    color: var(--gp-soft) !important;
    font: 730 0.78rem/1.45 var(--gp-font) !important;
    overflow-wrap: anywhere !important;
}

.source-post-card li::before {
    content: "↳ " !important;
    color: var(--gp-blue) !important;
    font-weight: 900 !important;
}

.source-post-card li.is-empty {
    color: #94A3B8 !important;
}

.source-collection-empty {
    padding: 18px !important;
    border: 1px dashed var(--gp-line) !important;
    border-radius: 18px !important;
    color: var(--gp-muted) !important;
    font: 800 0.9rem/1.4 var(--gp-font) !important;
}

@media (max-width: 1100px) {
    .source-post-grid {
        grid-template-columns: minmax(0, 1fr) !important;
    }
}

.stable-progress {
    display: grid !important;
    gap: 7px !important;
    margin: 8px 0 12px !important;
}

.stable-progress-meta {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 12px !important;
    color: var(--gp-muted) !important;
    font: 800 0.72rem/1 var(--gp-font) !important;
}

.stable-progress-meta span {
    color: var(--gp-blue) !important;
}

.stable-progress-meta b {
    color: var(--gp-soft) !important;
    font: 850 0.72rem/1 var(--gp-font) !important;
}

.stable-progress-track {
    height: 8px !important;
    overflow: hidden !important;
    border-radius: 999px !important;
    background: #E2E8F0 !important;
}

.stable-progress-fill {
    height: 100% !important;
    border-radius: inherit !important;
    background: var(--gp-gradient) !important;
    transition: none !important;
}

.activity-empty {
    padding: 14px 0 !important;
    color: var(--gp-muted) !important;
    font: 700 0.82rem/1.4 var(--gp-font) !important;
}

.studio-intel-card {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) auto !important;
    gap: 8px 16px !important;
    padding: 16px !important;
    margin-top: 12px !important;
}

.studio-card-head {
    display: contents !important;
}

.studio-card-head span {
    color: var(--gp-blue) !important;
    font: 800 0.68rem/1 var(--gp-mono) !important;
    letter-spacing: 0.12em !important;
}

.studio-card-head b {
    color: var(--gp-muted) !important;
    font: 800 0.68rem/1 var(--gp-mono) !important;
}

.studio-intel-mood {
    grid-column: 1 / -1 !important;
    justify-self: start !important;
    padding: 5px 9px !important;
    border: 1px solid rgba(199, 210, 254, 0.95) !important;
    border-radius: 999px !important;
    background: #EEF2FF !important;
    color: var(--gp-blue) !important;
    font: 800 0.72rem/1 var(--gp-font) !important;
}

.studio-intel-card p,
.studio-preview-card p {
    grid-column: 1 / -1 !important;
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 600 0.94rem/1.55 var(--gp-font) !important;
}

.studio-guidance-box {
    grid-column: 1 / -1 !important;
    display: grid !important;
    gap: 5px !important;
    padding: 10px 12px !important;
    border: 1px solid #C7D2FE !important;
    border-radius: 14px !important;
    background: linear-gradient(135deg, rgba(238, 242, 255, 0.95), rgba(245, 243, 255, 0.80)) !important;
}

.studio-guidance-box span {
    color: var(--gp-blue) !important;
    font: 850 0.66rem/1 var(--gp-font) !important;
}

.studio-guidance-box p {
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 650 0.86rem/1.55 var(--gp-font) !important;
}

.studio-intel-card small {
    grid-column: 1 / -1 !important;
    display: block !important;
    margin-top: 5px !important;
    color: var(--gp-muted) !important;
    font: 600 0.82rem/1.45 var(--gp-font) !important;
}

.studio-chip-row {
    grid-column: 1 / -1 !important;
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
    margin: 2px 0 !important;
}

.studio-chip-row span,
.studio-chip-row em {
    display: inline-flex !important;
    align-items: center !important;
    min-height: 26px !important;
    padding: 3px 9px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 999px !important;
    background: #FFFFFF !important;
    color: var(--gp-soft) !important;
    font: 700 0.72rem/1 var(--gp-font) !important;
    font-style: normal !important;
}

[data-testid="stPopover"] .studio-terminal,
[data-testid="stPopover"] .studio-log-line {
    background: #FFFFFF !important;
    color: var(--gp-ink) !important;
}

.studio-chip-row.is-hot span {
    background: #EEF2FF !important;
    border-color: #C7D2FE !important;
    color: var(--gp-blue) !important;
}

.studio-intel-foot {
    grid-column: 1 / -1 !important;
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin-top: 7px !important;
    padding-top: 9px !important;
    border-top: 1px solid var(--gp-line) !important;
}

.studio-intel-foot span,
.signal-count {
    color: var(--gp-muted) !important;
    font: 750 0.82rem/1.35 var(--gp-font) !important;
}

.section-hdr {
    color: var(--gp-blue) !important;
    font: 800 0.72rem/1 var(--gp-mono) !important;
    letter-spacing: 0.14em !important;
}

.review-tile-grid {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    gap: 7px !important;
    max-height: none !important;
    overflow: visible !important;
    padding-right: 0 !important;
    margin: 12px 0 14px !important;
}

.review-tile {
    min-height: 74px !important;
    padding: 9px 13px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 18px !important;
    background: #FFFFFF !important;
    box-shadow: var(--gp-shadow) !important;
    transition: none !important;
}

.review-tile:hover {
    transform: none !important;
    box-shadow: var(--gp-shadow) !important;
}

.review-tile-layout {
    display: grid !important;
    grid-template-columns: minmax(0, 1.55fr) minmax(220px, 0.8fr) !important;
    gap: 16px !important;
    align-items: stretch !important;
}

.review-tile-copy {
    min-width: 0 !important;
}

.review-tile-comments {
    min-width: 0 !important;
    padding-left: 14px !important;
    border-left: 1px solid var(--gp-line) !important;
}

.review-tile header {
    display: grid !important;
    grid-template-columns: auto minmax(0, 1fr) !important;
    gap: 8px !important;
    align-items: center !important;
    margin-bottom: 7px !important;
}

.review-tile header span {
    color: var(--gp-blue) !important;
    font: 800 0.68rem/1 var(--gp-mono) !important;
}

.review-tile header em {
    color: var(--gp-muted) !important;
    font: 700 0.68rem/1 var(--gp-font) !important;
    font-style: normal !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

.review-tile h3 {
    margin: 0 0 4px !important;
    color: var(--gp-ink) !important;
    font: 800 1rem/1.18 var(--gp-font) !important;
    letter-spacing: -0.035em !important;
}

.review-tile-body {
    margin: 0 !important;
    color: var(--gp-soft) !important;
    font: 650 0.86rem/1.42 var(--gp-font) !important;
    display: -webkit-box !important;
    -webkit-line-clamp: 3 !important;
    -webkit-box-orient: vertical !important;
    overflow: hidden !important;
}

.review-action-hint {
    margin-top: 8px !important;
    color: var(--gp-muted) !important;
    font: 750 0.78rem/1.35 var(--gp-font) !important;
    text-align: center !important;
}

.failed-review-title {
    display: flex !important;
    align-items: baseline !important;
    gap: 8px !important;
    margin: 18px 0 10px !important;
    color: var(--gp-ink) !important;
    font: 850 0.9rem/1.3 var(--gp-font) !important;
}

.failed-review-title b {
    color: #DC2626 !important;
}

.failed-review-title span {
    color: var(--gp-muted) !important;
    font-size: 0.76rem !important;
    font-weight: 650 !important;
}

.failed-review-tile {
    margin-top: 8px !important;
    padding: 12px 14px !important;
    border: 1px dashed #CBD5E1 !important;
    border-radius: 14px !important;
    background: #F8FAFC !important;
}

.failed-review-tile header {
    display: flex !important;
    gap: 8px !important;
    margin-bottom: 7px !important;
    color: var(--gp-muted) !important;
    font: 750 0.7rem/1.2 var(--gp-font) !important;
}

.failed-review-tile header span {
    color: #DC2626 !important;
    font-weight: 850 !important;
}

.failed-review-tile header em {
    font-style: normal !important;
}

.failed-review-tile strong {
    display: block !important;
    color: var(--gp-ink) !important;
    font: 820 0.96rem/1.35 var(--gp-font) !important;
}

.failed-review-tile p {
    margin: 6px 0 !important;
    color: var(--gp-soft) !important;
    font: 650 0.84rem/1.45 var(--gp-font) !important;
    white-space: pre-wrap !important;
}

.failed-review-tile small {
    color: #B45309 !important;
    font: 700 0.72rem/1.35 var(--gp-font) !important;
}

.studio-preview-card {
    padding: 16px !important;
}

.studio-preview-card span {
    color: var(--gp-blue) !important;
    font: 800 0.68rem/1 var(--gp-mono) !important;
    letter-spacing: 0.12em !important;
}

.studio-preview-card h3 {
    margin: 8px 0 !important;
    color: var(--gp-ink) !important;
    font: 800 1.12rem/1.24 var(--gp-font) !important;
    letter-spacing: -0.035em !important;
}

.studio-stat {
    min-height: 72px !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 10px !important;
}

.studio-stat b {
    color: var(--gp-blue) !important;
    font: 800 1.35rem/1 var(--gp-mono) !important;
}

.studio-stat span {
    color: var(--gp-muted) !important;
    font: 800 0.68rem/1 var(--gp-font) !important;
}

.studio-terminal {
    max-height: none !important;
    overflow: auto !important;
    padding: 12px !important;
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    background: #0F172A !important;
    color: #E2E8F0 !important;
    font-family: var(--gp-mono) !important;
}

.studio-log-line {
    color: #E2E8F0 !important;
    font: 760 0.88rem/1.58 var(--gp-mono) !important;
    white-space: pre-wrap !important;
}

[data-testid="stDataFrame"],
.stPlotlyChart {
    border: 1px solid var(--gp-line) !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    background: #FFFFFF !important;
}

[data-testid="stProgress"] > div > div > div {
    background: var(--gp-gradient) !important;
}

hr {
    border-color: var(--gp-line) !important;
}

@media (max-width: 1120px) {
    .stMainBlockContainer {
        width: calc(100vw - 18px) !important;
    }

    [data-testid="stHorizontalBlock"]:has(.stack-panel-marker):has(.active-panel-marker):has(.log-panel-marker) {
        flex-direction: column !important;
    }

    [data-testid="stColumn"]:has(.stage-panel-marker),
    [data-testid="stColumn"]:has(.topic-panel-marker),
    [data-testid="stColumn"]:has(.run-panel-marker),
    [data-testid="stColumn"]:has(.stack-panel-marker),
    [data-testid="stColumn"]:has(.active-panel-marker),
    [data-testid="stColumn"]:has(.log-panel-marker) {
        width: 100% !important;
        flex: 1 1 auto !important;
        min-height: auto !important;
    }

    [data-testid="stColumn"]:has(.stack-panel-marker) {
        order: 2 !important;
    }

    [data-testid="stColumn"]:has(.active-panel-marker) {
        order: 1 !important;
    }

    [data-testid="stColumn"]:has(.log-panel-marker) {
        order: 3 !important;
    }

    .review-tile-grid {
        grid-template-columns: 1fr !important;
    }
}

@media (max-width: 760px) {
    .stMainBlockContainer {
        width: calc(100vw - 12px) !important;
    }

    .review-tile-layout {
        grid-template-columns: 1fr !important;
    }

    .review-tile-comments {
        padding: 10px 0 0 !important;
        border-left: 0 !important;
        border-top: 1px solid var(--gp-line) !important;
    }

    .mission-title {
        padding: 18px !important;
        border-radius: 22px !important;
    }

    .mission-title b {
        font-size: 2.15rem !important;
        line-height: 1.05 !important;
    }

    .panel-heading,
    .command-heading {
        grid-template-columns: auto minmax(0, 1fr) !important;
    }

    .process-rail {
        grid-template-columns: 1fr !important;
    }
}
</style>
"""
