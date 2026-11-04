"""
FinGen v2 — Portfolio Repository (Report #10)
"""

from typing import List, Optional, Dict
from uuid import UUID
from datetime import date

from core.db.repos.base import BaseRepo


class PortfolioRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("portfolios", use_service_key)
    
    def create_portfolio(self, user_id: UUID, name: str, **kwargs) -> dict:
        data = {"user_id": str(user_id), "name": name, **kwargs}
        return self.create(data)
    
    def get_by_user(self, user_id: UUID) -> List[dict]:
        return self.list({"user_id": str(user_id)}, order_by="created_at", desc=True)


class HoldingRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("holdings", use_service_key)
    
    def upsert_holding(self, portfolio_id: UUID, user_id: UUID, ticker: str, **kwargs) -> dict:
        data = {
            "portfolio_id": str(portfolio_id),
            "user_id": str(user_id),
            "ticker": ticker,
            **kwargs
        }
        result = self.client.table(self.table).upsert(
            data, on_conflict="portfolio_id,ticker"
        ).execute()
        return result.data[0] if result.data else {}
    
    def get_by_portfolio(self, portfolio_id: UUID) -> List[dict]:
        return self.list({"portfolio_id": str(portfolio_id)}, order_by="ticker")
    
    def update_price(self, holding_id: UUID, current_price: float, current_value: float, unrealized_pnl: float, unrealized_pnl_pct: float) -> dict:
        data = {
            "current_price": current_price,
            "current_value": current_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "last_price_update": "now()",
        }
        return self.update(holding_id, data)


class TransactionRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("transactions", use_service_key)
    
    def add_transaction(self, portfolio_id: UUID, user_id: UUID, ticker: str, **kwargs) -> dict:
        data = {
            "portfolio_id": str(portfolio_id),
            "user_id": str(user_id),
            "ticker": ticker,
            **kwargs
        }
        return self.create(data)
    
    def get_by_portfolio(self, portfolio_id: UUID, limit: int = 100) -> List[dict]:
        return self.list({"portfolio_id": str(portfolio_id)}, order_by="trade_date", desc=True, limit=limit)


class PriceRepo(BaseRepo):
    def __init__(self, use_service_key: bool = True):
        super().__init__("price_history", use_service_key)
    
    def bulk_upsert_prices(self, prices: List[Dict]) -> int:
        """Bulk upsert price data."""
        if not prices:
            return 0
        try:
            result = self.client.table(self.table).upsert(
                prices,
                on_conflict="ticker,exchange,date"
            ).execute()
            return len(result.data) if result.data else 0
        except Exception as e:
            logger.error(f"Bulk upsert prices failed: {e}")
            raise
    
    def get_latest_price(self, ticker: str, exchange: str = None) -> Optional[dict]:
        query = self.client.table(self.table).select("*").eq("ticker", ticker).order("date", desc=True).limit(1)
        if exchange:
            query = query.eq("exchange", exchange)
        result = query.execute()
        return result.data[0] if result.data else None
    
    def get_price_series(self, ticker: str, exchange: str = None, start_date: date = None, end_date: date = None) -> List[dict]:
        query = self.client.table(self.table).select("*").eq("ticker", ticker)
        if exchange:
            query = query.eq("exchange", exchange)
        if start_date:
            query = query.gte("date", start_date.isoformat())
        if end_date:
            query = query.lte("date", end_date.isoformat())
        query = query.order("date", desc=False)
        result = query.execute()
        return result.data or []
    
    def get_prices_for_tickers(self, tickers: List[str], date: date = None) -> Dict[str, float]:
        """Get prices for multiple tickers on a specific date (or latest)."""
        query = self.client.table(self.table).select("ticker,close,date").in_("ticker", tickers)
        if date:
            query = query.eq("date", date.isoformat())
        else:
            query = query.order("date", desc=True)
        result = query.execute()
        
        prices = {}
        for row in result.data or []:
            ticker = row["ticker"]
            if ticker not in prices:
                prices[ticker] = float(row["close"])
        return prices


import logging
logger = logging.getLogger(__name__)