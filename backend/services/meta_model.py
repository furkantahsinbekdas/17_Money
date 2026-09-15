"""
Meta-model — Sprint 4.

López de Prado'nun meta-labeling yaklaşımı: birincil model (Claude sinyali /
deterministik kural) YÖNÜ söyler; bu model "bu sinyal tutacak mı?" sorusuna
olasılık verir. Düşük olasılıklı sinyaller filtrelenir → işlem sayısı düşer,
kalan işlemlerin isabeti yükselir.

Model: HistGradientBoostingClassifier
- NaN'i doğal işler (eksik funding/OI/fear_greed sorun değil)
- numba gerektirmez (Python 3.14 uyumlu)

Doğrulama: ZAMAN SIRALI %70/30 bölme (shuffle YOK — finansal veride
karıştırmalı CV bakış-ileri sızıntısıdır). Erken durdurma kapalı çünkü
sklearn'ün iç doğrulama bölmesi rastgeledir.
"""

import json
import os
import threading
from datetime import datetime

import numpy as np
import pandas as pd

from services.feature_service import FEATURE_COLUMNS

import config

# Yollar ve eşikler config.py'de (DATA_DIR / META_* / TRAIN_*)
MODEL_PATH = config.META_MODEL_PATH
META_PATH = config.META_INFO_PATH
# Ebeveyn (bir önceki nesil) — geri-alma güvencesi (model çöküşü/zehirlenme için)
PARENT_MODEL_PATH = config.PARENT_MODEL_PATH
PARENT_META_PATH = config.PARENT_INFO_PATH

MIN_SAMPLES = config.MIN_SAMPLES              # altında eğitim reddedilir
DEFAULT_THRESHOLD = config.DEFAULT_THRESHOLD  # işlem onay eşiği


class MetaModel:

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._meta: dict | None = None
        self._load()

    # ------------------------------------------------------------------
    def _load(self):
        try:
            if os.path.exists(MODEL_PATH) and os.path.exists(META_PATH):
                import joblib
                self._model = joblib.load(MODEL_PATH)
                with open(META_PATH, encoding="utf-8") as f:
                    self._meta = json.load(f)
        except Exception as e:
            print(f"[meta_model] model yüklenemedi: {e}")
            self._model, self._meta = None, None

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def info(self) -> dict | None:
        return self._meta

    # ------------------------------------------------------------------
    def train(self, X: pd.DataFrame, y: pd.Series, promote: bool = True) -> dict:
        """
        promote=True (manuel eğitim): değerlendirir VE canlı şampiyonu değiştirir.
        promote=False (meydan-okuyan): sadece değerlendirir, raporu döndürür,
          canlı modeli DEĞİŞTİRMEZ. Terfi kararını çağıran (trainer_service) verir.

        Zaman sıralı veriyle eğitir, son %30 üzerinde değerlendirir,
        modeli diske yazar. Dönen sözlük eğitim raporudur.
        """
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import precision_score, recall_score, roc_auc_score

        if len(X) < MIN_SAMPLES:
            return {
                "egitildi": False,
                "neden": f"Yetersiz etiketli veri: {len(X)} < {MIN_SAMPLES}. "
                         f"Önce backfill çalıştırın veya canlı sinyal biriktirin.",
            }
        if y.nunique() < 2:
            return {"egitildi": False, "neden": "Tek sınıf var — hem kazanan hem kaybeden örnek gerekli."}

        # Kanonik sütun hizalaması (eksikler NaN)
        X = X.reindex(columns=FEATURE_COLUMNS).astype(float)

        split = int(len(X) * 0.7)
        X_tr, X_te = X.iloc[:split], X.iloc[split:]
        y_tr, y_te = y.iloc[:split], y.iloc[split:]
        if y_tr.nunique() < 2 or len(X_te) < 10:
            return {"egitildi": False, "neden": "Bölme sonrası sınıf/örnek yetersiz."}

        model = HistGradientBoostingClassifier(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=False,  # iç doğrulama rastgele böler — zaman sızıntısı olur
            random_state=42,
        )
        model.fit(X_tr, y_tr)

        proba = model.predict_proba(X_te)[:, 1]
        baseline = float(y_te.mean())  # filtresiz kazanma oranı

        thresholds = {}
        for th in (0.50, 0.55, 0.60, 0.65, 0.70):
            taken = proba >= th
            n_taken = int(taken.sum())
            thresholds[f"{th:.2f}"] = {
                "alinan_islem": n_taken,
                "kapsam": round(n_taken / len(y_te), 3),
                "kazanma_orani": round(float(y_te[taken].mean()), 3) if n_taken else None,
            }

        try:
            auc = round(float(roc_auc_score(y_te, proba)), 3)
        except ValueError:
            auc = None

        pred = (proba >= DEFAULT_THRESHOLD).astype(int)

        # SAĞLIK DENETİMİ (zehirlenme/çöküş erken uyarısı):
        # Dejenere model hep aynı şeyi söyler → tahmin std'si ~0. Sağlıklı
        # model çeşitli olasılıklar üretir. std çok düşükse model çökmüş demektir.
        proba_std = float(np.std(proba))
        # Tahminlerin ne kadarı 0.45-0.55 "kararsız" bandında sıkışmış (yapı yok işareti)
        kararsiz_oran = float(np.mean((proba > 0.45) & (proba < 0.55)))
        saglikli = bool(proba_std > 0.02 and kararsiz_oran < 0.95)

        report = {
            "egitildi": True,
            "egitim_zamani": datetime.utcnow().isoformat(),
            "n_egitim": len(X_tr),
            "n_test": len(X_te),
            "taban_kazanma_orani": round(baseline, 3),
            "auc": auc,
            "varsayilan_esik": DEFAULT_THRESHOLD,
            "esik_tablosu": thresholds,
            "precision_esikte": round(float(precision_score(y_te, pred, zero_division=0)), 3),
            "kapsam_esikte": round(float(recall_score(y_te, pred, zero_division=0)), 3),
            "ozellik_sayisi": len(FEATURE_COLUMNS),
            # sağlık metrikleri — trainer terfi öncesi kontrol eder
            "saglik": {
                "saglikli": saglikli,
                "tahmin_std": round(proba_std, 4),
                "kararsiz_oran": round(kararsiz_oran, 3),
            },
        }

        # Canlı skorlama için model TÜM veriyle yeniden eğitilir (son veri en
        # değerli). Bu "challenger" — promote=True ise şampiyon olur.
        final_model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=1.0,
            early_stopping=False, random_state=42,
        )
        final_model.fit(X, y)
        report["_challenger_model"] = final_model  # trainer_service kullanır

        if promote:
            self.promote(final_model, report)

        return {k: v for k, v in report.items() if not k.startswith("_")}

    # ------------------------------------------------------------------
    def promote(self, model, report: dict):
        """
        Verilen modeli yeni nesil şampiyon yapar.
        - Mevcut şampiyonu EBEVEYN olarak yedekler (geri-alma güvencesi).
        - Nesil numarasını 1 arttırır (ebeveynin nesli + 1).
        - Nesil geçmişini kaydeder (her terfide AUC).
        """
        import joblib
        clean_report = {k: v for k, v in report.items() if not k.startswith("_")}
        clean_report["terfi_zamani"] = datetime.utcnow().isoformat()

        with self._lock:
            onceki = self._meta or {}
            onceki_nesil = onceki.get("nesil", 0)
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

            # Mevcut şampiyonu EBEVEYN olarak yedekle (varsa)
            if self._model is not None:
                try:
                    joblib.dump(self._model, PARENT_MODEL_PATH)
                    with open(PARENT_META_PATH, "w", encoding="utf-8") as f:
                        json.dump(onceki, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"[meta_model] ebeveyn yedeklenemedi: {e}")

            # Yeni nesil bilgileri
            clean_report["nesil"] = onceki_nesil + 1
            clean_report["ebeveyn_nesil"] = onceki_nesil
            clean_report["ebeveyn_auc"] = onceki.get("auc")
            # Nesil geçmişi (her terfinin özeti — kullanıcı ilerleyişi görsün)
            gecmis = list(onceki.get("nesil_gecmisi", []))
            gecmis.append({
                "nesil": clean_report["nesil"],
                "auc": clean_report.get("auc"),
                "zaman": clean_report["terfi_zamani"],
                "n_egitim": clean_report.get("n_egitim"),
            })
            clean_report["nesil_gecmisi"] = gecmis[-30:]

            joblib.dump(model, MODEL_PATH)
            with open(META_PATH, "w", encoding="utf-8") as f:
                json.dump(clean_report, f, ensure_ascii=False, indent=2)
            self._model = model
            self._meta = clean_report

    def rollback_to_parent(self) -> dict:
        """
        Ebeveyn nesle geri döner — yeni nesil zehirlendiyse/çöktüyse güvence.
        Mevcut (bozuk) nesli atar, ebeveyni şampiyon yapar.
        """
        import joblib
        if not os.path.exists(PARENT_MODEL_PATH):
            return {"basarili": False, "neden": "Ebeveyn nesil yok (henüz terfi olmadı)."}
        with self._lock:
            try:
                parent_model = joblib.load(PARENT_MODEL_PATH)
                with open(PARENT_META_PATH, encoding="utf-8") as f:
                    parent_meta = json.load(f)
                joblib.dump(parent_model, MODEL_PATH)
                with open(META_PATH, "w", encoding="utf-8") as f:
                    json.dump(parent_meta, f, ensure_ascii=False, indent=2)
                self._model = parent_model
                self._meta = parent_meta
                return {"basarili": True, "donulen_nesil": parent_meta.get("nesil", 0)}
            except Exception as e:
                return {"basarili": False, "neden": str(e)}

    # ------------------------------------------------------------------
    def score(self, features: dict) -> dict | None:
        """
        Tek sinyal için kazanma olasılığı + karar. Model yoksa None.
        """
        with self._lock:
            model, meta = self._model, self._meta
        if model is None:
            return None

        row = pd.DataFrame([{c: features.get(c, np.nan) for c in FEATURE_COLUMNS}]).astype(float)
        prob = float(model.predict_proba(row)[0, 1])
        threshold = (meta or {}).get("varsayilan_esik", DEFAULT_THRESHOLD)

        return {
            "olasilik": round(prob, 3),
            "esik": threshold,
            "karar": "ONAYLA" if prob >= threshold else "ATLA",
            "egitim_zamani": (meta or {}).get("egitim_zamani"),
            "test_taban_orani": (meta or {}).get("taban_kazanma_orani"),
            "test_auc": (meta or {}).get("auc"),
            "aciklama": "Meta-model bu sinyalin triple-barrier kazanma olasılığını tahmin eder. "
                        "ATLA = istatistiksel olarak zayıf koşullar, işlemi atlamayı değerlendir.",
        }


# Uygulama genelinde tek örnek
meta_model = MetaModel()
