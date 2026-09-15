"""
Olay-tetikli acil haber alarmı — "günün ortasında savaş çıkarsa naneyi yeme" sigortası.

Felsefe: günde 1 haber özeti ANİ krize kör kalır (savaş, hack, ban dakikalar
içinde piyasayı vurur). Bu yüzden KATMANLI bir alarm:

  1. SÜREKLI (BEDAVA): haber başlıklarında kriz kelimesi + ani fiyat sıçraması
     tara. Claude YOK — sadece bedava haber API'si + yerel string/sayı kontrolü.
  2. TETİKLENİRSE (1 Claude çağrısı, opsiyonel): SADECE şiddetli olay yakalanırsa
     Claude'u uyandırıp "bu gerçek kriz mi?" sor. Sakin günde sıfır maliyet.

Bu modül 1. katmanı (bedava tarama) sağlar. Claude çağrısı çağıran tarafta,
sadece tetik=True olduğunda yapılır — kredi olaya bağlanır, takvime değil.
"""

from __future__ import annotations

import re

import config

# Kriz kelimeleri, şiddet işaretleri ve alarm eşikleri config.py'de
# (CRISIS_KEYWORDS / HIGH_SEVERITY_KEYWORDS / ALERT_* ile ezilebilir).
CRISIS_KEYWORDS = config.CRISIS_KEYWORDS
HIGH_SEVERITY = set(config.HIGH_SEVERITY_KEYWORDS)

# Kök eşleşme: kelime BAŞINDA boundary, sonda değil — "hack" → hacked/hacking
# de yakalanır. Sonda \b koyarsak "hacked" kaçar (gerçek krizi kaçırmak yasak).
_word_re = {kw: re.compile(r"\b" + re.escape(kw), re.IGNORECASE)
            for kw in CRISIS_KEYWORDS}


def scan_headlines(news: list[dict]) -> dict:
    """
    Haber başlıklarını kriz kelimeleri için tarar (BEDAVA, Claude yok).
    Döner: {alarm, siddet, eslesen_kelimeler, eslesen_basliklar}
    """
    matched_kw: set[str] = set()
    matched_titles: list[str] = []
    high = False

    for item in news or []:
        title = (item.get("title") or "")
        hits = [kw for kw, rx in _word_re.items() if rx.search(title)]
        if hits:
            matched_kw.update(hits)
            matched_titles.append(title)
            if any(h in HIGH_SEVERITY for h in hits):
                high = True

    if not matched_kw:
        siddet = "yok"
    elif high or len(matched_kw) >= config.ALERT_HIGH_MIN_KEYWORDS:
        siddet = "yüksek"
    elif len(matched_kw) >= config.ALERT_MEDIUM_MIN_KEYWORDS:
        siddet = "orta"
    else:
        siddet = "düşük"

    return {
        "alarm": bool(matched_kw),
        "siddet": siddet,
        "eslesen_kelimeler": sorted(matched_kw),
        "eslesen_basliklar": matched_titles[:config.ALERT_TITLE_LIMIT],
    }


def price_shock(klines, lookback: int = config.SHOCK_LOOKBACK_BARS,
                threshold_pct: float = config.SHOCK_THRESHOLD_PCT) -> dict:
    """
    Son birkaç mumda ani fiyat sıçraması var mı? (BEDAVA, sadece fiyat).
    klines: OHLCV DataFrame (en az lookback+1 satır). threshold_pct: %X hareket.
    """
    try:
        closes = klines["close"].tail(lookback + 1).values
        if len(closes) < 2:
            return {"sok": False}
        degisim = float((closes[-1] / closes[0] - 1) * 100)
        return {
            "sok": bool(abs(degisim) >= threshold_pct),  # numpy.bool → python bool (JSON)
            "degisim_yuzde": round(degisim, 2),
            "yon": "düşüş" if degisim < 0 else "yükseliş",
            "esik": threshold_pct,
        }
    except Exception:
        return {"sok": False}


def evaluate(news: list[dict], klines=None) -> dict:
    """
    Tam alarm değerlendirmesi (BEDAVA). Haber + fiyat şokunu birleştirir.
    Döner: claude_uyandir bayrağı = SADECE bu True ise Claude çağrısı yapılır.
    """
    haber = scan_headlines(news)
    fiyat = price_shock(klines) if klines is not None else {"sok": False}

    # Claude'u uyandırma kuralı: yüksek şiddetli haber, VEYA orta haber + fiyat şoku
    uyandir = (
        haber["siddet"] == "yüksek"
        or (haber["siddet"] == "orta" and fiyat.get("sok"))
        or (haber["alarm"] and fiyat.get("sok") and abs(fiyat.get("degisim_yuzde", 0)) >= config.SHOCK_STRONG_PCT)
    )

    return {
        "claude_uyandir": bool(uyandir),
        "haber_alarmi": haber,
        "fiyat_soku": fiyat,
        "ozet": _ozet(haber, fiyat, uyandir),
    }


def _ozet(haber: dict, fiyat: dict, uyandir: bool) -> str:
    if uyandir:
        parc = []
        if haber["siddet"] in ("yüksek", "orta"):
            parc.append(f"kriz haberi ({', '.join(haber['eslesen_kelimeler'][:config.ALERT_SUMMARY_KEYWORD_LIMIT])})")
        if fiyat.get("sok"):
            parc.append(f"ani %{abs(fiyat['degisim_yuzde'])} {fiyat['yon']}")
        return "⚠ ACİL: " + " + ".join(parc) + " — Claude değerlendirmesi öneriliyor."
    if haber["alarm"]:
        return f"Hafif sinyal: {', '.join(haber['eslesen_kelimeler'][:config.ALERT_SUMMARY_KEYWORD_LIMIT])} — izlemede, Claude gerekmez."
    return "Sakin — kriz sinyali yok."
