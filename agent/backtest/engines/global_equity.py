"""Global equity (US / HK / AU) backtest engine.

Market rules:
  US:
    - T+0, long/short allowed
    - Zero commission (retail brokers)
    - Fractional shares supported (round to 0.01)
    - Low slippage (high liquidity)
  HK:
    - T+0, long/short allowed
    - Stamp tax 0.1% bilateral + levies
    - Lot-size rounding (simplified to 100 shares)
    - Higher slippage than US
  AU (ASX):
    - T+0 intraday trading allowed (unlike India's T+1 delivery rule)
    - Long/short allowed (covered short; fine for a daily-bar model)
    - Decimal share sizing, lot size 1 — no board-lot rounding
    - No per-scrip daily price limits (unlike India's circuit bands)
    - No stamp duty on shares (abolished); cost = brokerage + 10% GST on
      brokerage. Rates are config-driven placeholders — verify against a
      live ASX broker schedule before trusting absolute cost figures (see
      docs/design/first-class-markets-and-asx.md section 8).

India (NSE/BSE) is handled by the dedicated ``backtest.engines.india_equity``
``IndiaEquityEngine`` (T+1 delivery, circuit bands, STT/stamp/GST stack) —
AU is mechanically closer to US/HK than to India, so it lives here instead.
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """US / HK / AU equity engine, selected by *market* parameter.

    Config keys:
      - slippage_us: default 0.0005
      - slippage_hk: default 0.001
      - hk_stamp_tax: default 0.001 (0.1% bilateral)
      - hk_commission: default 0.00015 (万1.5)
      - hk_levy: default 0.0000565 (SFC + FRC)
      - hk_settlement: default 0.00002 (CCASS)
      - slippage_au: default 0.0007
      - au_commission: default 0.001 (0.1% brokerage)
      - au_gst: default 0.10 (10% GST on brokerage)
    """

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market

        # US defaults
        self.slippage_us: float = config.get("slippage_us", 0.0005)
        # HK defaults
        self.slippage_hk: float = config.get("slippage_hk", 0.001)
        self.hk_stamp_tax: float = config.get("hk_stamp_tax", 0.001)
        self.hk_commission: float = config.get("hk_commission", 0.00015)
        self.hk_levy: float = config.get("hk_levy", 0.0000565)
        self.hk_settlement: float = config.get("hk_settlement", 0.00002)
        # AU defaults
        self.slippage_au: float = config.get("slippage_au", 0.0007)
        self.au_commission: float = config.get("au_commission", 0.001)
        self.au_gst: float = config.get("au_gst", 0.10)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """US/HK/AU: T+0, both directions allowed."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """US/AU: fractional shares (0.01). HK: 100-share lots."""
        if self.market == "hk":
            return max(int(raw_size / 100) * 100, 0)
        return round(max(raw_size, 0.0), 2)

    def calc_commission(self, size: float, price: float, _direction: int, is_open: bool) -> float:
        """US: zero commission. HK: stamp tax + levies. AU: brokerage + GST.

        ``_direction`` is unused — reserved for future short-borrow fees
        (US Reg-T margin, HK SBL costs).
        """
        notional = size * price
        if self.market == "hk":
            comm = notional * self.hk_commission       # broker commission
            comm += notional * self.hk_stamp_tax       # stamp tax bilateral
            comm += notional * self.hk_levy            # SFC + FRC levies
            comm += notional * self.hk_settlement      # CCASS settlement
            return comm
        if self.market == "au":
            brokerage = notional * self.au_commission
            gst = brokerage * self.au_gst               # 10% GST on brokerage
            return brokerage + gst                       # no stamp duty (abolished)
        # US: zero commission (SEC fee negligible)
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        """US: low slippage. HK: moderate slippage. AU: moderate slippage."""
        if self.market == "hk":
            rate = self.slippage_hk
        elif self.market == "au":
            rate = self.slippage_au
        else:
            rate = self.slippage_us
        return price * (1 + direction * rate)
