"""
Paper trading endpoint'leri — Aşama 5: canlı kanıt (gerçek para yok).

Hesap defteri (paper_account) ile signal_store'u senkron tutar. resolve_loop
zaten arka planda çözülen sinyalleri paper'a işliyor; bu router durum okuma,
sıfırlama ve manuel senkron sağlar.
"""

import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.signal_store import SignalStore
from services.paper_account import PaperAccount

import config

router = APIRouter(prefix="/api/paper", tags=["paper"])

paper = PaperAccount()
store = SignalStore()


@router.post("/run-once")
async def paper_run_once(interval: str = config.DEFAULT_INTERVAL,
                        with_vote: bool = False):
    """
    Elle tek tur: (1) deterministik motorla bir sinyal üret + model olasılığı ekle,
    (2) açık sinyalleri triple-barrier ile çözmeye çalış, (3) çözülenleri paper'a işle.

    interval: işlemin temel zaman dilimi (15m/1h/4h/1d). MTF analizi her durumda
    yapılır (geniş pencere); interval sadece giriş/TP/SL/etiketleme zeminini seçer.

    Not: yeni üretilen sinyal HEMEN çözülemez (TP/SL'e ulaşmak zaman alır) — açık
    pozisyon olarak kalır, ileride çözülür. Bu buton sistemi 'dürtükler', anında
    kâr göstermez; biriken açık sinyaller zamanla sonuçlanır.
    """
    # Geçerli işlem zaman dilimleri config.py'de (TRADE_INTERVALS)
    if interval not in config.TRADE_INTERVALS:
        interval = config.DEFAULT_INTERVAL
    try:
        # 1) Yeni sinyal üret (seçili zaman diliminde, model olasılığı + KARAR İZİ + oy verisi)
        yeni_id, karar_izi, oy_verisi = await asyncio.to_thread(_produce_scored_signal, interval)
        # 1b) OYLAMA (with_vote=true ise Claude oyu da alınır — KREDİ yakar)
        oylama = None
        if with_vote and oy_verisi:
            oylama = await _run_voting(oy_verisi)
        # 2) Açık sinyalleri çöz (gerçek fiyat hareketine göre)
        from main import binance_svc
        resolved = await asyncio.to_thread(store.resolve_open_signals, binance_svc)
        # 3) Çözülenleri paper hesaba işle
        psync = await asyncio.to_thread(paper.sync_from_store, store)
        durum = await asyncio.to_thread(paper.status, 10, store)
        return {
            "yeni_sinyal_id": yeni_id,
            "yeni_sinyal_uretildi": yeni_id is not None,
            "karar_izi": karar_izi,        # Görev 4: "arkada ne oldu" adım adım
            "oylama": oylama,              # model + Claude oyu (with_vote=true ise)
            "cozulen": resolved.get("resolved", 0),
            "hala_acik": resolved.get("still_open", 0),
            "paper_yeni_islem": psync.get("yeni_islenen", 0),
            "durum": durum,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_voting(oy_verisi: dict) -> dict:
    """Model oyu + Claude oyu → eşit uzlaşma kararı."""
    from services import claude_vote, vote_combine
    from services.news_service import NewsService
    from routers.ai import claude as claude_service
    d = oy_verisi
    # Güncel haberi çek (Claude oyu için bağlam)
    try:
        news = await NewsService().get_crypto_news()
    except Exception:
        news = []
    # Oylama modeli config.py'de (CLAUDE_VOTE_MODEL) — varsayılan model bazı
    # hesaplarda erişilemez, bu yüzden ayrı ayar.
    vote_model = config.CLAUDE_VOTE_MODEL
    mo = vote_combine.model_vote(d["direction"], d["meta_prob"], d["esik"])
    co = await asyncio.to_thread(
        claude_vote.build_vote,
        claude=claude_service, direction=d["direction"],
        mtf_summary=d["mtf_summary"], news=news,
        model_prob=d["meta_prob"], session_ctx=d["session"],
        model=vote_model,
    )
    return vote_combine.combine(mo, co, d["direction"])


def _produce_scored_signal(interval: str = config.DEFAULT_INTERVAL):
    """Deterministik motorla bir sinyal üretir + meta_prob ekler + KARAR İZİ + OY VERİSİ döner.
    interval: işlemin temel zaman dilimi. Döner: (sinyal_id|None, karar_izi, oy_verisi|None)."""
    from main import _collect_one_signal
    from services.meta_model import meta_model
    import json

    sid, trace, vote_data = _collect_one_signal(with_trace=True, primary_iv=interval)
    if sid is None:
        return None, trace, None  # yatay piyasa → sinyal yok
    # Üretilen sinyali skorla → meta_prob (paper'a girebilmesi için şart)
    with store._conn() as conn:
        row = conn.execute("SELECT features FROM signals WHERE id=?", (sid,)).fetchone()
        if row and meta_model.is_ready:
            feats = json.loads(row["features"])
            score = meta_model.score(feats)
            prob = score.get("olasilik") if isinstance(score, dict) else None
            if prob is not None:
                conn.execute("UPDATE signals SET meta_prob=? WHERE id=?", (prob, sid))
    return sid, trace, vote_data


@router.get("/status")
async def paper_status(recent: int = 15):
    """Paper hesabın tam durumu — sermaye, getiri, açık/kapalı istatistik, son işlemler,
    AÇIK pozisyonlar (sonuç bekleyenler)."""
    return await asyncio.to_thread(paper.status, recent, store)


@router.get("/equity")
async def paper_equity():
    """Sermaye eğrisi — işlem işlem sermaye seyri (grafik için)."""
    return {"egri": await asyncio.to_thread(paper.equity_curve)}


@router.post("/sync")
async def paper_sync():
    """Çözülmüş sinyalleri paper hesaba elle işle (resolve_loop dışında manuel tetik)."""
    return await asyncio.to_thread(paper.sync_from_store, store)


class PaperConfig(BaseModel):
    start_balance: float | None = None
    risk_pct: float | None = None
    cost_r: float | None = None
    meta_threshold: float | None = None


@router.post("/reset")
async def paper_reset(cfg: PaperConfig | None = None):
    """Hesabı sıfırla — işlemleri sil, sermayeyi başa al, parametreleri ayarla."""
    cfg = cfg or PaperConfig()
    return await asyncio.to_thread(
        paper.reset, cfg.start_balance, cfg.risk_pct, cfg.cost_r, cfg.meta_threshold
    )


@router.post("/breaker/reset")
async def breaker_reset():
    """
    Devre kesiciyi elle yeniden etkinleştir (İNSAN ONAYI — kasıtlı olarak otomatik
    değil). Tepe sermaye mevcut sermayeye çekilir: temiz sayfa, anında yeniden
    tetiklenme olmaz.
    """
    return await asyncio.to_thread(paper.breaker_reset)
