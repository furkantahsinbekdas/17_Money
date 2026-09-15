"""
Claude erişim katmanı — sinyal, tahmin, derin araştırma ve sohbet.

İki transport (config.py karar verir):
- "api": CLAUDE_API_KEY varsa Anthropic SDK (structured output + web_search +
  prompt caching — tam özellik).
- "cli": API key yoksa bu makinede oturum açılmış Claude Code CLI headless
  çağrılır; kullanım CLI aboneliğinden gider.

Ayarlar (model, token/timeout limitleri) config.py'de; sistem promptları ve
JSON şemaları prompts.py'de — bu dosyada gömülü prompt/ayar YOKTUR.
"""
import json
import os

import anthropic

import config
import prompts
from prompts import (
    CHAT_SYSTEM_PROMPT,
    EXPERT_SYSTEM_PROMPT,
    FORECAST_SCHEMA,
    SIGNAL_SCHEMA,
)
from services.claude_cli import ClaudeCLI, ClaudeCLIError, parse_json_loose


def _extract_text(response) -> str:
    """Thinking blokları atlayıp ilk text bloğunu döndürür."""
    return next((b.text for b in response.content if b.type == "text"), "")


def _decode_block(cozme: dict | None) -> str:
    """Sinyal çözme (örüntü deşifre) bağlamını prompt metnine çevirir."""
    if not cozme:
        return ""
    return f"""
# ÖRÜNTÜ ÇÖZME / DEŞİFRE (sinyal işleme — gürültünün altındaki yapı)
- Öngörülebilirlik (entropi): {json.dumps(cozme.get('ongorulebilirlik'), ensure_ascii=False)}
  → seviye 'gürültü' ise yön tahminine GÜVENME; 'yapısal' ise öngörülebilirlik yüksek, güven artabilir.
- Yön hafızası (otokorelasyon): {json.dumps(cozme.get('yon_hafizasi'), ensure_ascii=False)}
  → 'momentum' yön devamı destekler, 'ortalama_donus' ters dönüş destekler.
- Baskın döngü (Fourier): {json.dumps(cozme.get('baskin_dongu'), ensure_ascii=False)}
  → net döngü varsa periyot konumu zamanlamaya katkı verir."""


class ClaudeService:
    """
    İki erişim yolu (transport):
    - "api": config/.env'de geçerli CLAUDE_API_KEY varsa Anthropic SDK
      (structured output + web_search + prompt caching — tam özellik).
    - "cli": API key yoksa, bu makinede oturum açılmış Claude Code CLI
      headless modda çağrılır; kullanım CLI'daki hesabın aboneliğinden gider.
    """

    def __init__(self):
        api_key = config.CLAUDE_API_KEY
        self.has_api_key = config.is_configured("CLAUDE_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key) if self.has_api_key else None
        self.cli = ClaudeCLI(model=config.CLAUDE_CLI_MODEL)
        self.model = config.CLAUDE_MODEL

    @property
    def backend(self) -> str:
        if self.has_api_key:
            return "api"
        if self.cli.available:
            return "cli"
        return "yok"

    @property
    def available(self) -> bool:
        return self.backend != "yok"

    # ------------------------------------------------------------------
    # Sinyal üretimi — derin düşünce + structured output
    # ------------------------------------------------------------------
    def analyze_market(
        self,
        mtf_data: dict,
        news_data: list,
        market_context: dict,
        derivatives: dict | None = None,
        research_notes: str | None = None,
        model: str | None = None,
        stochastic: dict | None = None,
    ) -> dict:
        """
        Çoklu zaman dilimi verisi + türev verileri + makro bağlam + haberleri
        adaptive thinking (derin düşünce) ile analiz edip yapısal sinyal üretir.
        JSON şeması API tarafında garanti edilir (structured output).
        model: config.ALLOWED_CHAT_MODELS içinden (None → varsayılan).
        stochastic: compact_for_signal() çıktısı — bilimsel bağlam.
        """
        if model and model not in config.ALLOWED_CHAT_MODELS:
            model = None
        news_text = "\n".join([
            f"- {n.get('title', '')} ({n.get('source', '')}, sentiment: {n.get('sentiment', 0)})"
            for n in news_data[:config.SIGNAL_NEWS_LIMIT]
        ]) or "Güncel önemli haber yok."

        stochastic_block = ""
        if stochastic:
            stochastic_block = f"""
# STOKASTİK MATEMATİK BAĞLAMI (rastgeleliğin matematiği — bilimsel katman)
Bu veriler fiyatı TAHMİN ETMEZ; tahminini DOĞRULAMAYA/ÇÜRÜTMEYE yarar:
- Tahmin edilebilirlik (Hurst): {json.dumps(stochastic.get('tahmin_edilebilirlik'), ensure_ascii=False)}
  → rejim 'random_walk' ise yön tahminine GÜVENME, güveni düşür. 'trend' ise trend takibi anlamlı.
- Kuyruk riski: {json.dumps(stochastic.get('kuyruk_riski'), ensure_ascii=False)}
  → kuyruk kalınsa stop'u GENİŞLET, aşırı hareket normalden sık.
- Volatilite tahmini (GARCH): {json.dumps(stochastic.get('volatilite_tahmini'), ensure_ascii=False)}
  → vol 'yükseliyor' ise pozisyon KÜÇÜLT, kaldıraç DÜŞÜR.
- Volatilite rejimi: {json.dumps(stochastic.get('volatilite_rejimi'), ensure_ascii=False)}
- Difüzyon bandı (±1σ, ~%68 olasılık): {json.dumps(stochastic.get('difuzyon_bandi_1sigma'), ensure_ascii=False)}
  → hedeflerin bu bandın MAKUL içinde/yakınında olsun; bant dışı hedef düşük olasılıklı.
- Aktif seans (likidite bağlamı): {json.dumps(stochastic.get('seans'), ensure_ascii=False)}
  → 'dusuk_likidite' true ise (derin Asya gecesi 00-05 UTC) teknik sinyaller daha az güvenilir;
    GÜVENİ DÜŞÜR veya BEKLE de. Avrupa/ABD seansında kurumsal hacim → trendler daha gerçek.
{_decode_block(stochastic.get('cozme'))}"""

        user_message = f"""Aşağıdaki güncel piyasa verilerini playbook'una göre analiz et ve sinyal üret.

# ÇOKLU ZAMAN DİLİMİ VERİSİ (BTC/USDT)
{json.dumps(mtf_data, ensure_ascii=False, indent=2, default=str)}

# TÜREV PİYASA VERİLERİ
{json.dumps(derivatives or {}, ensure_ascii=False, indent=2, default=str)}

# MAKRO & SENTIMENT BAĞLAMI
{json.dumps(market_context, ensure_ascii=False, indent=2, default=str)}
{stochastic_block}
# SON HABERLER (piyasa tepkisini SEN yorumla)
Bu haberleri pasif okuma — her birinin OLASI PİYASA TEPKİSİNİ değerlendir:
- Olumlu katalizör mü (ETF girişi, kurumsal benimseme, faiz indirimi beklentisi) → boğa baskısı?
- Olumsuz katalizör mü (regülasyon, hack, iflas, faiz artışı, makro risk) → ayı baskısı / risk-off?
- Yaklaşan olay mı (FOMC, CPI, halving, vade) → belirsizlik, yeni pozisyonda TEMKİN/BEKLE?
Haber teknik sinyalle ÇELİŞİYORSA bunu açıkça belirt ve güveni buna göre ayarla.
Güncel/önemli olay varsa ve bağlam eksikse web aramasını kullan.
{news_text}
"""
        if research_notes:
            user_message += f"""
# DERİN ARAŞTIRMA NOTLARI (web araştırma modundan)
{research_notes}
"""

        if self.has_api_key:
            response = self.client.messages.create(
                model=model or self.model,
                max_tokens=config.CLAUDE_MAX_TOKENS_SIGNAL,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "high",
                    "format": {"type": "json_schema", "schema": SIGNAL_SCHEMA},
                },
                system=[{
                    "type": "text",
                    "text": EXPERT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_message}],
            )
            text = _extract_text(response)
        else:
            text = self.cli.complete(
                prompt=user_message,
                system_prompt=EXPERT_SYSTEM_PROMPT,
                json_schema=SIGNAL_SCHEMA,
                model=model,
            )

        signal = parse_json_loose(text)
        if signal is None:
            return {"raw": text, "sinyal": "BEKLE", "guven_skoru": 0,
                    "uyarilar": ["Yanıt JSON olarak çözümlenemedi"]}

        # Eski frontend alanlarıyla geriye dönük uyumluluk
        hedefler = signal.get("hedefler") or []
        signal["hedef"] = hedefler[0] if hedefler else None
        return signal

    # ------------------------------------------------------------------
    # AI Tahmin — deterministik motor + uzman yorumu (VantagePoint tarzı)
    # ------------------------------------------------------------------
    def ai_forecast(
        self,
        deterministic_forecast: dict,
        mtf_data: dict,
        intermarket: dict,
        market_context: dict,
        model: str | None = None,
        stochastic: dict | None = None,
    ) -> dict:
        """
        Deterministik tahmin motorunun çıktısını (Yön Endeksi, vektörler,
        tahmini aralık) uzman playbook'uyla sentezleyip olasılıklı, gerekçeli
        ve senaryolu bir öngörüye dönüştürür.
        model: config.ALLOWED_CHAT_MODELS içinden (None → varsayılan).
        stochastic: compact_for_signal() çıktısı — bilimsel bağlam.
        """
        if model and model not in config.ALLOWED_CHAT_MODELS:
            model = None

        stochastic_block = ""
        if stochastic:
            stochastic_block = f"""
# STOKASTİK MATEMATİK BAĞLAMI (rastgeleliğin matematiği)
- Tahmin edilebilirlik (Hurst): {json.dumps(stochastic.get('tahmin_edilebilirlik'), ensure_ascii=False)}
  → 'random_walk' ise olasılığı 50'ye yaklaştır; 'trend' ise yön güveni artar.
- Kuyruk riski: {json.dumps(stochastic.get('kuyruk_riski'), ensure_ascii=False)}
- Volatilite tahmini (GARCH): {json.dumps(stochastic.get('volatilite_tahmini'), ensure_ascii=False)}
- Volatilite rejimi: {json.dumps(stochastic.get('volatilite_rejimi'), ensure_ascii=False)}
- Difüzyon bandı (±1σ): {json.dumps(stochastic.get('difuzyon_bandi_1sigma'), ensure_ascii=False)}
  → tahmini_aralik bu difüzyon bandıyla TUTARLI olsun.
{_decode_block(stochastic.get('cozme'))}"""

        user_message = f"""Tahmin görevi: Aşağıdaki deterministik tahmin motoru çıktısını, çoklu zaman dilimi verisini ve intermarket korelasyonlarını sentezleyerek BTC için 24-72 saatlik bir öngörü üret.

Deterministik motor sadece gösterge konsensüsünü ölçer — senin görevin bunu yapı (SMC), likidite, türev verileri, intermarket VE stokastik matematik bağlamıyla DOĞRULAMAK veya ÇÜRÜTMEK. Motora körü körüne katılma; çelişki görüyorsan belirt ve olasılığı düşür.

# DETERMİNİSTİK TAHMİN MOTORU ÇIKTISI
{json.dumps(deterministic_forecast, ensure_ascii=False, indent=2, default=str)}

# ÇOKLU ZAMAN DİLİMİ VERİSİ
{json.dumps(mtf_data, ensure_ascii=False, indent=2, default=str)}

# INTERMARKET KORELASYONLARI (90 günlük getiri korelasyonu)
{json.dumps(intermarket, ensure_ascii=False, indent=2, default=str)}

# PİYASA BAĞLAMI
{json.dumps(market_context, ensure_ascii=False, indent=2, default=str)}
{stochastic_block}"""

        if self.has_api_key:
            response = self.client.messages.create(
                model=model or self.model,
                max_tokens=config.CLAUDE_MAX_TOKENS_SIGNAL,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "high",
                    "format": {"type": "json_schema", "schema": FORECAST_SCHEMA},
                },
                system=[{
                    "type": "text",
                    "text": EXPERT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_message}],
            )
            text = _extract_text(response)
        else:
            text = self.cli.complete(
                prompt=user_message,
                system_prompt=EXPERT_SYSTEM_PROMPT,
                json_schema=FORECAST_SCHEMA,
                model=model,
            )

        forecast = parse_json_loose(text)
        if forecast is None:
            return {"raw": text, "yon": "yatay", "olasilik": 0,
                    "riskler": ["Yanıt JSON olarak çözümlenemedi"]}
        return forecast

    # ------------------------------------------------------------------
    # Derin araştırma modu — web search ile güncel piyasa istihbaratı
    # ------------------------------------------------------------------
    def deep_research(self, market_context: dict, focus: str | None = None,
                      model: str | None = None) -> dict:
        """
        Web araması ile güncel BTC piyasa istihbaratı toplar:
        son haberler, makro takvim, kurumsal akışlar, on-chain gelişmeler.
        Sinyal üretimine beslenebilir veya bağımsız kullanılabilir.
        model: config.ALLOWED_CHAT_MODELS içinden (None → varsayılan).
        """
        if model and model not in config.ALLOWED_CHAT_MODELS:
            model = None
        focus_text = focus or config.RESEARCH_DEFAULT_FOCUS

        user_message = f"""Araştırma görevi: {focus_text}

Mevcut piyasa durumu (referans):
{json.dumps(market_context, ensure_ascii=False, indent=2, default=str)}

Web aramasını kullanarak şunları araştır ve sentezle:
1. Bitcoin/kripto ile ilgili son 24-48 saatin en önemli haberleri ve piyasa etkileri
2. Yaklaşan makro olaylar (FOMC, CPI, istihdam verileri vb.) ve tarihleri
3. ETF akışları, kurumsal alım/satım haberleri, regülasyon gelişmeleri
4. Piyasada öne çıkan analist görüşleri ve kritik seviye beklentileri

Çıktı formatı:
- **Özet** (2-3 cümle: genel risk iştahı yönü)
- **Önemli Gelişmeler** (maddeler halinde, her birinin olası fiyat etkisiyle)
- **Yaklaşan Riskler/Olaylar** (tarihleriyle)
- **Sonuç** (bu araştırmanın trade kararına etkisi: boğa/ayı/nötr ağırlığı)

Türkçe yaz. Kaynaklara dayan, spekülasyon yapma."""

        if not self.has_api_key:
            rapor = self.cli.complete(
                prompt=user_message + prompts.RESEARCH_REPORT_FOOTER,
                system_prompt=EXPERT_SYSTEM_PROMPT,
                web_search=True,
                model=model,
            )
            return {"rapor": rapor, "kaynaklar": []}

        messages = [{"role": "user", "content": user_message}]
        response = None

        # Web search server-side döngüsü pause_turn ile durabilir — devam ettir
        for _ in range(config.CLAUDE_WEB_SEARCH_MAX_TURNS_RESEARCH):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=config.CLAUDE_MAX_TOKENS_RESEARCH,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                system=[{
                    "type": "text",
                    "text": EXPERT_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=[{
                    "type": config.CLAUDE_WEB_SEARCH_TOOL, "name": "web_search",
                    "max_uses": config.CLAUDE_WEB_SEARCH_MAX_USES_RESEARCH,
                }],
                messages=messages,
            )
            if response.stop_reason != "pause_turn":
                break
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content},
            ]

        # Kullanılan kaynakları topla
        sources = []
        for block in response.content:
            if block.type == "web_search_tool_result":
                try:
                    for item in block.content:
                        url = getattr(item, "url", None)
                        title = getattr(item, "title", None)
                        if url:
                            sources.append({"title": title or url, "url": url})
                except TypeError:
                    pass

        return {
            "rapor": _extract_text(response),
            "kaynaklar": sources[:config.RESEARCH_SOURCES_LIMIT],
        }

    # ------------------------------------------------------------------
    # Sohbet oturumu kalıcılığı (CLI --resume için)
    # ------------------------------------------------------------------

    def _load_chat_session(self) -> dict | None:
        try:
            with open(config.CHAT_SESSION_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _save_chat_session(self, session_id: str | None, model: str):
        try:
            if not session_id:
                return
            with open(config.CHAT_SESSION_PATH, "w", encoding="utf-8") as f:
                json.dump({"session_id": session_id, "model": model}, f)
        except OSError:
            pass

    def reset_chat(self) -> None:
        """Kalıcı CLI sohbet oturumunu siler — sonraki mesaj temiz başlar."""
        try:
            os.remove(config.CHAT_SESSION_PATH)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Terminal sohbet — uzman partner + isteğe bağlı web araştırma
    # ------------------------------------------------------------------
    def chat(self, conversation_history: list, user_message: str,
             market_context: dict, model: str | None = None) -> str:
        """
        Kullanıcıyla sohbet modu. Sabit persona cache'lenir; güncel piyasa
        bağlamı ayrı (volatil) blokta eklenir. Web search açık — uzman,
        güncel bilgi gerektiğinde kendi araştırmasını yapar.

        model: config.ALLOWED_CHAT_MODELS içinden seçim (None → varsayılan model).
        CLI yolunda oturum kalıcıdır: ilk mesajda oturum açılır, sonraki
        mesajlar --resume ile aynı oturumda devam eder (Claude izin verdiği
        sürece); model değişirse yeni oturum başlar.
        """
        if model and model not in config.ALLOWED_CHAT_MODELS:
            model = None
        context_block = f"""GÜNCEL PİYASA VERİSİ (otomatik enjekte edildi):
- BTC Fiyat: ${market_context.get('btc_price', 'bilinmiyor')}
- Trend (1H): {market_context.get('trend', 'bilinmiyor')}
- RSI (1H): {market_context.get('rsi', 'bilinmiyor')}
- ADX (1H): {market_context.get('adx', 'bilinmiyor')}
- ATR%: {market_context.get('atr_yuzde', 'bilinmiyor')}
- Fear & Greed: {market_context.get('fear_greed', 'bilinmiyor')}
- Funding Rate: {market_context.get('funding_rate', 'bilinmiyor')}
- Open Interest: {market_context.get('open_interest', 'bilinmiyor')}
- Intermarket (DXY/VIX/S&P/Altın korelasyonu): {json.dumps(market_context.get('intermarket'), ensure_ascii=False, default=str) if market_context.get('intermarket') else 'yok'}
- Tahmin Tablosu (MTF forecast endeksi): {json.dumps(market_context.get('tahmin_tablosu'), ensure_ascii=False, default=str) if market_context.get('tahmin_tablosu') else 'yok'}"""

        if not self.has_api_key:
            chosen_model = model or self.cli.model

            # Aynı modelle açık bir oturum varsa devam et (--resume):
            # bağlam CLI tarafında saklanır, geçmişi yeniden göndermeye gerek yok.
            sess = self._load_chat_session()
            resume_id = (sess or {}).get("session_id") if (sess or {}).get("model") == chosen_model else None

            resume_prompt = f"{context_block}\n\n# KULLANICININ YENİ MESAJI\n{user_message}"

            if resume_id:
                try:
                    env = self.cli.run(
                        prompt=resume_prompt,
                        system_prompt=CHAT_SYSTEM_PROMPT,
                        web_search=True,
                        effort="medium",
                        model=chosen_model,
                        resume=resume_id,
                        persist=True,
                        timeout=config.CLAUDE_CLI_CHAT_TIMEOUT_SEC,
                    )
                    self._save_chat_session(env.get("session_id"), chosen_model)
                    return env.get("result", "")
                except ClaudeCLIError:
                    pass  # oturum süresi dolmuş/silinmiş olabilir — temiz başla

            # Yeni oturum: frontend geçmişini bir kez taşı, sonrası resume ile sürer
            transcript = "\n".join(
                f"{'Kullanıcı' if m['role'] == 'user' else '17Money'}: {m['content']}"
                for m in conversation_history[-config.CHAT_HISTORY_TURNS:]
            )
            prompt = context_block + "\n\n"
            if transcript:
                prompt += f"# ÖNCEKİ KONUŞMA\n{transcript}\n\n"
            prompt += f"# KULLANICININ YENİ MESAJI\n{user_message}"

            env = self.cli.run(
                prompt=prompt,
                system_prompt=CHAT_SYSTEM_PROMPT,
                web_search=True,
                effort="medium",
                model=chosen_model,
                persist=True,
                timeout=config.CLAUDE_CLI_CHAT_TIMEOUT_SEC,
            )
            self._save_chat_session(env.get("session_id"), chosen_model)
            return env.get("result", "")

        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in conversation_history[-config.CHAT_HISTORY_TURNS:]
        ]
        messages.append({"role": "user", "content": user_message})

        response = None
        for _ in range(config.CLAUDE_WEB_SEARCH_MAX_TURNS_CHAT):
            response = self.client.messages.create(
                model=model or self.model,
                max_tokens=4000,
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": CHAT_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": context_block},
                ],
                tools=[{
                    "type": config.CLAUDE_WEB_SEARCH_TOOL, "name": "web_search",
                    "max_uses": config.CLAUDE_WEB_SEARCH_MAX_USES_CHAT,
                }],
                messages=messages,
            )
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]

        return _extract_text(response)

    # ------------------------------------------------------------------
    # Oylama (paper run-once → claude_vote.py) — yalnızca API transport'u
    # ------------------------------------------------------------------
    def vote_raw(self, user_prompt: str, system_prompt: str, schema: dict,
                 model: str | None = None) -> str:
        """Oylama promptunu yapısal JSON (şema garantili) olarak döndürür.

        NOT: Bu metot eskiden hiç tanımlı değildi; claude_vote.py onu API
        yolunda çağırıyordu ve AttributeError sessizce yutuluyordu → API
        kullanıcıları hiçbir zaman gerçek oy alamıyordu (hep 'çekimser').
        Hata durumunda claude_vote yine çekimser'e düşer (davranış güvenli).
        """
        response = self.client.messages.create(
            model=model or self.model,
            max_tokens=config.CLAUDE_MAX_TOKENS_CHAT,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": schema},
            },
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _extract_text(response)
