"""Stage 1 contract test for backtest/markets.py.

Verifies the three previously-independent classifiers (_market_hooks,
benchmark, correlation) now agree with the shared registry, and that the
India benchmark/correlation gap identified in
docs/design/first-class-markets-and-asx.md is closed.
"""

from __future__ import annotations

import pytest

from backtest.markets import MARKET_REGISTRY, classify
from backtest.engines._market_hooks import _detect_market
from backtest.benchmark import MARKET_BENCHMARKS, _infer_market
from backtest.correlation import infer_market as correlation_infer_market


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
