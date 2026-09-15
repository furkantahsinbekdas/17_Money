from fastapi import APIRouter, HTTPException
from services.binance_service import BinanceService
from services.technical import TechnicalService
from services.news_service import NewsService
from services.forecast_service import ForecastService
from services import stochastic_service
from services import signal_decode_service

import config

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

binance = BinanceService()
technical = TechnicalService()
news = NewsService()
forecast_svc = ForecastService()

FORECAST_INTERVALS = config.FORECAST_INTERVALS

# Zaman dilimi → günlük bar sayısı (yıllıklaştırma/difüzyon ölçeklemesi için)
_BARS_PER_DAY = config.BARS_PER_DAY


@router.get("/forecast/{symbol}")
async def forecast(symbol: str = config.SYMBOL):
    """
    17Money Tahmin Motoru (VantagePoint tarzı) — Claude anahtarı GEREKTİRMEZ.
    Yön Endeksi (0-100), kısa/orta/uzun vade vektörleri, tahmini 24s aralık
    ve gösterge katkı dökümü döndürür.
    """
    try:
        analyses = {
            iv: technical.calculate_all(binance.get_klines(symbol, iv, config.KLINE_LIMIT))
            for iv in FORECAST_INTERVALS
        }
        fc = forecast_svc.mtf_forecast(analyses)
        fc["symbol"] = symbol
        fc["current_price"] = analyses[config.DEFAULT_INTERVAL]["current_price"]
        return fc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intermarket/{symbol}")
async def intermarket(symbol: str = config.SYMBOL):
    """
    Intermarket analizi — BTC'nin DXY/VIX/Altın/S&P/Nasdaq ile 90 günlük
    getiri korelasyonları. VantagePoint'in intermarket yaklaşımının karşılığı.
    """
    try:
        df = binance.get_klines(symbol, "1d", config.DAILY_KLINE_LIMIT)
        data = await news.get_intermarket(df["close"])
        return {"symbol": symbol, "piyasalar": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/full/{symbol}")
async def full_analysis(symbol: str = config.SYMBOL,
                        interval: str = config.DEFAULT_INTERVAL):
    """Teknik analiz + makro bağlam + haberler."""
    try:
        df = binance.get_klines(symbol, interval, config.BROADCAST_KLINE_LIMIT)
        tech = technical.calculate_all(df)
        funding = binance.get_funding_rate(symbol)
        macro = await news.get_macro_data()
        fg = await news.get_fear_greed()

        return {
            "symbol": symbol,
            "interval": interval,
            "technical": tech,
            "macro": macro,
            "fear_greed": fg,
            "funding_rate": funding,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stochastic/{symbol}")
async def stochastic(symbol: str = config.SYMBOL,
                     interval: str = config.DEFAULT_INTERVAL,
                     limit: int = config.SCIENCE_KLINE_LIMIT):
    """
    Stokastik matematik motoru — rastgeleliğin matematiği.

    Bachelier random-walk testi (Hurst), getiri dağılımı (kalın kuyruk),
    GBM sürüklenme/difüzyon, Yang-Zhang volatilite, GARCH(1,1) volatilite
    tahmini ve volatilite rejimi. Teknik analizden BAĞIMSIZ bir bilimsel
    katmandır; tahmin yeteneğine olasılık+volatilite boyutu ekler.
    """
    try:
        df = binance.get_klines(symbol, interval, min(max(limit, config.SCIENCE_KLINE_MIN), config.BINANCE_MAX_KLINES_PER_CALL))
        bpd = _BARS_PER_DAY.get(interval, 24)
        # Ufuk: ~1 günlük projeksiyon (bar cinsinden)
        horizon = max(int(bpd), 1)
        result = stochastic_service.full_analysis(df, horizon_bars=horizon, bars_per_day=bpd)
        # Örüntü çözme / deşifre katmanını da ekle (FFT, otokorelasyon, entropi)
        result["cozme"] = signal_decode_service.full_decode(df["close"])
        result["symbol"] = symbol
        result["interval"] = interval
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/structure/{symbol}")
async def market_structure(symbol: str = config.SYMBOL, interval: str = "4h"):
    """SMC yapı analizi: OB, FVG, likidite, BOS/CHoCH."""
    try:
        df = binance.get_klines(symbol, interval, config.INTERMARKET_KLINE_LIMIT)
        tech = technical.calculate_all(df)
        return {
            "symbol": symbol,
            "interval": interval,
            "order_blocks": tech["order_blocks"],
            "fvg": tech["fvg"],
            "liquidity": tech["liquidity"],
            "structure": tech["structure"],
            "current_price": tech["current_price"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
