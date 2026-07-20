# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Vibe-Trading is a natural-language finance research agent: a FastAPI + LangGraph
ReAct agent backend with a vectorized daily/options backtesting engine, a
Vite+React frontend, an MCP server, and IM channel adapters (Telegram, Slack,
Discord, WeChat, etc.). Originally a fork of HKUDS/Vibe-Trading; upstream OSS
scaffolding (wiki, multilingual READMEs, community templates) has been
stripped from this private fork, but runtime code, tests, and licensing were
preserved.

## Commands

### Backend (Python 3.11+)
```bash
pip install -e ".[dev]"                 # install with black/ruff/pytest
vibe-trading                            # launch interactive CLI/TUI
vibe-trading serve --port 8899          # launch FastAPI web server
vibe-trading-mcp                        # start MCP server (stdio)

pytest --ignore=agent/tests/e2e_backtest --ignore=agent/tests/test_e2e_harness_v2.py --tb=short -q
pytest agent/tests/some_test.py -q      # single file
pytest agent/tests/some_test.py::test_name -q   # single test

black --check agent/src/example.py agent/tests/test_example.py
ruff check agent/src/example.py agent/tests/test_example.py
```
There is no whole-tree black/ruff enforcement yet — lint/format only the files you changed.

Targeted suites for specific surfaces:
```bash
# live/order safety changes
pytest agent/tests/test_sdk_order_gate.py agent/tests/test_mandate_enforcement.py \
  agent/tests/test_killswitch_blocks_orders.py agent/tests/test_readonly_default.py -q

# factor-zoo changes (purity + lookahead gates — must pass for any agent/src/factors/zoo/**/*.py edit)
pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q
```

### Frontend (`frontend/`)
```bash
npm ci                    # or npm install
npm run dev               # Vite dev server on :5899, proxies API to :8899
npm run build              # tsc -b && vite build
npm run preview
npm run test               # vitest (watch)
npm run test:run           # vitest run (CI mode)
npm run test:coverage
```

### Docker
```bash
docker compose up --build   # backend + frontend on 127.0.0.1:8899 (loopback by default)
```

## Architecture

### Backend layout (`agent/`)
- `agent/api_server.py` — thin FastAPI assembler: creates the app, mounts
  middleware, registers route modules. Shared infra (auth, CORS, security
  headers, SSE tickets) lives in `agent/src/api/security.py`, `helpers.py`,
  `state.py`, `models.py`. Route modules live alongside
  (`alpha_routes.py`, `live_routes.py`, `runs_routes.py`, `sessions_routes.py`,
  `settings_routes.py`, `swarm_routes.py`, `system_routes.py`, `channels_routes.py`,
  `scheduled_routes.py`, `qveris_routes.py`, `uploads_routes.py`, `auth_routes.py`).
- `agent/mcp_server.py` — MCP server exposing the same tool surface over stdio/HTTP.
- `agent/cli/` — Rich/`prompt_toolkit`-based interactive CLI/TUI (`main.py`,
  `onboard.py`, `stream.py`, `theme.py`, `completer.py`).
- `agent/src/agent/loop.py` — the core ReAct agent loop (plan → ground → execute →
  validate → deliver): selects skills/tools/data sources, executes tool calls,
  streams progress, compresses context over long sessions.
- `agent/src/skills/` — ~90 finance skill packages (data source, strategy,
  analysis, asset-class, crypto, flow, tool, research categories), each a
  self-contained markdown+metadata bundle the agent loop can select at runtime.
- `agent/src/factors/zoo/` — pre-built alpha factor library (Qlib158, Alpha101,
  GTJA191, academic, PIT-safe fundamentals). Every factor module must define
  `__alpha_meta__` (validated against `agent/src/factors/registry.py`'s
  `AlphaMeta` schema) and a pure `compute(panel)` function. Changes here are
  gated by `agent/tests/factors/test_alpha_purity.py` (AST-scanned import/name
  allowlist — no `os`, `subprocess`, `socket`, network, `eval`/`exec`, etc.) and
  `test_lookahead.py` (no negative shifts / forward leakage). See
  `AGENT_CONTRIBUTOR_GUIDE.md` and `CONTRIBUTING.md`'s Alpha PR checklist
  before touching zoo files.
- `agent/backtest/` — the backtesting engines. `markets.py` is the single
  source of truth for symbol → market classification and per-market data
  source fallback chains (`MARKET_REGISTRY`); `runner.py`, `benchmark.py`,
  `correlation.py`, and the loader registry all derive from it rather than
  keeping their own copies (see `docs/design/first-class-markets-and-asx.md`
  for the registry consolidation rationale). `engines/` holds per-market
  engines (equity, futures, forex, options, crypto, composite cross-market).
  `loaders/` holds the ~19 free data-source loaders plus optional
  key-gated/premium ones (Longbridge, QVeris), each duck-typed against
  `DataLoaderProtocol` — no shared base class required, register via
  `backtest.loaders.registry.register`.
- `agent/src/live/` — broker connectors, trading mandate, order gate, kill
  switch, and audit ledger. **Safety-critical even for small changes**: must
  stay mandate-gated, kill-switch-aware, fail-closed, and audit-logged. Get
  explicit approval before running anything that places/cancels/approves
  real broker orders.
- `agent/src/channels/` — IM channel adapters (Telegram, Slack, Discord,
  Matrix, WhatsApp, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, QQ/NapCat,
  Mochat, email) sharing the same session runtime as CLI/REST/Web.
- `agent/src/shadow_account/` — parses broker journal exports, extracts an
  implied strategy, backtests it as a "shadow," and renders behavior-diagnostic
  HTML/PDF reports.
- `agent/src/security/` — the AST-hardened sandbox for executing
  agent-generated backtest strategy code (blocks network/subprocess/eval/
  `os.environ`/unsafe `open`, including inside nested function bodies).
- `agent/src/config/` — centralized Pydantic `EnvConfig` schema; all env var
  reads should go through it. A CI grep gate (`tools/ci_grep_gates.sh`) blocks
  new raw `os.getenv` sprawl outside that module.
- `agent/src/swarm/` — multi-agent "team" presets (investment/quant/crypto/risk
  analyst crews) with YAML presets under `presets/`; user overrides load from
  `~/.vibe-trading/`.
- `agent/src/scheduled_research/`, `agent/src/memory/`, `agent/src/session/` —
  cron-style scheduled runs, persistent cross-session memory/FTS5 search, and
  session state respectively.

### Frontend layout (`frontend/src/`)
- React 19 + Vite + TypeScript + Tailwind, Zustand for state, react-i18next
  for i18n, react-router for routing, ECharts for charts.
- `components/{charts,chat,common,layout,settings}`, `pages/`, `stores/`,
  `hooks/`, `lib/`, `i18n/locales/`.
- Dev server proxies API calls to `localhost:8899`; production build is
  served as static files by `vibe-trading serve`.

### Cross-cutting: markets
Symbols carry market-qualifying suffixes (`.SZ/.SH/.BJ` A-share, `.US`,
`.HK`, `.NS/.BO` India, etc.). `agent/backtest/markets.py::MARKET_REGISTRY`
is the only place that should define new market patterns, benchmarks, and
data-source fallback chains — do not add parallel pattern tables elsewhere.

## Contribution & safety conventions
(Full detail in `CONTRIBUTING.md` and `AGENT_CONTRIBUTOR_GUIDE.md` — read
those before large or safety-relevant changes.)

- Community-style commits use `Signed-off-by:` (DCO) via `git commit -s`, but
  this repo does not add `Co-Authored-By:`/AI-attribution trailers.
- Keep files under ~400 lines where practical, 800 hard cap; type-annotate
  public signatures; Google-style docstrings.
- No hardcoded paths/secrets/URLs — config via `.env`, YAML, or module
  constants (route env access through `agent/src/config`).
- Never commit real credentials, `.env` files with real values, run
  artifacts, or private trading exports; use sanitized fixtures instead.
- API/Web deployments beyond loopback must set `API_AUTH_KEY`.
- Broker/live-trading, MCP, and money-moving code paths are high-risk — do
  not exercise them as part of routine local validation; get explicit
  approval first.
