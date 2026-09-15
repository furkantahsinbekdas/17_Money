"""
Tarihsel Veri İndirici — data.binance.vision arşivi.
=====================================================

Binance'in resmi açık veri arşivinden TÜM BTC geçmişini indirir.
Önemli: Bu STATİK dosya sunucusudur (api.binance.com değil) — makinedeki
ağ engelinden ETKİLENMEZ. Hesap/anahtar gerekmez.

Strateji:
- Spot BTCUSDT 1h, 2017-08'den (Binance'in başı) bugüne aylık zip.
- Her ay ~21 KB sıkıştırılmış; 9 yıl ≈ birkaç MB. Çok küçük.
- Birleştirilip TEK parquet dosyası olarak saklanır (sıkıştırılmış,
  CSV'den ~4x küçük): backend/data/history/BTCUSDT_1h.parquet
- İdempotent: zaten inen aylar atlanır (önbellek), parquet üzerine eklenir.

Kolonlar Binance kline formatı: open_time, open, high, low, close, volume,
close_time, quote_volume, trades, taker_buy_base, taker_buy_quote, ignore.
"""

import io
import os

import config
import zipfile
from datetime import datetime

import pandas as pd
import urllib.request
import urllib.error

BASE = config.BINANCE_VISION_URL
HISTORY_DIR = config.HISTORY_DIR
CACHE_DIR = config.HISTORY_CACHE_DIR

# Arşiv başlangıcı config.py'de (HISTORY_START_YEAR/MONTH)
START_YEAR, START_MONTH = config.HISTORY_START_YEAR, config.HISTORY_START_MONTH

_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _months(start_y, start_m, end_y, end_m):
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _download_month(symbol: str, interval: str, ym: str) -> pd.DataFrame | None:
    """Tek ayı indirip DataFrame döndürür. Önbellekte varsa oradan okur."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{symbol}-{interval}-{ym}.parquet")
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass  # bozuk önbellek → yeniden indir

    url = BASE.format(sym=symbol, iv=interval, ym=ym)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": config.HTTP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=config.HISTORY_TIMEOUT_SEC) as resp:
            raw = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None  # o ay yok veya ağ hatası

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as f:
                # Binance bazı dosyalara başlık ekledi (2025+); otomatik algıla
                first = f.read(20)
            with zf.open(name) as f:
                header = 0 if first[:9] == b"open_time" else None
                df = pd.read_csv(f, header=header, names=None if header == 0 else _KLINE_COLS)
        if header == 0:
            df.columns = _KLINE_COLS[:len(df.columns)]
    except Exception:
        return None

    # Tipleri düzelt
    for c in ["open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_base", "taker_buy_quote"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", errors="coerce")
    df = df.dropna(subset=["open_time", "close"])
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()

    try:
        df.to_parquet(cache_file, index=False)
    except Exception:
        pass
    return df


def download_full_history(symbol: str = config.SYMBOL, interval: str = config.DEFAULT_INTERVAL,
                          progress: bool = True) -> dict:
    """
    2017-08'den bugüne tüm geçmişi indirir, tek parquet'e birleştirir.
    Dönüş: özet (satır sayısı, tarih aralığı, dosya boyutu, atlanan aylar).
    """
    os.makedirs(HISTORY_DIR, exist_ok=True)
    now = datetime.utcnow()
    frames = []
    indirilen, atlanan = 0, []

    for ym in _months(START_YEAR, START_MONTH, now.year, now.month):
        dfm = _download_month(symbol, interval, ym)
        if dfm is not None and len(dfm):
            frames.append(dfm)
            indirilen += 1
            if progress:
                print(f"[history] {ym}: {len(dfm)} bar")
        else:
            atlanan.append(ym)

    if not frames:
        return {"basarili": False, "neden": "Hiçbir ay indirilemedi (ağ?)."}

    full = pd.concat(frames, ignore_index=True)
    full = full.drop_duplicates(subset=["open_time"]).sort_values("open_time")
    full = full.set_index("open_time")

    out_path = os.path.join(HISTORY_DIR, f"{symbol}_{interval}.parquet")
    full.to_parquet(out_path)
    size_mb = os.path.getsize(out_path) / 1024 / 1024

    return {
        "basarili": True,
        "satir": len(full),
        "ilk_tarih": str(full.index[0]),
        "son_tarih": str(full.index[-1]),
        "indirilen_ay": indirilen,
        "atlanan_ay": atlanan,
        "dosya_mb": round(size_mb, 2),
        "yol": out_path,
    }


def load_history(symbol: str = config.SYMBOL, interval: str = config.DEFAULT_INTERVAL) -> pd.DataFrame | None:
    """Kayıtlı parquet geçmişini OHLCV DataFrame (open_time indeksli) olarak okur."""
    path = os.path.join(HISTORY_DIR, f"{symbol}_{interval}.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


# ----------------------------------------------------------------------
# Funding rate geçmişi — "kalabalık nerede yığılmış" verisi
# ----------------------------------------------------------------------

FUNDING_URL = config.BINANCE_VISION_FUNDING_URL
FUNDING_START_YEAR, FUNDING_START_MONTH = (config.FUNDING_START_YEAR,
                                           config.FUNDING_START_MONTH)


def _download_funding_month(symbol: str, ym: str) -> pd.DataFrame | None:
    cache_file = os.path.join(CACHE_DIR, f"{symbol}-funding-{ym}.parquet")
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass
    url = FUNDING_URL.format(sym=symbol, ym=ym)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": config.HTTP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=config.HISTORY_TIMEOUT_SEC) as resp:
            raw = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as f:
                first = f.read(9)
            with zf.open(name) as f:
                header = 0 if first[:9] == b"calc_time" else None
                cols = ["calc_time", "funding_interval_hours", "last_funding_rate"]
                df = pd.read_csv(f, header=header, names=None if header == 0 else cols)
        if header is None:
            df.columns = cols[:len(df.columns)]
    except Exception:
        return None
    df["calc_time"] = pd.to_datetime(df["calc_time"], unit="ms", errors="coerce")
    df["funding"] = pd.to_numeric(df["last_funding_rate"], errors="coerce")
    df = df.dropna(subset=["calc_time", "funding"])[["calc_time", "funding"]]
    try:
        df.to_parquet(cache_file, index=False)
    except Exception:
        pass
    return df


def download_funding_history(symbol: str = config.SYMBOL) -> dict:
    """Tüm funding geçmişini indirir, tek parquet'e saklar."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    now = datetime.utcnow()
    frames, indirilen = [], 0
    for ym in _months(FUNDING_START_YEAR, FUNDING_START_MONTH, now.year, now.month):
        d = _download_funding_month(symbol, ym)
        if d is not None and len(d):
            frames.append(d)
            indirilen += 1
    if not frames:
        return {"basarili": False, "neden": "Funding indirilemedi."}
    full = pd.concat(frames, ignore_index=True).drop_duplicates("calc_time").sort_values("calc_time")
    full = full.set_index("calc_time")
    out = os.path.join(HISTORY_DIR, f"{symbol}_funding.parquet")
    full.to_parquet(out)
    return {"basarili": True, "satir": len(full), "indirilen_ay": indirilen,
            "ilk": str(full.index[0]), "son": str(full.index[-1])}


def load_funding(symbol: str = config.SYMBOL) -> pd.DataFrame | None:
    path = os.path.join(HISTORY_DIR, f"{symbol}_funding.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def history_info(symbol: str = config.SYMBOL, interval: str = config.DEFAULT_INTERVAL) -> dict:
    """Kayıtlı geçmiş hakkında özet (indirildi mi, kaç satır, aralık)."""
    df = load_history(symbol, interval)
    if df is None or df.empty:
        return {"var": False}
    return {
        "var": True,
        "satir": len(df),
        "ilk_tarih": str(df.index[0]),
        "son_tarih": str(df.index[-1]),
        "dosya_mb": round(os.path.getsize(
            os.path.join(HISTORY_DIR, f"{symbol}_{interval}.parquet")) / 1024 / 1024, 2),
    }
