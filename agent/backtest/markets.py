"""Single source of truth for symbol -> market classification and routing.

Stage 1 of the first-class-markets registry described in
``docs/design/first-class-markets-and-asx.md`` consolidated the symbol
pattern table that was previously duplicated (and had drifted out of
sync) across ``_market_hooks.py``, ``benchmark.py``, and
``correlation.py``.

Stage 2 extends ``MarketSpec`` with ``source_chain``/``default_source`` so
``registry.FALLBACK_CHAINS`` and ``runner._MARKET_TO_SOURCE`` derive from
this module instead of holding their own copies. Engine selection and
loader-gate allowlists still live in their own modules (``runner.py``,
``composite.py``, the loader modules) — the branching logic there is
market-specific enough that folding it into a generic callable would trade
a handful of explicit ``if`` branches for an equally-sized layer of
indirection, so it is left as-is and only extended per market.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Pattern, Tuple


class UnsupportedMarketError(ValueError):
    """Raised when a symbol carries a market-qualifying suffix that no
    registered ``MarketSpec`` recognizes (e.g. a typo, or a market not yet
    onboarded). Distinct from a bare/unqualified code, which is genuinely
    ambiguous and keeps the legacy ``a_share`` default."""


@dataclass(frozen=True)
class MarketSpec:
    key: str
    patterns: Tuple[Pattern[str], ...]
    benchmark: Optional[str]  # None means deliberately no benchmark (e.g. forex)
    source_chain: Tuple[str, ...] = field(default_factory=tuple)
    default_source: Optional[str] = None


def _p(pattern: str, flags: int = re.I) -> Pattern[str]:
    return re.compile(pattern, flags)


# Order matters: patterns are tried in registry order and the first match
# wins, matching the precedence of the original ``_MARKET_PATTERNS`` list.
MARKET_REGISTRY: dict[str, MarketSpec] = {
    "a_share": MarketSpec(
        key="a_share",
        patterns=(
            _p(r"^\d{6}\.(SZ|SH|BJ)$"),
            _p(r"^(51|15|56)\d{4}\.(SZ|SH)$"),
        ),
        benchmark="000300.SH",  # CSI 300 (China A-share core index)
        source_chain=("tencent", "mootdx", "eastmoney", "baostock", "akshare", "tushare", "local"),
        default_source="tushare",
    ),
    "us_equity": MarketSpec(
        key="us_equity",
        patterns=(_p(r"^[A-Z]+\.US$"),),
        benchmark="SPY",
        source_chain=("yahoo", "stooq", "sina", "eastmoney", "yfinance", "tiingo", "fmp", "finnhub", "alphavantage", "longbridge", "akshare", "local"),
        default_source="yfinance",
    ),
    "hk_equity": MarketSpec(
        key="hk_equity",
        patterns=(_p(r"^\d{3,5}\.HK$"),),
        benchmark="HK.03100",  # Hang Seng China Enterprises ETF
        source_chain=("eastmoney", "yahoo", "futu", "yfinance", "akshare", "longbridge", "local"),
        default_source="yfinance",
    ),
    "india_equity": MarketSpec(
        key="india_equity",
        # NSE (RELIANCE.NS) / BSE (500325.BO); tickers may carry '&' and '-'
        # (e.g. M&M.NS, BAJAJ-AUTO.NS).
        patterns=(_p(r"^[A-Z0-9&.\-]+\.(NS|BO)$"),),
        benchmark="^NSEI",  # Nifty 50 — previously missing from MARKET_BENCHMARKS
        source_chain=("yahoo", "yfinance", "india_broker", "local"),
        default_source="yahoo",
    ),
    "au_equity": MarketSpec(
        key="au_equity",
        # ASX (BHP.AX, CBA.AX); Yahoo/yfinance both accept the suffix verbatim.
        patterns=(_p(r"^[A-Z0-9]+\.AX$"),),
        benchmark="^AXJO",  # S&P/ASX 200
        source_chain=("yahoo", "yfinance", "local"),
        default_source="yahoo",
    ),
    "crypto": MarketSpec(
        key="crypto",
        patterns=(_p(r"^[A-Z]+-USDT$"), _p(r"^[A-Z]+/USDT$")),
        benchmark="BTC-USDT",
        source_chain=("okx", "binance", "ccxt", "yfinance", "local"),
        default_source="okx",
    ),
    "futures": MarketSpec(
        key="futures",
        patterns=(
            # China futures: product+delivery.exchange (e.g. IF2406.CFFEX, rb2410.SHFE)
            _p(r"^[A-Za-z]{1,2}\d{3,4}\.(ZCE|DCE|SHFE|INE|CFFEX|GFEX)$"),
            # Global futures: product+month-code (e.g. ESZ4, CLF25, GCM2025)
            _p(r"^[A-Z]{2,4}[FGHJKMNQUVXZ]\d{1,2}$"),
            # Global futures: product+YYMM (e.g. CL2412, ES2503)
            _p(r"^[A-Z]{2,4}\d{4}$"),
            # Global futures: bare product code with exchange (e.g. ES.CME)
            _p(r"^[A-Z]{2,4}\.(CME|CBOT|NYMEX|COMEX|ICE|EUREX)$"),
        ),
        benchmark="ES.CME",  # E-mini S&P 500 futures
        source_chain=("tushare", "akshare", "local"),
        default_source="tushare",
    ),
    "forex": MarketSpec(
        key="forex",
        patterns=(_p(r"^[A-Z]{3}/[A-Z]{3}$", 0), _p(r"^[A-Z]{6}\.FX$", 0)),
        benchmark=None,  # no universal benchmark
        source_chain=("akshare", "yfinance", "local"),
        default_source="akshare",
    ),
}

# Suffix-qualified but unrecognized (e.g. "FOO.L", a typo, or a market not
# yet onboarded) — used by classify_strict() to fail closed instead of
# silently defaulting to a_share. Deliberately narrower than "contains a
# dot": bare numeric/alpha codes with no suffix are genuinely ambiguous and
# keep the legacy a_share default (test_market_detection.py pins this).
_QUALIFIED_SUFFIX_RE = re.compile(r"^[A-Z0-9&\-]+\.[A-Z]{1,6}$", re.I)


def classify(code: str) -> Optional[str]:
    """Match ``code`` against every registered pattern, in registry order.

    Returns the market key, or ``None`` if no pattern matches (bare numeric
    codes, unqualified tickers, typos, etc.) — callers apply their own
    source-aware fallback for these, since a bare code is genuinely
    ambiguous without knowing which data source it came from.
    """
    for key, spec in MARKET_REGISTRY.items():
        for pattern in spec.patterns:
            if pattern.match(code):
                return key
    return None


def classify_strict(code: str) -> str:
    """Classify ``code`` for auto-mode routing, failing closed on typos.

    Same as ``classify()`` for anything a registered ``MarketSpec`` matches.
    For codes that carry a market-qualifying suffix (``FOO.XY``) but match no
    registered pattern, raises ``UnsupportedMarketError`` instead of silently
    routing to ``a_share`` — this is what stopped ``BHP.AX`` from failing
    opaquely against Chinese data sources (see design doc section 1/4.2).
    Bare/unqualified codes remain ambiguous by design and keep the legacy
    ``a_share`` default.
    """
    market = classify(code)
    if market is not None:
        return market
    if _QUALIFIED_SUFFIX_RE.match(code.strip()):
        raise UnsupportedMarketError(
            f"Unsupported market for symbol {code!r}: no registered market "
            "recognizes this suffix. Check for a typo, or this market needs "
            "a MarketSpec entry in backtest/markets.py."
        )
    return "a_share"
