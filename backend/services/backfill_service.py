"""
Backfill motoru — Sprint 4.

Meta-model eğitimi için yüzlerce etiketli örnek gerekir; canlı sinyal
birikmesini beklemek haftalar alır. Bu motor tarihsel klines üzerinde:

1. 1h/4h/1d özellik çerçevelerini vektörize hesaplar (feature_service ile
   birebir aynı isim ve matematik — bakış-ileri yok),
2. Deterministik bir birincil kural ile LONG/SHORT sinyalleri üretir
   (ForecastService ağırlık felsefesinin vektörize hali),
3. Her sinyali triple-barrier ile anında etiketler,
4. SignalStore'a source='backfill' olarak yazar.

Nedensellik notları:
- Karar, i barının KAPANIŞINDA verilir; giriş fiyatı close[i],
  bariyer yürüyüşü i+1'den başlar.
- 4h/1d özellikleri merge_asof ile KAPANMIŞ üst-TF barından alınır
  (canlıda forming bar kullanılıyor — bilinen v1 kayması, kabul edildi).
- Ardışık sinyaller arasında MIN_GAP_BARS boşluk zorlanır — örtüşen
  etiketlerin (concurrent labels) bağımsızlık varsayımını bozmasını azaltır.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from services.feature_service import vectorized_frame, FEATURE_TFS, FEATURE_COLUMNS
from services.signal_store import SignalStore, TP_ATR_MULT, SL_ATR_MULT, HORIZON_BARS

import config
from services import market_events

# Birincil kural parametreleri
VOTE_THRESHOLD = config.BACKFILL_VOTE_THRESHOLD
MIN_ADX = config.BACKFILL_MIN_ADX
MIN_GAP_BARS = config.BACKFILL_MIN_GAP_BARS

# Rejime-duyarlı bariyer çarpanları (2026-06-24).
# Sabit TP 1.5 / SL 1.0 yerine: trend güçlüyse (yüksek ADX) geniş TP bırak —
# büyük hareketi yakala; yatay rejimde (düşük ADX) dar TP — çabuk al-çık.
# Rejim sinyal ANINDAKİ ADX ile belirlenir (geçmiş veri → bakış-ileri YOK).
def _regime_barriers(adx: float) -> tuple[float, float]:
    """ADX rejimine göre (tp_mult, sl_mult). NaN/düşük → temkinli dar hedef."""
    if adx is None or not (adx == adx):  # NaN
        return TP_ATR_MULT, SL_ATR_MULT
    if adx >= 30.0:      # güçlü trend → geniş TP
        return 2.5, 1.2
    if adx >= 22.0:      # ılımlı trend → mevcut
        return 1.5, 1.0
    return 1.0, 1.0      # zayıf/yatay → dar, simetrik

_TF_MINUTES = {"1h": 60, "4h": 240, "1d": 1440}


def _primary_vote(feats_1h: pd.DataFrame) -> pd.Series:
    """
    Deterministik birincil yön oyu (-1..+1) — ForecastService ağırlıklarının
    sade, vektörize karşılığı. Meta-modelin işi bu kuralın NE ZAMAN
    çalıştığını öğrenmek; kuralın kendisi mükemmel olmak zorunda değil.
    """
    f = feats_1h
    score = (
        2.0 * f["trend_code"] / 2.0
        + 1.5 * np.sign(f["macd_hist_pct"].fillna(0))
        + 1.5 * np.sign(f["di_diff"].fillna(0))
        + 1.0 * np.where(f["rsi"] >= 50, 1.0, -1.0)
        + 1.0 * f["obv_trend"].fillna(0)
        + 1.5 * f["bos"].fillna(0)
        + 0.5 * np.sign(f["vwap_diff_pct"].fillna(0))
        + 0.5 * np.where(f["pd_pos"] <= 30, 1.0, np.where(f["pd_pos"] >= 70, -1.0, 0.0))
    )
    max_score = 2.0 + 1.5 + 1.5 + 1.0 + 1.0 + 1.5 + 0.5 + 0.5
    return score / max_score


def _resample(df_1h: pd.DataFrame, rule: str) -> pd.DataFrame:
    """1h OHLCV'yi üst zaman dilimine yeniden örnekler (4h/1d)."""
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    out = df_1h.resample(rule, label="left", closed="left").agg(agg).dropna()
    return out


def run_backfill(binance_service, store: SignalStore,
                 symbol: str = config.SYMBOL, interval: str = config.DEFAULT_INTERVAL,
                 limit: int = 1500, use_history: bool = False) -> dict:
    """
    Tarihsel sinyal üretimi + etiketleme. İdempotent (INSERT OR IGNORE).
    use_history=True → data.binance.vision'dan indirilmiş TÜM geçmişi kullanır
    (binsel/on binlerce örnek); 4h/1d 1h'ten resample edilir.
    """
    if interval != "1h":
        raise ValueError("Backfill v1 yalnızca 1h birincil zaman dilimini destekler.")

    # --- Veri çek ---
    if use_history:
        from services.history_downloader import load_history
        df_1h = load_history(symbol, "1h")
        if df_1h is None or df_1h.empty:
            raise ValueError("İndirilmiş geçmiş yok. Önce POST /api/meta/download-history çalıştırın.")
        df_4h = _resample(df_1h, "4h")
        df_1d = _resample(df_1h, "1D")
    else:
        df_1h = binance_service.get_klines(
        symbol, "1h", min(limit, config.BINANCE_MAX_KLINES_PER_CALL))
        df_4h = binance_service.get_klines(symbol, "4h", config.BACKFILL_KLINE_LIMIT_4H)
        df_1d = binance_service.get_klines(symbol, "1d", config.BACKFILL_KLINE_LIMIT_1D)

    # Son bar forming olabilir — kapanmamış barı tüm TF'lerde at
    now = pd.Timestamp(datetime.utcnow())
    frames = {}
    for tf, df in (("1h", df_1h), ("4h", df_4h), ("1d", df_1d)):
        closed = df[df.index + pd.Timedelta(minutes=_TF_MINUTES[tf]) <= now]
        frames[tf] = closed

    # --- Özellik çerçeveleri ---
    feat = {tf: vectorized_frame(frames[tf]) for tf in FEATURE_TFS}

    # --- Üst TF'leri 1h karar zamanlarına hizala (yalnızca KAPANMIŞ barlar) ---
    base = feat["1h"].add_prefix("1h_")
    base["decision_time"] = frames["1h"].index + pd.Timedelta(minutes=60)
    base["entry_price"] = frames["1h"]["close"].values
    base = base.reset_index(drop=True)

    for tf in ("4h", "1d"):
        f = feat[tf].add_prefix(f"{tf}_").copy()
        f["tf_close_time"] = frames[tf].index + pd.Timedelta(minutes=_TF_MINUTES[tf])
        f = f.sort_values("tf_close_time").reset_index(drop=True)
        base = pd.merge_asof(
            base.sort_values("decision_time"),
            f,
            left_on="decision_time",
            right_on="tf_close_time",
            direction="backward",
        ).drop(columns=["tf_close_time"])

    # --- Funding rate'i hizala (kalabalık konumlandırması) ---
    # use_history modunda tarihsel funding parquet'inden; en son bilinen değer.
    if use_history:
        try:
            from services.history_downloader import load_funding
            fund = load_funding(symbol)
            if fund is not None and len(fund):
                fund = fund.reset_index().rename(columns={"calc_time": "fund_time"})
                fund = fund.sort_values("fund_time").reset_index(drop=True)
                # --- İŞLENMİŞ funding: "normalden ne kadar sapmış" (uçları yakala) ---
                # Funding 8h periyodik; FUND_WIN nokta ≈ 10 gün geçmiş normali.
                # BAKIŞ-İLERİ YASAK: z-skor SADECE geçmiş pencereden (shift(1) ile
                # mevcut değer ortalamaya KARIŞMAZ → o bar için bilinemezdi).
                FUND_WIN = 30          # ~10 gün (3 funding/gün)
                FUND_EXTREME_Z = 2.0   # 2σ üstü "aşırı" sayılır
                FUND_SD_FLOOR = 1e-4   # std tabanı: funding düz olunca bölme patlamasın
                Z_CLIP = 8.0           # makul sınır: ötesi sayısal anlam katmaz, bayrak zaten yakalar
                f = fund["funding"]
                roll = f.shift(1).rolling(FUND_WIN, min_periods=10)
                mu = roll.mean()
                sd = roll.std(ddof=0).clip(lower=FUND_SD_FLOOR)
                fund["funding_z"] = ((f - mu) / sd).clip(-Z_CLIP, Z_CLIP)
                fund["funding_extreme"] = 0.0
                fund.loc[fund["funding_z"] >= FUND_EXTREME_Z, "funding_extreme"] = 1.0
                fund.loc[fund["funding_z"] <= -FUND_EXTREME_Z, "funding_extreme"] = -1.0
                base = pd.merge_asof(
                    base.sort_values("decision_time"),
                    fund[["fund_time", "funding", "funding_z", "funding_extreme"]],
                    left_on="decision_time", right_on="fund_time",
                    direction="backward",
                ).drop(columns=["fund_time"])
        except Exception:
            pass

    # --- Birincil sinyal ---
    vote = _primary_vote(base.rename(columns=lambda c: c.removeprefix("1h_")
                                     if c.startswith("1h_") else c))
    base["vote"] = vote.values
    warmup = 220  # EMA200 + tampon: erken barlarda göstergeler NaN/güvenilmez
    candidates = base.index[
        (base.index >= warmup)
        & (base["vote"].abs() >= VOTE_THRESHOLD)
        & (base["1h_adx"] >= MIN_ADX)
        & base["1h_atr_pct"].notna()
    ].tolist()

    # Örtüşme azaltma: ardışık sinyaller arasında min boşluk
    selected = []
    last = -10**9
    for i in candidates:
        if i - last >= MIN_GAP_BARS:
            selected.append(i)
            last = i

    # --- Etiketle ve yaz ---
    ohlc = frames["1h"].reset_index()
    inserted = wins = losses = timeouts = unresolved = 0

    for i in selected:
        row = base.loc[i]
        direction = "LONG" if row["vote"] > 0 else "SHORT"
        entry = float(row["entry_price"])
        atr = float(row["1h_atr_pct"]) / 100 * entry
        if atr <= 0:
            continue

        sign = 1 if direction == "LONG" else -1
        adx_now = row.get("1h_adx")
        tp_mult, sl_mult = _regime_barriers(float(adx_now) if pd.notna(adx_now) else None)
        tp = entry + sign * tp_mult * atr
        sl = entry - sign * sl_mult * atr

        created = (ohlc.loc[i, "open_time"] + pd.Timedelta(minutes=60)).to_pydatetime()
        deadline = created + timedelta(minutes=60 * HORIZON_BARS)
        after = frames["1h"].iloc[i + 1: i + 1 + HORIZON_BARS + 1]
        if after.empty:
            continue

        outcome = SignalStore.walk_barriers(direction, entry, tp, sl, after, deadline)
        if outcome is None:
            unresolved += 1
            continue  # ufuk içinde çözülemeyen (veri sonu) sinyali yazma

        status, label, exit_price, exited_at = outcome

        # Özellik sözlüğü — kanonik sütun sırasıyla
        features = {}
        for col in FEATURE_COLUMNS:
            if col in base.columns:
                v = row[col]
                features[col] = float(v) if pd.notna(v) else None
            else:
                features[col] = None
        features["hour"] = float(created.hour)
        features["dow"] = float(created.weekday())
        features["direction_long"] = 1.0 if direction == "LONG" else 0.0
        features["primary_conf"] = round(abs(float(row["vote"])) * 100, 1)
        # Funding rate (kalabalık konumlandırması) — tarihsel veriden hizalandıysa
        if "funding" in base.columns:
            fv = row.get("funding")
            features["funding_rate"] = float(fv) if pd.notna(fv) else None
            # İşlenmiş funding: z-skor (normalden sapma) + aşırı bayrağı
            fz = row.get("funding_z")
            features["funding_z"] = float(fz) if pd.notna(fz) else None
            fe = row.get("funding_extreme")
            features["funding_extreme"] = float(fe) if pd.notna(fe) else None
        # Olay-farkındalığı: bu barın tarihinde bilinen büyük olay var mıydı?
        ev = market_events.event_feature(created)
        features["olay_yakin"] = ev["olay_yakin"]
        features["olay_etki"] = ev["olay_etki"]
        features["olay_gun"] = ev["olay_gun"]

        sid = store.log_signal(
            created_at=created, source="backfill", symbol=symbol, interval=interval,
            direction=direction, features=features,
            confidence=features["primary_conf"], entry_price=entry, atr=atr,
        )
        if sid is None:
            continue  # zaten vardı (idempotent yeniden çalıştırma)

        store.set_outcome(sid, status, label, exit_price, exited_at)
        inserted += 1
        if status == "win":
            wins += 1
        elif status == "loss":
            losses += 1
        else:
            timeouts += 1

    labeled = wins + losses + timeouts
    return {
        "aday_bar": len(candidates),
        "secilen_sinyal": len(selected),
        "yazilan": inserted,
        "kazanan": wins,
        "kaybeden": losses,
        "zaman_asimi": timeouts,
        "cozulemeyen": unresolved,
        "backfill_kazanma_orani": round(wins / labeled, 3) if labeled else None,
        "parametreler": {
            "oy_esigi": VOTE_THRESHOLD, "min_adx": MIN_ADX,
            "min_bosluk_bar": MIN_GAP_BARS, "tp_atr": TP_ATR_MULT,
            "sl_atr": SL_ATR_MULT, "ufuk_bar": HORIZON_BARS,
        },
    }
