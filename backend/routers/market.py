from fastapi import APIRouter, HTTPException
from services.binance_service import BinanceService
from services.technical import TechnicalService

import config

router = APIRouter(prefix="/api/market", tags=["market"])

binance = BinanceService()
technical = TechnicalService()


@router.get("/btc")
async def get_btc_data(interval: str = config.DEFAULT_INTERVAL,
                       limit: int = config.BROADCAST_KLINE_LIMIT):
    """BTC/USDT teknik analiz verisi — ana endpoint."""
    try:
        df = binance.get_klines(config.SYMBOL, interval, limit)
        analysis = technical.calculate_all(df)
        ticker = binance.get_ticker(config.SYMBOL)
        funding = binance.get_funding_rate(config.SYMBOL)
        oi = binance.get_open_interest(config.SYMBOL)

        return {
            "symbol": config.SYMBOL,
            "interval": interval,
            "ticker": ticker,
            "technical": analysis,
            "funding_rate": funding,
            "open_interest": oi,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/klines")
async def get_klines(symbol: str = config.SYMBOL,
                     interval: str = config.DEFAULT_INTERVAL,
                     limit: int = config.BROADCAST_KLINE_LIMIT):
    """Ham OHLCV mum verisi — grafik çizmek için."""
    try:
        df = binance.get_klines(symbol, interval, limit)
        df = df.reset_index()
        df["open_time"] = df["open_time"].astype(str)
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Anlık fiyat ve 24 saatlik özet."""
    try:
        return binance.get_ticker(symbol.upper())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str, limit: int = config.ORDERBOOK_LIMIT):
    """Emir defteri."""
    try:
        return binance.get_orderbook(symbol.upper(), limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
