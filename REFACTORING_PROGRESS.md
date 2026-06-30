# Refactoring Progress

## 2026-05-09

### Completed

- Added a `ghost_protocol.domain` package for behavior that should be testable without Streamlit.
- Added a `ghost_protocol.application` package for worker handoff contracts.
- Moved batch generation worker config filtering into `ghost_protocol/application/worker_contracts.py`.
- Centralized background queue message type constants and message construction in `worker_contracts.py`.
- Added a shared `drain_queue()` helper for non-blocking worker queue polling.
- Moved runtime test-log append behavior into `ghost_protocol/application/run_logs.py`.
- Moved persona lineup policy into `ghost_protocol/domain/lineup.py`.
- Moved slot diversity validation into `ghost_protocol/domain/validators.py`.
- Added a `ghost_protocol.ui` package for dashboard-only helpers.
- Moved terminal rendering, script export formatting, and intel chart creation into `ghost_protocol/ui/formatters.py`.
- Moved test-mode wave summary formatting into `ghost_protocol/ui/formatters.py`.
- Moved session defaults into `ghost_protocol/ui/session_state.py`.
- Moved recent gallery history persistence into `ghost_protocol/ui/gallery_history.py`.
- Moved dashboard option labels and value mappings into `ghost_protocol/ui/options.py`.
- Session defaults now consume the shared UI option defaults.
- Added session action helpers for clearing test summaries and resetting monitor stats.
- Added session message reducers for Intel, Swarm/Post, and Batch worker queue messages.
- Moved Intel cache key, freshness checks, age labels, and last-topic cache file helpers into `ghost_protocol/ui/intel_cache.py`.
- Removed old unreachable compatibility bodies for delegated app helpers, including lineup, session, validator, formatter, and log wrappers.
- Removed stale local gallery-history constants and the no-longer-needed Plotly import from `app.py`.
- Removed unused local lineup aliases and the no-longer-needed `math` import from `app.py`.
- Moved dashboard DB export count/CSV helper calls into `ghost_protocol/application/data_exports.py`.
- Moved Streamlit CSV download caching into `ghost_protocol/ui/export_cache.py`.
- Moved Intel sentiment class selection, bot/human occupation metrics, and keyword-chart cache key logic into `ghost_protocol/ui/intel_view_model.py`.
- Moved Intel occupation, briefing, and situation-summary HTML builders into `ghost_protocol/ui/formatters.py`.
- Moved Intel raw-post debug table row construction and diagnostic captions into `ghost_protocol/ui/intel_view_model.py`.
- Moved DB export limit-warning caption formatting into `ghost_protocol/ui/formatters.py`.
- Added `ghost_protocol/ui/intel_panels.py` for Streamlit-specific Intel raw-post debug and DB export panels.
- Moved Intel running-log, running-empty, and idle-empty HTML states into `ghost_protocol/ui/formatters.py`.
- Moved Swarm preview cards, idle terminal placeholder, and mission-stat pill HTML into `ghost_protocol/ui/formatters.py`.
- Added `ghost_protocol/ui/swarm_panels.py` for Streamlit-specific Swarm test-summary and log-copy panels.
- Moved Swarm test-log captions and recent-log copy formatting into `ghost_protocol/ui/formatters.py`.
- Added `ghost_protocol/ui/theme.py` as a new visual overlay for a quieter operator console.
- Added focused unittest coverage for lineup policy, validators, UI formatters, theme output, session defaults, export helpers, Intel view-model helpers, extracted Intel card HTML escaping, debug rows, export captions, Intel empty/log states, Swarm preview/stat rendering, and Swarm log-copy formatting.

### Validation

- `python -m unittest discover -s tests` (53 tests)
- `python -m py_compile app.py ghost_protocol\\application\\data_exports.py ghost_protocol\\application\\run_logs.py ghost_protocol\\application\\worker_contracts.py ghost_protocol\\domain\\lineup.py ghost_protocol\\domain\\validators.py ghost_protocol\\ui\\export_cache.py ghost_protocol\\ui\\formatters.py ghost_protocol\\ui\\theme.py ghost_protocol\\ui\\session_state.py ghost_protocol\\ui\\gallery_history.py ghost_protocol\\ui\\options.py ghost_protocol\\ui\\intel_cache.py ghost_protocol\\ui\\intel_view_model.py ghost_protocol\\ui\\intel_panels.py ghost_protocol\\ui\\swarm_panels.py`
- Streamlit started successfully on `http://localhost:8501`.

### Next Refactor Targets

- Move the four Streamlit fragments into `ghost_protocol/ui/fragments.py` once their dependencies are narrowed.
- Extract the batch-generation progress terminal/empty state from `_batch_gen_fragment()`.
- Expand worker result/status contracts inside the new `application` package.
- Split the left control panel and review board into dedicated UI modules.
- Continue replacing direct DB details in `app.py` with small application services where behavior stays read-only.
