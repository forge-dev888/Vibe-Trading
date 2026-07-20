"""Contract test for backtest/markets.py.

Stage 1 verified the three previously-independent classifiers
(_market_hooks, benchmark, correlation) agree with the shared registry, and
that the India benchmark/correlation gap identified in
docs/design/first-class-markets-and-asx.md is closed.

Stage 2/3 extend this to the routing surfaces described in the design doc
section 4.3: every registered market must have a non-empty, source-valid
fallback chain, at least one loader that will actually accept a sample
symbol for it, and the registry-derived FALLBACK_CHAINS/_MARKET_TO_SOURCE
must agree with the registry itself. This is the enforcement that keeps a
market from landing "half-wired like India" again.
"""

from __future__ import annotations

import pytest

from backtest.markets import MARKET_REGISTRY, classify, classify_strict, UnsupportedMarketError
from backtest.engines._market_hooks import _detect_market
from backtest.benchmark import MARKET_BENCHMARKS, _infer_market
from backtest.correlation import infer_market as correlation_infer_market
from backtest.loaders.registry import FALLBACK_CHAINS, VALID_SOURCES, LOADER_REGISTRY, _ensure_registered
from backtest.runner import _MARKET_TO_SOURCE


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestRegistryCompleteness:
    def test_every_market_has_a_benchmark_entry(self) -> None:
        # forex is allowed to be None; every other market must have a ticker.
        for key, spec in MARKET_REGISTRY.items():
            assert key in MARKET_BENCHMARKS
            if key != "forex":
                assert spec.benchmark is not None

    def test_india_equity_registered(self) -> None:
        # The gap called out in the design doc: india_equity previously had
        # no benchmark entry and no correlation classification.
        assert "india_equity" in MARKET_REGISTRY
        assert MARKET_BENCHMARKS["india_equity"] == "^NSEI"


# ---------------------------------------------------------------------------
# Cross-classifier agreement for registry-covered symbols
# ---------------------------------------------------------------------------


REGISTRY_COVERED_CODES = [
    "000001.SZ",
    "600519.SH",
    "830799.BJ",
    "AAPL.US",
    "0700.HK",
    "RELIANCE.NS",
    "500325.BO",
    "BHP.AX",
    "BTC-USDT",
    "IF2406.CFFEX",
    "EUR/USD",
]


class TestClassifierAgreement:
    @pytest.mark.parametrize("code", REGISTRY_COVERED_CODES)
    def test_detect_market_matches_registry(self, code: str) -> None:
        assert _detect_market(code) == classify(code)

    @pytest.mark.parametrize("code", REGISTRY_COVERED_CODES)
    def test_correlation_infer_market_matches_registry(self, code: str) -> None:
        assert correlation_infer_market(code) == classify(code)

    @pytest.mark.parametrize(
        "code",
        [c for c in REGISTRY_COVERED_CODES if c != "EUR/USD"],  # forex has no benchmark source path
    )
    def test_benchmark_infer_market_matches_registry(self, code: str) -> None:
        assert _infer_market([code], source="") == classify(code)


# ---------------------------------------------------------------------------
# India gap closed end-to-end
# ---------------------------------------------------------------------------


class TestIndiaGapClosed:
    def test_india_no_longer_falls_back_to_us_equity_in_benchmark(self) -> None:
        assert _infer_market(["RELIANCE.NS"], source="yahoo") == "india_equity"

    def test_india_no_longer_falls_back_to_us_equity_in_correlation(self) -> None:
        assert correlation_infer_market("RELIANCE.NS") == "india_equity"


# ---------------------------------------------------------------------------
# Stage 2: routing completeness (design doc section 4.3)
# ---------------------------------------------------------------------------


class TestRoutingCompleteness:
    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_source_chain_non_empty(self, key: str) -> None:
        spec = MARKET_REGISTRY[key]
        assert spec.source_chain, f"{key} has an empty source_chain"

    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_source_chain_names_are_valid_sources(self, key: str) -> None:
        spec = MARKET_REGISTRY[key]
        for name in spec.source_chain:
            assert name in VALID_SOURCES, f"{key} source_chain has unknown source {name!r}"

    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_default_source_is_in_its_own_chain(self, key: str) -> None:
        spec = MARKET_REGISTRY[key]
        assert spec.default_source in spec.source_chain

    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_fallback_chains_matches_registry(self, key: str) -> None:
        assert FALLBACK_CHAINS[key] == list(MARKET_REGISTRY[key].source_chain)

    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_market_to_source_matches_registry(self, key: str) -> None:
        assert _MARKET_TO_SOURCE[key] == MARKET_REGISTRY[key].default_source

    @pytest.mark.parametrize("key", list(MARKET_REGISTRY.keys()))
    def test_at_least_one_loader_accepts_the_market(self, key: str) -> None:
        # Every market must be reachable by at least one loader in its own
        # chain — otherwise a source_chain entry is dead, unreachable
        # configuration (the bug this registry exists to prevent).
        _ensure_registered()
        chain = MARKET_REGISTRY[key].source_chain
        accepting = [
            name for name in chain
            if name in LOADER_REGISTRY and key in getattr(LOADER_REGISTRY[name], "markets", set())
        ]
        assert accepting, f"{key}: no loader in {chain} declares it in .markets"


# ---------------------------------------------------------------------------
# Stage 2: fail-closed auto-mode classification
# ---------------------------------------------------------------------------


class TestFailClosedClassification:
    def test_registered_market_classifies_normally(self) -> None:
        assert classify_strict("BHP.AX") == "au_equity"

    def test_bare_unqualified_code_still_defaults_to_a_share(self) -> None:
        # Genuinely ambiguous (no suffix) — legacy behavior, pinned by
        # test_market_detection.py too.
        assert classify_strict("UNKNOWN") == "a_share"
        assert classify_strict("random-string") == "a_share"

    def test_unknown_qualified_suffix_fails_closed(self) -> None:
        with pytest.raises(UnsupportedMarketError):
            classify_strict("FOO.ZZ")


# ---------------------------------------------------------------------------
# Stage 3: ASX (au_equity) onboarded correctly
# ---------------------------------------------------------------------------


class TestAuEquityOnboarded:
    def test_au_equity_registered(self) -> None:
        assert "au_equity" in MARKET_REGISTRY
        assert MARKET_BENCHMARKS["au_equity"] == "^AXJO"

    def test_bhp_ax_classifies_as_au_equity_everywhere(self) -> None:
        assert _detect_market("BHP.AX") == "au_equity"
        assert classify("BHP.AX") == "au_equity"
        assert correlation_infer_market("BHP.AX") == "au_equity"
        assert _infer_market(["BHP.AX"], source="yahoo") == "au_equity"

    def test_au_equity_routes_through_yahoo_yfinance(self) -> None:
        assert MARKET_REGISTRY["au_equity"].source_chain[0] == "yahoo"
        assert "yfinance" in MARKET_REGISTRY["au_equity"].source_chain
        assert "local" in MARKET_REGISTRY["au_equity"].source_chain
