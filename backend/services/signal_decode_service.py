"""
Sinyal Çözme Motoru — piyasanın "şifresini kırma" katmanı.
============================================================

Kullanıcının "kod kırıcılık / şifre çözme" sezgisinin BİLİMSEL karşılığı.

NET AYRIM: Kriptografik şifre kırma (AES/RSA) ile piyasa tahmini arasında
hiçbir bağ YOKTUR — o imkânsız ve alakasızdır. Ama piyasanın gürültüsünün
ALTINDAKİ gizli yapıyı "deşifre etmek" gerçek bir bilim dalıdır: SİNYAL
İŞLEME + BİLGİ TEORİSİ. Bu modül onu yapar.

"Şifre çözme" burada şu demektir: fiyat serisi rastgele görünür, ama
içinde saklı periyotlar, tekrarlar ve öngörülebilir yapı olabilir. Bunları
matematikle açığa çıkarırız — tıpkı bir şifreyi çözer gibi.

YÖNTEMLER ve KAYNAKLARI:
1. Fourier dönüşümü (FFT) — Joseph Fourier (1822):
   Herhangi bir sinyal, farklı frekanslardaki dalgaların toplamıdır.
   FFT fiyat serisindeki "baskın periyotları" (örn. 24-saatlik döngü)
   açığa çıkarır. → dominant_cycles()

2. Otokorelasyon — Yule (1927):
   Seri kendisinin gecikmeli haliyle ne kadar benziyor? Yüksek
   otokorelasyon = saklı tekrar = öngörülebilirlik. → autocorrelation_signal()

3. Shannon entropisi — Claude Shannon (1948), "bilgi teorisi":
   Bir sinyalin ne kadar "rastgele/öngörülemez" olduğunun ÖLÇÜSÜ. Bu,
   şifre kırmanın matematiksel temelidir: düşük entropi = yapı var =
   kırılabilir/tahmin edilebilir; yüksek entropi = saf gürültü.
   → permutation_entropy()

4. Sinyal-Gürültü Oranı (SNR):
   Baskın döngünün gücü / toplam gürültü. Yüksek SNR = net sinyal var.
   → dominant_cycles() içinde.

Hiçbir ağır bağımlılık yok — yalnızca numpy. Python 3.14 uyumlu.

REFERANSLAR:
  [F] Fourier, J. (1822). Théorie analytique de la chaleur.
  [Y] Yule, G.U. (1927). Periodicities in disturbed series.
  [S] Shannon, C.E. (1948). A Mathematical Theory of Communication.
  [B] Bandt & Pompe (2002). Permutation entropy: a natural complexity measure.
"""

import math

import numpy as np
import pandas as pd

_EPS = 1e-12


def _log_returns(close: pd.Series) -> np.ndarray:
    p = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    p = p[np.isfinite(p) & (p > 0)]
    if p.size < 2:
        return np.array([])
    return np.diff(np.log(p))


# ======================================================================
# 1. Baskın döngüler — FFT [F]
# ======================================================================

def dominant_cycles(close: pd.Series, top_n: int = 3, min_period: int = 3) -> dict:
    """
    Fourier dönüşümü [F] ile fiyat serisindeki baskın periyotları bulur.

    Fiyat serisi = farklı frekanslı dalgaların toplamı. FFT bu dalgaları
    ayrıştırır; en güçlü olanlar piyasadaki gizli döngülerdir (örn. "her
    ~24 barda bir tekrar eden hareket"). Bu döngüler tahmine yardımcı olur:
    döngünün neresindeyiz → bir sonraki adım yukarı mı aşağı mı eğilimli.

    Sinyal-Gürültü Oranı (SNR): en güçlü döngünün gücü ortalamaya kıyasla
    ne kadar baskın. Yüksek SNR = net döngü; düşük = gürültüde kaybolmuş.
    """
    r = _log_returns(close)
    if r.size < min_period * 4:
        return {"yeterli_veri": False}

    # Trendi çıkar (detrend) — FFT durağan sinyalde anlamlı
    r = r - np.mean(r)
    n = r.size
    # Pencereleme (spektral sızıntıyı azalt — Hann penceresi)
    window = np.hanning(n)
    spectrum = np.abs(np.fft.rfft(r * window)) ** 2  # güç spektrumu
    freqs = np.fft.rfftfreq(n, d=1.0)

    # DC bileşeni (freq=0) ve çok kısa periyotları at
    valid = freqs > _EPS
    periods = np.zeros_like(freqs)
    periods[valid] = 1.0 / freqs[valid]
    mask = valid & (periods >= min_period) & (periods <= n / 2)
    if mask.sum() < 1:
        return {"yeterli_veri": False}

    p_spec = spectrum[mask]
    p_per = periods[mask]
    order = np.argsort(p_spec)[::-1][:top_n]

    mean_power = float(np.mean(spectrum[mask])) + _EPS
    cycles = []
    for i in order:
        snr = float(p_spec[i] / mean_power)
        cycles.append({
            "periyot_bar": round(float(p_per[i]), 1),
            "guc": round(float(p_spec[i]), 4),
            "snr": round(snr, 2),  # >3 anlamlı sayılır
        })

    en_guclu = cycles[0] if cycles else None
    net_dongu = bool(en_guclu and en_guclu["snr"] >= 3.0)
    return {
        "yeterli_veri": True,
        "baskin_donguler": cycles,
        "net_dongu_var": net_dongu,
        "yorum": (f"Baskın {en_guclu['periyot_bar']:.0f}-barlık döngü tespit edildi "
                  f"(SNR {en_guclu['snr']:.1f}) — periyodik yapı var, döngü konumu "
                  f"tahmine katkı verir." if net_dongu else
                  "Belirgin periyodik döngü yok — hareket büyük ölçüde gürültü."),
    }


# ======================================================================
# 2. Otokorelasyon — saklı tekrarlar [Y]
# ======================================================================

def autocorrelation_signal(close: pd.Series, max_lag: int = 30) -> dict:
    """
    Otokorelasyon [Y]: getiri serisi kendisinin gecikmeli haliyle ne kadar
    benziyor? Anlamlı otokorelasyon = saklı tekrar = kısa-vade öngörülebilirlik.

      lag-1 pozitif → momentum (yön devam etme eğilimi)
      lag-1 negatif → ortalamaya dönüş (yön ters dönme eğilimi)

    %95 güven bandı (±1.96/√N) dışındaki gecikmeler istatistiksel anlamlı.
    """
    r = _log_returns(close)
    n = r.size
    if n < max_lag * 2:
        return {"yeterli_veri": False}

    r = r - np.mean(r)
    var = np.dot(r, r)
    if var < _EPS:
        return {"yeterli_veri": False}

    conf = 1.96 / math.sqrt(n)  # %95 anlamlılık bandı
    acf = []
    anlamli = []
    for lag in range(1, max_lag + 1):
        c = np.dot(r[:-lag], r[lag:]) / var
        acf.append(round(float(c), 4))
        if abs(c) > conf:
            anlamli.append({"gecikme": lag, "deger": round(float(c), 3)})

    lag1 = acf[0]
    if abs(lag1) <= conf:
        yon = "yok"
        yorum = "Lag-1 otokorelasyon zayıf — kısa vadede yön hafızası yok (random-walk'a yakın)."
    elif lag1 > 0:
        yon = "momentum"
        yorum = f"Pozitif lag-1 ({lag1:.3f}) — momentum: yön devam etme eğiliminde."
    else:
        yon = "ortalama_donus"
        yorum = f"Negatif lag-1 ({lag1:.3f}) — ortalamaya dönüş: yön ters dönme eğiliminde."

    return {
        "yeterli_veri": True,
        "lag1": lag1,
        "yon_hafizasi": yon,
        "anlamli_gecikmeler": anlamli[:8],
        "guven_bandi": round(conf, 4),
        "yorum": yorum,
    }


# ======================================================================
# 3. Permütasyon entropisi — öngörülebilirlik (şifre kırma çekirdeği) [S][B]
# ======================================================================

def permutation_entropy(close: pd.Series, order: int = 3, delay: int = 1) -> dict:
    """
    Permütasyon entropisi [S][B] — Shannon bilgi teorisinin [S] zaman
    serisine uygulanmış hali. Serinin ne kadar ÖNGÖRÜLEBİLİR olduğunu
    0-1 arası tek sayıyla ölçer. "Şifre kırma" sezgisinin tam karşılığı:

      ~0.0  → tamamen düzenli/öngörülebilir (yapı var, "şifre kırık")
      ~1.0  → tamamen rastgele/öngörülemez (saf gürültü, "şifre kırılamaz")

    Yöntem (Bandt-Pompe): ardışık `order` değerin sıralama desenlerini
    (permütasyonlar) sayar, bu desenlerin dağılımının Shannon entropisini
    hesaplar. Yapısı olan seride bazı desenler baskın olur → düşük entropi.
    """
    r = _log_returns(close)
    n = r.size
    need = order * delay + 1
    if n < need + 20:
        return {"yeterli_veri": False}

    # Her pencere için sıralama deseni (hangi sıra büyük→küçük)
    patterns = {}
    count = 0
    for i in range(n - (order - 1) * delay):
        window = r[i: i + order * delay: delay]
        if window.size < order:
            continue
        # argsort ile sıralama deseni (permütasyon kimliği)
        pat = tuple(np.argsort(window))
        patterns[pat] = patterns.get(pat, 0) + 1
        count += 1

    if count < 1:
        return {"yeterli_veri": False}

    probs = np.array(list(patterns.values()), dtype=float) / count
    # Shannon entropisi, mümkün max permütasyon sayısına normalize (order!)
    shannon = -np.sum(probs * np.log(probs + _EPS))
    max_ent = math.log(math.factorial(order))
    pe = float(shannon / max_ent) if max_ent > 0 else 1.0
    pe = max(0.0, min(1.0, pe))

    if pe < 0.85:
        seviye = "yapısal"
        yorum = (f"Düşük entropi ({pe:.2f}) — seride istatistiksel yapı var, "
                 f"kısmen öngörülebilir. Tahmine güven artabilir.")
    elif pe < 0.95:
        seviye = "karışık"
        yorum = f"Orta entropi ({pe:.2f}) — kısmi yapı, kısmi gürültü."
    else:
        seviye = "gürültü"
        yorum = (f"Yüksek entropi ({pe:.2f}) — neredeyse saf gürültü, "
                 f"öngörülebilirlik düşük. Tahmine GÜVENME, güveni kır.")

    return {
        "yeterli_veri": True,
        "entropi": round(pe, 3),
        "ongorulebilirlik": round(1.0 - pe, 3),  # 1 = çok öngörülebilir
        "seviye": seviye,
        "yorum": yorum,
    }


# ======================================================================
# Birleşik özet
# ======================================================================

def full_decode(close: pd.Series) -> dict:
    """Üç çözme yöntemini tek çağrıda çalıştırır."""
    return {
        "baskin_donguler": dominant_cycles(close),       # [F]
        "otokorelasyon": autocorrelation_signal(close),  # [Y]
        "ongorulebilirlik": permutation_entropy(close),  # [S][B]
        "_referanslar": "Fourier[F] Yule-otokorelasyon[Y] Shannon-entropi[S] Bandt-Pompe[B]",
    }


def compact_for_signal(decode: dict) -> dict:
    """Sinyal prompt'una sığacak kısa özet."""
    cyc = decode.get("baskin_donguler", {})
    acf = decode.get("otokorelasyon", {})
    pe = decode.get("ongorulebilirlik", {})
    en_guclu = (cyc.get("baskin_donguler") or [{}])[0] if cyc.get("yeterli_veri") else {}
    return {
        "ongorulebilirlik": {
            "skor": pe.get("ongorulebilirlik"),
            "seviye": pe.get("seviye"),
            "not": pe.get("yorum"),
        },
        "yon_hafizasi": {
            "tip": acf.get("yon_hafizasi"),
            "lag1": acf.get("lag1"),
            "not": acf.get("yorum"),
        },
        "baskin_dongu": {
            "periyot_bar": en_guclu.get("periyot_bar"),
            "snr": en_guclu.get("snr"),
            "net": cyc.get("net_dongu_var"),
            "not": cyc.get("yorum"),
        },
    }
