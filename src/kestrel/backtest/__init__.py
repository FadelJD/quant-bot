"""Event-driven backtester: decisions at bar close, fills at next open, realistic costs."""

from kestrel.backtest.engine import Backtester, BacktestResult
from kestrel.backtest.fills import FillModel, FillResult
from kestrel.backtest.portfolio import Portfolio, Trade

__all__ = ["BacktestResult", "Backtester", "FillModel", "FillResult", "Portfolio", "Trade"]
