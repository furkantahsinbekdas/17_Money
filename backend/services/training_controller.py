"""
Eğitim Denetleyici — kullanıcı kontrollü başlat/durdur.
=======================================================

Kullanıcı arayüzden "EĞİTİME BAŞLA" der → arka planda sürekli şampiyon-meydan
okuyan turları çalışır (model kendini eğitir, kanıtlarsa terfi eder).
"DURDUR" der → döngü durur ve backtest raporu üretilir ("şu kadar hayali
işlem yaptım, geçmiş veriyle şu kadar başarılı oldum").

Tek örnek (singleton) — uygulama genelinde tek eğitim durumu.
Thread güvenli: durum bir kilitle korunur, döngü ayrı thread'de döner.
"""

import threading
import time
from datetime import datetime

from services.signal_store import SignalStore
from services.trainer_service import run_challenge
from services.backtest_service import run_backtest, robust_backtest

import config

# Turlar arası bekleme (sn) config.py'de (TRAINING_CHALLENGE_INTERVAL_SEC)
CHALLENGE_INTERVAL = config.TRAINING_CHALLENGE_INTERVAL_SEC


class TrainingController:

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._store = SignalStore()
        self._state = {
            "calisiyor": False,
            "baslangic": None,
            "tur_sayisi": 0,
            "terfi_sayisi": 0,
            "son_tur": None,
            "son_rapor": None,   # durdurulunca üretilen backtest raporu
        }

    # ------------------------------------------------------------------
    def start(self) -> dict:
        with self._lock:
            if self._running:
                return {"baslatildi": False, "neden": "Eğitim zaten çalışıyor."}
            self._running = True
            self._state.update({
                "calisiyor": True,
                "baslangic": datetime.utcnow().isoformat(),
                "tur_sayisi": 0,
                "terfi_sayisi": 0,
                "son_tur": None,
            })
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return {"baslatildi": True, "aciklama": "Eğitim başladı — model kendini sürekli "
                "sınıyor, kanıtlarsa terfi ediyor. DURDUR'a basınca rapor gelir."}

    def stop(self) -> dict:
        with self._lock:
            if not self._running:
                return {"durduruldu": False, "neden": "Eğitim zaten durmuş."}
            self._running = False
        # Thread'in turu bitirmesini kısa bekle
        if self._thread:
            self._thread.join(timeout=config.TRAINING_STOP_JOIN_TIMEOUT_SEC)
        # Durdurma raporu: SAĞLAM çoklu-pencere + maliyet (güvenilir sonuç).
        # Az veri varsa tek-pencereye düşer.
        rapor = robust_backtest(self._store)
        if not rapor.get("yeterli_veri"):
            rapor = run_backtest(self._store)
        with self._lock:
            self._state["calisiyor"] = False
            self._state["son_rapor"] = rapor
            self._state["bitis"] = datetime.utcnow().isoformat()
        return {"durduruldu": True, "rapor": rapor, "durum": self.status()}

    # ------------------------------------------------------------------
    def _loop(self):
        """Arka plan: sürekli meydan-okuma turları."""
        while True:
            with self._lock:
                if not self._running:
                    break
            try:
                result = run_challenge(self._store)
                with self._lock:
                    self._state["tur_sayisi"] += 1
                    self._state["son_tur"] = {
                        "zaman": datetime.utcnow().isoformat(),
                        "terfi": result.get("terfi"),
                        "neden": result.get("neden"),
                        "challenger_auc": result.get("challenger_auc"),
                        "champion_auc": result.get("champion_auc"),
                    }
                    if result.get("terfi"):
                        self._state["terfi_sayisi"] += 1
            except Exception as e:
                with self._lock:
                    self._state["son_tur"] = {"hata": str(e)[:200]}
            # Beklerken de durdurmaya duyarlı kal
            for _ in range(CHALLENGE_INTERVAL):
                with self._lock:
                    if not self._running:
                        return
                time.sleep(1)

    # ------------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            s = dict(self._state)
        # geçen süre
        if s.get("baslangic"):
            try:
                start = datetime.fromisoformat(s["baslangic"])
                ref = datetime.utcnow() if s["calisiyor"] else \
                    datetime.fromisoformat(s.get("bitis", s["baslangic"]))
                s["sure_saniye"] = int((ref - start).total_seconds())
            except Exception:
                pass
        return s


# Uygulama genelinde tek örnek
training_controller = TrainingController()
