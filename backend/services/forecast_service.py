"""
17Money Tahmin Motoru — VantagePoint AI'dan esinlenen yapı:

- Yön Endeksi (0-100): VantagePoint'in "Neural Index"inin karşılığı.
  Tüm göstergelerin ağırlıklı konsensüsü; 50 üstü boğa, altı ayı baskısı.
- Tahmini 24s Aralık: VantagePoint'in "Predicted High/Low" karşılığı.
  Günlük ATR + yön eğilimi ile asimetrik bant.
- Trend Vektörleri: kısa (15m+1h) / orta (1h+4h) / uzun (4h+1d) vade
  yön ve güç — VantagePoint'in predicted MA crossover üçlüsünün karşılığı.

Tamamen deterministik çalışır (Claude anahtarı gerektirmez); AI katmanı
bu çıktıyı girdi olarak alıp yorum ve senaryo ekler.
"""

import config


# Ağırlık tabloları config.py'de (FORECAST_WEIGHTS / FORECAST_HORIZON_BLEND /
# FORECAST_OVERALL_BLEND — hepsi .env ile ezilebilir).
WEIGHTS = config.FORECAST_WEIGHTS

HORIZON_BLEND = config.FORECAST_HORIZON_BLEND

OVERALL_BLEND = config.FORECAST_OVERALL_BLEND


class ForecastService:

    def direction_score(self, a: dict) -> dict:
        """
        Tek zaman dilimi için -1..+1 arası ağırlıklı yön skoru ve
        gösterge bazında katkı dökümü üretir.
        """
        contributions = []

        def add(name, raw_score, detail):
            w = WEIGHTS[name]
            contributions.append({
                "gosterge": name,
                "skor": round(raw_score, 2),     # -1..+1
                "agirlik": w,
                "katki": round(raw_score * w, 3),
                "detay": detail,
            })

        # EMA dizilimi
        trend = a.get("trend", "belirsiz")
        trend_map = {
            "güçlü_yükseliş": 1.0, "yükseliş": 0.5, "yatay": 0.0,
            "düşüş": -0.5, "güçlü_düşüş": -1.0, "belirsiz": 0.0,
        }
        add("ema_dizilimi", trend_map.get(trend, 0.0), trend)

        # MACD: histogram işareti + kesişim + momentum
        macd = a.get("macd") or {}
        s = 0.0
        hist = macd.get("histogram")
        if hist is not None:
            s += 0.4 if hist > 0 else -0.4
        if macd.get("crossover") == "bullish":
            s += 0.4
        elif macd.get("crossover") == "bearish":
            s -= 0.4
        if macd.get("histogram_momentum") == "güçleniyor":
            s += 0.2 if (hist or 0) > 0 else -0.2  # mevcut yön güçleniyor
        elif macd.get("histogram_momentum") == "zayıflıyor":
            s -= 0.2 if (hist or 0) > 0 else -0.2
        add("macd", max(-1.0, min(1.0, s)),
            f"hist={hist}, kesişim={macd.get('crossover')}, momentum={macd.get('histogram_momentum')}")

        # ADX yönü — trend gücüyle ölçeklenir (chop'ta sinyal kısılır)
        adx = a.get("adx") or {}
        adx_val, dip, dim = adx.get("adx"), adx.get("di_plus"), adx.get("di_minus")
        s = 0.0
        if dip is not None and dim is not None:
            yon = 1.0 if dip > dim else -1.0
            guc = adx.get("trend_gucu")
            mult = {"trendsiz_chop": 0.2, "zayıf_trend": 0.5,
                    "güçlü_trend": 1.0, "çok_güçlü_trend": 0.8}.get(guc, 0.5)
            s = yon * mult
        add("adx_yon", s, f"ADX={adx_val}, DI+={dip}, DI-={dim}, güç={adx.get('trend_gucu')}")

        # Yapı: BOS / CHoCH
        struct = a.get("structure") or {}
        s = 0.0
        detay = []
        bos = struct.get("bos")
        if bos:
            s += 1.0 if bos.get("direction") == "bullish" else -1.0
            detay.append(f"BOS {bos.get('direction')}")
        choch = struct.get("choch")
        if choch:
            s += 0.75 if choch.get("direction") == "bullish" else -0.75
            detay.append(f"CHoCH {choch.get('direction')}")
        add("yapi", max(-1.0, min(1.0, s)), ", ".join(detay) or "kırılım yok")

        # Divergence
        div = a.get("divergence") or {}
        s = {"bullish": 1.0, "bearish": -1.0}.get(div.get("tespit"), 0.0)
        add("divergence", s, div.get("detay") or "tespit yok")

        # RSI
        rsi = a.get("rsi")
        s = 0.0
        if rsi is not None:
            if rsi >= 60:
                s = 1.0
            elif rsi >= 50:
                s = 0.5
            elif rsi >= 40:
                s = -0.5
            else:
                s = -1.0
        add("rsi", s, f"RSI={rsi}")

        # OBV
        obv = a.get("obv") or {}
        s = {"yükselen": 1.0, "düşen": -1.0}.get(obv.get("trend"), 0.0)
        add("obv", s, f"OBV trendi {obv.get('trend')}")

        # Bollinger pozisyonu
        bb = a.get("bollinger") or {}
        s = {"üst_bant_üstü": 1.0, "orta_üstü": 0.5,
             "orta_altı": -0.5, "alt_bant_altı": -1.0}.get(bb.get("pozisyon"), 0.0)
        add("bollinger", s,
            f"pozisyon={bb.get('pozisyon')}, squeeze={bb.get('squeeze')}")

        # StochRSI — kontraryan zamanlama sinyali
        srsi = a.get("stoch_rsi") or {}
        s = {"aşırı_satım": 0.5, "aşırı_alım": -0.5}.get(srsi.get("durum"), 0.0)
        add("stoch_rsi", s, f"K={srsi.get('k')}, durum={srsi.get('durum')}")

        # VWAP
        vwap = a.get("vwap")
        price = a.get("current_price")
        s = 0.0
        if vwap is not None and price is not None:
            s = 0.5 if price > vwap else -0.5
        add("vwap", s, f"fiyat {'üstünde' if s > 0 else 'altında' if s < 0 else '—'}")

        # Premium/Discount — discount long dostu
        pd_zone = (a.get("premium_discount") or {}).get("bolge")
        s = {"discount": 0.5, "premium": -0.5}.get(pd_zone, 0.0)
        add("premium_discount", s, f"bölge={pd_zone}")

        total = sum(c["katki"] for c in contributions)
        max_total = sum(WEIGHTS.values())
        norm = max(-1.0, min(1.0, total / max_total))  # -1..+1

        return {
            "skor": round(norm, 4),
            "endeks": round((norm + 1) * 50, 1),  # 0-100
            "katkilar": contributions,
        }

    def mtf_forecast(self, analyses: dict) -> dict:
        """
        analyses: {"15m": calculate_all(...), "1h": ..., "4h": ..., "1d": ...}
        VantagePoint tarzı tam tahmin paketi döndürür.
        """
        per_tf = {tf: self.direction_score(a) for tf, a in analyses.items()}

        # Vade vektörleri
        vektorler = {}
        for horizon, blend in HORIZON_BLEND.items():
            score = sum(per_tf[tf]["skor"] * w for tf, w in blend.items() if tf in per_tf)
            endeks = round((score + 1) * 50, 1)
            vektorler[horizon] = {
                "endeks": endeks,
                "yon": "yukarı" if endeks >= 55 else "aşağı" if endeks <= 45 else "yatay",
                "guc": self._strength_label(endeks),
            }

        genel_skor = sum(
            ((vektorler[h]["endeks"] / 50) - 1) * w
            for h, w in OVERALL_BLEND.items()
        )
        genel_endeks = round((genel_skor + 1) * 50, 1)

        # Tahmini 24 saat aralığı — günlük ATR + yön eğilimli asimetri
        d1 = analyses.get("1d", {})
        price = d1.get("current_price")
        atr_1d = (d1.get("atr") or {}).get("atr")
        aralik = None
        if price and atr_1d:
            bias = (genel_endeks - 50) / 50  # -1..+1
            up_mult = 0.7 + 0.4 * max(0.0, bias)
            dn_mult = 0.7 + 0.4 * max(0.0, -bias)
            aralik = {
                "beklenen_yuksek": round(price + atr_1d * up_mult, 1),
                "beklenen_dusuk": round(price - atr_1d * dn_mult, 1),
                "atr_1d": round(atr_1d, 1),
            }

        # MTF uyum kontrolü
        endeksler = [v["endeks"] for v in vektorler.values()]
        uyum = max(endeksler) - min(endeksler) <= 25 if endeksler else False

        return {
            "yon_endeksi": genel_endeks,
            "yon": "yukarı" if genel_endeks >= 55 else "aşağı" if genel_endeks <= 45 else "yatay",
            "guc": self._strength_label(genel_endeks),
            "mtf_uyumlu": uyum,
            "vektorler": vektorler,
            "tahmini_aralik_24s": aralik,
            "zaman_dilimi_detay": {
                tf: {"endeks": v["endeks"], "katkilar": v["katkilar"]}
                for tf, v in per_tf.items()
            },
        }

    @staticmethod
    def _strength_label(endeks: float) -> str:
        d = abs(endeks - 50)
        if d >= 30:
            return "çok_güçlü"
        if d >= 18:
            return "güçlü"
        if d >= 8:
            return "ılımlı"
        return "zayıf"
