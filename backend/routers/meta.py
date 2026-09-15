"""
Meta-labeling endpoint'leri — Sprint 4.

Akış:
1. POST /api/meta/backfill  → tarihsel sinyal + etiket üretimi (bir kez)
2. POST /api/meta/train     → meta-model eğitimi (yeterli etiket birikince)
3. GET  /api/ai/signal      → canlı sinyaller otomatik loglanır + skorlanır
4. POST /api/meta/resolve   → açık canlı sinyallerin sonuçlarını günceller
   (arka planda da periyodik çalışır)
"""

from fastapi import APIRouter, HTTPException

from services.binance_service import BinanceService, BinanceUnreachable
from services.signal_store import SignalStore
from services.backfill_service import run_backfill
from services.meta_model import meta_model

import config

router = APIRouter(prefix="/api/meta", tags=["meta"])

binance = BinanceService()
store = SignalStore()


@router.post("/download-history")
async def download_history(symbol: str = config.SYMBOL,
                           interval: str = config.DEFAULT_INTERVAL):
    """
    data.binance.vision'dan TÜM BTC geçmişini indirir (2017→bugün), tek
    sıkıştırılmış parquet'e saklar. Ağ engelinden etkilenmez (statik arşiv)."""
    import asyncio
    from services.history_downloader import download_full_history
    try:
        return await asyncio.to_thread(download_full_history, symbol, interval, False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history-info")
async def history_info_endpoint(symbol: str = config.SYMBOL,
                                interval: str = config.DEFAULT_INTERVAL):
    """Kayıtlı geçmiş özeti (indirildi mi, kaç satır, tarih aralığı)."""
    from services.history_downloader import history_info
    return history_info(symbol, interval)


@router.post("/backfill")
async def backfill(symbol: str = config.SYMBOL,
                   interval: str = config.DEFAULT_INTERVAL,
                   limit: int = config.BINANCE_MAX_KLINES_PER_CALL,
                   use_history: bool = False):
    """
    Tarihsel veriden etiketli eğitim örnekleri üretir (idempotent).
    use_history=true → indirilmiş TÜM geçmişi kullanır (on binlerce örnek)."""
    import asyncio
    try:
        result = await asyncio.to_thread(
            run_backfill, binance, store,
            symbol=symbol, interval=interval, limit=limit, use_history=use_history)
        return {"symbol": symbol, "interval": interval, **result}
    except BinanceUnreachable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/train")
async def train():
    """Etiketli verilerle meta-modeli eğitir; walk-forward test raporu döner."""
    try:
        X, y = store.labeled_dataset()
        return meta_model.train(X, y)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trainer-status")
async def trainer_status_endpoint():
    """Şampiyon-Meydan Okuyan eğitim durumu (frontend kartı)."""
    from services.trainer_service import trainer_status
    return trainer_status()


@router.post("/training/start")
async def training_start():
    """Kullanıcı kontrollü sürekli eğitimi başlatır."""
    from services.training_controller import training_controller
    return training_controller.start()


@router.post("/training/stop")
async def training_stop():
    """Eğitimi durdurur ve backtest raporu döndürür."""
    import asyncio
    from services.training_controller import training_controller
    return await asyncio.to_thread(training_controller.stop)


@router.get("/training/status")
async def training_status():
    """Eğitim durumu (çalışıyor mu, tur sayısı, son rapor)."""
    from services.training_controller import training_controller
    return training_controller.status()


@router.post("/backtest")
async def backtest_endpoint():
    """Anlık backtest raporu (tek pencere — hızlı bakış)."""
    import asyncio
    from services.backtest_service import run_backtest
    return await asyncio.to_thread(run_backtest, store)


@router.post("/robust-backtest")
async def robust_backtest_endpoint(periods: int = 5):
    """
    SAĞLAM çoklu-pencere backtest + gerçekçi maliyet. Modelin tek döneme mi
    şanslı yoksa tutarlı mı olduğunu gösterir (güvenilirlik hükmü)."""
    import asyncio
    from services.backtest_service import robust_backtest
    return await asyncio.to_thread(robust_backtest, store, periods)


@router.post("/cpcv")
async def cpcv_endpoint():
    """
    CPCV + Deflated Sharpe — en sağlam kanıt testi (López de Prado).
    'Getiri gerçek kenar mı yoksa şans mı' sorusunu istatistiksel kapatır."""
    import asyncio
    from services.backtest_service import cpcv_backtest
    return await asyncio.to_thread(cpcv_backtest, store)


@router.post("/challenge")
async def challenge():
    """Manuel meydan-okuma turu tetikler (otomatik 6 saatte bir de çalışır)."""
    import asyncio
    from services.trainer_service import run_challenge
    return await asyncio.to_thread(run_challenge, store)


@router.post("/rollback")
async def rollback():
    """
    Ebeveyn nesle geri döner — yeni nesil zehirlendiyse/çöktüyse güvence.
    Mevcut nesli atar, bir önceki (ebeveyn) nesli şampiyon yapar.
    """
    from services.meta_model import meta_model
    return meta_model.rollback_to_parent()


@router.post("/resolve")
async def resolve():
    """Açık canlı sinyallerin triple-barrier sonuçlarını çözer."""
    try:
        return store.resolve_open_signals(binance)
    except BinanceUnreachable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def stats():
    """Depo istatistikleri + model durumu."""
    return {
        "depo": store.stats(),
        "model": {
            "hazir": meta_model.is_ready,
            "egitim_raporu": meta_model.info(),
        },
    }


@router.get("/signals")
async def signals(limit: int = 50):
    """Son loglanan sinyaller (özellik vektörü hariç)."""
    return store.recent(limit=min(limit, config.SIGNALS_RECENT_MAX))
