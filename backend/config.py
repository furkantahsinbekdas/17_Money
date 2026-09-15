"""
17Money Algorithm — MERKEZÎ YAPILANDIRMA.

Tek kural: ayarlar ve gizli bilgiler bu dosyada yaşar; iş mantığı dosyalarında
(SERVICES/ROUTERS) sabit sayı, URL, model adı veya anahtar BULUNMAZ.

Katmanlar:
  1. GİZLİLER  → yalnızca config/.env'den okunur (koda asla gömülmez).
  2. AYARLAR   → her biri ortam değişkeniyle ezilebilir; varsayılanlar burada.
  3. YOLLAR    → veri/model/oturum dosyalarının tek doğruluk kaynağı.

İlkeler:
- .env TEK burada yüklenir (load_dotenv) → başka modüllerde load_dotenv yoktur.
- config/.env yoksa (taze klon / CI) sessizce varsayılanlarla çalışır; program
  çökmez, sadece Claude/Binance gibi dış servisler "yapılandırılmamış" olur.
- Sistem promptları ve JSON şemaları burada DEĞİL, prompts.py'dedir.
- Özellik (feature) üretim pencereleri feature_service.py'dedir: onlar
  eğitilmiş meta-modelin SÖZLEŞMESİdir, keyfî değiştirilirse model geçersiz olur.
"""

from __future__ import annotations

import json as _json
import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 0. Yollar ve .env yükleme (tek nokta)
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent          # backend/
PROJECT_ROOT = BACKEND_DIR.parent                      # repo kökü
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_PATH = CONFIG_DIR / ".env"
ENV_EXAMPLE_PATH = CONFIG_DIR / ".env.example"
ML_DIR = PROJECT_ROOT / "ml"

# .env yalnızca BURADA yüklenir. override=False → gerçek ortam değişkenleri
# (Docker/CI/systemd) .env'i her zaman ezer.
load_dotenv(dotenv_path=str(ENV_PATH), override=False)

# .env.example'da kullanılan yer tutucu öneki: "your_..." → yapılandırılmamış
PLACEHOLDER_PREFIX = "your_"


# ---------------------------------------------------------------------------
# 1. Tip güvenli ortam okuyucular
# ---------------------------------------------------------------------------
def env_str(name: str, default: str = "") -> str:
    """Boş/whitespace değerleri 'ayarlanmamış' sayar → varsayılana düşer."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(float(env_str(name, str(default))))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env_str(name, str(default)))
    except (TypeError, ValueError):
        return default


_TRUE = {"1", "true", "yes", "on", "evet", "aktif"}
_FALSE = {"0", "false", "no", "off", "hayir", "pasif"}


def env_bool(name: str, default: bool) -> bool:
    raw = env_str(name, "").lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def env_list(name: str, default: list[str]) -> list[str]:
    """Virgülle ayrılmış liste: MTF_INTERVALS=1d,4h,1h,15m"""
    raw = env_str(name, "")
    if not raw:
        return list(default)
    items = [p.strip() for p in raw.split(",")]
    return [p for p in items if p] or list(default)


def env_json_dict(name: str, default: dict) -> dict:
    """JSON nesnesi olarak ezilebilen sözlük (ör. ağırlık tabloları)."""
    raw = env_str(name, "")
    if not raw:
        return dict(default)
    try:
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, dict) else dict(default)
    except _json.JSONDecodeError:
        return dict(default)


def env_model_map(name: str, default: dict[str, str]) -> dict[str, str]:
    """Model listesi: 'id=etiket,id=etiket' biçiminde ezilebilir."""
    raw = env_str(name, "")
    if not raw:
        return dict(default)
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        model_id, _, label = pair.partition("=")
        model_id = model_id.strip()
        if model_id:
            out[model_id] = label.strip() or model_id
    return out or dict(default)


def is_configured(value: str | None) -> bool:
    """Anahtar gerçekten girilmiş mi? Yer tutucu ('your_...') yapılandırılmış sayılmaz."""
    return bool(value) and not str(value).startswith(PLACEHOLDER_PREFIX)


# ---------------------------------------------------------------------------
# 2. GİZLİ ANAHTARLAR (yalnızca .env'den; koda asla gömülmez)
# ---------------------------------------------------------------------------
BINANCE_API_KEY = env_str("BINANCE_API_KEY")
BINANCE_SECRET_KEY = env_str("BINANCE_SECRET_KEY")
BINANCE_TESTNET = env_bool("BINANCE_TESTNET", True)

CLAUDE_API_KEY = env_str("CLAUDE_API_KEY")
HAS_CLAUDE_API_KEY = is_configured(CLAUDE_API_KEY)

NEWS_API_KEY = env_str("NEWS_API_KEY")
CRYPTOPANIC_KEY = env_str("CRYPTOPANIC_KEY")

SECRET_NAMES = (
    "BINANCE_API_KEY", "BINANCE_SECRET_KEY", "CLAUDE_API_KEY",
    "NEWS_API_KEY", "CRYPTOPANIC_KEY",
)


def missing_secrets() -> list[str]:
    """Eksik/yer tutucu bırakılmış anahtarların adları (kurulum tanısı)."""
    return [
        ad for ad, deger in (
            ("BINANCE_API_KEY", BINANCE_API_KEY),
            ("BINANCE_SECRET_KEY", BINANCE_SECRET_KEY),
            ("CLAUDE_API_KEY", CLAUDE_API_KEY),
            ("NEWS_API_KEY", NEWS_API_KEY),
            ("CRYPTOPANIC_KEY", CRYPTOPANIC_KEY),
        ) if not is_configured(deger)
    ]


# ---------------------------------------------------------------------------
# 3. SUNUCU / UYGULAMA
# ---------------------------------------------------------------------------
APP_TITLE = env_str("APP_TITLE", "17Money Algorithm API")
APP_DESCRIPTION = env_str("APP_DESCRIPTION", "BTC/USDT Futures AI Trading Partner")
APP_VERSION = env_str("APP_VERSION", "1.0.0")
APP_HOST = env_str("APP_HOST", "0.0.0.0")
APP_PORT = env_int("APP_PORT", 8000)
APP_RELOAD = env_bool("APP_RELOAD", True)
LOG_LEVEL = env_str("LOG_LEVEL", "info")

# CORS: virgülle ayrılmış liste (CORS_ORIGINS=http://localhost:3000,...)
CORS_ORIGINS = env_list("CORS_ORIGINS", [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
])


# ---------------------------------------------------------------------------
# 4. PİYASA / SEMBOL / ZAMAN DİLİMLERİ
# ---------------------------------------------------------------------------
SYMBOL = env_str("SYMBOL", "BTCUSDT")

# Analiz hiyerarşisi: 1d rejim → 4h yapı → 1h kurulum → 15m zamanlama
MTF_INTERVALS = env_list("MTF_INTERVALS", ["1d", "4h", "1h", "15m"])
FORECAST_INTERVALS = env_list("FORECAST_INTERVALS", ["15m", "1h", "4h", "1d"])
TRADE_INTERVALS = env_list("TRADE_INTERVALS", ["15m", "1h", "4h", "1d"])
DEFAULT_INTERVAL = env_str("DEFAULT_INTERVAL", "1h")

# Kline (mum) çekme limitleri
KLINE_LIMIT = env_int("KLINE_LIMIT", 250)              # sinyal/analiz penceresi
BROADCAST_KLINE_LIMIT = env_int("BROADCAST_KLINE_LIMIT", 200)  # WS yayını
DAILY_KLINE_LIMIT = env_int("DAILY_KLINE_LIMIT", 120)  # intermarket baz penceresi
INTERMARKET_KLINE_LIMIT = env_int("INTERMARKET_KLINE_LIMIT", 100)
SCIENCE_KLINE_LIMIT = env_int("SCIENCE_KLINE_LIMIT", 500)      # stokastik motor
SCIENCE_KLINE_MIN = env_int("SCIENCE_KLINE_MIN", 120)          # alt sınır (istatistik)
ORDERBOOK_LIMIT = env_int("ORDERBOOK_LIMIT", 20)               # emir defteri derinliği
SHOCK_KLINE_LIMIT = env_int("SHOCK_KLINE_LIMIT", 5)            # alarm fiyat şoku

# Zaman dilimi → günlük bar sayısı (yıllıklaştırma / difüzyon ölçeklemesi)
BARS_PER_DAY = env_json_dict("BARS_PER_DAY", {
    "1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1,
})


# ---------------------------------------------------------------------------
# 5. ARKA PLAN DÖNGÜLERİ (saniye) — main.py lifespan
# ---------------------------------------------------------------------------
BROADCAST_INTERVAL_SEC = env_int("BROADCAST_INTERVAL_SEC", 60)      # piyasa yayını
RESOLVE_INTERVAL_SEC = env_int("RESOLVE_INTERVAL_SEC", 600)         # etiket çözümü
COLLECT_INTERVAL_SEC = env_int("COLLECT_INTERVAL_SEC", 3600)        # AI'sız toplama
COLLECT_STARTUP_DELAY_SEC = env_int("COLLECT_STARTUP_DELAY_SEC", 120)
CHALLENGE_CHECK_INTERVAL_SEC = env_int("CHALLENGE_CHECK_INTERVAL_SEC", 3600)
CHALLENGE_STARTUP_DELAY_SEC = env_int("CHALLENGE_STARTUP_DELAY_SEC", 300)
ALERT_INTERVAL_SEC = env_int("ALERT_INTERVAL_SEC", 900)             # haber alarmı
ALERT_STARTUP_DELAY_SEC = env_int("ALERT_STARTUP_DELAY_SEC", 45)
STARTUP_RECOVERY_DELAY_SEC = env_int("STARTUP_RECOVERY_DELAY_SEC", 20)

# Elle "EĞİTİME BAŞLA" döngüsü (training_controller) + durdurma join süresi
TRAINING_CHALLENGE_INTERVAL_SEC = env_int("TRAINING_CHALLENGE_INTERVAL_SEC", 60)
TRAINING_STOP_JOIN_TIMEOUT_SEC = env_int("TRAINING_STOP_JOIN_TIMEOUT_SEC", 5)


# ---------------------------------------------------------------------------
# 6. CLAUDE / LLM
# ---------------------------------------------------------------------------
# NOT: Varsayılanlar projenin kurulu olduğu hedef modellerdir. Anthropic model
# kimlikleri zamanla değişir — hesabınızda geçerli kimliği buraya/.env'e yazın.
CLAUDE_MODEL = env_str("CLAUDE_MODEL", "claude-fable-5")
CLAUDE_CLI_MODEL = env_str("CLAUDE_CLI_MODEL", "") or CLAUDE_MODEL
CLAUDE_CLI_PATH = env_str("CLAUDE_CLI_PATH")

# Oylama (paper run-once) için erişilebilir model — varsayılan model bazı
# hesaplarda açık olmayabilir; bu yüzden ayrı ayar.
CLAUDE_VOTE_MODEL = env_str("CLAUDE_VOTE_MODEL", "claude-sonnet-4-6")

# Sohbette seçilebilir modeller (frontend dropdown + CLI argüman doğrulaması:
# keyfî string CLI'ya geçmesin). CLAUDE_CHAT_MODELS=id=etiket,id=etiket
DEFAULT_CHAT_MODELS = {
    "claude-fable-5": "Fable 5 — en güçlü, en derin analiz",
    "claude-opus-4-8": "Opus 4.8 — güçlü, daha verimli",
    "claude-sonnet-4-6": "Sonnet 4.6 — hızlı ve dengeli",
    "claude-haiku-4-5": "Haiku 4.5 — en hızlı, basit sorular",
}
CLAUDE_CHAT_MODELS = env_model_map("CLAUDE_CHAT_MODELS", DEFAULT_CHAT_MODELS)
# Geriye dönük uyumluluk (routers/ai.py bu adı import ediyor):
ALLOWED_CHAT_MODELS = CLAUDE_CHAT_MODELS

CLAUDE_MAX_TOKENS_SIGNAL = env_int("CLAUDE_MAX_TOKENS_SIGNAL", 16000)
CLAUDE_MAX_TOKENS_FORECAST = env_int("CLAUDE_MAX_TOKENS_FORECAST", 16000)
CLAUDE_MAX_TOKENS_CHAT = env_int("CLAUDE_MAX_TOKENS_CHAT", 4000)
CLAUDE_MAX_TOKENS_RESEARCH = env_int("CLAUDE_MAX_TOKENS_RESEARCH", 16000)

CLAUDE_WEB_SEARCH_TOOL = env_str("CLAUDE_WEB_SEARCH_TOOL", "web_search_20260209")
CLAUDE_WEB_SEARCH_MAX_USES_CHAT = env_int("CLAUDE_WEB_SEARCH_MAX_USES_CHAT", 4)
CLAUDE_WEB_SEARCH_MAX_USES_RESEARCH = env_int("CLAUDE_WEB_SEARCH_MAX_USES_RESEARCH", 8)
# Server-side web search döngüsü pause_turn ile döner → yoklama tavanı
CLAUDE_WEB_SEARCH_MAX_TURNS_CHAT = env_int("CLAUDE_WEB_SEARCH_MAX_TURNS_CHAT", 4)
CLAUDE_WEB_SEARCH_MAX_TURNS_RESEARCH = env_int("CLAUDE_WEB_SEARCH_MAX_TURNS_RESEARCH", 5)

CHAT_HISTORY_TURNS = env_int("CHAT_HISTORY_TURNS", 12)   # pencereye taşınan mesaj
SIGNAL_NEWS_LIMIT = env_int("SIGNAL_NEWS_LIMIT", 8)      # prompt'a giren haber
RESEARCH_SOURCES_LIMIT = env_int("RESEARCH_SOURCES_LIMIT", 10)

# CLI çağrı süreleri (sn): derin sinyal uzun, sohbet/oy kısa
CLAUDE_CLI_TIMEOUT_SEC = env_int("CLAUDE_CLI_TIMEOUT_SEC", 300)
CLAUDE_CLI_CHAT_TIMEOUT_SEC = env_int("CLAUDE_CLI_CHAT_TIMEOUT_SEC", 180)
CLAUDE_CLI_VOTE_TIMEOUT_SEC = env_int("CLAUDE_CLI_VOTE_TIMEOUT_SEC", 90)
CLAUDE_CLI_STATUS_TIMEOUT_SEC = env_int("CLAUDE_CLI_STATUS_TIMEOUT_SEC", 30)

# Derin araştırma promptunun varsayılan odak metni (focus verilmezse)
RESEARCH_DEFAULT_FOCUS = env_str(
    "RESEARCH_DEFAULT_FOCUS",
    "BTC fiyatını önümüzdeki 24-72 saatte etkileyebilecek gelişmeler",
)


# ---------------------------------------------------------------------------
# 7. DOSYA YOLLARI (tek doğruluk kaynağı)
# ---------------------------------------------------------------------------
DATA_DIR = BACKEND_DIR / "data"
SIGNALS_DB_PATH = str(DATA_DIR / "signals.db")
PAPER_DB_PATH = str(DATA_DIR / "paper.db")
META_MODEL_PATH = str(DATA_DIR / "meta_model.joblib")
META_INFO_PATH = str(DATA_DIR / "meta_model.json")
PARENT_MODEL_PATH = str(DATA_DIR / "meta_model_parent.joblib")
PARENT_INFO_PATH = str(DATA_DIR / "meta_model_parent.json")
TRAINER_HISTORY_PATH = str(DATA_DIR / "trainer_history.json")
CHAT_SESSION_PATH = str(DATA_DIR / "chat_session.json")
CLI_WORKSPACE_DIR = str(DATA_DIR / "cli_workspace")
HISTORY_DIR = str(DATA_DIR / "history")
HISTORY_CACHE_DIR = str(DATA_DIR / "history" / "_cache")


# ---------------------------------------------------------------------------
# 8. TRIPLE-BARRIER + REJİME DUYARLI BARIYERLER (etiketleme matematiği)
# ---------------------------------------------------------------------------
# TP 1.5R : SL 1R → rastgele yürüyüşte ~%40 taban kazanma oranı; meta-modelin
# işi bunu seçicilikle yukarı çekmek.
TP_ATR_MULT = env_float("TP_ATR_MULT", 1.5)
SL_ATR_MULT = env_float("SL_ATR_MULT", 1.0)
HORIZON_BARS = env_int("HORIZON_BARS", 24)

# Rejim-duyarlı çarpanlar (ADX ile): güçlü trendde geniş TP, yatayda dar/simetrik
REGIME_ADX_STRONG = env_float("REGIME_ADX_STRONG", 30.0)
REGIME_ADX_MILD = env_float("REGIME_ADX_MILD", 22.0)
REGIME_BARRIERS_STRONG = (
    env_float("REGIME_TP_STRONG", 2.5), env_float("REGIME_SL_STRONG", 1.2),
)
REGIME_BARRIERS_MILD = (
    env_float("REGIME_TP_MILD", 1.5), env_float("REGIME_SL_MILD", 1.0),
)
REGIME_BARRIERS_WEAK = (
    env_float("REGIME_TP_WEAK", 1.0), env_float("REGIME_SL_WEAK", 1.0),
)


# ---------------------------------------------------------------------------
# 9. PAPER TRADING + DEVRE KESİCİ (kill switch)
# ---------------------------------------------------------------------------
DEFAULT_START_BALANCE = env_float("PAPER_START_BALANCE", 1000.0)
DEFAULT_RISK_PCT = env_float("PAPER_RISK_PCT", 0.02)          # işlem başına %2
DEFAULT_COST_R = env_float("PAPER_COST_R", 0.06)              # komisyon+funding+slipaj (R)
COST_PER_TRADE_R = DEFAULT_COST_R   # backtest ile AYNI maliyet (tek kaynak)
DEFAULT_META_THRESHOLD = env_float("PAPER_META_THRESHOLD", 0.60)

# Model üst üste kaybederse/hesap erirse sistem KENDİNİ durdurur; kör devam yok.
BREAKER_DD_LIMIT = env_float("BREAKER_DD_LIMIT", 0.25)        # tepeden -%25 → DUR
COOLDOWN_LOSSES = env_int("COOLDOWN_LOSSES", 5)               # ardışık kayıp → soğuma
COOLDOWN_EXIT_WINS = env_int("COOLDOWN_EXIT_WINS", 2)         # soğumadan çıkış
COOLDOWN_RISK_SCALE = env_float("COOLDOWN_RISK_SCALE", 0.5)   # soğumada risk çarpanı


# ---------------------------------------------------------------------------
# 10. META-MODEL + EĞİTİM (şampiyon–meydan okuyan)
# ---------------------------------------------------------------------------
MIN_SAMPLES = env_int("META_MIN_SAMPLES", 100)          # altında eğitim reddedilir
DEFAULT_THRESHOLD = env_float("META_THRESHOLD", 0.60)   # işlem onay eşiği
TRAIN_SPLIT = env_float("META_TRAIN_SPLIT", 0.70)       # ZAMAN SIRALI %70/%30

# Terfi eşikleri — meydan okuyan bunları geçmeden şampiyon olamaz
MIN_AUC_GAIN = env_float("TRAIN_MIN_AUC_GAIN", 0.01)
MIN_ABS_AUC = env_float("TRAIN_MIN_ABS_AUC", 0.50)
MIN_NEW_SAMPLES = env_int("TRAIN_MIN_NEW_SAMPLES", 30)

# Backfill (tarihsel örnek üretimi) birincil kural parametreleri
BACKFILL_VOTE_THRESHOLD = env_float("BACKFILL_VOTE_THRESHOLD", 0.35)  # |oy| eşiği
BACKFILL_MIN_ADX = env_float("BACKFILL_MIN_ADX", 18.0)                # chop filtresi
BACKFILL_MIN_GAP_BARS = env_int("BACKFILL_MIN_GAP_BARS", 6)           # örtüşme azaltma
# Canlı veri yoksa kullanılan geçmiş pencere uzunlukları (bar)
BACKFILL_KLINE_LIMIT_4H = env_int("BACKFILL_KLINE_LIMIT_4H", 1000)
BACKFILL_KLINE_LIMIT_1D = env_int("BACKFILL_KLINE_LIMIT_1D", 500)


# ---------------------------------------------------------------------------
# 11. SEANS / LİKİDİTE (nedensel, kanıtlanmış zayıf pencere)
# ---------------------------------------------------------------------------
LOW_LIQUIDITY_HOUR_START = env_int("LOW_LIQUIDITY_HOUR_START", 0)   # dahil
LOW_LIQUIDITY_HOUR_END = env_int("LOW_LIQUIDITY_HOUR_END", 6)       # hariç
LOW_LIQUIDITY_HOURS = frozenset(range(LOW_LIQUIDITY_HOUR_START, LOW_LIQUIDITY_HOUR_END))

SESSION_ASIA_HOURS = (env_int("SESSION_ASIA_START", 0), env_int("SESSION_ASIA_END", 8))
SESSION_EUROPE_HOURS = (env_int("SESSION_EUROPE_START", 8), env_int("SESSION_EUROPE_END", 13))
SESSION_US_HOURS = (env_int("SESSION_US_START", 13), env_int("SESSION_US_END", 21))


# ---------------------------------------------------------------------------
# 12. ACİL HABER ALARMI (bedava tarama katmanı)
# ---------------------------------------------------------------------------
# Kriz sinyali kelimeleri (başlıkta geçerse şüphe). Türkçe+İngilizce, küçük harf.
CRISIS_KEYWORDS = env_list("CRISIS_KEYWORDS", [
    # Jeopolitik
    "war", "savaş", "invasion", "attack", "saldırı", "missile", "nuclear",
    "conflict", "military", "sanction", "yaptırım",
    # Borsa/protokol felaketi
    "hack", "exploit", "stolen", "çalındı", "breach", "drain", "rug",
    "insolvent", "bankrupt", "iflas", "collapse", "çöküş", "halt", "freeze",
    "liquidation", "likidasyon", "depeg", "exit scam",
    # Regülasyon/yasak
    "ban", "yasak", "lawsuit", "dava", "sec charges", "indictment",
    "crackdown", "shutdown", "delisting", "delist",
    # Makro şok
    "emergency", "acil", "crash", "plunge", "çakıldı", "black swan",
    "default", "contagion", "bailout",
])

# Çok güçlü tekil işaretler (tek başına yüksek alarm)
HIGH_SEVERITY_KEYWORDS = env_list("HIGH_SEVERITY_KEYWORDS", [
    "war", "savaş", "hack", "nuclear", "collapse", "çöküş",
    "bankrupt", "iflas", "black swan", "depeg",
])

SHOCK_LOOKBACK_BARS = env_int("SHOCK_LOOKBACK_BARS", 3)      # kaç mum geriye
SHOCK_THRESHOLD_PCT = env_float("SHOCK_THRESHOLD_PCT", 4.0)  # şok eşiği (%)
SHOCK_STRONG_PCT = env_float("SHOCK_STRONG_PCT", 6.0)        # güçlü şok (%)
ALERT_MEDIUM_MIN_KEYWORDS = env_int("ALERT_MEDIUM_MIN_KEYWORDS", 2)
ALERT_HIGH_MIN_KEYWORDS = env_int("ALERT_HIGH_MIN_KEYWORDS", 3)
ALERT_TITLE_LIMIT = env_int("ALERT_TITLE_LIMIT", 5)
ALERT_SUMMARY_KEYWORD_LIMIT = env_int("ALERT_SUMMARY_KEYWORD_LIMIT", 3)
ALERT_KLINE_INTERVAL = env_str("ALERT_KLINE_INTERVAL", "15m")  # şok taraması dilimi


# ---------------------------------------------------------------------------
# 13. DIŞ SERVİSLER (URL / timeout / başlık)
# ---------------------------------------------------------------------------
FEAR_GREED_API = env_str("FEAR_GREED_API", "https://api.alternative.me/fng/")
CRYPTOPANIC_API = env_str("CRYPTOPANIC_API", "https://cryptopanic.com/api/v1/posts/")
NEWSAPI_URL = env_str("NEWSAPI_URL", "https://newsapi.org/v2/everything")
YAHOO_CHART_URL = env_str("YAHOO_CHART_URL", "https://query1.finance.yahoo.com/v8/finance/chart")
BINANCE_VISION_URL = env_str(
    "BINANCE_VISION_URL",
    "https://data.binance.vision/data/spot/monthly/klines/{sym}/{iv}/{sym}-{iv}-{ym}.zip",
)
# Funding rate arşivi (futures um) — "kalabalık nerede yığılmış" verisi
BINANCE_VISION_FUNDING_URL = env_str(
    "BINANCE_VISION_FUNDING_URL",
    "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
    "{sym}/{sym}-fundingRate-{ym}.zip",
)
# Binance tek çağrıda en fazla bu kadar mum döner (API sözleşmesi)
BINANCE_MAX_KLINES_PER_CALL = env_int("BINANCE_MAX_KLINES_PER_CALL", 1500)

HTTP_TIMEOUT_SEC = env_float("HTTP_TIMEOUT_SEC", 10.0)          # haber/F&G
YAHOO_TIMEOUT_SEC = env_float("YAHOO_TIMEOUT_SEC", 15.0)        # Yahoo intermarket
HISTORY_TIMEOUT_SEC = env_float("HISTORY_TIMEOUT_SEC", 30.0)    # arşiv indirme
HTTP_USER_AGENT = env_str("HTTP_USER_AGENT", "Mozilla/5.0")

NEWS_QUERY = env_str("NEWS_QUERY", "bitcoin+crypto")
NEWS_LANGUAGE = env_str("NEWS_LANGUAGE", "en")
NEWS_ITEM_LIMIT = env_int("NEWS_ITEM_LIMIT", 10)     # CryptoPanic sonuç sayısı
NEWSAPI_PAGE_SIZE = env_int("NEWSAPI_PAGE_SIZE", 5)
NEWSAPI_CURRENCY = env_str("NEWSAPI_CURRENCY", "BTC")

# İntermarket analizi: takip edilen piyasalar (key → ticker, ad, beklenen ilişki)
INTERMARKET_TICKERS = env_json_dict("INTERMARKET_TICKERS", {
    "dxy": ["DX-Y.NYB", "Dolar Endeksi", "negatif"],
    "vix": ["^VIX", "Volatilite (VIX)", "negatif"],
    "gold": ["GC=F", "Altın", "pozitif"],
    "sp500": ["^GSPC", "S&P 500", "pozitif"],
    "ndx": ["^IXIC", "Nasdaq", "pozitif"],
})

# Makro özet için (fiyat seviyesi) takip edilenler
MACRO_TICKERS = env_json_dict("MACRO_TICKERS", {
    "dxy": "DX-Y.NYB",
    "vix": "^VIX",
    "gold": "GC=F",
    "sp500": "^GSPC",
})

CORRELATION_RANGE = env_str("CORRELATION_RANGE", "3mo")     # Yahoo aralık
CORRELATION_MIN_POINTS = env_int("CORRELATION_MIN_POINTS", 20)  # min ortak gün

# Tarihsel arşiv indirme başlangıcı (Binance BTCUSDT spot başlangıcı)
HISTORY_START_YEAR = env_int("HISTORY_START_YEAR", 2017)
HISTORY_START_MONTH = env_int("HISTORY_START_MONTH", 8)
# Funding arşivi başlangıcı (futures um)
FUNDING_START_YEAR = env_int("FUNDING_START_YEAR", 2019)
FUNDING_START_MONTH = env_int("FUNDING_START_MONTH", 9)

# Meta depo listeleme tavanı (GET /api/meta/signals)
SIGNALS_RECENT_MAX = env_int("SIGNALS_RECENT_MAX", 500)


# ---------------------------------------------------------------------------
# 14. GÖSTERGE PARAMETRELERİ (technical.py)
# ---------------------------------------------------------------------------
# DİKKAT: feature_service.py bu pencerelerin BİREBİR aynısını kullanır ve
# eğitilmiş meta-model bu tanıma bağlıdır. Burada değişiklik yaparsanız modeli
# yeniden eğitmeniz gerekir (POST /api/meta/train).
EMA_FAST, EMA_MID, EMA_SLOW = env_int("EMA_FAST", 20), env_int("EMA_MID", 50), env_int("EMA_SLOW", 200)
EMA_WINDOWS = [EMA_FAST, EMA_MID, EMA_SLOW]

RSI_PERIOD = env_int("RSI_PERIOD", 14)
MACD_FAST = env_int("MACD_FAST", 12)
MACD_SLOW = env_int("MACD_SLOW", 26)
MACD_SIGNAL = env_int("MACD_SIGNAL", 9)
ATR_PERIOD = env_int("ATR_PERIOD", 14)
ADX_PERIOD = env_int("ADX_PERIOD", 14)
BB_PERIOD = env_int("BB_PERIOD", 20)
BB_DEV = env_float("BB_DEV", 2.0)
STOCH_RSI_PERIOD = env_int("STOCH_RSI_PERIOD", 14)
STOCH_RSI_SMOOTH1 = env_int("STOCH_RSI_SMOOTH1", 3)
STOCH_RSI_SMOOTH2 = env_int("STOCH_RSI_SMOOTH2", 3)
VWAP_PERIOD = env_int("VWAP_PERIOD", 50)
VOLUME_AVG_PERIOD = env_int("VOLUME_AVG_PERIOD", 20)

# SMC / yapı pencereleri
DIVERGENCE_LOOKBACK = env_int("DIVERGENCE_LOOKBACK", 60)
DIVERGENCE_SWING = env_int("DIVERGENCE_SWING", 3)
PREMIUM_DISCOUNT_LOOKBACK = env_int("PREMIUM_DISCOUNT_LOOKBACK", 100)
SR_LOOKBACK = env_int("SR_LOOKBACK", 150)
SR_SWING = env_int("SR_SWING", 5)
SR_CLUSTER_PCT = env_float("SR_CLUSTER_PCT", 0.005)
OB_LOOKBACK = env_int("OB_LOOKBACK", 50)
FVG_LOOKBACK = env_int("FVG_LOOKBACK", 30)
LIQUIDITY_LOOKBACK = env_int("LIQUIDITY_LOOKBACK", 50)
LIQUIDITY_SWING_PERIOD = env_int("LIQUIDITY_SWING_PERIOD", 5)
STRUCTURE_LOOKBACK = env_int("STRUCTURE_LOOKBACK", 50)

# Yön endeksi: 50 nötr; güç = |endeks-50|*2, tavan bu değer
NEUTRAL_INDEX = env_float("NEUTRAL_INDEX", 50.0)


# ---------------------------------------------------------------------------
# 15. TAHMİN MOTORU AĞIRLIKLARI (forecast_service.py)
# ---------------------------------------------------------------------------
# Trend/yapı göstergeleri momentum osilatörlerinden ağır
FORECAST_WEIGHTS = env_json_dict("FORECAST_WEIGHTS", {
    "ema_dizilimi": 2.0,
    "macd": 1.5,
    "adx_yon": 1.5,
    "yapi": 1.5,        # BOS / CHoCH
    "divergence": 1.5,
    "rsi": 1.0,
    "obv": 1.0,
    "bollinger": 0.5,
    "stoch_rsi": 0.5,
    "vwap": 0.5,
    "premium_discount": 0.5,
})

# Zaman dilimi harmanları (vade → {tf: ağırlık})
FORECAST_HORIZON_BLEND = env_json_dict("FORECAST_HORIZON_BLEND", {
    "kisa": {"15m": 0.4, "1h": 0.6},
    "orta": {"1h": 0.4, "4h": 0.6},
    "uzun": {"4h": 0.3, "1d": 0.7},
})

# Genel endeks: uzun vade en ağır (rejim belirleyici)
FORECAST_OVERALL_BLEND = env_json_dict("FORECAST_OVERALL_BLEND", {
    "kisa": 0.20, "orta": 0.35, "uzun": 0.45,
})


# ---------------------------------------------------------------------------
# 16. STOKASTİK MOTOR
# ---------------------------------------------------------------------------
STOCHASTIC_DAYS_PER_YEAR = env_int("STOCHASTIC_DAYS_PER_YEAR", 365)  # kripto 7/24
FORECAST_HORIZON_HOURS = env_int("FORECAST_HORIZON_HOURS", 24)       # 24s aralık


# ---------------------------------------------------------------------------
# 17. TANI (opsiyonel) — eksik ayar varsa günlüğe tek satır
# ---------------------------------------------------------------------------
if os.getenv("CONFIG_DIAGNOSTICS", "").lower() in _TRUE:
    _eksik = missing_secrets()
    print(f"[config] .env: {ENV_PATH} | eksik/yer tutucu: {_eksik or 'yok'}")
