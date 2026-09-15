"""
Seans (trading session) filtresi — likidite-temelli, nedensel.

Bulgu (2026-06-24, sızıntısız walk-forward testiyle KANITLANDI): derin Asya
gecesi (00-05 UTC) düşük likidite nedeniyle teknik sinyallerin güvenilirliği
DÜŞÜK — kazanma %35-36, beklenti -0.16R (ham). Bu saatleri elemek model
filtresinin üstüne işlem başına beklentiyi +0.093R → +0.110R çıkardı (+%18).

NEDEN nedensel (hava durumu DEĞİL): kripto 7/24 ama likidite seanslara bağlı.
Asya derin gecesinde kurumsal hacim yok → false breakout'lar artar → teknik
göstergeler kandırır. Avrupa/ABD açılışında gerçek hacim → trendler güvenilir.

NOT: Bu modele ÖZELLİK olarak eklenmedi — 'hour' özelliği zaten modelde ve
seans bilgisini yakalıyor (seans kategorisi eklemek AUC'yi değiştirmedi). Bunun
yerine canlı sinyal kararında bir GÜVEN KIRICI olarak kullanılır (stokastik
motorun random-walk rejiminde güveni kırması gibi).
"""

from __future__ import annotations
from datetime import datetime

import config

# Düşük güvenilirlik penceresi config.py'de (LOW_LIQUIDITY_HOUR_START/END)
LOW_LIQUIDITY_HOURS = config.LOW_LIQUIDITY_HOURS


def session_name(ts: datetime) -> str:
    """UTC saatine göre baskın seans adı (likidite bağlamı)."""
    h = ts.hour
    if config.SESSION_ASIA_HOURS[0] <= h < config.SESSION_ASIA_HOURS[1]:
        return "Asya"
    if config.SESSION_EUROPE_HOURS[0] <= h < config.SESSION_EUROPE_HOURS[1]:
        return "Avrupa"
    if config.SESSION_US_HOURS[0] <= h < config.SESSION_US_HOURS[1]:
        return "ABD"
    return "Geç ABD/Asya geçişi"


def is_low_liquidity(ts: datetime) -> bool:
    """Bu zaman düşük-likidite (güvenilmez) seansta mı? (derin Asya gecesi)"""
    return ts.hour in LOW_LIQUIDITY_HOURS


def session_context(ts: datetime) -> dict:
    """Canlı sinyal/Claude için seans bağlamı — düşük likiditede uyarı içerir."""
    low = is_low_liquidity(ts)
    return {
        "seans": session_name(ts),
        "saat_utc": ts.hour,
        "dusuk_likidite": low,
        "uyari": (
            f"Derin Asya gecesi ({config.LOW_LIQUIDITY_HOUR_START:02d}-"
            f"{config.LOW_LIQUIDITY_HOUR_END - 1:02d} UTC) — düşük likidite, "
            "teknik sinyaller daha "
            "az güvenilir. Güveni düşür veya BEKLE."
            if low else None
        ),
    }
