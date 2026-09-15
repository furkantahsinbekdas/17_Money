"""
Piyasa Olayları Katmanı — "neden" hafızası.
============================================

Kullanıcı sordu: model "şu tarihte şu olay oldu, o yüzden düştü/patladı"
biliyor mu? Bu modülden ÖNCE: hayır — model sadece fiyat hareketini görür,
sebebini değil. Bu modül sebep bağlamını ekler.

Bilinen büyük BTC/kripto olayları tarih damgalı listelenir (halving'ler,
çöküşler, ETF onayı, regülasyon şokları). Eğitim sırasında her bar için
"en yakın büyük olaya kaç gün uzaklıktayız ve etkisi neydi" hesaplanır;
bu, meta-modele bir BAĞLAM özelliği olarak girer.

NEDEN tarihsel olayları elle giriyoruz: tarihteki büyük rejim kırıcı
olaylar nadirdir ve sayılıdır; bunları haber API'siyle güvenilir biçimde
geçmişe dönük etiketlemek zordur. Elle küratörlük, az ama YÜKSEK kaliteli
sinyal verir. (Canlı haber akışı ayrı; bu tarihsel "ders kitabı".)

etki: -2 (çok sert düşüş) .. +2 (çok sert yükseliş tetikleyici)
tip: makro | regülasyon | borsa_iflas | protokol | benimseme | halving
"""

from datetime import datetime

# (tarih, etiket, etki, tip) — kronolojik
MARKET_EVENTS = [
    ("2017-12-17", " Bitcoin ATH ~20k, ilk büyük balon zirvesi", -2, "makro"),
    ("2018-01-16", "Büyük ayı başlangıcı, kripto geneli çöküş", -2, "makro"),
    ("2020-03-12", "COVID 'Kara Perşembe' — BTC tek günde ~%50 düştü", -2, "makro"),
    ("2020-05-11", "3. Halving (blok ödülü 12.5→6.25)", 1, "halving"),
    ("2020-10-08", "Square 50M$ BTC aldı — kurumsal benimseme dalgası", 1, "benimseme"),
    ("2021-02-08", "Tesla 1.5 milyar$ BTC aldı", 2, "benimseme"),
    ("2021-04-14", "Coinbase halka arzı, boğa zirvesi yakını", 1, "benimseme"),
    ("2021-05-19", "Çin madencilik yasağı + Tesla geri adımı — sert çöküş", -2, "regülasyon"),
    ("2021-11-10", "Döngü ATH ~69k", -2, "makro"),
    ("2022-05-09", "Terra/LUNA çöküşü — ~40 milyar$ buharlaştı", -2, "protokol"),
    ("2022-06-13", "Celsius dondurma + 3AC iflası", -2, "borsa_iflas"),
    ("2022-11-08", "FTX çöküşü — sektör güven krizi", -2, "borsa_iflas"),
    ("2023-03-10", "SVB/banka krizi — paradoks: BTC yükseldi", 1, "makro"),
    ("2023-06-15", "BlackRock spot ETF başvurusu", 1, "benimseme"),
    ("2024-01-11", "ABD spot BTC ETF onayı — tarihi dönüm", 2, "benimseme"),
    ("2024-04-20", "4. Halving (blok ödülü 6.25→3.125)", 1, "halving"),
    ("2024-03-14", "ETF sonrası yeni ATH ~73k", 1, "makro"),
]

_PARSED = [(datetime.strptime(d, "%Y-%m-%d"), lbl, eff, typ)
           for d, lbl, eff, typ in MARKET_EVENTS]


def nearest_event(ts, window_days: int = 14):
    """
    Verilen zamana en yakın büyük olayı ve uzaklığını döndürür.
    Sadece o tarihten ÖNCEKİ veya window içindeki olayları sayar
    (bakış-ileri yok — gelecekteki olayı bilemezdik).
    """
    if not isinstance(ts, datetime):
        try:
            ts = ts.to_pydatetime()
        except AttributeError:
            ts = datetime.fromisoformat(str(ts))

    best = None
    for ev_t, lbl, eff, typ in _PARSED:
        gun = (ts - ev_t).days  # pozitif = olay geçmişte
        # Olay yakın geçmişte (0..window) ya da çok yakın gelecekte değil
        if -1 <= gun <= window_days:
            if best is None or abs(gun) < abs(best["gun"]):
                best = {"etiket": lbl.strip(), "gun_once": gun,
                        "etki": eff, "tip": typ}
    return best


def event_feature(ts, window_days: int = 14) -> dict:
    """
    Meta-model için sayısal olay özelliği:
      olay_yakin: 1/0 (window içinde büyük olay var mı)
      olay_etki: -2..+2 (yoksa 0)
      olay_gun: olaydan kaç gün sonra (yoksa -1)
    """
    ev = nearest_event(ts, window_days)
    if not ev:
        return {"olay_yakin": 0.0, "olay_etki": 0.0, "olay_gun": -1.0}
    return {
        "olay_yakin": 1.0,
        "olay_etki": float(ev["etki"]),
        "olay_gun": float(ev["gun_once"]),
    }


def events_in_range(start, end) -> list:
    """Bir tarih aralığındaki tüm olayları döndürür (panel/açıklama için)."""
    out = []
    for ev_t, lbl, eff, typ in _PARSED:
        if start <= ev_t <= end:
            out.append({"tarih": ev_t.strftime("%Y-%m-%d"), "etiket": lbl.strip(),
                        "etki": eff, "tip": typ})
    return out
