"""
Backtest Servisi — geçmiş veride hayali işlem simülasyonu.
==========================================================

Kullanıcının "şu kadar hayali işlem yaptım, geçmiş yılların verisiyle şu kadar
başarılı oldum" raporu. Eğitim durdurulunca gösterilir.

Mantık: Elimizde 2017→2024 geçmişinden üretilmiş, triple-barrier ile
etiketlenmiş binlerce sinyal var (kazandı=1 / kaybetti=0, gerçek fiyat
hareketiyle doğrulanmış). Bu, "geçmişte bu sinyalle işlem açsaydım ne olurdu"
sorusunun GERÇEK cevabıdır — uydurma değil.

İki senaryo karşılaştırılır:
- HAM: tüm sinyaller (meta-model filtresi YOK)
- FİLTRELİ: sadece şampiyon modelin onayladığı sinyaller (meta_prob ≥ eşik)

Böylece "model bana ne kattı" net görünür. Risk/ödül 1.5:1 (TP_ATR/SL_ATR)
olduğundan her kazanç +1.5R, her kayıp -1R sayılır (R = riske edilen birim).
"""

import numpy as np

from services.signal_store import TP_ATR_MULT, SL_ATR_MULT
from services.meta_model import meta_model, DEFAULT_THRESHOLD
from services.feature_service import FEATURE_COLUMNS

import config


# Gerçekçi işlem maliyeti (R cinsinden) config.py'de: komisyon + funding + slipaj.
# Tek kaynak: paper_account ile AYNI değer (COST_PER_TRADE_R / PAPER_COST_R).
COST_PER_TRADE_R = config.COST_PER_TRADE_R


def _equity_curve(labels, r_win=TP_ATR_MULT, r_loss=SL_ATR_MULT, cost_R=0.0):
    """
    Etiket dizisinden (1=kazanç, 0=kayıp) R-cinsinden birikimli getiri ve
    maksimum düşüş (drawdown) hesaplar. Her işlemde sabit 1 birim risk.
    cost_R: her işlemden düşülen gerçekçi maliyet (komisyon+funding+slipaj).

    r_win/r_loss SKALER (sabit R:R, eski davranış) veya işlem-başına DİZİ
    olabilir — rejime-duyarlı etiketlemede her sinyalin gerçek TP/SL oranı
    farklıdır (trend rejiminde win=2.5R, yatayda win=1R). Dizi verildiğinde
    her işlem kendi gerçek R'siyle hesaplanır; sabit varsayım sahte sonuç verir.
    """
    if not len(labels):
        return {"islem": 0}
    labels = np.array(labels)
    rw = np.asarray(r_win, dtype=float)
    rl = np.asarray(r_loss, dtype=float)
    if rw.ndim == 0:
        rw = np.full(len(labels), float(rw))
    if rl.ndim == 0:
        rl = np.full(len(labels), float(rl))
    pnl = np.where(labels == 1, rw, -rl) - cost_R
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    n = len(labels)
    wins = int(np.sum(np.array(labels) == 1))
    return {
        "islem": n,
        "kazanan": wins,
        "kaybeden": n - wins,
        "basari_orani": round(wins / n, 3),
        "toplam_getiri_R": round(float(equity[-1]), 2),
        "ortalama_R": round(float(np.mean(pnl)), 3),
        "max_drawdown_R": round(float(abs(drawdown.min())), 2),
        # Beklenti (expectancy): işlem başına ortalama kazanç, R cinsinden
        "beklenti_R": round(float(np.mean(pnl)), 3),
        "maliyet_dahil": cost_R > 0,
    }


def _equity_from_trades(trades, cost_R=0.0):
    """(label, r_win, r_loss) tuple listesinden equity hesaplar —
    her işlem kendi gerçek R:R'siyle (rejime-duyarlı)."""
    if not trades:
        return {"islem": 0}
    labels = [t[0] for t in trades]
    rw = [t[1] for t in trades]
    rl = [t[2] for t in trades]
    return _equity_curve(labels, r_win=rw, r_loss=rl, cost_R=cost_R)


def _signal_rr(r: dict) -> tuple[float, float]:
    """Bir sinyalin GERÇEK (r_win, r_loss) oranı — rejime-duyarlı etiketlemede
    sinyalden sinyale değişir. Fiyatlardan geri hesaplanır; eksikse sabit varsayım.
    Sabit varsayıma düşmek, eski sabit-bariyer verisiyle geriye uyumu korur."""
    atr = r.get("atr")
    ep, tp, sl = r.get("entry_price"), r.get("tp_price"), r.get("sl_price")
    if atr and atr > 0 and ep is not None and tp is not None and sl is not None:
        return abs(tp - ep) / atr, abs(ep - sl) / atr
    return TP_ATR_MULT, SL_ATR_MULT


def run_backtest(store, threshold: float | None = None, train_frac: float = 0.6) -> dict:
    """
    Etiketli geçmiş sinyaller üzerinde DÜRÜST (walk-forward) hayali işlem
    simülasyonu. Ham vs meta-model-filtreli karşılaştırması.

    KRİTİK: Veri sızıntısını önlemek için model SADECE ilk train_frac (%60)
    veriyle eğitilir, geri kalan %40'ta test edilir. Yani model test
    işlemlerini ÖNCEDEN GÖRMEZ — gerçek hayatta olacağı gibi. Tüm veriyle
    eğitip aynı veride test etmek %99 gibi SAHTE sonuç verir (lookahead bias).
    """
    import json
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier

    with store._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT created_at, features, label, direction,
                      entry_price, tp_price, sl_price, atr FROM signals
               WHERE label IS NOT NULL AND direction IN ('LONG','SHORT')
               ORDER BY created_at"""
        )]

    if len(rows) < 200:
        return {"yeterli_veri": False,
                "neden": f"Walk-forward backtest için en az 200 etiketli sinyal gerekir ({len(rows)} var)."}

    # Zaman sıralı bölme — eğitim geçmişte, test gelecekte (sızıntı yok)
    split = int(len(rows) * train_frac)
    train_rows, test_rows = rows[:split], rows[split:]

    ham_trades = [(r["label"], *_signal_rr(r)) for r in test_rows]
    ham = _equity_from_trades(ham_trades)
    ham["tarih_ilk"] = test_rows[0]["created_at"][:10]
    ham["tarih_son"] = test_rows[-1]["created_at"][:10]
    ham["aciklama"] = "Filtresiz: her sinyalde işlem (model devre dışı)"

    sonuc = {
        "yeterli_veri": True,
        "yontem": "Walk-forward: model ilk %60'la eğitildi, son %40'ta test edildi (sızıntısız).",
        "egitim_ornegi": len(train_rows),
        "test_ornegi": len(test_rows),
        "ham": ham,
    }

    # --- Filtreli: SADECE eğitim verisiyle model kur, test verisinde uygula ---
    def _feat_matrix(rs):
        return pd.DataFrame(
            [{c: (json.loads(r["features"]).get(c)) for c in FEATURE_COLUMNS} for r in rs]
        ).astype(float)

    y_train = pd.Series([r["label"] for r in train_rows])
    if y_train.nunique() < 2:
        sonuc["filtreli"] = {"neden": "Eğitim verisinde tek sınıf — filtre kurulamadı."}
        return sonuc

    model = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=20, l2_regularization=1.0,
        early_stopping=False, random_state=42,
    )
    model.fit(_feat_matrix(train_rows), y_train)

    th = threshold if threshold is not None else DEFAULT_THRESHOLD
    test_proba = model.predict_proba(_feat_matrix(test_rows))[:, 1]
    filt_trades = [(test_rows[i]["label"], *_signal_rr(test_rows[i]))
                   for i in range(len(test_rows)) if test_proba[i] >= th]

    if filt_trades:
        filt = _equity_from_trades(filt_trades)
        filt["esik"] = th
        filt["aciklama"] = "Filtreli: sadece modelin onayladığı sinyallerde işlem"
        sonuc["filtreli"] = filt
        sonuc["kazanim"] = {
            "basari_artisi": round(filt["basari_orani"] - ham["basari_orani"], 3),
            "islem_azalmasi": ham["islem"] - filt["islem"],
            "kapsam": round(filt["islem"] / ham["islem"], 3) if ham["islem"] else 0,
        }
    else:
        sonuc["filtreli"] = {"islem": 0, "neden": f"Eşik {th} üstü test sinyali yok."}

    return sonuc


def robust_backtest(store, n_periods: int = 5, threshold: float | None = None,
                    cost_R: float = COST_PER_TRADE_R) -> dict:
    """
    SAĞLAM çoklu-pencere backtest (rolling walk-forward) + gerçekçi maliyet.

    Tek bir %60/%40 bölme yanıltıcı olabilir — model tek bir döneme şanslıca
    uymuş olabilir. Bu yöntem veriyi n_periods ardışık döneme böler ve her
    dönemde "önceki tüm dönemlerle eğit, BU dönemde test et" yapar. Sonuç:
    her dönemin ayrı sonucu + TUTARLILIK (kaç dönem pozitif).

    Kenar gerçekse çoğu dönemde +R verir. Sadece 1 dönemde +R, ötekilerde
    -R veriyorsa o "kenar" yanıltıcıydı (overfitting/şans).

    Maliyet: her işlemden cost_R düşülür (komisyon+funding+slipaj) — gerçek tablo.
    Kaynak: López de Prado, walk-forward + purged CV literatürü.
    """
    import json
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier

    with store._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT created_at, features, label,
                      entry_price, tp_price, sl_price, atr FROM signals
               WHERE label IS NOT NULL AND direction IN ('LONG','SHORT')
               ORDER BY created_at"""
        )]

    # Her dönemde anlamlı test için yeterli veri gerekir
    if len(rows) < n_periods * 150:
        return {"yeterli_veri": False,
                "neden": f"{n_periods}-dönem testi için en az {n_periods*150} sinyal gerekir ({len(rows)} var)."}

    def _feat_matrix(rs):
        return pd.DataFrame(
            [{c: (json.loads(r["features"]).get(c)) for c in FEATURE_COLUMNS} for r in rs]
        ).astype(float)

    th = threshold if threshold is not None else DEFAULT_THRESHOLD
    # Veriyi n eşit ardışık döneme böl; ilk dönem sadece eğitim (test yok)
    bounds = [int(len(rows) * k / n_periods) for k in range(n_periods + 1)]

    donemler = []
    tum_filt_labels = []
    tum_ham_labels = []
    pozitif_donem = 0

    for p in range(1, n_periods):
        tr = rows[:bounds[p]]          # önceki TÜM dönemler (genişleyen pencere)
        te = rows[bounds[p]:bounds[p + 1]]  # bu dönem
        if len(te) < 30:
            continue
        y_tr = pd.Series([r["label"] for r in tr])
        if y_tr.nunique() < 2:
            continue

        model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=1.0,
            early_stopping=False, random_state=42,
        )
        model.fit(_feat_matrix(tr), y_tr)
        proba = model.predict_proba(_feat_matrix(te))[:, 1]
        # Her test sinyali için (label, r_win, r_loss) — gerçek rejim-duyarlı R
        te_rr = [_signal_rr(te[i]) for i in range(len(te))]
        filt = [(te[i]["label"], te_rr[i][0], te_rr[i][1])
                for i in range(len(te)) if proba[i] >= th]
        ham = [(te[i]["label"], te_rr[i][0], te_rr[i][1]) for i in range(len(te))]

        tum_ham_labels += ham
        tum_filt_labels += filt

        f_eq = _equity_from_trades(filt, cost_R=cost_R) if filt else {"islem": 0}
        getiri = f_eq.get("toplam_getiri_R", 0)
        if f_eq.get("islem", 0) > 0 and getiri > 0:
            pozitif_donem += 1
        donemler.append({
            "donem": p,
            "tarih_ilk": te[0]["created_at"][:10],
            "tarih_son": te[-1]["created_at"][:10],
            "islem": f_eq.get("islem", 0),
            "basari_orani": f_eq.get("basari_orani"),
            "net_getiri_R": getiri,
            "beklenti_R": f_eq.get("beklenti_R"),
        })

    test_donem = len(donemler)
    if test_donem == 0:
        return {"yeterli_veri": False, "neden": "Hiçbir dönem test edilemedi."}

    # Birleşik (maliyet dahil) sonuç — işlem-başına gerçek R ile
    ham_top = _equity_from_trades(tum_ham_labels, cost_R=cost_R) if tum_ham_labels else {"islem": 0}
    filt_top = _equity_from_trades(tum_filt_labels, cost_R=cost_R) if tum_filt_labels else {"islem": 0}

    tutarlilik = round(pozitif_donem / test_donem, 2)
    # Hüküm: çoğu dönem pozitifse kenar güvenilir
    if tutarlilik >= 0.8:
        huküm = "GÜVENİLİR — dönemlerin çoğunda pozitif, kenar tutarlı."
    elif tutarlilik >= 0.6:
        huküm = "UMUT VERİCİ — çoğu dönem pozitif ama tam istikrar yok, izle."
    elif tutarlilik >= 0.4:
        huküm = "KARARSIZ — dönemlere göre değişiyor, kenar zayıf/şüpheli."
    else:
        huküm = "GÜVENİLMEZ — çoğu dönem negatif, görünen getiri yanıltıcı."

    return {
        "yeterli_veri": True,
        "yontem": f"Rolling walk-forward: {test_donem} ayrı dönemde test, "
                  f"her dönemde önceki tüm dönemlerle eğitildi. Maliyet dahil (işlem başı {cost_R}R).",
        "donem_sayisi": test_donem,
        "pozitif_donem": pozitif_donem,
        "tutarlilik": tutarlilik,
        "huküm": huküm,
        "donemler": donemler,
        "birlesik_ham": ham_top,
        "birlesik_filtreli": filt_top,
        "maliyet_R": cost_R,
    }


def _deflated_sharpe(sharpes: list, observed_best: float) -> float:
    """
    Deflated Sharpe Ratio (López de Prado) basitleştirilmiş —
    "bu kadar deneme yaptık, en iyisi şans eseri mi iyi göründü?" cevabı.

    N farklı test yolundan en iyi Sharpe'ı, denemelerin varyansı ve sayısıyla
    ceza­landırır. Çıktı: gözlenen en iyi Sharpe'ın GERÇEK (şans değil) olma
    olasılığı (0-1). 0.95+ = güçlü kanıt, <0.5 = muhtemelen şans.
    """
    import math
    n = len(sharpes)
    if n < 2:
        return 0.0
    arr = np.array(sharpes, dtype=float)
    var = float(np.var(arr, ddof=1))
    if var <= 1e-12:
        return 1.0 if observed_best > 0 else 0.0
    # Beklenen maksimum (çok deneme yaparsan en iyisi şişer) — Gumbel yaklaşımı
    emc = 0.5772156649  # Euler-Mascheroni
    z1 = float(np.percentile(np.random.standard_normal(10000), 100 * (1 - 1.0 / n)))
    z2 = float(np.percentile(np.random.standard_normal(10000), 100 * (1 - 1.0 / (n * math.e))))
    beklenen_max = math.sqrt(var) * ((1 - emc) * z1 + emc * z2)
    # Gözlenen en iyi, beklenen maksimumu ne kadar aşıyor → standart normal cdf
    z = (observed_best - beklenen_max) / (math.sqrt(var) + 1e-12)
    # Normal CDF (erf ile)
    return round(0.5 * (1 + math.erf(z / math.sqrt(2))), 3)


def cpcv_backtest(store, n_groups: int = 6, k_test: int = 2,
                  cost_R: float = COST_PER_TRADE_R, max_paths: int = 15) -> dict:
    """
    Combinatorial Purged Cross-Validation (López de Prado 2017) — walk-forward'dan
    DAHA SAĞLAM kanıt testi. Akademik konsensüs: en düşük overfitting riski.

    Mantık: Veriyi n_groups gruba böl. Bu gruplardan k_test tanesini TEST,
    gerisini EĞİTİM yapan TÜM kombinasyonları dene (purge: test komşusu barları
    eğitimden çıkar — sızıntı yok). Her kombinasyon bir "yol" = bir getiri sonucu.

    Sonuç: tek bir sayı değil, bir DAĞILIM (kaç yolda pozitif, ortalama, en kötü).
    + Deflated Sharpe: "en iyi yol şans eseri mi iyi göründü?" cezası.

    Bu, '+14R gerçek kenar mı yoksa şans mı' sorusunu istatistiksel kapatır.
    """
    import json
    import math
    from itertools import combinations
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier

    with store._conn() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT created_at, features, label,
                      entry_price, tp_price, sl_price, atr FROM signals
               WHERE label IS NOT NULL AND direction IN ('LONG','SHORT')
               ORDER BY created_at"""
        )]

    if len(rows) < n_groups * 200:
        return {"yeterli_veri": False,
                "neden": f"CPCV için en az {n_groups*200} sinyal gerekir ({len(rows)} var)."}

    def _feat_matrix(rs):
        return pd.DataFrame(
            [{c: (json.loads(r["features"]).get(c)) for c in FEATURE_COLUMNS} for r in rs]
        ).astype(float)

    # Grupları zaman sıralı eşit böl
    bounds = [int(len(rows) * g / n_groups) for g in range(n_groups + 1)]
    groups = [list(range(bounds[g], bounds[g + 1])) for g in range(n_groups)]
    embargo = max(5, len(rows) // 200)  # purge tamponu (komşu sızıntı önleme)

    # k_test'li tüm kombinasyonlar (çok fazlaysa kırp)
    combos = list(combinations(range(n_groups), k_test))[:max_paths]
    th = DEFAULT_THRESHOLD

    yol_getiriler, yol_sharpes, yol_basari = [], [], []
    pozitif_yol = 0

    for test_groups in combos:
        test_idx = sorted(i for g in test_groups for i in groups[g])
        # purge: test indekslerinin embargo komşuluğunu eğitimden çıkar
        yasak = set()
        for i in test_idx:
            for j in range(i - embargo, i + embargo + 1):
                yasak.add(j)
        train_idx = [i for i in range(len(rows)) if i not in set(test_idx) and i not in yasak]
        if len(train_idx) < 200 or len(test_idx) < 50:
            continue

        tr = [rows[i] for i in train_idx]
        te = [rows[i] for i in test_idx]
        y_tr = pd.Series([r["label"] for r in tr])
        if y_tr.nunique() < 2:
            continue

        model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=1.0,
            early_stopping=False, random_state=42,
        )
        model.fit(_feat_matrix(tr), y_tr)
        proba = model.predict_proba(_feat_matrix(te))[:, 1]
        # Rejime-duyarlı gerçek R ile (her sinyal kendi TP/SL oranıyla)
        filt = [(te[i]["label"], *_signal_rr(te[i]))
                for i in range(len(te)) if proba[i] >= th]
        if not filt:
            continue

        eq = _equity_from_trades(filt, cost_R=cost_R)
        getiri = eq["toplam_getiri_R"]
        # işlem başına Sharpe benzeri: ortalama / std (gerçek rejim-duyarlı R)
        f_lab = np.array([t[0] for t in filt])
        f_rw = np.array([t[1] for t in filt])
        f_rl = np.array([t[2] for t in filt])
        pnl = np.where(f_lab == 1, f_rw, -f_rl) - cost_R
        sharpe = float(np.mean(pnl) / (np.std(pnl) + 1e-9)) if len(pnl) > 1 else 0.0
        yol_getiriler.append(round(getiri, 2))
        yol_sharpes.append(sharpe)
        yol_basari.append(eq["basari_orani"])
        if getiri > 0:
            pozitif_yol += 1

    n_yol = len(yol_getiriler)
    if n_yol == 0:
        return {"yeterli_veri": False, "neden": "Hiçbir CPCV yolu test edilemedi."}

    arr = np.array(yol_getiriler)
    sharpe_arr = np.array(yol_sharpes)
    en_iyi_sharpe = float(np.max(sharpe_arr))
    dsr = _deflated_sharpe(yol_sharpes, en_iyi_sharpe)
    pozitif_oran = round(pozitif_yol / n_yol, 2)

    # Hüküm: hem yolların çoğu pozitif OLMALI hem DSR yüksek olmalı
    if pozitif_oran >= 0.8 and dsr >= 0.9:
        huküm = "GÜÇLÜ KANIT — yolların çoğu pozitif ve şans olasılığı düşük. Kenar gerçek."
    elif pozitif_oran >= 0.7 and dsr >= 0.6:
        huküm = "MAKUL KANIT — çoğu yol pozitif ama biraz şans payı var. Dikkatle kullan."
    elif pozitif_oran >= 0.5:
        huküm = "ZAYIF — yolların yarısı pozitif, kenar belirsiz/kırılgan."
    else:
        huküm = "KANIT YOK — yolların çoğu negatif, görünen getiri büyük olasılıkla şans."

    return {
        "yeterli_veri": True,
        "yontem": f"CPCV: {n_yol} farklı eğitim/test yolu (purge+embargo {embargo} bar). "
                  f"Maliyet dahil. Walk-forward'dan sağlam (López de Prado).",
        "yol_sayisi": n_yol,
        "pozitif_yol": pozitif_yol,
        "pozitif_oran": pozitif_oran,
        "ortalama_getiri_R": round(float(np.mean(arr)), 2),
        "medyan_getiri_R": round(float(np.median(arr)), 2),
        "en_kotu_R": round(float(np.min(arr)), 2),
        "en_iyi_R": round(float(np.max(arr)), 2),
        "deflated_sharpe": dsr,   # 0-1, gerçeklik olasılığı
        "ortalama_basari": round(float(np.mean(yol_basari)), 3),
        "huküm": huküm,
        "maliyet_R": cost_R,
    }
