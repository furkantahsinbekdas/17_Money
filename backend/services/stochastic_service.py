"""
Stokastik Matematik Motoru — 17Money'in bilimsel çekirdeği.
=============================================================

Bu modül, fiyat hareketinin "rastgeleliğin matematiği" literatürüne dayanan
ölçülerini hesaplar. Teknik analiz (EMA/RSI/SMC) "ne yönde" sorusuna bakar;
bu motor "hareket ne kadar rastgele, ne kadar oynak, hangi rejimdeyiz, ve
fiyat random-walk'tan ne kadar sapıyor" sorularına bakar.

Hiçbir harici ağır bağımlılık yok (arch/numba/hmmlearn YOK) — yalnızca
numpy + scipy. Python 3.14 uyumlu. Her formül kaynağıyla birlikte yorumlandı.

TEORİ ZİNCİRİ ve KOD KARŞILIĞI
------------------------------------------------------------------
1. Bachelier (1900), "Théorie de la spéculation":
   Fiyat = aritmetik Brown hareketi; getiriler bağımsız, ortalaması ~0.
   → hurst_exponent(): hareket gerçekten random-walk mı (H≈0.5),
     yoksa trendli (H>0.5) / ortalamaya dönen (H<0.5) mi? Random-walk
     hipotezini SAYIYLA test eder — sistemin "tahmin edilebilirlik" ölçüsü.

2. Einstein (1905) + Brown hareketi + Merkezi Limit Teoremi:
   Difüzyon ∝ √zaman. Çok sayıda bağımsız küçük etkinin toplamı normal
   dağılıma yakınsar — AMA finansal getiriler "kalın kuyrukludur".
   → return_distribution(): basıklık (kurtosis) ve çarpıklık (skew) ile
     normallikten sapmayı ölçer. Kalın kuyruk = aşırı hareket riski.
   → diffusion_projection(): σ·√t difüzyon ölçeklemesiyle beklenen aralık.

3. Itô (1944) + Geometrik Brown Hareketi (GBM):
   dS = μ·S·dt + σ·S·dW. Fiyatın kendisi değil, LOG-getirisi modellenir
   (fiyat negatif olamaz). Black-Scholes'un da temeli.
   → log_return_stats(): tüm motor log-getiri üzerinden çalışır (GBM'in
     doğru ölçeği). gbm_drift_diffusion(): μ (sürüklenme) ve σ (difüzyon).

4. Black-Scholes-Merton (1973) — dynamic hedging ruhu:
   Asıl ders: riski yok etmek değil, sürekli ÖLÇÜP yönetmek. Opsiyon
   fiyatlamıyoruz (perpetual futures), ama volatilite tahminini risk
   boyutlandırmaya besliyoruz.
   → forecast_volatility() çıktısı → (ilerideki) risk motoru.

5. GARCH(1,1) — Engle (1982, ARCH) & Bollerslev (1986):
   "Volatilite kümelenir": σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}.
   Yarının oynaklığını dünün şokundan ve dünün oynaklığından tahmin eder.
   scipy MLE ile tahmin (arch kütüphanesi gerekmez).
   → garch11_fit() + garch11_forecast().

6. Range-based realized volatility — Yang-Zhang (2000):
   OHLC'nin tamamını kullanan, açılış sıçramalarına dayanıklı, klasik
   kapanış-kapanış tahmininden ~5-14x daha verimli volatilite ölçüsü.
   → yang_zhang_volatility().

7. Hidden Markov rejim (Hamilton 1989 ruhu, hafif uygulama):
   Piyasanın gözlemlenemeyen rejimleri (düşük/orta/yüksek oynaklık).
   Tam Baum-Welch yerine, Gaussian karışım + olasılıksal atama ile
   numba'sız, hafif bir rejim olasılığı üretir.
   → volatility_regime().

REFERANSLAR (kod yorumlarında [n] olarak anılır):
  [1] Bachelier, L. (1900). Théorie de la spéculation. Ann. Sci. ENS.
  [2] Einstein, A. (1905). Brown hareketi üzerine. Ann. der Physik.
  [3] Itô, K. (1944). Stochastic Integral. Proc. Imp. Acad. Tokyo.
  [4] Black, F. & Scholes, M. (1973). J. Political Economy.
  [5] Bollerslev, T. (1986). Generalized ARCH. J. Econometrics.
  [6] Yang, D. & Zhang, Q. (2000). Drift-independent volatility. J. Business.
  [7] Hurst, H.E. (1951). Long-term storage capacity of reservoirs.
  [8] Hamilton, J.D. (1989). Regime-switching. Econometrica.
"""

import math

import config

import numpy as np
import pandas as pd
from scipy import optimize, stats

# Yıllıklaştırma: kripto 7/24 işlem görür → 365 gün
ANNUALIZE_DAILY = math.sqrt(config.STOCHASTIC_DAYS_PER_YEAR)
_EPS = 1e-12


# ======================================================================
# Yardımcılar — log-getiri (Itô/GBM'in doğru ölçeği) [3]
# ======================================================================

def log_returns(close: pd.Series) -> np.ndarray:
    """
    Log-getiri: r_t = ln(P_t / P_{t-1}).
    GBM [3] fiyatın kendisini değil log-fiyatı Brown hareketi sayar;
    bu yüzden tüm stokastik hesaplar log-getiri üzerinden yapılır
    (toplanabilir, ölçek-bağımsız, fiyatı negatife düşürmez).
    """
    p = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    p = p[np.isfinite(p) & (p > 0)]
    if p.size < 2:
        return np.array([])
    return np.diff(np.log(p))


# ======================================================================
# 1. Random-walk testi — Hurst üssü [1][7]
# ======================================================================

def hurst_exponent(close: pd.Series, max_lag: int = 40) -> dict:
    """
    Hurst üssü (H) — Bachelier'in random-walk hipotezini [1] SAYIYLA test eder.

    Yöntem: farklı gecikmelerde log-getirilerin standart sapmasının
    gecikmeyle nasıl ölçeklendiğine bakar (Brown hareketinde σ ∝ √lag → H=0.5).

      H ≈ 0.5  → saf random-walk: yön tahmin edilemez (Bachelier haklı)
      H > 0.5  → kalıcılık/trend: hareketler birbirini izler (trend takip edilebilir)
      H < 0.5  → ortalamaya dönüş: hareketler ters döner (mean-reversion)

    Bu, sistemin "şu an tahmin edilebilir bir rejimde miyiz?" pusulasıdır.
    """
    r = log_returns(close)
    if r.size < max_lag * 2:
        return {"hurst": None, "yorum": "yetersiz veri", "rejim": "bilinmiyor"}

    # Kümülatif log-fiyat serisi üzerinde rescaled-range tarzı ölçekleme:
    # farklı gecikmelerde, log-getirilerin `lag` adımlık TOPLAMININ std'si.
    # Brown hareketinde bu toplam std'si ∝ lag^H olur (H=0.5 random-walk).
    series = np.cumsum(r)
    lags = np.arange(2, max_lag)
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]   # lag-adımlık değişim
        sd = np.std(diff, ddof=1) if diff.size > 1 else _EPS
        tau.append(max(sd, _EPS))
    tau = np.array(tau)

    # log(std) = H · log(lag) + sabit  →  eğim = H doğrudan
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    h = float(poly[0])
    h = max(0.0, min(1.0, h))

    if h > 0.55:
        rejim, yorum = "trend", "Kalıcılık var — trend takibi anlamlı (H>0.5)"
    elif h < 0.45:
        rejim, yorum = "ortalama_donus", "Ortalamaya dönüş — kontra-trend anlamlı (H<0.5)"
    else:
        rejim, yorum = "random_walk", "Saf rastgele yürüyüş — yön tahmini zayıf (H≈0.5)"

    return {"hurst": round(h, 3), "rejim": rejim, "yorum": yorum}


# ======================================================================
# 2. Getiri dağılımı — normallik & kalın kuyruk [2]
# ======================================================================

def return_distribution(close: pd.Series) -> dict:
    """
    Getiri dağılımının normallikten sapmasını ölçer [2].

    Merkezi Limit Teoremi getirileri normale yakınsatmalı; AMA finansal
    getiriler "kalın kuyrukludur" (leptokurtic): aşırı hareketler normal
    dağılımın öngördüğünden çok daha sık. Bunu görmezden gelmek, riskleri
    sistematik olarak HAFİFE almak demektir (Black-Scholes'un gizli hatası).

      basıklık (excess kurtosis) > 0  → kalın kuyruk: kara kuğu riski yüksek
      çarpıklık (skew) < 0            → sol kuyruk uzun: ani çöküş eğilimi
    """
    r = log_returns(close)
    if r.size < 30:
        return {"yeterli_veri": False}

    excess_kurt = float(stats.kurtosis(r, fisher=True, bias=False))
    skew = float(stats.skew(r, bias=False))
    # Jarque-Bera: H0 = veri normal dağılımlı
    try:
        jb_stat, jb_p = stats.jarque_bera(r)
        normal_mi = bool(jb_p > 0.05)
    except Exception:
        jb_p, normal_mi = None, None

    if excess_kurt > 3:
        kuyruk = "çok_kalın"
    elif excess_kurt > 1:
        kuyruk = "kalın"
    else:
        kuyruk = "normale_yakın"

    return {
        "yeterli_veri": True,
        "basiklik_fazlasi": round(excess_kurt, 2),
        "carpiklik": round(skew, 3),
        "kuyruk": kuyruk,
        "normal_dagilim_mi": normal_mi,
        "jarque_bera_p": round(float(jb_p), 4) if jb_p is not None else None,
        "yorum": ("Kalın kuyruk: aşırı hareketler normalden sık — risk hesabında "
                  "normal dağılıma güvenme, stop'ları geniş tut."
                  if excess_kurt > 1 else
                  "Dağılım normale yakın — standart volatilite ölçüleri güvenilir."),
    }


# ======================================================================
# 3. GBM sürüklenme & difüzyon [3] + difüzyon projeksiyonu [2]
# ======================================================================

def gbm_drift_diffusion(close: pd.Series, bars_per_day: float = 1.0) -> dict:
    """
    GBM [3] parametreleri: μ (sürüklenme/drift) ve σ (difüzyon/volatilite).
    dS = μ·S·dt + σ·S·dW — log-getirinin ortalaması μ, std'si σ.

    Değerler BAR bazında ölçülür, sonra bars_per_day ile güne, oradan yıla
    çevrilir. Brown hareketi [2]: volatilite √zaman ile ölçeklenir, sürüklenme
    doğrusal. bars_per_day: 1h verisi için 24, 4h için 6, 1d için 1.
    """
    r = log_returns(close)
    if r.size < 2:
        return {"yeterli_veri": False}
    mu_bar = float(np.mean(r))
    sigma_bar = float(np.std(r, ddof=1))
    bpd = max(bars_per_day, _EPS)
    # bar → gün: drift doğrusal (×bpd), difüzyon karekök (×√bpd)
    mu_day = mu_bar * bpd
    sigma_day = sigma_bar * math.sqrt(bpd)
    return {
        "yeterli_veri": True,
        "bar_difuzyon": round(sigma_bar, 6),       # ham bar-bazlı σ
        "gunluk_suruklenme": round(mu_day, 6),
        "gunluk_difuzyon": round(sigma_day, 6),
        "yillik_suruklenme_yuzde": round(mu_day * 365 * 100, 2),
        "yillik_volatilite_yuzde": round(sigma_day * ANNUALIZE_DAILY * 100, 2),
    }


def diffusion_projection(price: float, daily_sigma: float, horizon_bars: int,
                         bars_per_day: float = 1.0, drift: float = 0.0) -> dict:
    """
    Brown hareketi difüzyonu [2]: belirsizlik √zaman ile büyür.
    horizon ufkunda ±1σ ve ±2σ beklenen fiyat bandı.

      σ_ufuk = σ_bar · √(bar_sayısı)
      bant   = P · exp(drift·t ± z·σ_ufuk)   (log-normal, GBM tutarlı)
    """
    if not price or daily_sigma is None or daily_sigma <= 0:
        return {"yeterli_veri": False}
    sigma_bar = daily_sigma / math.sqrt(max(bars_per_day, _EPS))
    sigma_h = sigma_bar * math.sqrt(max(horizon_bars, 0))
    drift_h = drift * horizon_bars

    def band(z):
        return {
            "alt": round(price * math.exp(drift_h - z * sigma_h), 1),
            "ust": round(price * math.exp(drift_h + z * sigma_h), 1),
        }

    return {
        "yeterli_veri": True,
        "ufuk_bar": horizon_bars,
        "sigma_ufuk_yuzde": round(sigma_h * 100, 3),
        "bant_1sigma": band(1.0),   # ~%68 olasılık
        "bant_2sigma": band(2.0),   # ~%95 olasılık
        "yorum": "±1σ ≈ %68, ±2σ ≈ %95 olasılıkla fiyatın kalacağı aralık (difüzyon).",
    }


# ======================================================================
# 4. Yang-Zhang range-based volatilite [6]
# ======================================================================

def yang_zhang_volatility(df: pd.DataFrame, window: int = 30) -> dict:
    """
    Yang-Zhang (2000) [6] volatilite tahmincisi — OHLC'nin tamamını kullanır,
    açılış sıçramalarına dayanıklı, kapanış-kapanış tahmininden çok daha verimli.

    σ²_YZ = σ²_overnight + k·σ²_open-close + (1-k)·σ²_RogersSatchell
    k = 0.34 / (1.34 + (n+1)/(n-1))
    """
    need = {"open", "high", "low", "close"}
    if not need.issubset(df.columns) or len(df) < window + 1:
        return {"yeterli_veri": False}

    o = df["open"].to_numpy(float)[-window-1:]
    h = df["high"].to_numpy(float)[-window-1:]
    l = df["low"].to_numpy(float)[-window-1:]
    c = df["close"].to_numpy(float)[-window-1:]
    if np.any(~np.isfinite([o, h, l, c])) or np.any(o <= 0):
        # geçersiz barları at
        mask = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (o > 0)
        o, h, l, c = o[mask], h[mask], l[mask], c[mask]
        if c.size < window:
            return {"yeterli_veri": False}

    # overnight: ln(O_t / C_{t-1})
    on = np.log(o[1:] / c[:-1])
    # open-to-close: ln(C_t / O_t)
    oc = np.log(c[1:] / o[1:])
    # Rogers-Satchell günlük varyans bileşeni (drift-bağımsız)
    ho = np.log(h[1:] / o[1:])
    lo = np.log(l[1:] / o[1:])
    co = np.log(c[1:] / o[1:])
    rs = ho * (ho - co) + lo * (lo - co)

    n = on.size
    if n < 2:
        return {"yeterli_veri": False}
    var_on = np.var(on, ddof=1)
    var_oc = np.var(oc, ddof=1)
    var_rs = np.mean(rs)
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var_yz = var_on + k * var_oc + (1 - k) * var_rs
    sigma_yz = math.sqrt(max(var_yz, 0.0))

    return {
        "yeterli_veri": True,
        "pencere": int(n),
        "gunluk_volatilite_yuzde": round(sigma_yz * 100, 3),
        "yillik_volatilite_yuzde": round(sigma_yz * ANNUALIZE_DAILY * 100, 2),
        "yontem": "Yang-Zhang (range-based, açılış-sıçramasına dayanıklı)",
    }


# ======================================================================
# 5. GARCH(1,1) — scipy MLE [5] (arch kütüphanesi gerekmez)
# ======================================================================

def garch11_fit(close: pd.Series, max_obs: int = 1000) -> dict:
    """
    GARCH(1,1) [5]: σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}.

    "Volatilite kümelenir" — büyük şoku büyük şok, sakini sakin izler.
    Parametreler scipy ile maksimum olabilirlik (MLE) tahmini; ağır
    bağımlılık (arch/numba) yok. Getiriler %100 ölçeğinde işlenir
    (sayısal kararlılık), sonra geri ölçeklenir.

    α+β → kalıcılık (persistence); 1'e ne kadar yakınsa şoklar o kadar
    uzun yaşar. α+β ≥ 1 ise süreç durağan değil (uyarı verilir).
    """
    r = log_returns(close)
    if r.size < 100:
        return {"basarili": False, "neden": "GARCH için en az 100 bar gerekir."}
    r = r[-max_obs:] * 100.0  # yüzde ölçeği — optimizer sayısal kararlılığı
    var0 = np.var(r, ddof=1)
    if var0 <= _EPS:
        return {"basarili": False, "neden": "Volatilite sıfır — sabit fiyat."}

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1.0:
            return 1e10
        sigma2 = np.empty(r.size)
        sigma2[0] = var0
        for t in range(1, r.size):
            sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        sigma2 = np.maximum(sigma2, _EPS)
        # Gaussian negatif log-olabilirlik
        ll = 0.5 * np.sum(np.log(2*np.pi*sigma2) + r**2 / sigma2)
        return ll if np.isfinite(ll) else 1e10

    # Başlangıç: tipik finansal GARCH değerleri (α≈0.1, β≈0.85)
    x0 = [var0 * 0.05, 0.10, 0.85]
    bounds = [(_EPS, var0 * 5), (0.0, 0.999), (0.0, 0.999)]
    try:
        res = optimize.minimize(neg_loglik, x0, method="L-BFGS-B", bounds=bounds)
    except Exception as e:
        return {"basarili": False, "neden": f"Optimizasyon hatası: {e}"}
    if not res.success and res.fun >= 1e9:
        return {"basarili": False, "neden": "GARCH yakınsamadı."}

    omega, alpha, beta = res.x
    persistence = alpha + beta
    # Uzun-vade (koşulsuz) BAR volatilitesi — %ölçekten orana geri çevir.
    # NOT: yıllıklaştırmıyoruz çünkü bars_per_day bu fonksiyona gelmiyor;
    # tutarlı yıllık kıyas full_analysis'teki GBM/Yang-Zhang'da yapılır.
    uncond_var = omega / max(1 - persistence, _EPS)
    uncond_sigma_bar = math.sqrt(uncond_var) / 100.0

    return {
        "basarili": True,
        "omega": round(float(omega), 6),
        "alpha": round(float(alpha), 4),
        "beta": round(float(beta), 4),
        "kalicilik": round(float(persistence), 4),
        "kosulsuz_bar_vol_yuzde": round(uncond_sigma_bar * 100, 4),
        "durağan_mi": bool(persistence < 1.0),
        "_son_sigma2": float(omega + alpha*r[-1]**2 + beta*var0),  # forecast için
        "_son_getiri2": float(r[-1]**2),
        "yorum": (f"Kalıcılık {persistence:.2f}: "
                  + ("şoklar uzun yaşıyor, volatilite inatçı." if persistence > 0.9
                     else "şoklar çabuk sönüyor, volatilite esnek.")),
    }


def garch11_forecast(fit: dict, horizon: int = 24) -> dict:
    """
    Eğitilmiş GARCH(1,1)'den [5] ileriye dönük volatilite tahmini.
    h-adım ileri varyans uzun-vade varyansa doğru yakınsar:
      σ²_{t+h} = σ²_LR + (α+β)^(h-1) · (σ²_{t+1} - σ²_LR)
    """
    if not fit.get("basarili"):
        return {"yeterli_veri": False}
    omega, alpha, beta = fit["omega"], fit["alpha"], fit["beta"]
    p = alpha + beta
    var_lr = omega / max(1 - p, _EPS)
    sigma2_next = omega + alpha * fit["_son_getiri2"] + beta * fit["_son_sigma2"]

    path = []
    s2 = sigma2_next
    for _ in range(horizon):
        path.append(s2)
        s2 = var_lr + p * (s2 - var_lr)
    # ufuk toplam volatilitesi (bağımsız artışların karekök toplamı), %→oran
    cum_sigma = math.sqrt(sum(path)) / 100.0
    next_daily = math.sqrt(max(sigma2_next, 0.0)) / 100.0

    return {
        "yeterli_veri": True,
        "sonraki_bar_vol_yuzde": round(next_daily * 100, 3),
        "ufuk_bar": horizon,
        "ufuk_toplam_vol_yuzde": round(cum_sigma * 100, 2),
        "yon": ("yükseliyor" if sigma2_next > fit["_son_sigma2"] else "düşüyor"),
        "yorum": ("Volatilite artıyor — pozisyon boyutunu küçült, stop'u genişlet."
                  if sigma2_next > fit["_son_sigma2"] else
                  "Volatilite sönüyor — sakin piyasa, normal boyutlandırma."),
    }


# ======================================================================
# 6. Volatilite rejimi — hafif Gaussian rejim atama [8]
# ======================================================================

def volatility_regime(close: pd.Series, window: int = 20, n_regimes: int = 3) -> dict:
    """
    Volatilite rejim tespiti — Hamilton (1989) [8] rejim-değişim fikrinin
    hafif uygulaması. Tam HMM (Baum-Welch) yerine: yuvarlanan volatiliteyi
    olasılıksal olarak düşük/orta/yüksek rejimlere ayırır.

    Çıktı: mevcut rejim + her rejimin olasılığı + geçiş eğilimi.
    Bu, "şu an hangi piyasa dünyasındayız" pusulasıdır; risk motoru ve
    meta-model için güçlü bir bağlam değişkenidir.
    """
    r = log_returns(close)
    if r.size < window * 3:
        return {"yeterli_veri": False}

    # yuvarlanan volatilite serisi (rejim göstergesi)
    s = pd.Series(r)
    roll_vol = s.rolling(window).std(ddof=1).dropna().to_numpy()
    if roll_vol.size < n_regimes * 4:
        return {"yeterli_veri": False}

    # Rejim eşikleri: volatilite dağılımının kantilleri (düşük/orta/yüksek)
    q = np.quantile(roll_vol, [1/3, 2/3])
    cur = roll_vol[-1]
    if cur <= q[0]:
        rejim, idx = "düşük_volatilite", 0
    elif cur <= q[1]:
        rejim, idx = "orta_volatilite", 1
    else:
        rejim, idx = "yüksek_volatilite", 2

    # Olasılıksal yumuşatma: son `window` gözlemin rejim dağılımı
    recent = roll_vol[-window:]
    labels = np.where(recent <= q[0], 0, np.where(recent <= q[1], 1, 2))
    probs = [round(float(np.mean(labels == k)), 3) for k in range(n_regimes)]

    # Basit geçiş eğilimi: volatilite yön türevi
    egim = float(np.polyfit(range(len(recent)), recent, 1)[0])

    return {
        "yeterli_veri": True,
        "mevcut_rejim": rejim,
        "rejim_indeksi": idx,
        "olasiliklar": {"düşük": probs[0], "orta": probs[1], "yüksek": probs[2]},
        "gecis_egilimi": ("artıyor" if egim > 0 else "azalıyor" if egim < 0 else "sabit"),
        "yorum": {
            "düşük_volatilite": "Sıkışma — patlama yaklaşıyor olabilir, kırılımı bekle.",
            "orta_volatilite": "Normal rejim — standart stratejiler çalışır.",
            "yüksek_volatilite": "Çalkantı — pozisyon küçült, kaldıraç düşür, dikkat.",
        }[rejim],
    }


# ======================================================================
# Birleşik özet — tüm motoru tek çağrıda çalıştırır
# ======================================================================

def full_analysis(df: pd.DataFrame, horizon_bars: int = 24,
                  bars_per_day: float = 1.0) -> dict:
    """
    Tüm stokastik motoru çalıştırıp tek sözlük döndürür.
    df: OHLC(V) DataFrame (1 birincil zaman dilimi).
    horizon_bars: difüzyon/GARCH projeksiyon ufku (bar cinsinden).
    bars_per_day: günlük→bar ölçeklemesi (1h için 24, 1d için 1).
    """
    close = df["close"]
    price = float(close.iloc[-1]) if len(close) else None

    gbm = gbm_drift_diffusion(close, bars_per_day)
    daily_sigma = gbm["gunluk_difuzyon"] if gbm.get("yeterli_veri") else None

    garch = garch11_fit(close)
    garch_fc = garch11_forecast(garch, horizon_bars) if garch.get("basarili") else {"yeterli_veri": False}

    return {
        "fiyat": price,
        "random_walk_testi": hurst_exponent(close),       # [1][7]
        "getiri_dagilimi": return_distribution(close),     # [2]
        "gbm_parametreleri": gbm,                          # [3]
        "difuzyon_projeksiyonu": diffusion_projection(     # [2]
            price, daily_sigma, horizon_bars, bars_per_day,
            # bar-başı drift: günlük drift / bar_sayısı (diffusion_projection
            # drift'i horizon_bars ile çarpar, o yüzden bar ölçeğinde verilir)
            drift=(gbm.get("gunluk_suruklenme", 0.0) / max(bars_per_day, _EPS))
                  if gbm.get("yeterli_veri") else 0.0,
        ),
        "yang_zhang_volatilite": yang_zhang_volatility(df),  # [6]
        "garch": {k: v for k, v in garch.items() if not k.startswith("_")},  # [5]
        "garch_tahmin": garch_fc,                          # [5]
        "volatilite_rejimi": volatility_regime(close),     # [8]
        "_referanslar": "Bachelier[1] Einstein[2] Itô[3] Black-Scholes[4] "
                        "Bollerslev/GARCH[5] Yang-Zhang[6] Hurst[7] Hamilton[8]",
    }


def compact_for_signal(full: dict) -> dict:
    """
    full_analysis çıktısını, Claude sinyal/tahmin prompt'una sığacak kısa,
    karar-odaklı bir özete indirger. Sayılar değil, YORUMLAR öne çıkar —
    model "fiyat tahmin et" değil "bu koşullar tahmini güçlendirir mi
    zayıflatır mı" diye okusun.
    """
    rw = full.get("random_walk_testi", {})
    dist = full.get("getiri_dagilimi", {})
    garch_fc = full.get("garch_tahmin", {})
    rejim = full.get("volatilite_rejimi", {})
    dif = full.get("difuzyon_projeksiyonu", {})

    return {
        "tahmin_edilebilirlik": {
            "hurst": rw.get("hurst"),
            "rejim": rw.get("rejim"),  # trend / ortalama_donus / random_walk
            "not": rw.get("yorum"),
        },
        "kuyruk_riski": {
            "kuyruk": dist.get("kuyruk"),
            "carpiklik": dist.get("carpiklik"),
            "not": dist.get("yorum"),
        },
        "volatilite_tahmini": {
            "yon": garch_fc.get("yon"),  # yükseliyor / düşüyor
            "sonraki_bar_vol_yuzde": garch_fc.get("sonraki_bar_vol_yuzde"),
            "ufuk_vol_yuzde": garch_fc.get("ufuk_toplam_vol_yuzde"),
            "not": garch_fc.get("yorum"),
        },
        "volatilite_rejimi": {
            "rejim": rejim.get("mevcut_rejim"),
            "egilim": rejim.get("gecis_egilimi"),
            "not": rejim.get("yorum"),
        },
        "difuzyon_bandi_1sigma": dif.get("bant_1sigma"),
    }
