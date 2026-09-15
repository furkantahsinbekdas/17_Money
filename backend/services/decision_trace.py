"""
Karar izi (decision trace) — "arkada ne oluyor" şeffaflığı.

Her sinyal kararını, tıpkı bir AI'nın düşünme adımları gibi, ADIM ADIM açıklar:
yön skoru → model onayı → rejim → seans → bariyer kurulumu. Kullanıcı her işlemin
NEDEN o kararı verdiğini görür. İşlem bitince ayrıntılı rapor üretir.

Bu modül SADECE açıklama üretir (yorumlama katmanı) — karar mantığını DEĞİŞTİRMEZ,
sadece mevcut kararların gerekçesini insan-okunur adımlara çevirir. Claude YOK,
tamamen yerel/bedava.
"""

from __future__ import annotations


def build_trace(*, direction, forecast, score, regime_barriers, session, atr, entry) -> dict:
    """
    Bir sinyalin karar adımlarını üretir.
    direction: "LONG"/"SHORT"/None
    forecast: forecast_service.mtf_forecast çıktısı (yön, yon_endeksi...)
    score: meta_model.score çıktısı (olasilik, karar, esik) veya None
    regime_barriers: (tp_mult, sl_mult) — rejime göre seçilen çarpanlar
    session: session_filter.session_context çıktısı
    atr/entry: bariyer fiyat hesabı için
    """
    adimlar = []

    # Adım 1 — Yön analizi (forecast)
    endeks = forecast.get("yon_endeksi", 50) if forecast else 50
    guc = abs(endeks - 50) * 2  # 0-100
    adimlar.append({
        "no": 1,
        "ad": "Yön analizi",
        "girdi": "3 zaman dilimi (1g/4s/1s) teknik göstergeleri",
        "sonuc": f"{direction or 'BEKLE'} · güç {guc:.0f}/100",
        "aciklama": (
            f"Çoklu zaman dilimi göstergeleri {('yukarı' if direction=='LONG' else 'aşağı') if direction else 'kararsız'} "
            f"eğilim gösteriyor (yön endeksi {endeks:.0f}/100)."
            if direction else "Göstergeler yatay/çelişkili — sinyal üretilmez (BEKLE)."
        ),
    })

    if direction is None:
        return {"karar": "BEKLE", "adimlar": adimlar, "ozet": "Yatay piyasa — işlem açılmadı."}

    # Adım 2 — Seans (likidite) kontrolü
    dusuk = session.get("dusuk_likidite") if session else False
    adimlar.append({
        "no": 2,
        "ad": "Seans / likidite",
        "girdi": f"{session.get('seans','?') if session else '?'} ({session.get('saat_utc','?') if session else '?'}:00 UTC)",
        "sonuc": "DÜŞÜK likidite — riskli" if dusuk else "Yeterli likidite",
        "aciklama": (
            "Derin Asya gecesi (00-05 UTC) — teknik sinyaller daha az güvenilir, güven düşürülür."
            if dusuk else "Aktif seans — kurumsal hacim var, sinyaller daha güvenilir."
        ),
    })

    # Adım 3 — Model onayı (kötü sinyal eleme)
    if score:
        prob = score.get("olasilik")
        karar = score.get("karar")
        esik = score.get("esik")
        adimlar.append({
            "no": 3,
            "ad": "Model onayı (kötü sinyal eleme)",
            "girdi": "70 özellik → meta-model",
            "sonuc": f"{karar} · olasılık {prob} (eşik {esik})",
            "aciklama": (
                f"Model bu sinyalin kazanma olasılığını {prob} hesapladı. "
                + ("Eşiği geçti → işleme değer." if karar == "ONAYLA"
                   else "Eşiğin altında → istatistiksel olarak zayıf, atlanması önerilir.")
            ),
        })
    else:
        adimlar.append({
            "no": 3, "ad": "Model onayı", "girdi": "—",
            "sonuc": "Model yok", "aciklama": "Meta-model henüz eğitilmemiş — filtre uygulanmadı.",
        })

    # Adım 4 — Rejim & bariyer kurulumu
    tp_mult, sl_mult = regime_barriers
    rejim = "trend (geniş hedef)" if tp_mult >= 2.0 else ("yatay (dar hedef)" if tp_mult <= 1.0 else "ılımlı")
    rr = round(tp_mult / sl_mult, 2) if sl_mult else None
    bariyer_txt = ""
    if atr and entry:
        sign = 1 if direction == "LONG" else -1
        tp = entry + sign * tp_mult * atr
        sl = entry - sign * sl_mult * atr
        bariyer_txt = f" · giriş {entry:.0f} → hedef {tp:.0f} / stop {sl:.0f}"
    adimlar.append({
        "no": 4,
        "ad": "Rejim & hedef kurulumu",
        "girdi": "ADX (trend gücü)",
        "sonuc": f"{rejim} · TP {tp_mult}R / SL {sl_mult}R (R:R {rr}){bariyer_txt}",
        "aciklama": (
            f"Piyasa {rejim} rejiminde. Hedef buna göre ayarlandı: "
            + ("trend güçlü, geniş hedefle büyük hareketi yakala."
               if tp_mult >= 2.0 else "trend zayıf, dar hedefle çabuk al-çık.")
        ),
    })

    # Nihai karar
    nihai = "İŞLE" if (score and score.get("karar") == "ONAYLA" and not dusuk) else "ATLA/BEKLE"
    ozet_parc = []
    if score and score.get("karar") != "ONAYLA":
        ozet_parc.append("model elemesi")
    if dusuk:
        ozet_parc.append("düşük likidite")
    ozet = (
        f"{direction} işlemi açıldı (R:R {rr})." if nihai == "İŞLE"
        else f"İşlem atlandı: {', '.join(ozet_parc) or 'zayıf koşul'}."
    )

    return {"karar": nihai, "yon": direction, "adimlar": adimlar, "ozet": ozet}


def build_report(trade: dict) -> dict:
    """
    Bir işlem ÇÖZÜLDÜKTEN sonra ayrıntılı sonuç raporu.
    trade: paper_trades satırı (label, pnl_r, pnl_dollar, r_win, r_loss,
           entry_price, exit_price, direction, balance_after...)
    """
    label = trade.get("label")
    kazandi = label == 1
    rr = round(trade.get("r_win", 0) / trade.get("r_loss", 1), 2) if trade.get("r_loss") else None
    return {
        "sonuc": "KAZANÇ" if kazandi else "KAYIP",
        "yon": trade.get("direction"),
        "giris": trade.get("entry_price"),
        "cikis": trade.get("exit_price"),
        "kar_zarar_dolar": trade.get("pnl_dollar"),
        "kar_zarar_R": trade.get("pnl_r"),
        "risk_odul": rr,
        "yeni_sermaye": trade.get("balance_after"),
        "yorum": (
            f"{trade.get('direction')} işlemi {'hedefe ulaştı' if kazandi else 'stop oldu'}. "
            + (f"Kazanç {trade.get('pnl_r')}R (R:R {rr} — kazanç kayıptan büyük, sistemin sırrı bu)."
               if kazandi else
               f"Kayıp {trade.get('pnl_r')}R. Tek kayıp normal — sistem uzun vadede kazanır, "
               "her işlem değil.")
        ),
    }
