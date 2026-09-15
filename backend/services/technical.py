import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice


def _safe(series_or_val):
    """NaN güvenli float dönüşümü."""
    try:
        if isinstance(series_or_val, pd.Series):
            val = series_or_val.iloc[-1]
        else:
            val = series_or_val
        return round(float(val), 6) if not pd.isna(val) else None
    except (IndexError, TypeError, ValueError):
        return None


class TechnicalService:

    def calculate_all(self, df: pd.DataFrame) -> dict:
        """Tüm teknik göstergeleri hesaplayıp tek sözlük olarak döndürür."""
        df = df.copy()

        ema_20 = self._ema(df, 20)
        ema_50 = self._ema(df, 50)
        ema_200 = self._ema(df, 200)
        rsi_series = self._rsi_series(df)
        macd_data = self._macd(df)
        order_blocks = self.find_order_blocks(df)
        fvg = self.find_fair_value_gaps(df)
        liquidity = self.find_liquidity_levels(df)
        structure = self.find_structure_breaks(df)

        last = df.iloc[-1]
        current_price = float(last["close"])

        return {
            "current_price": current_price,
            "ema_20": _safe(ema_20),
            "ema_50": _safe(ema_50),
            "ema_200": _safe(ema_200),
            "rsi": _safe(rsi_series),
            "macd": macd_data,
            "trend": self._determine_trend(df, ema_20, ema_50, ema_200),
            "order_blocks": order_blocks,
            "fvg": fvg,
            "liquidity": liquidity,
            "structure": structure,
            # --- Uzman seviye göstergeler ---
            "atr": self._atr(df),
            "bollinger": self._bollinger(df),
            "stoch_rsi": self._stoch_rsi(df),
            "adx": self._adx(df),
            "obv": self._obv(df),
            "vwap": self._vwap(df),
            "volume": self._volume_analysis(df),
            "divergence": self._rsi_divergence(df, rsi_series),
            "premium_discount": self._premium_discount(df),
            "support_resistance": self._support_resistance(df),
        }

    def compact_summary(self, analysis: dict) -> dict:
        """
        Çoklu zaman dilimi analizi için kompakt özet —
        AI prompt'unda token tasarrufu sağlar.
        """
        macd = analysis.get("macd", {})
        bb = analysis.get("bollinger", {})
        adx = analysis.get("adx", {})
        div = analysis.get("divergence", {})
        struct = analysis.get("structure", {})
        return {
            "fiyat": analysis.get("current_price"),
            "trend": analysis.get("trend"),
            "rsi": analysis.get("rsi"),
            "stoch_rsi_k": (analysis.get("stoch_rsi") or {}).get("k"),
            "macd_histogram": macd.get("histogram"),
            "macd_kesisim": macd.get("crossover"),
            "adx": adx.get("adx"),
            "trend_gucu": adx.get("trend_gucu"),
            "bb_pozisyon": bb.get("pozisyon"),
            "bb_squeeze": bb.get("squeeze"),
            "atr_yuzde": (analysis.get("atr") or {}).get("atr_yuzde"),
            "vwap_ustu": analysis.get("vwap") is not None
            and analysis.get("current_price", 0) > (analysis.get("vwap") or 0),
            "hacim_durumu": (analysis.get("volume") or {}).get("durum"),
            "obv_trend": (analysis.get("obv") or {}).get("trend"),
            "divergence": div.get("tespit"),
            "bos": struct.get("bos"),
            "choch": struct.get("choch"),
            "premium_discount": (analysis.get("premium_discount") or {}).get("bolge"),
            "yakin_destekler": (analysis.get("support_resistance") or {}).get("destekler", [])[:2],
            "yakin_direncler": (analysis.get("support_resistance") or {}).get("direncler", [])[:2],
        }

    # ------------------------------------------------------------------
    # Temel göstergeler
    # ------------------------------------------------------------------

    def _ema(self, df: pd.DataFrame, period: int) -> pd.Series:
        return EMAIndicator(close=df["close"], window=period).ema_indicator()

    def _rsi_series(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        return RSIIndicator(close=df["close"], window=period).rsi()

    def _macd(self, df: pd.DataFrame) -> dict:
        macd = MACD(close=df["close"], window_fast=12, window_slow=26, window_sign=9)
        macd_line = macd.macd()
        signal_line = macd.macd_signal()
        histogram = macd.macd_diff()

        macd_val = _safe(macd_line)
        signal_val = _safe(signal_line)
        hist_val = _safe(histogram)

        crossover = None
        if len(macd_line) >= 2 and macd_val is not None and signal_val is not None:
            prev_macd = macd_line.iloc[-2]
            prev_signal = signal_line.iloc[-2]
            if not pd.isna(prev_macd) and not pd.isna(prev_signal):
                if prev_macd < prev_signal and macd_val > signal_val:
                    crossover = "bullish"
                elif prev_macd > prev_signal and macd_val < signal_val:
                    crossover = "bearish"

        # Histogram momentumu: son 3 bar artıyor mu azalıyor mu
        hist_momentum = None
        if len(histogram) >= 3:
            h = histogram.dropna().tail(3)
            if len(h) == 3:
                if h.iloc[2] > h.iloc[1] > h.iloc[0]:
                    hist_momentum = "güçleniyor"
                elif h.iloc[2] < h.iloc[1] < h.iloc[0]:
                    hist_momentum = "zayıflıyor"

        return {
            "macd": macd_val,
            "signal": signal_val,
            "histogram": hist_val,
            "crossover": crossover,
            "histogram_momentum": hist_momentum,
        }

    def _determine_trend(self, df, ema_20, ema_50, ema_200) -> str:
        """EMA sırasına göre genel trendi belirler."""
        close = df["close"].iloc[-1]
        e20 = ema_20.iloc[-1]
        e50 = ema_50.iloc[-1]
        e200 = ema_200.iloc[-1]

        if pd.isna(e20) or pd.isna(e50) or pd.isna(e200):
            return "belirsiz"

        if close > e20 > e50 > e200:
            return "güçlü_yükseliş"
        elif close > e50 > e200:
            return "yükseliş"
        elif close < e20 < e50 < e200:
            return "güçlü_düşüş"
        elif close < e50 < e200:
            return "düşüş"
        else:
            return "yatay"

    # ------------------------------------------------------------------
    # Uzman seviye göstergeler
    # ------------------------------------------------------------------

    def _atr(self, df: pd.DataFrame, period: int = 14) -> dict:
        """ATR — volatilite ölçümü ve stop-loss mesafesi hesabı için temel."""
        atr = AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=period
        ).average_true_range()
        atr_val = _safe(atr)
        close = float(df["close"].iloc[-1])
        return {
            "atr": atr_val,
            "atr_yuzde": round(atr_val / close * 100, 3) if atr_val else None,
        }

    def _bollinger(self, df: pd.DataFrame, period: int = 20, dev: int = 2) -> dict:
        """Bollinger Bantları — squeeze tespiti dahil (düşük volatilite → patlama beklentisi)."""
        bb = BollingerBands(close=df["close"], window=period, window_dev=dev)
        upper = bb.bollinger_hband()
        middle = bb.bollinger_mavg()
        lower = bb.bollinger_lband()

        u, m, l = _safe(upper), _safe(middle), _safe(lower)
        close = float(df["close"].iloc[-1])

        width = None
        squeeze = None
        pozisyon = None
        if u and m and l:
            width = round((u - l) / m * 100, 3)
            # Squeeze: mevcut bant genişliği son 50 barın en dar %20'lik dilimindeyse
            hist_width = ((bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg() * 100).dropna().tail(50)
            if len(hist_width) >= 20:
                squeeze = bool(width <= hist_width.quantile(0.2))
            if close > u:
                pozisyon = "üst_bant_üstü"
            elif close < l:
                pozisyon = "alt_bant_altı"
            elif close > m:
                pozisyon = "orta_üstü"
            else:
                pozisyon = "orta_altı"

        return {"ust": u, "orta": m, "alt": l, "genislik_yuzde": width, "squeeze": squeeze, "pozisyon": pozisyon}

    def _stoch_rsi(self, df: pd.DataFrame) -> dict:
        """Stochastic RSI — aşırı alım/satım bölgelerinde hassas zamanlama."""
        try:
            srsi = StochRSIIndicator(close=df["close"], window=14, smooth1=3, smooth2=3)
            k = _safe(srsi.stochrsi_k())
            d = _safe(srsi.stochrsi_d())
        except Exception:
            return {"k": None, "d": None, "durum": None}

        durum = None
        if k is not None:
            k_pct = k * 100
            if k_pct >= 80:
                durum = "aşırı_alım"
            elif k_pct <= 20:
                durum = "aşırı_satım"
            else:
                durum = "nötr"
        return {
            "k": round(k * 100, 2) if k is not None else None,
            "d": round(d * 100, 2) if d is not None else None,
            "durum": durum,
        }

    def _adx(self, df: pd.DataFrame, period: int = 14) -> dict:
        """ADX — trend gücü. ADX<20 = trendsiz piyasa (chop), >25 = güçlü trend."""
        try:
            adx_ind = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=period)
            adx_val = _safe(adx_ind.adx())
            di_plus = _safe(adx_ind.adx_pos())
            di_minus = _safe(adx_ind.adx_neg())
        except Exception:
            return {"adx": None, "di_plus": None, "di_minus": None, "trend_gucu": None}

        trend_gucu = None
        if adx_val is not None:
            if adx_val < 20:
                trend_gucu = "trendsiz_chop"
            elif adx_val < 25:
                trend_gucu = "zayıf_trend"
            elif adx_val < 40:
                trend_gucu = "güçlü_trend"
            else:
                trend_gucu = "çok_güçlü_trend"

        return {"adx": adx_val, "di_plus": di_plus, "di_minus": di_minus, "trend_gucu": trend_gucu}

    def _obv(self, df: pd.DataFrame) -> dict:
        """OBV — hacim akışı. Fiyat hareketinin hacimle onaylanıp onaylanmadığını gösterir."""
        obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"]).on_balance_volume()
        obv_ma = obv.rolling(20).mean()
        obv_val = _safe(obv)
        obv_ma_val = _safe(obv_ma)

        trend = None
        if obv_val is not None and obv_ma_val is not None:
            trend = "yükselen" if obv_val > obv_ma_val else "düşen"

        return {"deger": obv_val, "trend": trend}

    def _vwap(self, df: pd.DataFrame, period: int = 50):
        """Rolling VWAP — kurumsal ortalama maliyet referansı."""
        try:
            vwap = VolumeWeightedAveragePrice(
                high=df["high"], low=df["low"], close=df["close"],
                volume=df["volume"], window=period,
            ).volume_weighted_average_price()
            return _safe(vwap)
        except Exception:
            return None

    def _volume_analysis(self, df: pd.DataFrame) -> dict:
        """Hacim analizi — ortalamaya göre oran ve spike tespiti."""
        vol = df["volume"]
        vol_ma = vol.rolling(20).mean()
        son = _safe(vol)
        ort = _safe(vol_ma)

        oran = None
        durum = None
        if son is not None and ort:
            oran = round(son / ort, 2)
            if oran >= 2.0:
                durum = "spike"
            elif oran >= 1.3:
                durum = "yüksek"
            elif oran <= 0.6:
                durum = "düşük"
            else:
                durum = "normal"

        return {"son_hacim": son, "ortalama_20": ort, "oran": oran, "durum": durum}

    def _rsi_divergence(self, df: pd.DataFrame, rsi: pd.Series, lookback: int = 60, swing: int = 3) -> dict:
        """
        RSI uyumsuzluğu (divergence) tespiti.
        Bullish: fiyat daha düşük dip, RSI daha yüksek dip → dönüş sinyali.
        Bearish: fiyat daha yüksek tepe, RSI daha düşük tepe → zayıflama sinyali.
        """
        df_t = df.tail(lookback).reset_index(drop=True)
        rsi_t = rsi.tail(lookback).reset_index(drop=True)

        lows, highs = [], []
        for i in range(swing, len(df_t) - swing):
            win_low = df_t["low"].iloc[i - swing: i + swing + 1]
            win_high = df_t["high"].iloc[i - swing: i + swing + 1]
            if df_t["low"].iloc[i] == win_low.min():
                lows.append(i)
            if df_t["high"].iloc[i] == win_high.max():
                highs.append(i)

        tespit = None
        detay = None

        if len(lows) >= 2:
            i1, i2 = lows[-2], lows[-1]
            p1, p2 = df_t["low"].iloc[i1], df_t["low"].iloc[i2]
            r1, r2 = rsi_t.iloc[i1], rsi_t.iloc[i2]
            if not (pd.isna(r1) or pd.isna(r2)) and p2 < p1 and r2 > r1:
                tespit = "bullish"
                detay = f"Fiyat düşük dip ({p2:.0f} < {p1:.0f}) ama RSI yüksek dip ({r2:.1f} > {r1:.1f})"

        if tespit is None and len(highs) >= 2:
            i1, i2 = highs[-2], highs[-1]
            p1, p2 = df_t["high"].iloc[i1], df_t["high"].iloc[i2]
            r1, r2 = rsi_t.iloc[i1], rsi_t.iloc[i2]
            if not (pd.isna(r1) or pd.isna(r2)) and p2 > p1 and r2 < r1:
                tespit = "bearish"
                detay = f"Fiyat yüksek tepe ({p2:.0f} > {p1:.0f}) ama RSI düşük tepe ({r2:.1f} < {r1:.1f})"

        return {"tespit": tespit, "detay": detay}

    def _premium_discount(self, df: pd.DataFrame, lookback: int = 100) -> dict:
        """
        SMC Premium/Discount — son aralığın ortası (equilibrium) referans alınır.
        Discount bölgesinde long, premium bölgesinde short aranır.
        """
        df_t = df.tail(lookback)
        range_high = float(df_t["high"].max())
        range_low = float(df_t["low"].min())
        equilibrium = (range_high + range_low) / 2
        close = float(df["close"].iloc[-1])

        konum = (close - range_low) / (range_high - range_low) if range_high != range_low else 0.5
        if konum >= 0.7:
            bolge = "premium"
        elif konum <= 0.3:
            bolge = "discount"
        else:
            bolge = "equilibrium"

        return {
            "aralik_tepe": round(range_high, 2),
            "aralik_dip": round(range_low, 2),
            "equilibrium": round(equilibrium, 2),
            "konum_yuzde": round(konum * 100, 1),
            "bolge": bolge,
        }

    def _support_resistance(self, df: pd.DataFrame, lookback: int = 150, swing: int = 5, cluster_pct: float = 0.005) -> dict:
        """
        Swing noktalarını kümeleyerek destek/direnç seviyeleri çıkarır.
        Birbirine %0.5 yakın seviyeler tek seviyede birleştirilir (dokunuş sayısıyla).
        """
        df_t = df.tail(lookback).reset_index(drop=True)
        close = float(df["close"].iloc[-1])
        pivots = []

        for i in range(swing, len(df_t) - swing):
            win_high = df_t["high"].iloc[i - swing: i + swing + 1]
            win_low = df_t["low"].iloc[i - swing: i + swing + 1]
            if df_t["high"].iloc[i] == win_high.max():
                pivots.append(float(df_t["high"].iloc[i]))
            if df_t["low"].iloc[i] == win_low.min():
                pivots.append(float(df_t["low"].iloc[i]))

        # Kümeleme
        clusters: list[list[float]] = []
        for p in sorted(pivots):
            if clusters and abs(p - clusters[-1][-1]) / p <= cluster_pct:
                clusters[-1].append(p)
            else:
                clusters.append([p])

        levels = [
            {"seviye": round(sum(c) / len(c), 2), "dokunus": len(c)}
            for c in clusters if len(c) >= 2
        ]

        destekler = sorted(
            [lv for lv in levels if lv["seviye"] < close],
            key=lambda x: x["seviye"], reverse=True,
        )[:3]
        direncler = sorted(
            [lv for lv in levels if lv["seviye"] >= close],
            key=lambda x: x["seviye"],
        )[:3]

        return {"destekler": destekler, "direncler": direncler}

    # ------------------------------------------------------------------
    # SMC (Smart Money Concepts)
    # ------------------------------------------------------------------

    def find_order_blocks(self, df: pd.DataFrame, lookback: int = 50) -> list:
        """
        SMC Order Block tespiti.
        Güçlü yukarı hareket öncesindeki son ayı mumu = bullish OB (destek)
        Güçlü aşağı hareket öncesindeki son boğa mumu = bearish OB (direnç)
        """
        blocks = []
        df = df.tail(lookback).reset_index(drop=True)
        threshold = 0.003  # %0.3 minimum hareket eşiği

        for i in range(1, len(df) - 2):
            candle = df.iloc[i]
            next1 = df.iloc[i + 1]

            move_up = (next1["close"] - candle["close"]) / candle["close"]
            move_down = (candle["close"] - next1["close"]) / candle["close"]

            # Bullish OB: ayı mumu ardından güçlü yukarı hareket
            if candle["close"] < candle["open"] and move_up > threshold:
                blocks.append({
                    "type": "bullish",
                    "top": float(candle["open"]),
                    "bottom": float(candle["low"]),
                    "index": i,
                })

            # Bearish OB: boğa mumu ardından güçlü aşağı hareket
            if candle["close"] > candle["open"] and move_down > threshold:
                blocks.append({
                    "type": "bearish",
                    "top": float(candle["high"]),
                    "bottom": float(candle["close"]),
                    "index": i,
                })

        return blocks[-3:] if len(blocks) > 3 else blocks

    def find_fair_value_gaps(self, df: pd.DataFrame, lookback: int = 30) -> list:
        """
        FVG tespiti: 3 ardışık mumda mum1.high < mum3.low → bullish FVG
        Fiyatın doldurması beklenen boşlukları işaret eder.
        """
        fvgs = []
        df = df.tail(lookback).reset_index(drop=True)

        for i in range(len(df) - 2):
            c1 = df.iloc[i]
            c3 = df.iloc[i + 2]

            if c1["high"] < c3["low"]:
                fvgs.append({
                    "type": "bullish",
                    "top": float(c3["low"]),
                    "bottom": float(c1["high"]),
                    "index": i + 1,
                })

            if c1["low"] > c3["high"]:
                fvgs.append({
                    "type": "bearish",
                    "top": float(c1["low"]),
                    "bottom": float(c3["high"]),
                    "index": i + 1,
                })

        return fvgs[-3:] if len(fvgs) > 3 else fvgs

    def find_liquidity_levels(self, df: pd.DataFrame, lookback: int = 50, swing_period: int = 5) -> dict:
        """
        Swing high/low = likidite havuzları.
        Stop emirleri bu seviyelerin etrafında birikir; büyük oyuncular
        bu seviyeleri sweep ederek likidite toplar.
        """
        df = df.tail(lookback).reset_index(drop=True)
        highs = []
        lows = []

        for i in range(swing_period, len(df) - swing_period):
            window_high = df["high"].iloc[i - swing_period: i + swing_period + 1]
            window_low = df["low"].iloc[i - swing_period: i + swing_period + 1]

            if df["high"].iloc[i] == window_high.max():
                highs.append(float(df["high"].iloc[i]))

            if df["low"].iloc[i] == window_low.min():
                lows.append(float(df["low"].iloc[i]))

        return {
            "swing_highs": sorted(set(highs), reverse=True)[:3],
            "swing_lows": sorted(set(lows))[:3],
        }

    def find_structure_breaks(self, df: pd.DataFrame, lookback: int = 50) -> dict:
        """
        BOS (Break of Structure): mevcut trendin devam ettiğini onaylar.
        CHoCH (Change of Character): trend tersine dönüş sinyali verir.
        """
        df = df.tail(lookback).reset_index(drop=True)
        result = {"bos": None, "choch": None}

        recent_highs = []
        recent_lows = []

        for i in range(1, len(df) - 1):
            if df["high"].iloc[i] > df["high"].iloc[i - 1] and df["high"].iloc[i] > df["high"].iloc[i + 1]:
                recent_highs.append((i, float(df["high"].iloc[i])))
            if df["low"].iloc[i] < df["low"].iloc[i - 1] and df["low"].iloc[i] < df["low"].iloc[i + 1]:
                recent_lows.append((i, float(df["low"].iloc[i])))

        last_close = float(df["close"].iloc[-1])

        if len(recent_highs) >= 2:
            prev_high = recent_highs[-2][1]
            if last_close > prev_high:
                result["bos"] = {"direction": "bullish", "level": prev_high}

        if len(recent_lows) >= 2:
            prev_low = recent_lows[-2][1]
            if last_close < prev_low:
                result["bos"] = {"direction": "bearish", "level": prev_low}

        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            if (recent_lows[-1][1] > recent_lows[-2][1] and
                    recent_highs[-1][1] > recent_highs[-2][1]):
                result["choch"] = {"direction": "bullish", "note": "Düşüşten dönüş sinyali"}
            elif (recent_highs[-1][1] < recent_highs[-2][1] and
                  recent_lows[-1][1] < recent_lows[-2][1]):
                result["choch"] = {"direction": "bearish", "note": "Yükselişten dönüş sinyali"}

        return result
