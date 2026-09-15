"""
Şampiyon–Meydan Okuyan Eğitim Sistemi.
======================================

Kullanıcının "model kendini eğitsin" isteğinin GÜVENLİ versiyonu.

Neden tam-otomatik kendini-eğitme YOK: finansal piyasalar durağan değil
(non-stationary). Kendini körlemesine eğiten model, dünün gürültüsünü kural
sanıp yarın çöker; riskli bir örüntüyü pekiştirip felakete sürükleyebilir.
Bilim bunu açıkça söylüyor (overfitting, dejenere politika, feedback döngüsü).

ÇÖZÜM — gerçek quant fonların yöntemi:
- ŞAMPİYON: şu an canlı kullanılan, güvenilen model. Kararları o verir.
- MEYDAN OKUYAN: arka planda yeni veriyle eğitilen kopya. Canlıda HİÇBİR
  şeye karışmaz; yalnızca walk-forward testte değerlendirilir.
- TERFİ KURALI: Meydan okuyan, şampiyonu KANITLANMIŞ biçimde geçerse
  (AUC + işlem sayısı eşiği) şampiyon olur. Geçemezse atılır.

Böylece "sürekli öğrenme" VAR ama "kör pekiştirme" YOK. Kötü model asla
canlıya geçemez — önce kanıtlaması gerekir.
"""

import json
import os
from datetime import datetime

from services.meta_model import meta_model, MIN_SAMPLES

import config

# Terfi eşikleri — meydan okuyan bunları geçmeden şampiyon olamaz
MIN_AUC_GAIN = config.MIN_AUC_GAIN
MIN_ABS_AUC = config.MIN_ABS_AUC
MIN_NEW_SAMPLES = config.MIN_NEW_SAMPLES
HISTORY_PATH = config.TRAINER_HISTORY_PATH


def _load_history() -> dict:
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"son_egitim": None, "son_veri_sayisi": 0, "terfiler": [], "denemeler": []}


def _save_history(h: dict):
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def run_challenge(store) -> dict:
    """
    Bir meydan-okuma turu: yeni veriyle challenger eğit, şampiyonla karşılaştır,
    SADECE kanıtlanmış biçimde daha iyiyse terfi ettir.

    store: SignalStore (labeled_dataset sağlar).
    Dönüş: tur raporu (terfi etti mi, AUC karşılaştırması, neden).
    """
    h = _load_history()
    X, y = store.labeled_dataset()
    n = len(X)

    if n < MIN_SAMPLES:
        return {"calisti": True, "terfi": False,
                "neden": f"Yetersiz veri ({n}<{MIN_SAMPLES})."}

    # Son turdan beri yeterince YENİ veri biriktiyse dene (boşa eğitim yapma)
    yeni_veri = n - h.get("son_veri_sayisi", 0)
    if h.get("son_egitim") and yeni_veri < MIN_NEW_SAMPLES:
        return {"calisti": True, "terfi": False,
                "neden": f"Yeni veri yetersiz ({yeni_veri}<{MIN_NEW_SAMPLES}) — "
                         f"daha fazla sinyal birikmesini bekliyorum.",
                "toplam_veri": n}

    # --- Meydan okuyanı eğit ve değerlendir (canlıya ALMADAN) ---
    report = meta_model.train(X, y, promote=False)
    if not report.get("egitildi"):
        return {"calisti": True, "terfi": False, "neden": report.get("neden")}

    challenger_auc = report.get("auc")
    champion = meta_model.info() or {}
    champion_auc = champion.get("auc")

    # Şampiyon yoksa (ilk model) → doğrudan terfi
    ilk_model = not meta_model.is_ready or champion_auc is None
    karar = False
    neden = ""

    # SAĞLIK DENETİMİ (zehirlenme/model çöküşü koruması): meydan okuyan
    # dejenere ise (hep aynı şeyi söylüyor) AUC iyi görünse bile terfi YASAK.
    saglik = report.get("saglik", {})
    saglikli = saglik.get("saglikli", True)

    if challenger_auc is None:
        neden = "Meydan okuyan AUC hesaplanamadı (tek sınıf?)."
    elif not saglikli:
        neden = (f"⚠ Meydan okuyan SAĞLIKSIZ (tahmin std {saglik.get('tahmin_std')}, "
                 f"kararsız %{int(saglik.get('kararsiz_oran',0)*100)}) — model çökmüş/"
                 f"zehirlenmiş olabilir. Terfi REDDEDİLDİ, şampiyon korundu.")
    elif challenger_auc < MIN_ABS_AUC:
        neden = f"Meydan okuyan AUC {challenger_auc} < taban {MIN_ABS_AUC} — terfi yok."
    elif ilk_model:
        karar = True
        neden = f"İlk nesil şampiyon kuruldu (AUC {challenger_auc})."
    elif challenger_auc >= champion_auc + MIN_AUC_GAIN:
        karar = True
        neden = (f"Yeni nesil kanıtladı: AUC {challenger_auc} ≥ "
                 f"şampiyon {champion_auc} + {MIN_AUC_GAIN}. Terfi etti.")
    else:
        neden = (f"Meydan okuyan yetersiz: AUC {challenger_auc} < "
                 f"şampiyon {champion_auc} + {MIN_AUC_GAIN}. Şampiyon korundu.")

    # --- Terfi kararı ---
    if karar:
        meta_model.promote(report["_challenger_model"], report)

    # --- Geçmişi güncelle ---
    h["son_egitim"] = datetime.utcnow().isoformat()
    h["son_veri_sayisi"] = n
    kayit = {
        "zaman": datetime.utcnow().isoformat(),
        "veri": n, "challenger_auc": challenger_auc,
        "champion_auc_onceki": champion_auc, "terfi": karar,
    }
    h["denemeler"] = (h.get("denemeler", []) + [kayit])[-50:]
    if karar:
        h["terfiler"] = (h.get("terfiler", []) + [kayit])[-50:]
    _save_history(h)

    return {
        "calisti": True, "terfi": karar, "neden": neden,
        "toplam_veri": n, "yeni_veri": yeni_veri,
        "challenger_auc": challenger_auc, "champion_auc": champion_auc,
        "nesil": (meta_model.info() or {}).get("nesil", 0),
        "saglikli": saglikli,
    }


def trainer_status() -> dict:
    """Eğitim sistemi durumu — frontend kartı için."""
    h = _load_history()
    champion = meta_model.info() or {}
    son_terfi = h.get("terfiler", [])
    return {
        "model_hazir": meta_model.is_ready,
        "nesil": champion.get("nesil", 0),                 # mevcut nesil no
        "ebeveyn_nesil": champion.get("ebeveyn_nesil"),    # bir önceki (yedek)
        "ebeveyn_auc": champion.get("ebeveyn_auc"),
        "nesil_gecmisi": champion.get("nesil_gecmisi", []),  # her terfinin AUC'si
        "sampiyon_auc": champion.get("auc"),
        "saglik": champion.get("saglik"),
        "sampiyon_terfi_zamani": champion.get("terfi_zamani") or champion.get("egitim_zamani"),
        "sampiyon_n_egitim": champion.get("n_egitim"),
        "toplanan_veri": h.get("son_veri_sayisi", 0),
        "son_egitim_denemesi": h.get("son_egitim"),
        "toplam_terfi": len(h.get("terfiler", [])),
        "son_terfi": son_terfi[-1] if son_terfi else None,
        "esikler": {
            "min_auc_kazanc": MIN_AUC_GAIN,
            "min_mutlak_auc": MIN_ABS_AUC,
            "min_yeni_veri": MIN_NEW_SAMPLES,
        },
    }
