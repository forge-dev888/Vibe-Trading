"""Single source of truth for symbol -> market classification.

Stage 1 of the first-class-markets registry described in
``docs/design/first-class-markets-and-asx.md``. Consolidates the symbol
pattern table that was previously duplicated (and had drifted out of
sync) across ``_market_hooks.py``, ``benchmark.py``, and
``correlation.py``.

Routing (fallback chains, engine factories, loader gates) still lives in
``runner.py`` / ``registry.py`` / the loader modules; migrating those onto
this registry is a later stage. This module owns classification and the
market -> benchmark ticker mapping only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern, Tuple


@dataclass(frozen=True)
class MarketSpec:
    key: str
    patterns: Tuple[Pattern[str], ...]
    benchmark: Optional[str]  # None means deliberately no benchmark (e.g. forex)


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
    ),
    "us_equity": MarketSpec(
        key="us_equity",
        patterns=(_p(r"^[A-Z]+\.US$"),),
        benchmark="SPY",
    ),
    "hk_equity": MarketSpec(
        key="hk_equity",
        patterns=(_p(r"^\d{3,5}\.HK$"),),
        benchmark="HK.03100",  # Hang Seng China Enterprises ETF
    ),
    "india_equity": MarketSpec(
        key="india_equity",
        # NSE (RELIANCE.NS) / BSE (500325.BO); tickers may carry '&' and '-'
        # (e.g. M&M.NS, BAJAJ-AUTO.NS).
        patterns=(_p(r"^[A-Z0-9&.\-]+\.(NS|BO)$"),),
        benchmark="^NSEI",  # Nifty 50 — previously missing from MARKET_BENCHMARKS
    ),
    "crypto": MarketSpec(
        key="crypto",
        patterns=(_p(r"^[A-Z]+-USDT$"), _p(r"^[A-Z]+/USDT$")),
        benchmark="BTC-USDT",
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
    ),
    "forex": MarketSpec(
        key="forex",
        patterns=(_p(r"^[A-Z]{3}/[A-Z]{3}$", 0), _p(r"^[A-Z]{6}\.FX$", 0)),
        benchmark=None,  # no universal benchmark
    ),
}


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
