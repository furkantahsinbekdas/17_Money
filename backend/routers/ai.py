import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException
from services.binance_service import BinanceService
from services.technical import TechnicalService
from services.news_service import NewsService
from services.claude_service import ClaudeService
from services.claude_cli import ClaudeCLIError
from services import stochastic_service
from services import signal_decode_service

import config
import prompts

_BARS_PER_DAY = config.BARS_PER_DAY


def _science_context(symbol: str, interval: str) -> dict | None:
    """
    Stokastik matematik + sinyal çözme motorlarını çalıştırıp sinyale
    beslenecek kompakt bilimsel bağlamı döndürür. İki bölüm:
    - stokastik: Hurst, kuyruk, GARCH vol, rejim, difüzyon
    - cozme: öngörülebilirlik (entropi), yön hafızası, baskın döngü
    Hata sinyali bozmaz (None döner)."""
    try:
        df = binance.get_klines(symbol, interval, config.SCIENCE_KLINE_LIMIT)
        bpd = _BARS_PER_DAY.get(interval, 24)
        full = stochastic_service.full_analysis(df, horizon_bars=max(int(bpd), 1), bars_per_day=bpd)
        decode = signal_decode_service.full_decode(df["close"])
        out = stochastic_service.compact_for_signal(full)
        out["cozme"] = signal_decode_service.compact_for_signal(decode)
        # Seans bağlamı (likidite-temelli, nedensel): derin Asya gecesi düşük
        # güvenilirlik. Hava durumu DEĞİL — kanıtlanmış likidite etkisi.
        from services import session_filter
        from datetime import datetime
        out["seans"] = session_filter.session_context(datetime.utcnow())
        return out
    except Exception:
        return None
from services.forecast_service import ForecastService
from services.feature_service import features_from_analyses
from services.signal_store import SignalStore
from services.meta_model import meta_model
from models.signal import ChatRequest

router = APIRouter(prefix="/api/ai", tags=["ai"])

binance = BinanceService()
technical = TechnicalService()
news_svc = NewsService()
claude = ClaudeService()
forecast_svc = ForecastService()
signal_store = SignalStore()

# Analiz hiyerarşisi config.py'de (MTF_INTERVALS ile ezilebilir)
MTF_INTERVALS = config.MTF_INTERVALS


def _check_claude_key():
    if not claude.available:
        raise HTTPException(
            status_code=503,
            detail="Claude erişimi yok: ya config/.env'e CLAUDE_API_KEY ekleyin, "
                   "ya da bu makinede Claude Code CLI kurulu ve giriş yapılmış olsun "
                   "(terminalde 'claude' çalıştırıp /login).",
        )


def _collect_mtf(symbol: str, primary_interval: str) -> tuple[dict, dict, dict]:
    """
    Çoklu zaman dilimi teknik analizi toplar.
    Birincil zaman dilimi tam detay, diğerleri kompakt özet olarak döner.
    full_analyses: tüm TF'lerin tam analizi (meta-model özellik çıkarımı için).
    """
    mtf = {}
    primary_full = None
    full_analyses = {}
    intervals = MTF_INTERVALS if primary_interval in MTF_INTERVALS else MTF_INTERVALS + [primary_interval]

    for interval in intervals:
        df = binance.get_klines(symbol, interval, config.KLINE_LIMIT)
        analysis = technical.calculate_all(df)
        full_analyses[interval] = analysis
        if interval == primary_interval:
            primary_full = analysis
            mtf[interval] = analysis  # birincil TF tam detay
        else:
            mtf[interval] = technical.compact_summary(analysis)

    return mtf, primary_full, full_analyses


def _log_and_score(signal: dict, full_analyses: dict, derivatives: dict,
                   market_context: dict, symbol: str, interval: str) -> None:
    """
    Sprint 4: sinyali özellik vektörüyle loglar ve (model eğitildiyse)
    meta-model kazanma olasılığını sinyale ekler. Hata sinyali bozmaz.
    """
    now = datetime.utcnow()
    direction = signal.get("sinyal", "BEKLE")
    features = features_from_analyses(
        full_analyses, derivatives, market_context,
        direction, signal.get("guven_skoru"), now,
    )

    meta = meta_model.score(features) if direction in ("LONG", "SHORT") else None

    primary = full_analyses.get(interval) or {}
    log_id = signal_store.log_signal(
        created_at=now,
        source="live",
        symbol=symbol,
        interval=interval,
        direction=direction,
        features=features,
        confidence=signal.get("guven_skoru"),
        entry_price=primary.get("current_price"),
        atr=(primary.get("atr") or {}).get("atr"),
        signal_json=signal,
        meta_prob=meta["olasilik"] if meta else None,
    )

    signal["log_id"] = log_id
    if direction in ("LONG", "SHORT"):
        signal["meta_filtre"] = meta or {
            "durum": "model_henuz_egitilmedi",
            "aciklama": "Meta-model filtre için önce POST /api/meta/backfill "
                        "ve POST /api/meta/train çalıştırın.",
        }


def _collect_derivatives(symbol: str) -> dict:
    """Funding, açık pozisyon ve orderbook dengesizliği."""
    funding = binance.get_funding_rate(symbol)
    oi = binance.get_open_interest(symbol)
    book = binance.get_orderbook(symbol, config.ORDERBOOK_LIMIT)

    bid_qty = sum(q for _, q in book.get("bids", []))
    ask_qty = sum(q for _, q in book.get("asks", []))
    imbalance = round(bid_qty / ask_qty, 2) if ask_qty else None

    return {
        "funding_rate": funding.get("funding_rate", 0),
        "open_interest": oi.get("open_interest", 0),
        "orderbook_bid_ask_orani": imbalance,
    }


async def _collect_context(symbol: str, primary: dict, with_intermarket: bool = True) -> dict:
    """
    Makro + sentiment + INTERMARKET bağlamı.
    with_intermarket=True → intermarket korelasyon (DXY/VIX/S&P/Altın vs BTC) da
    eklenir — Claude'un karar bağlamına bağlı (modele DEĞİL, bilinçli: funding/
    stokastik denemesi AUC'yi düşürmüştü, bu tür bağlamsal veri model için
    overfitting riski taşır ama Claude için değerli yorum malzemesi).
    """
    macro = await news_svc.get_macro_data()
    fg = await news_svc.get_fear_greed()
    ctx = {
        **macro,
        "fear_greed": f"{fg['value']} ({fg['label']})",
        "btc_price": primary["current_price"],
        "trend": primary["trend"],
    }
    if with_intermarket:
        try:
            df_daily = await asyncio.to_thread(binance.get_klines, symbol, "1d", config.INTERMARKET_KLINE_LIMIT)
            inter = await news_svc.get_intermarket(df_daily["close"])
            ctx["intermarket"] = inter
        except Exception:
            pass
    return ctx


@router.get("/alert")
async def market_alert(symbol: str = config.SYMBOL,
                       ask_claude: bool = False):
    """
    Olay-tetikli acil haber alarmı (BEDAVA tarama + opsiyonel Claude).

    1. Haber başlıkları + fiyat şoku BEDAVA taranır (alert_service, Claude YOK).
    2. ask_claude=True VE şiddetli olay varsa SADECE o zaman Claude'a sorulur —
       kredi olaya bağlanır, takvime değil. Sakin günde sıfır Claude maliyeti.
    """
    from services import alert_service

    news = await news_svc.get_crypto_news()
    klines = None
    try:
        klines = await asyncio.to_thread(binance.get_klines, symbol, config.ALERT_KLINE_INTERVAL,
                               config.SHOCK_KLINE_LIMIT)
    except Exception:
        pass

    degerlendirme = alert_service.evaluate(news, klines)
    sonuc = {"alarm": degerlendirme}

    # Claude SADECE gerçek kriz işareti varsa ve istenirse uyandırılır
    if ask_claude and degerlendirme["claude_uyandir"] and claude.available:
        haberler = degerlendirme["haber_alarmi"]["eslesen_basliklar"]
        soru = prompts.CRISIS_QUESTION.format(
            basliklar="\n".join(f"- {h}" for h in haberler))
        try:
            if claude.backend == "cli":
                yanit = await asyncio.to_thread(claude.cli.complete, prompt=soru)
            else:
                yanit = await asyncio.to_thread(claude.chat, [], soru, {})
            sonuc["claude_degerlendirmesi"] = yanit
        except Exception as e:
            sonuc["claude_hata"] = str(e)

    return sonuc


@router.get("/status")
async def ai_status():
    """
    Claude erişim durumu: aktif sağlayıcı, CLI giriş bilgisi ve sohbette
    seçilebilir modeller. Frontend Terminal bu endpoint'le durum çizer.
    """
    from config import ALLOWED_CHAT_MODELS

    auth = None
    if claude.backend == "cli":
        auth = await asyncio.to_thread(claude.cli.auth_status)

    return {
        "saglayici": claude.backend,  # "api" | "cli" | "yok"
        "model": claude.cli.model if claude.backend == "cli" else claude.model,
        "modeller": ALLOWED_CHAT_MODELS,
        "giris": {
            "girisli": bool((auth or {}).get("loggedIn")),
            "email": (auth or {}).get("email"),
            "abonelik": (auth or {}).get("subscriptionType"),
            "yontem": (auth or {}).get("authMethod"),
        } if auth is not None else None,
        "aciklama": {
            "api": "Anthropic API (CLAUDE_API_KEY)",
            "cli": "Claude Code CLI (abonelik üzerinden, API key'siz)",
            "yok": "Claude erişimi yok — CLAUDE_API_KEY ekleyin veya Claude Code CLI ile giriş yapın",
        }[claude.backend],
    }


@router.post("/login")
async def ai_login(body: dict | None = None):
    """
    Kullanıcının masaüstünde `claude auth login` penceresi açar (tarayıcı
    ile hesap seçimi). body.email verilirse giriş sayfasında ön-doldurulur.
    Durum GET /api/ai/status ile takip edilir.
    """
    email = (body or {}).get("email")
    try:
        await asyncio.to_thread(claude.cli.launch_login, email)
        return {
            "baslatildi": True,
            "aciklama": (
                "Giriş başlatıldı — şu adımları izleyin:\n"
                "1) Açılan KONSOL penceresine bakın; giriş yöntemi sorulursa "
                "'Claude account with subscription' seçin.\n"
                f"2) Tarayıcıda {email or 'abonelikli hesabınızla'} oturum açın — "
                "yanlış hesap görünürse sayfadan hesap değiştirin.\n"
                "3) 'Authorize' (Yetkilendir) düğmesine basın ve konsol 'Login successful' "
                "diyene kadar pencereyi kapatmayın.\n"
                "Giriş algılandığında burada bildireceğim."
            ),
        }
    except ClaudeCLIError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/signal")
async def get_signal(symbol: str = config.SYMBOL,
                     interval: str = config.DEFAULT_INTERVAL,
                     deep: bool = False, model: str | None = None):
    """
    Claude ile tam piyasa analizi ve trading sinyali.
    deep=true → önce web araştırma modu çalışır, bulgular sinyale beslenir.
    model → ALLOWED_CHAT_MODELS içinden (None → varsayılan Fable 5).
    """
    _check_claude_key()
    try:
        mtf, primary, full_analyses = _collect_mtf(symbol, interval)
        derivatives = _collect_derivatives(symbol)
        market_context = await _collect_context(symbol, primary)
        market_context["funding_rate"] = derivatives["funding_rate"]
        # Tahmin tablosu (forecast) — Claude'un karar bağlamına bağlı (modele değil)
        try:
            market_context["tahmin_tablosu"] = forecast_svc.mtf_forecast(full_analyses)
        except Exception:
            pass
        crypto_news = await news_svc.get_crypto_news()

        research = None
        if deep:
            research = await asyncio.to_thread(claude.deep_research, market_context, None, model)

        stochastic = await asyncio.to_thread(_science_context, symbol, interval)

        signal = await asyncio.to_thread(
            claude.analyze_market,
            mtf_data=mtf,
            news_data=crypto_news,
            market_context=market_context,
            derivatives=derivatives,
            research_notes=research["rapor"] if research else None,
            model=model,
            stochastic=stochastic,
        )
        if stochastic:
            signal["stokastik"] = stochastic
        signal["symbol"] = symbol
        signal["interval"] = interval
        signal["market_context"] = market_context
        signal["derivatives"] = derivatives
        if research:
            signal["arastirma"] = research

        # Sprint 4: sinyali logla + meta-model filtresinden geçir
        try:
            _log_and_score(signal, full_analyses, derivatives, market_context, symbol, interval)
        except Exception as log_err:
            signal.setdefault("uyarilar", []).append(f"Meta loglama hatası: {log_err}")

        return signal
    except HTTPException:
        raise
    except ClaudeCLIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forecast")
async def get_ai_forecast(symbol: str = config.SYMBOL, model: str | None = None):
    """
    AI Tahmin (VantagePoint tarzı) — deterministik tahmin motoru çıktısını
    uzman Claude yorumuyla sentezler: yön olasılığı, vade görünümü,
    intermarket etkisi, kilit seviyeler ve riskler.
    model → ALLOWED_CHAT_MODELS içinden (None → varsayılan Fable 5).
    """
    _check_claude_key()
    try:
        analyses = {
            iv: technical.calculate_all(binance.get_klines(symbol, iv, config.KLINE_LIMIT))
            for iv in MTF_INTERVALS
        }
        deterministic = forecast_svc.mtf_forecast(analyses)

        mtf_compact = {iv: technical.compact_summary(a) for iv, a in analyses.items()}
        df_1d = binance.get_klines(symbol, "1d", config.DAILY_KLINE_LIMIT)
        intermarket = await news_svc.get_intermarket(df_1d["close"])
        derivatives = _collect_derivatives(symbol)
        market_context = await _collect_context(symbol, analyses[config.DEFAULT_INTERVAL])
        market_context["funding_rate"] = derivatives["funding_rate"]

        stochastic = await asyncio.to_thread(_science_context, symbol, config.DEFAULT_INTERVAL)

        ai_fc = await asyncio.to_thread(
            claude.ai_forecast,
            deterministic_forecast=deterministic,
            mtf_data=mtf_compact,
            intermarket=intermarket,
            market_context=market_context,
            model=model,
            stochastic=stochastic,
        )

        return {
            "symbol": symbol,
            "deterministik": deterministic,
            "ai_tahmin": ai_fc,
            "intermarket": intermarket,
            "stokastik": stochastic,
        }
    except HTTPException:
        raise
    except ClaudeCLIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/research")
async def get_research(symbol: str = config.SYMBOL, focus: str | None = None):
    """
    Bağımsız derin araştırma modu — web araması ile güncel piyasa istihbaratı.
    focus parametresiyle özel konu araştırılabilir.
    """
    _check_claude_key()
    try:
        df = binance.get_klines(symbol, config.DEFAULT_INTERVAL, config.KLINE_LIMIT)
        tech = technical.calculate_all(df)
        fg = await news_svc.get_fear_greed()

        market_context = {
            "btc_price": tech["current_price"],
            "trend": tech["trend"],
            "fear_greed": f"{fg['value']} ({fg['label']})",
        }

        research = await asyncio.to_thread(claude.deep_research, market_context, focus=focus)
        return {"symbol": symbol, **research, "market_context": market_context}
    except HTTPException:
        raise
    except ClaudeCLIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/reset")
async def chat_reset():
    """Kalıcı sohbet oturumunu sıfırlar — sonraki mesaj temiz başlar."""
    await asyncio.to_thread(claude.reset_chat)
    return {"sifirlandi": True}


@router.post("/chat")
async def chat(request: ChatRequest):
    """Terminal sohbet modu — uzman trading partneri, gerektiğinde web araştırması yapar."""
    _check_claude_key()
    try:
        ticker = binance.get_ticker(config.SYMBOL)
        fg = await news_svc.get_fear_greed()
        df = binance.get_klines(config.SYMBOL, config.DEFAULT_INTERVAL, config.KLINE_LIMIT)
        tech = technical.calculate_all(df)
        derivatives = _collect_derivatives(config.SYMBOL)

        market_context = {
            "btc_price": ticker.get("price"),
            "fear_greed": f"{fg['value']} ({fg['label']})",
            "trend": tech["trend"],
            "rsi": tech["rsi"],
            "adx": (tech.get("adx") or {}).get("adx"),
            "atr_yuzde": (tech.get("atr") or {}).get("atr_yuzde"),
            "funding_rate": derivatives["funding_rate"],
            "open_interest": derivatives["open_interest"],
        }

        history = [{"role": m.role, "content": m.content} for m in request.history]
        response = await asyncio.to_thread(
            claude.chat, history, request.message, market_context, request.model,
        )

        return {"response": response, "market_context": market_context}
    except HTTPException:
        raise
    except ClaudeCLIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
