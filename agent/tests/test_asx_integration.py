"""End-to-end integration coverage for ASX (au_equity) support.

Design doc: docs/design/first-class-markets-and-asx.md section 8. Proves
BHP.AX flows through the full pipeline the way the pre-existing markets do:
detection -> loader gate -> routing -> engine -> composite -> benchmark ->
correlation. All data is in-memory; no network access.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.benchmark import MARKET_BENCHMARKS, _infer_market
from backtest.correlation import infer_market as correlation_infer_market
from backtest.engines._market_hooks import _detect_market
from backtest.engines.composite import CompositeEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.loaders.yahoo_loader import DataLoader as YahooLoader
from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader
from backtest.runner import _create_market_engine, _group_codes_by_market


def _asx_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-04-01", periods=5)
    return pd.DataFrame(
        {
            "open": [40.0, 40.5, 41.0, 41.5, 42.0],
            "high": [40.5, 41.0, 41.5, 42.0, 42.5],
            "low": [39.5, 40.0, 40.5, 41.0, 41.5],
            "close": [40.5, 41.0, 41.5, 42.0, 42.5],
            "volume": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
        index=dates,
    )


def _us_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-04-01", periods=5)
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 106.0, 108.0],
            "high": [101.0, 103.0, 105.0, 107.0, 109.0],
            "low": [99.0, 101.0, 103.0, 105.0, 107.0],
            "close": [102.0, 104.0, 106.0, 108.0, 110.0],
            "volume": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
        index=dates,
    )


class _FakeLoader:
    def __init__(self, bars_by_code: dict[str, pd.DataFrame]) -> None:
        self._bars_by_code = bars_by_code

    def fetch(self, codes, *args, **kwargs):
        return {c: self._bars_by_code[c].copy() for c in codes if c in self._bars_by_code}


class _LongSignal:
    """Allocate fully long, split equally across all instruments, every bar."""

    def generate(self, data_map):
        signals = {}
        weight = 1.0 / len(data_map)
        for code, df in data_map.items():
            signals[code] = pd.Series(weight, index=df.index)
        return signals


class TestBhpAxDetectionAndRouting:
    def test_detected_as_au_equity(self) -> None:
        assert _detect_market("BHP.AX") == "au_equity"

    def test_groups_by_market_without_raising(self) -> None:
        groups = _group_codes_by_market(["BHP.AX"])
        assert groups == {"au_equity": ["BHP.AX"]}

    def test_yahoo_loader_accepts_ax_suffix(self) -> None:
        loader = YahooLoader()
        assert "au_equity" in loader.markets

    def test_yfinance_loader_accepts_ax_suffix(self) -> None:
        loader = YfinanceLoader()
        assert "au_equity" in loader.markets

    def test_single_market_routes_to_global_equity_engine(self) -> None:
        engine = _create_market_engine("yahoo", {"initial_cash": 1_000_000}, ["BHP.AX"])
        assert isinstance(engine, GlobalEquityEngine)
        assert engine.market == "au"


class TestBhpAxBenchmarkAndCorrelation:
    def test_benchmark_infers_au_equity(self) -> None:
        assert _infer_market(["BHP.AX"], source="yahoo") == "au_equity"
        assert MARKET_BENCHMARKS["au_equity"] == "^AXJO"

    def test_correlation_infers_au_equity(self) -> None:
        assert correlation_infer_market("BHP.AX") == "au_equity"


class TestBhpAxBacktestSmoke:
    def test_au_backtest_completes_and_emits_run_card(self, tmp_path: Path) -> None:
        engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="au")
        loader = _FakeLoader({"BHP.AX": _asx_bars()})
        metrics = engine.run_backtest(
            {
                "codes": ["BHP.AX"],
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "yahoo",
                "initial_cash": 1_000_000,
            },
            loader,
            _LongSignal(),
            tmp_path,
        )

        assert metrics
        assert (tmp_path / "run_card.json").exists()
        assert metrics.get("final_value") is not None
        assert metrics["trade_count"] >= 1

    def test_au_costs_are_applied_vs_zero_commission_us(self, tmp_path: Path) -> None:
        """Same price path; AU pays brokerage + GST, US pays nothing."""
        au_engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="au")
        us_engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")

        au_metrics = au_engine.run_backtest(
            {
                "codes": ["BHP.AX"],
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "yahoo",
                "initial_cash": 1_000_000,
            },
            _FakeLoader({"BHP.AX": _asx_bars()}),
            _LongSignal(),
            tmp_path / "au",
        )
        us_metrics = us_engine.run_backtest(
            {
                "codes": ["AAPL.US"],
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "yahoo",
                "initial_cash": 1_000_000,
            },
            _FakeLoader({"AAPL.US": _asx_bars()}),
            _LongSignal(),
            tmp_path / "us",
        )

        assert au_metrics["final_value"] < us_metrics["final_value"]


class TestMixedMarketComposite:
    def test_bhp_ax_and_aapl_us_route_to_composite_engine(self) -> None:
        engine = _create_market_engine(
            "yahoo", {"initial_cash": 1_000_000}, ["BHP.AX", "AAPL.US"],
        )
        assert isinstance(engine, CompositeEngine)

    def test_composite_backtest_runs_both_markets(self, tmp_path: Path) -> None:
        codes = ["BHP.AX", "AAPL.US"]
        engine = CompositeEngine({"initial_cash": 1_000_000}, codes)
        loader = _FakeLoader({"BHP.AX": _asx_bars(), "AAPL.US": _us_bars()})

        metrics = engine.run_backtest(
            {
                "codes": codes,
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "source": "yahoo",
                "initial_cash": 1_000_000,
            },
            loader,
            _LongSignal(),
            tmp_path,
        )

        assert metrics
        assert (tmp_path / "run_card.json").exists()
        assert metrics["trade_count"] >= 2
        # Both sub-engines were actually instantiated and used.
        assert set(engine._rule_engines.keys()) == {"au_equity", "us_equity"}
