"""
Hafif backend i18n katmanı — kaynak dil Türkçe, ikinci dil İngilizce.

Amaç: kullanıcıya görünen *düz metin* (prose) alanlarını istek diline göre
çevirmek. Makine tarafından okunan kısa değer/enum'lar (ör. "BEKLE", "yükseliş",
"yukarı") ÇEVRİLMEZ — onların yerelleştirmesi arayüzde `tv()` ile yapılır
(frontend/src/i18n/values.json). Böylece backend değerleri üzerinden karşılaştırma
yapan frontend mantığı bozulmaz.

Dil tespiti (öncelik sırası):
    1. ?lang=tr|en   (query param)
    2. X-Lang: tr|en (header — frontend axios interceptor gönderir)
    3. Accept-Language
    4. varsayılan: tr

Kullanım (main.py):
    app.add_middleware(I18nMiddleware)   # JSON yanıtlarını çevirir
    from i18n import current_lang, output_lang_note
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar

LANGS = ("tr", "en")
DEFAULT_LANG = "tr"

_current: ContextVar[str] = ContextVar("17money_lang", default=DEFAULT_LANG)


def normalize_lang(value: str | None) -> str | None:
    """'en-US,en;q=0.9' → 'en'; 'tr' → 'tr'; bilinmeyen → None."""
    if not value:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    for part in re.split(r"[,\s;]", raw):
        part = part.strip()
        if not part:
            continue
        code = part.split("-")[0].split("_")[0]
        if code in LANGS:
            return code
    return None


def resolve_lang(scope_or_request) -> str:
    """
    ASGI scope veya Starlette Request'ten dil çıkarır.
    Query param (?lang=) > X-Lang > Accept-Language > varsayılan.
    """
    headers = {}
    query = b""
    if isinstance(scope_or_request, dict) and "headers" in scope_or_request:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope_or_request.get("headers", [])}
        query = scope_or_request.get("query_string", b"") or b""
    else:  # Starlette Request
        try:
            headers = {k.lower(): v for k, v in scope_or_request.headers.items()}
            query = str(scope_or_request.url.query or "").encode("latin-1")
        except Exception:
            return DEFAULT_LANG

    for pair in query.decode("latin-1").split("&"):
        if pair.startswith("lang="):
            hit = normalize_lang(pair[5:])
            if hit:
                return hit
    hit = normalize_lang(headers.get("x-lang"))
    if hit:
        return hit
    return normalize_lang(headers.get("accept-language")) or DEFAULT_LANG


def set_lang(lang: str):
    """ContextVar'ı ayarlar; token döner (reset için)."""
    return _current.set(lang if lang in LANGS else DEFAULT_LANG)


def reset_lang(token) -> None:
    try:
        _current.reset(token)
    except Exception:
        pass


def current_lang() -> str:
    return _current.get()


def is_en() -> bool:
    return _current.get() == "en"


# --------------------------------------------------------------------------- #
# Claude prompt dili                                                            #
# --------------------------------------------------------------------------- #
EN_OUTPUT_NOTE = (
    "\n\n# OUTPUT LANGUAGE\n"
    "The user's interface language is ENGLISH. Write your ENTIRE response in English "
    "(analysis, reasoning, warnings). Keep tickers, indicator names and numeric levels as-is."
)


def output_lang_note(lang: str | None = None) -> str:
    """Sistem prompt'una eklenecek dil notu (TR için boş)."""
    code = lang or current_lang()
    return EN_OUTPUT_NOTE if code == "en" else ""


def localize_prompt(prompt: str, lang: str | None = None) -> str:
    """Prompt + dil notu (EN istenmişse)."""
    return f"{prompt}{output_lang_note(lang)}"


# --------------------------------------------------------------------------- #
# TR → EN SÖZLÜĞÜ                                                               #
#                                                                               #
# EXACT : yanıttaki metnin TAMAMI eşleşirse uygulanır (kısa etiketler dahil).    #
# PHRASES: cümle/kalıp parçaları; yalnızca BOŞLUK İÇEREN metinlerde uygulanır    #
#          (böylece 'BEKLE', 'yükseliş' gibi makine değerleri korunur).          #
# Uzun kalıplar önce denenir (en uzundan kısaya sıralama kodda yapılır).         #
# --------------------------------------------------------------------------- #
EXACT = {
    # --- stokastik / bilim paneli ---------------------------------------- #
    "Dağılım normale yakın — standart volatilite ölçüleri güvenilir.":
        "Distribution is close to normal — standard volatility measures are reliable.",
    "Volatilite artıyor — pozisyon boyutunu küçült, stop'u genişlet.":
        "Volatility rising — reduce position size, widen the stop.",
    "Volatilite sönüyor — sakin piyasa, normal boyutlandırma.":
        "Volatility fading — calm market, normal sizing.",
    "Volatilite kümelenir": "Volatility clusters",
    "Volatilite sıfır — sabit fiyat.": "Volatility is zero — flat price.",
    "Kalıcılık var — trend takibi anlamlı (H>0.5)":
        "Persistence present — trend following makes sense (H>0.5)",
    "Ortalamaya dönüş — kontra-trend anlamlı (H<0.5)":
        "Mean reversion — counter-trend makes sense (H<0.5)",
    "Saf rastgele yürüyüş — yön tahmini zayıf (H≈0.5)":
        "Pure random walk — direction forecast is weak (H≈0.5)",
    "Sıkışma — patlama yaklaşıyor olabilir, kırılımı bekle.":
        "Squeeze — an explosion may be near, wait for the breakout.",
    "Çalkantı — pozisyon küçült, kaldıraç düşür, dikkat.":
        "Choppy — reduce position, lower leverage, stay alert.",
    "Kalın kuyruk: aşırı hareketler normalden sık — risk hesabında":
        "Fat tail: extreme moves are more frequent than normal — in risk sizing",
    "normal dağılıma güvenme, stop'ları geniş tut.":
        "do not trust the normal distribution, keep stops wide.",
    "GARCH için en az 100 bar gerekir.": "GARCH needs at least 100 bars.",
    "GARCH yakınsamadı.": "GARCH did not converge.",
    "Yang-Zhang (range-based, açılış-sıçramasına dayanıklı)":
        "Yang-Zhang (range-based, resilient to opening jumps)",
    "rastgeleliğin matematiği": "the mathematics of randomness",
    "şu an hangi piyasa dünyasındayız": "which market world are we in right now",

    # --- sinyal çözme (decode) ------------------------------------------- #
    "Lag-1 otokorelasyon zayıf — kısa vadede yön hafızası yok (random-walk'a yakın).":
        "Lag-1 autocorrelation is weak — no short-term directional memory (close to random walk).",
    "Belirgin periyodik döngü yok — hareket büyük ölçüde gürültü.":
        "No clear periodic cycle — the move is largely noise.",
    "baskın periyotları": "dominant periods",
    "Şifre kırma": "Cipher breaking",
    "Şifre çözme": "Decoding",
    "şifre kırılamaz": "the cipher cannot be broken",
    "şifre kırık": "cipher broken",
    "şifresini kırma": "breaking its cipher",
    "deşifre etmek": "to decode",
    "kod kırıcılık / şifre çözme": "codebreaking / decoding",

    # --- karar izi (decision trace) -------------------------------------- #
    "Yatay piyasa — işlem açılmadı.": "Sideways market — no trade opened.",
    "Göstergeler yatay/çelişkili — sinyal üretilmez (BEKLE).":
        "Indicators flat/conflicting — no signal generated (WAIT).",
    "Aktif seans — kurumsal hacim var, sinyaller daha güvenilir.":
        "Active session — institutional volume present, signals are more reliable.",
    "Derin Asya gecesi (00-05 UTC) — teknik sinyaller daha az güvenilir, güven düşürülür.":
        "Deep Asian night (00-05 UTC) — technical signals less reliable, confidence lowered.",
    "DÜŞÜK likidite — riskli": "LOW liquidity — risky",
    "Model onayı (kötü sinyal eleme)": "Model approval (filtering out bad signals)",
    "Model onayı": "Model approval",
    "70 özellik → meta-model": "70 features → meta-model",
    "Eşiği geçti → işleme değer.": "Threshold passed → worth trading.",
    "Eşiğin altında → istatistiksel olarak zayıf, atlanması önerilir.":
        "Below threshold → statistically weak, skipping is recommended.",
    "Yön analizi": "Direction analysis",
    "ADX (trend gücü)": "ADX (trend strength)",
    "trend (geniş hedef)": "trend (wide target)",
    "düşük likidite": "low liquidity",
    "hedefe ulaştı": "hit the target",
    "stop oldu": "hit the stop",
    "Tek kayıp normal — sistem uzun vadede kazanır,":
        "A single loss is normal — the system wins over the long run,",
    "her işlem değil.": "not every trade.",
    "— kazanç kayıptan büyük, sistemin sırrı bu":
        "— wins are larger than losses, that is the system's secret",
    "Model bu sinyalin kazanma olasılığını":
        "The model calculated the win probability of this signal as",
    "Çoklu zaman dilimi göstergeleri": "Multi-timeframe indicators",
    "İşlem atlandı: ": "Trade skipped: ",
    "zayıf koşul": "weak condition",
    "kırılım yok": "no breakout",
    "üstünde": "above",
    "altında": "below",

    # --- oylama / paper hesap -------------------------------------------- #
    "Model henüz eğitilmemiş — oy yok.": "Model not trained yet — no vote.",
    "yön desteklenmedi": "direction not supported",
    "iki çekimser": "both abstained",
    "tek başına": "alone",
    "→ zayıf, çekimser.": "→ weak, abstain.",
    "Model kazanma olasılığını": "The model calculated the win probability as",
    "Aktif oy işlemin yönünü desteklemiyor — BEKLE.":
        "The active vote does not support the trade direction — WAIT.",
    "Pozitif lag-1": "Positive lag-1",
    "Negatif lag-1": "Negative lag-1",
    "Sermaye eğrisi — işlem işlem sermaye seyri (grafik için).":
        "Equity curve — capital path trade by trade (for the chart).",
    "Hesabı sıfırla — tüm işlemleri sil, sermayeyi başa al, parametreleri ayarla.":
        "Reset the account — delete all trades, restore the capital, set the parameters.",
    "— yeni işlemler durduruldu, onayın gerekiyor.":
        "— new trades stopped, your approval is needed.",
    "açık işlem": "open trade",
    "sinyal başlatmadan görünmüyor": "not visible until a signal is started",
    "canlı kanıt": "live proof",

    # --- eğitim / meta-model --------------------------------------------- #
    "Eğitim zaten çalışıyor.": "Training is already running.",
    "Eğitim zaten durmuş.": "Training has already stopped.",
    "EĞİTİME BAŞLA": "START TRAINING",
    "model kendini eğitsin": "let the model train itself",
    "sürekli öğrenme": "continuous learning",
    "kör pekiştirme": "blind reinforcement",
    "zehirlenmiş olabilir. Terfi REDDEDİLDİ, şampiyon korundu.":
        "may be poisoned. Promotion REJECTED, champion kept.",
    "Şampiyon korundu.": "Champion kept.",
    "Terfi etti.": "Promoted.",
    "sınıyor, kanıtlarsa terfi ediyor. DURDUR'a basınca rapor gelir.":
        "tests it and promotes it if it proves itself. Press STOP to get the report.",
    "Meta-model bu sinyalin triple-barrier kazanma olasılığını tahmin eder.":
        "The meta-model estimates the triple-barrier win probability of this signal.",
    "ATLA = istatistiksel olarak zayıf koşullar, işlemi atlamayı değerlendir.":
        "SKIP = statistically weak conditions, consider skipping the trade.",
    "Tek sınıf var — hem kazanan hem kaybeden örnek gerekli.":
        "Only one class present — both winning and losing samples are required.",
    "Önce backfill çalıştırın veya canlı sinyal biriktirin.":
        "First run the backfill or accumulate live signals.",
    "Bölme sonrası sınıf/örnek yetersiz.": "Not enough classes/samples after the split.",
    "bu sinyal tutacak mı?": "will this signal hold?",
    "Meta-model henüz eğitilmemiş — filtre uygulanmadı.":
        "The meta-model is not trained yet — no filter applied.",
    "Model olasılığı": "Model probability",
    "Getiri gerçek kenar mı yoksa şans mı": "Is the return a real edge or luck",

    # --- haber / olaylar -------------------------------------------------- #
    "bu gerçek kriz mi?": "is this a real crisis?",
    "— Claude değerlendirmesi öneriliyor.": "— a Claude review is recommended.",
    "Tesla 1.5 milyar$ BTC aldı": "Tesla bought $1.5B of BTC",
    "Çin madencilik yasağı + Tesla geri adımı — sert çöküş":
        "China mining ban + Tesla reversal — sharp crash",
    "FTX çöküşü — sektör güven krizi": "FTX collapse — sector confidence crisis",
    "Celsius dondurma + 3AC iflası": "Celsius freeze + 3AC bankruptcy",
    "BlackRock spot ETF başvurusu": "BlackRock spot ETF filing",
    "ETF sonrası yeni ATH ~73k": "New ATH ~73k after the ETF",
    "Döngü ATH ~69k": "Cycle ATH ~69k",
    "3. Halving (blok ödülü 12.5→6.25)": "3rd halving (block reward 12.5→6.25)",
    "4. Halving (blok ödülü 6.25→3.125)": "4th halving (block reward 6.25→3.125)",
    "en yakın büyük olaya kaç gün uzaklıktayız ve etkisi neydi":
        "how many days since the nearest major event and what its impact was",
    "ders kitabı": "textbook",
    "Henüz tarama yapılmadı": "No scan has run yet",
    "dönüm": "turning point",

    # --- Claude erişimi / kurulum ---------------------------------------- #
    "Claude erişimi yok — CLAUDE_API_KEY ekleyin veya Claude Code CLI ile giriş yapın":
        "No Claude access — add CLAUDE_API_KEY or sign in with Claude Code CLI",
    "Kalıcı sohbet oturumunu sıfırlar — sonraki mesaj temiz başlar.":
        "Resets the persistent chat session — the next message starts clean.",
    "Terminal sohbet modu — uzman trading partneri, gerektiğinde web araştırması yapar.":
        "Terminal chat mode — expert trading partner that researches the web when needed.",
    "Meta loglama hatası: ": "Meta logging error: ",
    "Çözülmüş sinyalleri paper hesaba elle işle (resolve_loop dışında manuel tetik).":
        "Manually post resolved signals to the paper account (outside resolve_loop).",

    # --- intermarket piyasa adları (config.INTERMARKET_TICKERS) ---------- #
    "Altın": "Gold",
    "Dolar Endeksi": "Dollar Index",
    "Volatilite (VIX)": "Volatility (VIX)",
    "Gümüş": "Silver",
    "Petrol": "Oil",

    # --- model açıklamaları (/api/ai/status) ----------------------------- #
    "Fable 5 — en güçlü, en derin analiz": "Fable 5 — strongest, deepest analysis",
    "Opus 4.8 — güçlü, daha verimli": "Opus 4.8 — strong, more efficient",
    "Sonnet 4.6 — hızlı ve dengeli": "Sonnet 4.6 — fast and balanced",
    "Haiku 4.5 — en hızlı, basit sorular": "Haiku 4.5 — fastest, simple questions",

    # --- teknik analiz notları ------------------------------------------- #
    "Yükselişten dönüş sinyali": "Reversal signal after an uptrend",
    "Düşüşten dönüş sinyali": "Reversal signal after a downtrend",
    "±1σ ≈ %68, ±2σ ≈ %95 olasılıkla fiyatın kalacağı aralık (difüzyon).":
        "±1σ ≈ 68%, ±2σ ≈ 95% probability band the price is expected to stay in (diffusion).",
    "Kalın kuyruk: aşırı hareketler normalden sık — risk hesabında normal dağılıma güvenme, stop'ları geniş tut.":
        "Fat tail: extreme moves are more frequent than normal — in risk sizing do not trust "
        "the normal distribution, keep stops wide.",

    # --- premium/discount `detay` metni (tek kelime → PHRASES'e takılmaz) -- #
    "bölge=premium": "zone=premium",
    "bölge=discount": "zone=discount",
    "bölge=equilibrium": "zone=equilibrium",
}

# Cümle içi kalıplar — yalnızca BOŞLUK İÇEREN metinlerde uygulanır (uzun önce).
PHRASES = (
    ("⚠ Meydan okuyan SAĞLIKSIZ", "⚠ Challenger is UNHEALTHY"),
    ("— model çökmüş/", "— the model may have collapsed/"),
    ("-barlık döngü tespit edildi", "-bar dominant cycle detected"),
    ("— periyodik yapı var, döngü konumu", "— periodic structure present, the cycle position"),
    ("tahmine katkı verir.", "contributes to the forecast."),
    ("— seride istatistiksel yapı var,", "— the series has statistical structure,"),
    ("— kısmi yapı, kısmi gürültü.", "— partly structure, partly noise."),
    ("öngörülebilirlik düşük. Tahmine GÜVENME, güveni kır.",
     "predictability is low. Do NOT trust the forecast, cut the confidence."),
    ("— momentum: yön devam etme eğiliminde.", "— momentum: the direction tends to continue."),
    ("— ortalamaya dönüş: yön ters dönme eğiliminde.",
     "— mean reversion: the direction tends to reverse."),
    ("dedi, diğeri çekimser → İŞLE (çekimser engellemez).",
     "said so and the other abstained → EXECUTE (abstention does not block)."),
    ("dedi — çelişki var, temkinli BEKLE.", "said — there is a conflict, stay cautious WAIT."),
    ("yönünde hemfikir → İŞLE.", "direction — both agree → EXECUTE."),
    ("rejiminde. Hedef buna göre ayarlandı:", "regime. The target was adjusted accordingly:"),
    ("· giriş ", "· entry "),
    ("→ hedef ", "→ target "),
    ("2) Tarayıcıda", "2) In the browser"),
    ("abonelikli hesabınızla", "with your subscription account"),
    ("oturum açın —", "sign in —"),
    ("diyene kadar pencereyi kapatmayın.", "until it says so."),
    ("1) Açılan KONSOL penceresine bakın; giriş yöntemi sorulursa",
     "1) Look at the CONSOLE window that opened; if you are asked for a login method"),
    ("'Authorize' (Yetkilendir) düğmesine basın ve konsol 'Login successful'",
     "press the 'Authorize' button and wait for the console to say 'Login successful'"),
    ("şampiyon ", "champion "),
    ("Kazanç ", "Win "),
    ("Kayıp ", "Loss "),
    ("işlemi ", "trade "),
    ("hedefe ulaştı.", "hit the target."),
    ("hâlâ açık", "still open"),
    ("sinyal çözüldü", "signals resolved"),
    ("işlem paper hesaba geçti", "trades posted to the paper account"),
    ("biriken sinyal", "queued signals"),
    ("Fiyat düşük dip", "Price lower low"),
    ("ama RSI yüksek dip", "but RSI higher low"),
    ("Yüksek entropi", "High entropy"),
    ("Düşük entropi", "Low entropy"),
    ("Orta entropi", "Medium entropy"),
    ("— neredeyse saf gürültü,", "— almost pure noise,"),
    ("Kalıcılık ", "Persistence "),
    (": şoklar çabuk sönüyor, volatilite esnek.", ": shocks fade quickly, volatility is flexible."),
    ("kesişim=", "crossover="),
    ("güç=", "strength="),
    ("zayıflıyor", "weakening"),
    ("güçleniyor", "strengthening"),
    ("Baskın ", "Dominant "),
    ("-bar dominant cycle detected", "-bar cycle detected"),
    ("=çok_güçlü_trend", "=very_strong_trend"),
    ("=güçlü_trend", "=strong_trend"),
    ("=zayıf_trend", "=weak_trend"),
    ("=trendsiz_chop", "=range_bound"),
    ("=güçleniyor", "=strengthening"),
    ("=zayıflıyor", "=weakening"),
    ("=orta_volatilite", "=medium_volatility"),
    ("=düşük_volatilite", "=low_volatility"),
    ("=yüksek_volatilite", "=high_volatility"),
    # Gösterge matrisi tooltip'leri (forecast_service `detay` cümleleri).
    ("OBV trendi yükselen", "OBV trend rising"),
    ("OBV trendi düşen", "OBV trend falling"),
    ("OBV trendi yatay", "OBV trend flat"),
    ("fiyat üstünde", "price above"),
    ("fiyat altında", "price below"),
    ("kırılım yok", "no break"),
    ("tespit yok", "no detection"),
    ("pozisyon=", "position="),
    ("durum=", "state="),
    ("bölge=", "zone="),
    ("=üst_bant_üstü", "=above_upper_band"),
    ("=alt_bant_altı", "=below_lower_band"),
    ("=orta_üstü", "=upper_half"),
    ("=orta_altı", "=lower_half"),
    ("=aşırı_alım", "=overbought"),
    ("=aşırı_satım", "=oversold"),
    ("=nötr", "=neutral"),
)
_PHRASES_SORTED = tuple(sorted(PHRASES, key=lambda pair: len(pair[0]), reverse=True))

# Çeviri yapılmayan teknik içerik (URL, dosya yolu, kod/JSON parçası, rakam ağırlıklı).
_SKIP = re.compile(r"https?://|/api/|\.(py|js|json|csv|parquet)\b|^[\W\d_]+$")



# --------------------------------------------------------------------------- #
# Çeviri                                                                        #
# --------------------------------------------------------------------------- #
def translate_text(text: str, lang: str | None = None) -> str:
    """Düz metni istek diline çevirir (TR kaynak → EN). Çevrilemeyen metin aynen döner."""
    code = lang or current_lang()
    if code != "en" or not isinstance(text, str) or len(text) < 4:
        return text
    if _SKIP.search(text):
        return text
    if text in EXACT:
        return EXACT[text]
    # Kaynak metinlerde satır kırılmaları olabilir (Python çok satırlı literal) →
    # karşılaştırmayı boşlukları sadeleştirerek yap.
    norm = re.sub(r"\s+", " ", text).strip()
    if norm in EXACT:
        return EXACT[norm]
    if " " not in norm:
        # Tek kelime = makine değeri (BEKLE, yükseliş...). Arayüz tarafı çevirir.
        return text
    out = norm
    for tr, en in _PHRASES_SORTED:
        if tr in out:
            out = out.replace(tr, en)
    return out if out != norm else text


def translate_payload(obj, lang: str | None = None):
    """
    Yanıt gövdesini (dict/list/str) yerelleştirir.
    Sözlük ANAHTARLARI (ör. 'getiri_yuzde') çevrilmez — yalnızca metin değerleri.
    """
    code = lang or current_lang()
    if code != "en":
        return obj
    if isinstance(obj, str):
        return translate_text(obj, code)
    if isinstance(obj, dict):
        return {k: translate_payload(v, code) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [translate_payload(v, code) for v in obj]
    return obj


def _json_fallback(value):
    """numpy/tarih vb. JSON'a çevrilemeyen tipler için güvenli dönüşüm."""
    try:
        return float(value)
    except Exception:
        return str(value)


# --------------------------------------------------------------------------- #
# ASGI middleware — JSON yanıtlarını istek diline göre çevirir                   #
# --------------------------------------------------------------------------- #
class I18nMiddleware:
    """
    Saf ASGI middleware (BaseHTTPMiddleware değil): WebSocket ve streaming
    yanıtlara dokunmaz, yalnızca tek parça halinde gelen application/json
    gövdesini çevirir. `lang != tr` olduğunda ContextVar'a yazılan dil,
    aynı istek içinde üretilen prompt/servis metinlerini de etkiler.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        lang = resolve_lang(scope)
        token = set_lang(lang)
        try:
            if lang != "en":
                await self.app(scope, receive, send)
                return
            await self._handle_with_translation(scope, receive, send, lang)
        finally:
            reset_lang(token)

    async def _handle_with_translation(self, scope, receive, send, lang: str):
        started: dict = {}
        body = bytearray()

        async def send_wrapper(message):
            mtype = message["type"]
            if mtype == "http.response.start":
                started.clear()
                started.update(message)
                return
            if mtype != "http.response.body":
                await send(message)
                return
            body.extend(message.get("body") or b"")
            if message.get("more_body"):
                return
            headers = list(started.get("headers") or [])
            ctype = b""
            for key, val in headers:
                if key.lower() == b"content-type":
                    ctype = val.lower()
            translated = False
            if body and b"application/json" in ctype:
                try:
                    payload = json.loads(bytes(body).decode("utf-8"))
                    new_body = json.dumps(translate_payload(payload, lang),
                                          ensure_ascii=False,
                                          default=_json_fallback).encode("utf-8")
                    body.clear()
                    body.extend(new_body)
                    headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                    headers.append((b"content-length", str(len(new_body)).encode("ascii")))
                    translated = True
                except Exception:
                    translated = False
            if not translated and body:
                headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
            headers = [(k, v) for k, v in headers if k.lower() != b"content-language"]
            headers.append((b"content-language", b"en"))
            await send({**started, "headers": headers})
            await send({"type": "http.response.body", "body": bytes(body), "more_body": False})

        await self.app(scope, receive, send_wrapper)

