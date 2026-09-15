import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import config
from routers import market, analysis, ai, meta, paper
from services.binance_service import BinanceService
from services.technical import TechnicalService
from services.signal_store import SignalStore
from services.paper_account import PaperAccount

binance_svc = BinanceService()
technical_svc = TechnicalService()
signal_store = SignalStore()
paper_account = PaperAccount()

# Aktif WebSocket bağlantılarını tutan küme
active_connections: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Arka plan döngüleri:
    - broadcast_loop: piyasa yayını (1 dk)
    - resolve_loop: açık sinyal sonuç etiketleme (10 dk)
    - collect_loop: AI'sız otomatik veri toplama (1 saat) — kota yakmaz
    - challenge_loop: şampiyon-meydan okuyan eğitim turu (6 saat)
    - alert_loop: olay-tetikli acil haber taraması (15 dk) — BEDAVA, Claude yakmaz
    """
    tasks = [
        asyncio.create_task(broadcast_loop()),
        asyncio.create_task(resolve_loop()),
        asyncio.create_task(collect_loop()),
        asyncio.create_task(challenge_loop()),
        asyncio.create_task(alert_loop()),
        asyncio.create_task(startup_recovery()),  # Görev 3: açılışta toparlanma
    ]
    yield
    for t in tasks:
        t.cancel()


async def startup_recovery():
    """
    Açılışta toparlanma (Görev 3): bilgisayar kapalı kaldıysa, açılır açılmaz
    biriken işi telafi et — açık sinyalleri çöz + eğitim kontrolü yap. Böylece
    "kaçırılan" eğitim hemen yakalanır, sürekli açık tutma zorunluluğu azalır.
    """
    await asyncio.sleep(config.STARTUP_RECOVERY_DELAY_SEC)  # backend tam otursun
    try:
        # 1) Kapalıyken sonuçlanmış açık sinyalleri çöz
        result = await asyncio.to_thread(signal_store.resolve_open_signals, binance_svc)
        if result.get("resolved"):
            print(f"[startup] {result['resolved']} biriken sinyal çözüldü (kapalı süre telafisi)")
            psync = await asyncio.to_thread(paper_account.sync_from_store, signal_store)
            if psync.get("yeni_islenen"):
                print(f"[startup] {psync['yeni_islenen']} işlem paper hesaba geçti")
        # 2) Eğitim gerekiyorsa hemen dene (6 saat bekleme)
        from services.trainer_service import run_challenge
        ch = await asyncio.to_thread(run_challenge, signal_store)
        if ch.get("terfi"):
            print(f"[startup] ✅ açılışta otomatik terfi: {ch.get('neden')}")
    except Exception as e:
        print(f"[startup_recovery] hata: {e}")


app = FastAPI(
    title=config.APP_TITLE,
    description=config.APP_DESCRIPTION,
    version=config.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(analysis.router)
app.include_router(ai.router)
app.include_router(meta.router)
app.include_router(paper.router)


@app.get("/")
async def root():
    return {"status": "online", "service": "17Money Algorithm", "time": datetime.utcnow().isoformat()}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """
    WebSocket endpoint — her 60 saniyede bir BTC/USDT teknik veri yayınlar.
    Frontend bu endpoint'e bağlanarak gerçek zamanlı güncellemeler alır.
    """
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)


async def broadcast_loop():
    """Her dakika tüm bağlı istemcilere piyasa verisi gönderir."""
    while True:
        try:
            if active_connections:
                df = binance_svc.get_klines(config.SYMBOL, config.DEFAULT_INTERVAL,
                                            config.BROADCAST_KLINE_LIMIT)
                tech = technical_svc.calculate_all(df)
                ticker = binance_svc.get_ticker(config.SYMBOL)

                payload = json.dumps({
                    "type": "market_update",
                    "symbol": config.SYMBOL,
                    "technical": tech,
                    "ticker": ticker,
                    "timestamp": datetime.utcnow().isoformat(),
                })

                dead = set()
                for ws in active_connections:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)

                active_connections.difference_update(dead)

        except Exception as e:
            print(f"[broadcast_loop] hata: {e}")

        await asyncio.sleep(config.BROADCAST_INTERVAL_SEC)


async def resolve_loop():
    """
    Sprint 4: açık canlı sinyallerin triple-barrier sonuçlarını her 10 dakikada
    bir çözümler — kazanan/kaybeden etiketleri meta-model eğitim verisine döner.
    """
    while True:
        await asyncio.sleep(config.RESOLVE_INTERVAL_SEC)
        try:
            result = await asyncio.to_thread(signal_store.resolve_open_signals, binance_svc)
            if result.get("resolved"):
                print(f"[resolve_loop] {result['resolved']} sinyal çözüldü, "
                      f"{result['still_open']} hâlâ açık")
                # Çözülen sinyalleri paper hesaba işle (Aşama 5: canlı kanıt)
                psync = await asyncio.to_thread(paper_account.sync_from_store, signal_store)
                if psync.get("yeni_islenen"):
                    print(f"[paper] {psync['yeni_islenen']} yeni işlem hesaba geçti")
        except Exception as e:
            print(f"[resolve_loop] hata: {e}")


# Son alarm durumu (frontend okur) — bellekte tutulur
_last_alert: dict = {"ozet": "Henüz tarama yapılmadı", "claude_uyandir": False}


def get_last_alert() -> dict:
    return _last_alert


async def alert_loop():
    """
    Olay-tetikli acil haber taraması — her 15 dk, BEDAVA (Claude yakmaz).
    Sadece YEREL tarama: kriz kelimesi + fiyat şoku. Şiddetli olay yakalarsa
    _last_alert'e işaretler; Claude çağrısı YAPMAZ (o, kullanıcı/frontend tetiğiyle
    /api/ai/alert?ask_claude=true ile yapılır — kredi kontrolü kullanıcıda).
    """
    global _last_alert
    from services import alert_service
    from services.news_service import NewsService
    nsvc = NewsService()
    await asyncio.sleep(config.ALERT_STARTUP_DELAY_SEC)  # başlangıçta otursun
    while True:
        try:
            news = await nsvc.get_crypto_news()
            klines = None
            try:
                klines = await asyncio.to_thread(binance_svc.get_klines, config.SYMBOL, config.ALERT_KLINE_INTERVAL,
                               config.SHOCK_KLINE_LIMIT)
            except Exception:
                pass
            _last_alert = alert_service.evaluate(news, klines)
            if _last_alert.get("claude_uyandir"):
                print(f"[alert] ⚠ ACİL SİNYAL: {_last_alert['ozet']}")
        except Exception as e:
            print(f"[alert_loop] hata: {e}")
        await asyncio.sleep(config.ALERT_INTERVAL_SEC)  # 15 dk


async def collect_loop():
    """
    Saatlik AI'SIZ veri toplama: deterministik motor tek bir sinyal üretip
    loglar (Claude kotası YAKILMAZ). resolve_loop sonradan etiketler. Böylece
    meydan-okuyan model için sürekli taze, gerçek-zamanlı veri akar.
    """
    await asyncio.sleep(config.COLLECT_STARTUP_DELAY_SEC)  # başlangıçta backend otursun
    while True:
        try:
            n = await asyncio.to_thread(_collect_one_signal)
            if n:
                print(f"[collect_loop] otomatik sinyal loglandı (id={n})")
        except Exception as e:
            print(f"[collect_loop] hata: {e}")
        await asyncio.sleep(config.COLLECT_INTERVAL_SEC)  # saatte bir


async def challenge_loop():
    """
    Şampiyon-Meydan Okuyan turu — AKILLI tetikleme (Görev 3):
    Sabit 6 saat yerine her 1 saatte bir KONTROL eder ama run_challenge
    SADECE yeterli yeni veri (MIN_NEW_SAMPLES) birikince eğitir (trainer_service
    bunu içeride zaten kontrol eder, az veriyle boşuna işlemci yakmaz).
    Kendini eğitir ama kör pekiştirmez. "Elle eğit" gereksiz — bu otomatik.
    """
    await asyncio.sleep(config.CHALLENGE_STARTUP_DELAY_SEC)
    while True:
        try:
            from services.trainer_service import run_challenge
            result = await asyncio.to_thread(run_challenge, signal_store)
            if result.get("terfi"):
                print(f"[challenge_loop] ✅ OTOMATİK TERFİ: {result.get('neden')}")
            elif result.get("calisti"):
                print(f"[challenge_loop] {result.get('neden')}")
        except Exception as e:
            print(f"[challenge_loop] hata: {e}")
        await asyncio.sleep(config.CHALLENGE_CHECK_INTERVAL_SEC)  # 1 saatte bir KONTROL (eğitim sadece veri yeterse)


def _collect_one_signal(with_trace: bool = False,
                        primary_iv: str = config.DEFAULT_INTERVAL):
    """
    Deterministik motorla (Claude'suz) tek bir canlı sinyal üretip,
    triple-barrier bariyerleriyle loglar. forecast_service'in oyunu kullanır.

    primary_iv: işlemin temel zaman dilimi (15m/1h/4h/1d) — giriş/TP/SL/etiketleme
    bu dilime göre kurulur. MTF analizi (4 dilim birlikte = geniş pencere) HER
    durumda yapılır; primary_iv sadece hangi dilimin "ana" olduğunu belirler.

    with_trace=True → (sinyal_id, karar_izi) döndürür (Görev 4: şeffaflık).
    Aksi halde geriye uyumlu: sadece sinyal_id (veya None).
    """
    from services.forecast_service import ForecastService
    from services.feature_service import features_from_analyses
    from services import session_filter, decision_trace
    from services.backfill_service import _regime_barriers
    from services.meta_model import meta_model

    intervals = config.MTF_INTERVALS
    analyses = {iv: technical_svc.calculate_all(
        binance_svc.get_klines(config.SYMBOL, iv, config.KLINE_LIMIT))
                for iv in intervals}
    fc = ForecastService().mtf_forecast(analyses)

    yon = fc.get("yon")
    now = datetime.utcnow()
    session = session_filter.session_context(now)

    if yon not in ("yukarı", "aşağı"):
        # Yatay → sinyal yok (BEKLE). İz isteniyorsa BEKLE izi üret.
        if with_trace:
            trace = decision_trace.build_trace(
                direction=None, forecast=fc, score=None,
                regime_barriers=config.REGIME_BARRIERS_MILD, session=session,
                atr=None, entry=None)
            return None, trace, None
        return None
    direction = "LONG" if yon == "yukarı" else "SHORT"

    primary = analyses.get(primary_iv) or analyses[config.DEFAULT_INTERVAL]  # seçili dilim ana, yoksa 1h
    conf = abs(fc.get("yon_endeksi", 50) - 50) * 2  # 0-100
    features = features_from_analyses(
        analyses, None, None, direction, conf, now,
    )
    entry = primary.get("current_price")
    atr = (primary.get("atr") or {}).get("atr")
    adx = (primary.get("adx") or {}).get("adx")
    regime = _regime_barriers(float(adx) if adx is not None else None)

    sid = signal_store.log_signal(
        created_at=now, source="auto", symbol=config.SYMBOL, interval=primary_iv,
        direction=direction, features=features, confidence=conf,
        entry_price=entry, atr=atr,
    )

    if with_trace:
        score = meta_model.score(features) if meta_model.is_ready else None
        trace = decision_trace.build_trace(
            direction=direction, forecast=fc, score=score,
            regime_barriers=regime, session=session, atr=atr, entry=entry)
        # Oylama için veri: geniş pencere (MTF) özeti + bağlam (Claude oyu kullanır)
        meta_prob = score.get("olasilik") if isinstance(score, dict) else None
        vote_data = {
            "direction": direction,
            "meta_prob": meta_prob,
            "esik": (score.get("esik") if isinstance(score, dict) else config.DEFAULT_META_THRESHOLD) or config.DEFAULT_META_THRESHOLD,
            "session": session,
            "mtf_summary": {
                "yon": yon, "yon_endeksi": fc.get("yon_endeksi"),
                "guc": conf,
                "zaman_dilimleri": {
                    iv: {
                        "trend": analyses[iv].get("trend"),
                        "rsi": analyses[iv].get("rsi"),
                        "adx": (analyses[iv].get("adx") or {}).get("adx"),
                    } for iv in intervals if analyses.get(iv)
                },
                "primary": primary_iv,
                "entry": entry,
            },
            "news": None,  # router async çekip ekler
        }
        return sid, trace, vote_data
    return sid


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.APP_HOST,
        port=config.APP_PORT,
        reload=config.APP_RELOAD,
        log_level=config.LOG_LEVEL,
    )
