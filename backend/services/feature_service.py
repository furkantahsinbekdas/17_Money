"""
Meta-model özellik çıkarımı — Sprint 4.

İki yol, TEK özellik sözlüğü:
- features_from_analyses(): canlı sinyal anında, calculate_all() çıktılarından
- vectorized_frame(): backfill için tüm tarih üzerinde vektörize seri hesabı

İki yol da AYNI isimlerle AYNI matematiği üretmek zorunda — aksi halde
train/serve kayması (skew) oluşur ve meta-model canlıda çöp üretir.
Eksik değerler NaN bırakılır; HistGradientBoosting NaN'i doğal işler.

Bilinen v1 kayması (kabul edilmiş): canlı analizde son bar henüz kapanmamış
(forming) olabilir; backfill yalnızca kapanmış barları kullanır.
"""

import math

import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice

# Özellik hesaplanan zaman dilimleri (15m canlıda var ama backfill'de yok —
# NaN toleranslı model için sorun değil; v1'de üçü de iki yolda mevcut)
FEATURE_TFS = ["1h", "4h", "1d"]

# Zaman dilimi başına özellikler
_TF_FEATURES = [
    "rsi",              # 0-100
    "stochk",           # 0-100
    "macd_hist_pct",    # histogram / fiyat * 100 (fiyat ölçeğinden bağımsız)
    "macd_cross",       # -1 / 0 / +1
    "adx",
    "di_diff",          # DI+ - DI-
    "trend_code",       # -2..+2 (EMA dizilimi)
    "bb_pos_code",      # -2,-1,+1,+2
    "bb_squeeze",       # 0/1
    "atr_pct",
    "vwap_diff_pct",    # (close/vwap - 1) * 100
    "vol_ratio",        # hacim / 20-bar ortalama
    "obv_trend",        # -1/+1
    "divergence",       # -1/0/+1
    "pd_pos",           # premium/discount konumu 0-100
    "bos",              # -1/0/+1
    "choch",            # -1/0/+1
    "ema20_dist_pct",
    "ema50_dist_pct",
    "ema200_dist_pct",
]

_GLOBAL_FEATURES = [
    "funding_rate",
    # NOT: funding_z / funding_extreme DENENDİ (2026-06-24) — AUC'yi 0.517→0.511'e
    # DÜŞÜRDÜ (gürültü; aşırı funding anları çok seyrek, ~%2.5). Model girdisinden
    # çıkarıldı. Hesaplama kodu backfill_service + bu dosyada KORUNDU (ileride
    # likidasyon/OI ile kombinasyonda denenebilir diye). Geri açmak: aşağı iki satırı
    # yorumdan çıkar.
    # "funding_z",
    # "funding_extreme",
    "ob_imbalance",     # orderbook bid/ask oranı
    "fear_greed",
    "hour",             # 0-23 UTC
    "dow",              # 0-6 (Pazartesi=0)
    "direction_long",   # 1=LONG, 0=SHORT
    "primary_conf",     # birincil modelin güven skoru (Claude: 0-100, backfill: |oy|*100)
    # Olay-farkındalığı (market_events.py): "şu tarihte şu oldu" bağlamı
    "olay_yakin",       # 1/0 — yakında büyük olay var mı
    "olay_etki",        # -2..+2 — olayın etki yönü/şiddeti
    "olay_gun",         # olaydan kaç gün sonra (-1 = yok)
]

FEATURE_COLUMNS = [f"{tf}_{f}" for tf in FEATURE_TFS for f in _TF_FEATURES] + _GLOBAL_FEATURES

_TREND_CODE = {
    "güçlü_yükseliş": 2, "yükseliş": 1, "yatay": 0,
    "düşüş": -1, "güçlü_düşüş": -2, "belirsiz": 0,
}
_BB_POS_CODE = {"alt_bant_altı": -2, "orta_altı": -1, "orta_üstü": 1, "üst_bant_üstü": 2}
_CROSS_CODE = {"bearish": -1, "bullish": 1}
_DIV_CODE = {"bearish": -1, "bullish": 1}
_OBV_CODE = {"düşen": -1, "yükselen": 1}


def _num(val):
    """None/str güvenli float; çevrilemiyorsa NaN."""
    if val is None or isinstance(val, bool):
        return float(val) if isinstance(val, bool) else math.nan
    try:
        f = float(val)
        return f if math.isfinite(f) else math.nan
    except (TypeError, ValueError):
        return math.nan


# ----------------------------------------------------------------------
# Canlı yol — calculate_all() sözlüklerinden özellik üretimi
# ----------------------------------------------------------------------

def _tf_features_from_analysis(a: dict) -> dict:
    """Tek zaman diliminin calculate_all() çıktısını düz özelliklere indirger."""
    price = _num(a.get("current_price"))
    macd = a.get("macd") or {}
    adx = a.get("adx") or {}
    bb = a.get("bollinger") or {}
    atr = a.get("atr") or {}
    vol = a.get("volume") or {}
    obv = a.get("obv") or {}
    div = a.get("divergence") or {}
    pdz = a.get("premium_discount") or {}
    struct = a.get("structure") or {}
    srsi = a.get("stoch_rsi") or {}

    hist = _num(macd.get("histogram"))
    vwap = _num(a.get("vwap"))

    def dist_pct(level):
        lv = _num(level)
        if math.isnan(lv) or math.isnan(price) or lv == 0:
            return math.nan
        return (price / lv - 1) * 100

    bos = struct.get("bos") or {}
    choch = struct.get("choch") or {}

    return {
        "rsi": _num(a.get("rsi")),
        "stochk": _num(srsi.get("k")),
        "macd_hist_pct": (hist / price * 100) if not (math.isnan(hist) or math.isnan(price) or price == 0) else math.nan,
        "macd_cross": float(_CROSS_CODE.get(macd.get("crossover"), 0)),
        "adx": _num(adx.get("adx")),
        "di_diff": _num(adx.get("di_plus")) - _num(adx.get("di_minus"))
        if not (math.isnan(_num(adx.get("di_plus"))) or math.isnan(_num(adx.get("di_minus")))) else math.nan,
        "trend_code": float(_TREND_CODE.get(a.get("trend"), 0)),
        "bb_pos_code": float(_BB_POS_CODE.get(bb.get("pozisyon"), 0)),
        "bb_squeeze": 1.0 if bb.get("squeeze") else 0.0,
        "atr_pct": _num(atr.get("atr_yuzde")),
        "vwap_diff_pct": (price / vwap - 1) * 100 if not (math.isnan(vwap) or math.isnan(price) or vwap == 0) else math.nan,
        "vol_ratio": _num(vol.get("oran")),
        "obv_trend": float(_OBV_CODE.get(obv.get("trend"), 0)),
        "divergence": float(_DIV_CODE.get(div.get("tespit"), 0)),
        "pd_pos": _num(pdz.get("konum_yuzde")),
        "bos": float(_CROSS_CODE.get(bos.get("direction"), 0)),
        "choch": float(_CROSS_CODE.get(choch.get("direction"), 0)),
        "ema20_dist_pct": dist_pct(a.get("ema_20")),
        "ema50_dist_pct": dist_pct(a.get("ema_50")),
        "ema200_dist_pct": dist_pct(a.get("ema_200")),
    }


def features_from_analyses(
    analyses: dict,
    derivatives: dict | None,
    market_context: dict | None,
    direction: str,
    primary_conf: float | None,
    at,
) -> dict:
    """
    Canlı sinyal anındaki tam özellik sözlüğü.
    analyses: {"1h": calculate_all(...), "4h": ..., "1d": ...}
    at: datetime (UTC) — sinyal/karar zamanı
    """
    feats: dict[str, float] = {c: math.nan for c in FEATURE_COLUMNS}

    for tf in FEATURE_TFS:
        a = analyses.get(tf)
        if not a:
            continue
        for name, val in _tf_features_from_analysis(a).items():
            feats[f"{tf}_{name}"] = val

    derivatives = derivatives or {}
    market_context = market_context or {}

    feats["funding_rate"] = _num(derivatives.get("funding_rate"))
    # funding_z / funding_extreme: tarihsel pencere gerektirir (rolling z-skor).
    # Canlıda backend derivatives'i önceden hesaplayıp geçerse kullan; yoksa
    # NaN kalır (model NaN tolere eder). Train asıl backfill yolundan beslenir.
    feats["funding_z"] = _num(derivatives.get("funding_z"))
    feats["funding_extreme"] = _num(derivatives.get("funding_extreme"))
    feats["ob_imbalance"] = _num(derivatives.get("orderbook_bid_ask_orani"))

    # market_context'te fear_greed "62 (Greed)" formatında geliyor
    fg = market_context.get("fear_greed")
    if isinstance(fg, str):
        fg = fg.split(" ")[0]
    feats["fear_greed"] = _num(fg)

    feats["hour"] = float(at.hour)
    feats["dow"] = float(at.weekday())
    feats["direction_long"] = 1.0 if direction == "LONG" else 0.0
    feats["primary_conf"] = _num(primary_conf)

    # Olay-farkındalığı (canlı): karar anında bilinen büyük olaya yakınlık
    try:
        from services import market_events
        ev = market_events.event_feature(at)
        feats["olay_yakin"] = ev["olay_yakin"]
        feats["olay_etki"] = ev["olay_etki"]
        feats["olay_gun"] = ev["olay_gun"]
    except Exception:
        pass  # NaN kalır, model tolere eder

    return feats


# ----------------------------------------------------------------------
# Backfill yolu — vektörize seri hesabı (bar başına, bakış-ileri yok)
# ----------------------------------------------------------------------

def vectorized_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bir zaman diliminin OHLCV verisi üzerinden TÜM barlar için özellik
    DataFrame'i üretir. Her satır o barın KAPANIŞI itibarıyla bilinen veridir
    (tüm `ta` göstergeleri nedensel/rolling — bakış-ileri içermez).
    Sütunlar _TF_FEATURES ile birebir aynı isimdedir (tf öneki yok).
    """
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    out = pd.DataFrame(index=df.index)

    # EMA'lar ve trend kodu (calculate_all._determine_trend ile aynı mantık)
    ema20 = EMAIndicator(close=close, window=20).ema_indicator()
    ema50 = EMAIndicator(close=close, window=50).ema_indicator()
    ema200 = EMAIndicator(close=close, window=200).ema_indicator()
    trend = pd.Series(0.0, index=df.index)
    valid = ema20.notna() & ema50.notna() & ema200.notna()
    strong_up = valid & (close > ema20) & (ema20 > ema50) & (ema50 > ema200)
    up = valid & ~strong_up & (close > ema50) & (ema50 > ema200)
    strong_dn = valid & (close < ema20) & (ema20 < ema50) & (ema50 < ema200)
    dn = valid & ~strong_dn & (close < ema50) & (ema50 < ema200)
    trend[strong_up], trend[up], trend[dn], trend[strong_dn] = 2.0, 1.0, -1.0, -2.0
    out["trend_code"] = trend
    out["ema20_dist_pct"] = (close / ema20 - 1) * 100
    out["ema50_dist_pct"] = (close / ema50 - 1) * 100
    out["ema200_dist_pct"] = (close / ema200 - 1) * 100

    # RSI + StochRSI
    out["rsi"] = RSIIndicator(close=close, window=14).rsi()
    try:
        srsi = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
        out["stochk"] = srsi.stochrsi_k() * 100
    except Exception:
        out["stochk"] = np.nan

    # MACD
    macd = MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    macd_line, sig_line, hist = macd.macd(), macd.macd_signal(), macd.macd_diff()
    out["macd_hist_pct"] = hist / close * 100
    cross_up = (macd_line.shift(1) < sig_line.shift(1)) & (macd_line > sig_line)
    cross_dn = (macd_line.shift(1) > sig_line.shift(1)) & (macd_line < sig_line)
    out["macd_cross"] = np.where(cross_up, 1.0, np.where(cross_dn, -1.0, 0.0))

    # ADX
    try:
        adx_ind = ADXIndicator(high=high, low=low, close=close, window=14)
        out["adx"] = adx_ind.adx()
        out["di_diff"] = adx_ind.adx_pos() - adx_ind.adx_neg()
    except Exception:
        out["adx"], out["di_diff"] = np.nan, np.nan

    # Bollinger: pozisyon kodu + squeeze (son 50 barın en dar %20'si — _bollinger ile aynı)
    bb = BollingerBands(close=close, window=20, window_dev=2)
    upper, mid, lower = bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()
    width = (upper - lower) / mid * 100
    out["bb_squeeze"] = (width <= width.rolling(50, min_periods=20).quantile(0.2)).astype(float)
    out["bb_pos_code"] = np.where(close > upper, 2.0, np.where(close < lower, -2.0,
                                  np.where(close > mid, 1.0, -1.0)))
    out.loc[mid.isna(), ["bb_pos_code", "bb_squeeze"]] = np.nan

    # ATR%
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    out["atr_pct"] = atr / close * 100

    # VWAP (rolling 50 — _vwap ile aynı pencere)
    try:
        vwap = VolumeWeightedAveragePrice(
            high=high, low=low, close=close, volume=volume, window=50,
        ).volume_weighted_average_price()
        out["vwap_diff_pct"] = (close / vwap - 1) * 100
    except Exception:
        out["vwap_diff_pct"] = np.nan

    # Hacim oranı + OBV trendi
    out["vol_ratio"] = volume / volume.rolling(20).mean()
    obv = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    obv_ma = obv.rolling(20).mean()
    out["obv_trend"] = np.where(obv_ma.isna(), np.nan, np.where(obv > obv_ma, 1.0, -1.0))

    # Premium/Discount konumu (rolling 100 — _premium_discount ile aynı pencere)
    roll_hi = high.rolling(100, min_periods=20).max()
    roll_lo = low.rolling(100, min_periods=20).min()
    rng = roll_hi - roll_lo
    out["pd_pos"] = np.where(rng > 0, (close - roll_lo) / rng * 100, 50.0)

    # BOS / CHoCH — pivot tabanlı, bar bar nedensel hesap
    out["bos"], out["choch"] = _structure_series(df)

    # Divergence: vektörize edilmesi pahalı ve canlıda da nadir — v1'de backfill için 0
    out["divergence"] = 0.0

    return out


def _structure_series(df: pd.DataFrame, lookback: int = 50) -> tuple[pd.Series, pd.Series]:
    """
    find_structure_breaks() mantığının bar-bar nedensel versiyonu.
    Her bar için yalnızca o bara kadar görülebilen pivotlar kullanılır
    (pivot onayı 1 bar gecikmeli: i pivotu i+1 kapanışında bilinir).
    """
    n = len(df)
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    bos = np.zeros(n)
    choch = np.zeros(n)
    piv_hi: list[tuple[int, float]] = []
    piv_lo: list[tuple[int, float]] = []

    for i in range(1, n):
        # Pivot onayı: j = i-1 noktası, komşuları j-1 ve j+1=i (i kapanışında bilinir)
        j = i - 1
        if j >= 1:
            if highs[j] > highs[j - 1] and highs[j] > highs[i]:
                piv_hi.append((j, highs[j]))
            if lows[j] < lows[j - 1] and lows[j] < lows[i]:
                piv_lo.append((j, lows[j]))

        # Pencere dışına düşen pivotları kırp
        cutoff = i - lookback
        while piv_hi and piv_hi[0][0] < cutoff:
            piv_hi.pop(0)
        while piv_lo and piv_lo[0][0] < cutoff:
            piv_lo.pop(0)

        if len(piv_hi) >= 2 and closes[i] > piv_hi[-2][1]:
            bos[i] = 1.0
        if len(piv_lo) >= 2 and closes[i] < piv_lo[-2][1]:
            bos[i] = -1.0

        if len(piv_hi) >= 2 and len(piv_lo) >= 2:
            if piv_lo[-1][1] > piv_lo[-2][1] and piv_hi[-1][1] > piv_hi[-2][1]:
                choch[i] = 1.0
            elif piv_hi[-1][1] < piv_hi[-2][1] and piv_lo[-1][1] < piv_lo[-2][1]:
                choch[i] = -1.0

    return pd.Series(bos, index=df.index), pd.Series(choch, index=df.index)
