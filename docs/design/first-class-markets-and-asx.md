# Design: First-Class Markets & Australian Equities (ASX)

**Status:** Proposed
**Audience:** The engineer implementing ASX support (and the next market after that)
**Scope:** Market classification, symbol handling, data-source routing, backtest engine selection, and the registry that ties them together.

---

## 0. Read this first

If you were handed "add Australian equities (`BHP.AX`) to the backtester," your instinct will be to copy whatever was done for India (`RELIANCE.NS`). **Don't start there.** The India integration is the most recent "first-class" market and it is *itself half-wired* — it works in the backtester but was never added to the benchmark or correlation subsystems. Copying it copies the bug.

The real task is smaller *and* larger than it looks:
- **Smaller:** the data layer can already fetch ASX today. Yahoo and yfinance both accept `BHP.AX` verbatim. Nothing needs to be built to *get the data*.
- **Larger:** "what is a market" is duplicated across ~13 sites with no single source of truth and no enforcement, so adding a market correctly means editing all of them from memory. That is the thing worth fixing.

This document explains the problem, the reasoning, the recommended architecture, and a staged implementation plan you can stop partway through and still have shipped something valuable.

---

## 1. The reported problem

`BHP.AX` (and any ASX ticker) fails in backtesting even though `yfinance.download("BHP.AX")` returns data fine outside the app.

### Root cause (traced, not guessed)

1. **Classification.** `BHP.AX` matches no rule in `_MARKET_PATTERNS`
   (`agent/backtest/engines/_market_hooks.py:25`). `_detect_market`
   (`_market_hooks.py:68`) therefore returns its **silent default: `"a_share"`**.
2. **Routing.** `_MARKET_TO_SOURCE["a_share"] = "tushare"` (`agent/backtest/runner.py:530`)
   and `FALLBACK_CHAINS["a_share"] = [tencent, mootdx, eastmoney, baostock, akshare,
   tushare, local]` (`agent/backtest/loaders/registry.py:132`).
   **None of these sources serve ASX.**
3. **Result.** The fetch returns nothing, the backtest has no data, and the failure is
   opaque — it looks like a data outage, not a misclassification.

### Why the data layer is not the problem

- `yahoo_client.map_symbol` (`agent/backtest/loaders/yahoo_client.py:69`) passes any
  unrecognized suffix through **verbatim**. Yahoo's native ASX ticker *is* `BHP.AX`, so no
  translation is needed.
- `yfinance_loader._to_yfinance_symbol` (`agent/backtest/loaders/yfinance_loader.py:42`)
  likewise returns `.AX` symbols unchanged, and yfinance serves ASX natively.

The **only** things blocking ASX are:
- the classifier has no `.AX` rule (so it picks the wrong market and the wrong chain), and
- the Yahoo loader gate `_is_supported` (`agent/backtest/loaders/yahoo_loader.py:41`)
  allowlists only `.US/.HK/.NS/.BO` and would reject `.AX` even if it were routed there.

This is a **classification + routing** bug, not a data-source bug.

---

## 2. The architectural weakness behind the bug

Market identity is a cross-cutting concern, but the codebase stores it as **duplicated
tables and hand-written `if`-chains scattered across ~13 sites**, including **three
independent re-implementations of symbol → market classification** that do not share code
and do not agree.

| # | Concern | Location | Notes |
|---|---|---|---|
| 1 | Classify (primary) | `_market_hooks._MARKET_PATTERNS` / `_detect_market` (`:25`, `:68`) | regex table; **fails open** to `a_share` |
| 2 | Classify (again) | `benchmark._infer_market` (`agent/backtest/benchmark.py:125`) | *different* logic (suffix + source) |
| 3 | Classify (again) | `correlation.infer_market` (`agent/backtest/correlation.py:19`) | *third* logic (suffix + digit-length) |
| 4 | Market → source chain | `registry.FALLBACK_CHAINS` (`:132`) | per-market |
| 5 | Market → default source | `runner._MARKET_TO_SOURCE` (`:530`) | per-market |
| 6 | Engine factory | `runner._create_market_engine` (`:979`) | imperative `if`-chain |
| 7 | Engine factory (again) | `composite._build_rule_engines` (`agent/backtest/engines/composite.py:25`) | duplicate `if`-chain |
| 8 | Loader accept gate | `yahoo_loader._is_supported` + `.markets` (`:41`, `:161`) | suffix allowlist |
| 9 | Loader accept gate | `yfinance_loader.markets` + `_to_yfinance_symbol` (`:217`, `:42`) | |
| 10 | Symbol → vendor form | `yahoo_client.map_symbol` (`:69`) | |
| 11 | Market → benchmark ticker | `benchmark.MARKET_BENCHMARKS` (`:21`) | |
| 12 | Engine implementation | `engines/*.py` | |
| 13 | Composite fallback default | `composite._rule_for` → `"a_share"` (`:90`) | landmine |

### The decisive evidence: India is already broken

India (`.NS`/`.BO`) was added as a "first-class" market. It is wired into sites 1, 4, 5, 6,
7, 8, 9, 10, and 12. It is **missing** from:
- `benchmark._infer_market` / `MARKET_BENCHMARKS` (site 2/11) — India has **no benchmark**.
- `correlation.infer_market` (site 3) — India symbols are **mis-classified** there.

Nobody caught this because **nothing enforces completeness**. A 13-point checklist
maintained by hand *will* leak, and it already has. Copying the India pattern for ASX copies
these two gaps unless you happen to remember them.

### Two systemic faults

1. **No single source of truth.** Adding a market = editing ~10–13 files correctly, from
   memory, with no compiler or test to catch a missed site.
2. **Fail-open default.** `_detect_market` returns `a_share` for *anything* unrecognized —
   `.AX`, `.L`, `.TO`, `.SW`, or a typo. Unknown qualified symbols silently become Chinese
   A-shares and fail opaquely. This *is* the ASX bug, and it will recur for every future
   market until the default fails closed.

---

## 3. Options considered

**Option A — Copy the India pattern for `.AX`.**
Smallest change; matches precedent. **Rejected as the primary strategy.** It re-commits to
the fragmentation that left India half-wired (it silently repeats the benchmark/correlation
gaps unless you manually remember the two files India forgot), keeps the fail-open landmine,
and adds zero enforcement. It fixes the symptom for one ticker suffix.

**Option B — Big-bang `MarketSpec` registry refactor of everything at once.**
Cleanest end state, but rewrites the routing of *every* existing market (China / US / HK /
crypto / futures) in a single change. In a fork whose China path is load-bearing, that is a
large regression surface to accept up front, and it is more than the ASX feature needs to
begin.

**Option C — Recommended. Introduce a `MarketSpec` registry as the single source of truth,
migrate the scattered market-knowledge onto it incrementally, and land ASX as the first
market that goes through it.**
The surplus work over Option A is *exactly the de-duplication that prevents this class of
bug* — not speculative abstraction. It also closes India's existing benchmark/correlation
gap as a side effect, and it can be delivered in stages with safe stop points.

---

## 4. Recommended architecture

### 4.1 A single market registry

Create `agent/backtest/markets.py`:

```python
@dataclass(frozen=True)
class MarketSpec:
    key: str                                 # "au_equity"
    matches: Callable[[str], bool]           # classification rule (suffix/regex)
    source_chain: list[str]                  # ["yahoo", "yfinance", "local"]
    default_source: str                      # "yahoo"
    build_engine: Callable[[dict], BaseEngine]
    benchmark: str | None                    # "^AXJO"  (None == deliberately none)
    accepts_symbol: Callable[[str], bool]    # loader-gate predicate

MARKET_REGISTRY: dict[str, MarketSpec] = {...}   # seeded with every existing market
```

Every consuming surface in the table above **delegates to the registry** instead of holding
its own copy of the knowledge:

- `_detect_market` iterates the specs. **Keep the existing public names** (`_detect_market`,
  `_MARKET_PATTERNS`, `_is_china_futures`, `_detect_submarket`) as thin wrappers —
  `swarm/grounding.py` and the test suite import them, and back-compat matters.
- `FALLBACK_CHAINS`, `_MARKET_TO_SOURCE`, `MARKET_BENCHMARKS`, both engine factories
  (`runner` and `composite`), and the loader `.markets` / `_is_supported` gates all read
  from the registry.
- **Collapse the three classifiers into one.** `benchmark._infer_market` and
  `correlation.infer_market` call the registry. This is the highest-value dedup and it
  directly closes the India benchmark/correlation gap.

### 4.2 Fail closed on unknown qualified symbols

A symbol that carries a suffix (`X.SOMETHING`) the registry does not recognize must raise a
clear "unsupported market for symbol X" error in `auto` mode — **not** default to `a_share`.
Preserve the bare-numeric → `a_share` default only where existing tests depend on it (that
path is a genuine Chinese-market convention, not a catch-all fallback). Verify against
`test_market_detection.py` before changing the default; there is at least one assertion that
pins the current behavior.

### 4.3 The contract test (the durable enforcement)

This is the point of the whole exercise. Add a test that iterates **every** registered
`MarketSpec` and asserts each consuming surface resolves:

- `build_engine(config)` returns a `BaseEngine` without raising;
- `source_chain` is non-empty and every name is in `registry.VALID_SOURCES`;
- at least one loader's `accepts_symbol` accepts a sample symbol for the market;
- `benchmark` is present **or** explicitly `None` (never silently absent);
- all classifiers (`_detect_market`, `benchmark`, `correlation`) agree on a sample symbol.

With this test, "half-wired like India" becomes a permanent, unmissable failure. It is the
thing that makes first-class-market support actually durable rather than checklist-durable.

---

## 5. ASX (`au_equity`) specifics — domain-correct

Do not model ASX on India. India's engine encodes T+1 delivery, per-scrip circuit bands, and
no-short defaults — **none of which apply to ASX.** ASX cash equities are mechanically close
to US equities:

- **T+0 intraday trading is allowed.** You can buy and sell the same day. India's
  "can't sell what you bought today" rule (`india_equity.py`) must **not** be carried over.
- **Long/short allowed** (covered short; fine for a daily-bar model).
- **Decimal share sizing**, lot size 1.
- **No per-scrip daily price limits** — drop India's `price_limit` circuit logic.
- **No stamp duty on shares** (abolished). Costs = brokerage + **10% GST on brokerage**.
- **Currency AUD.**

**Recommendation: reuse `GlobalEquityEngine` with `market="au"` rather than write a new
engine file.** `GlobalEquityEngine` already multiplexes `us`/`hk` by a `market` param
(`agent/backtest/engines/global_equity.py:32`); adding an `au` branch (brokerage + GST, AUD,
config-driven rates) is a small delta and matches the us/hk precedent far better than the
India precedent. Only split into a dedicated `AuEquityEngine` if AU mechanics later diverge
enough to make the shared engine unclear.

**Data + benchmark:**
- `source_chain = ["yahoo", "yfinance", "local"]`, `default_source = "yahoo"`. Both vendors
  already pass `.AX` through — the only change is removing `.AX` from the Yahoo loader's
  allowlist gate.
- `benchmark = "^AXJO"` (S&P/ASX 200), fetched via Yahoo.

---

## 6. A separable correctness fix worth noting

The fallback chain resolves **per source, not per symbol**: if Yahoo returns a partial
batch, unmatched ASX tickers are silently dropped rather than retried down the chain
(`yahoo_loader.fetch` omits failures; the chain does not re-drive them per symbol). Fixing
this to retry unmatched symbols down the chain improves robustness for *every* market, not
just ASX. It is independent of the registry work — schedule it separately so it doesn't
block the feature.

---

## 7. Staged implementation plan (with stop points)

**Stage 1 — Registry + classifier consolidation + contract test. No behavior change.**
Add `markets.py` seeded with the existing markets. Migrate the three classifiers and the
benchmark map onto it. Add the contract test. This alone fixes India's benchmark/correlation
gap and removes the triple-classifier duplication, with **zero change** to
China/US/HK/crypto/futures behavior. Fully testable in isolation. **Safe stop point** —
valuable even if ASX were dropped.

**Stage 2 — Migrate routing onto the registry; fail closed.**
Move `FALLBACK_CHAINS`, `_MARKET_TO_SOURCE`, both engine factories, and the loader gates to
read from the registry. Change the unknown-qualified-symbol default to fail loud.

**Stage 3 — Add ASX.**
Add the `au_equity` `MarketSpec`, `GlobalEquityEngine(market="au")`, and the `^AXJO`
benchmark. With the registry in place this is essentially one entry plus a small engine
mode. Add integration tests across detection → loader gate → routing → engine → composite →
benchmark → correlation for `BHP.AX`, including a mixed-market portfolio
(`["BHP.AX", "AAPL.US"]`) through `CompositeEngine`.

**Stage 4 — Optional: per-symbol fallback retry** (Section 6).

**Net result:** the next market — UK `.L`, Canada `.TO`, Japan `.T` — is one `MarketSpec`
entry plus at most an engine mode, and the contract test guarantees it is wired everywhere
before it can merge.

---

## 8. Risks & things to verify while implementing

- **Back-compat imports.** `_detect_market`, `_MARKET_PATTERNS`, `_is_china_futures`,
  `_detect_submarket` are imported elsewhere (`swarm/grounding.py`, tests). Keep the names.
- **The `a_share` default is load-bearing somewhere.** `test_market_detection.py` and
  `composite._rule_for` (`:90`) rely on it. Change the default deliberately, not blindly;
  distinguish "bare numeric → a_share" (keep) from "unknown suffix → a_share" (fail closed).
- **`VALID_SOURCES` is a contract.** It is shared by the config schema and the agent-facing
  backtest tool (`registry.py:33`) and enforced by
  `test_valid_sources_covers_all_registered_loaders`. If ASX needs no new source (it
  doesn't — it reuses `yahoo`/`yfinance`), leave it untouched.
- **Verify current ASX cost/settlement rules** against a live broker schedule before
  trusting absolute cost figures; treat every rate as config-driven, as the India engine
  docstring already warns for SEBI tariffs.
- **Composite mixed-market portfolios** are the sharpest integration test — a missing
  `au_equity` branch in `_build_rule_engines` would surface there, not in the single-market
  path.

---

## 9. One-paragraph summary for whoever reviews the PR

ASX fails because `.AX` matches no classifier rule and silently defaults to `a_share`, which
routes to Chinese data sources that don't serve ASX; the data layer itself already accepts
`.AX`. Rather than copy the India pattern (which is itself half-wired — it was never added to
benchmark or correlation), introduce a single `MarketSpec` registry that every
classification/routing/benchmark surface delegates to, collapse the three duplicate
classifiers into one, make unknown qualified symbols fail loud instead of defaulting to
China, and enforce completeness with a contract test that iterates every market. Land it in
stages: registry + classifier consolidation first (no behavior change, fixes India), then
routing migration, then ASX as a single registry entry plus a `GlobalEquityEngine(market=
"au")` mode benchmarked to `^AXJO`.
