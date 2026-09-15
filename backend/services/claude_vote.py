"""
Claude oyu — oylama sisteminin "dil beyni" kanadı (Görev: oylama mekanizması).

Felsefe: model (sayı beyni) bir olasılık verir; Claude (dil beyni) GENİŞ PENCERE
(çoklu zaman dilimi) + HABER + makro bağlamı sentezleyip gerekçeli bir OY verir.
Son karar EŞİT OYLAMA / uzlaşma kuralında birleşir (vote_combine.py).

Claude kendini tanıtır ("Seventeen AI ... finans motoru"), topladığı veriyi
özetler, öngörüsünü ve NEDENLERİNİ söyler, oyunu verir: yükseliş / düşüş /
çekimser. Çekimser oy sonucu ETKİLEMEZ (kullanıcı tarifi).

Kredi notu: bu çağrı Claude kredisi yakar. SADECE paper "Modeli Çalıştır"
butonunda (elle, kullanıcı tetiğiyle) çağrılır — otonom döngülerde DEĞİL.
"""

from __future__ import annotations

import json

import config
import prompts


def _extract_structured(envelope: dict) -> dict:
    """CLI zarfından oy JSON'unu çıkarır. Önce structured_output (şema garantili),
    yoksa result metninden gömülü JSON, o da yoksa markdown'dan kaba çıkarım."""
    import re
    if isinstance(envelope, dict):
        so = envelope.get("structured_output")
        if isinstance(so, dict) and "oy" in so:
            return so
        if isinstance(so, str) and so.strip():
            try:
                return json.loads(so)
            except Exception:
                pass
        result = envelope.get("result", "")
    else:
        result = str(envelope)

    # result içinde gömülü JSON ara
    m = re.search(r"\{[^{}]*\"oy\"[^{}]*\}", result, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # Son çare: markdown'dan kaba çıkarım (yön + güven)
    low = result.lower()
    if "yükseliş" in low or "long" in low or "📈" in result:
        oy = "yükseliş"
    elif "düşüş" in low or "short" in low or "📉" in result:
        oy = "düşüş"
    else:
        oy = "çekimser"
    gm = re.search(r"güven[:\s]*\(?(\d{1,3})", low)
    guven = int(gm.group(1)) if gm else (50 if oy != "çekimser" else 0)
    # Gerekçe: ilk birkaç anlamlı satır
    gerekce = re.sub(r"[#*`>📉📈🔍\-]", "", result).strip()[:400] or "Claude yanıtı (yapısal değil)."
    riski = "yüksek" if "yüksek risk" in low else ("orta" if "haber" in low and "risk" in low else "yok")
    return {"oy": oy, "guven": guven, "gerekce": gerekce, "haber_riski": riski}


def build_vote(*, claude, direction, mtf_summary, news, model_prob, session_ctx,
               model: str | None = None) -> dict:
    """
    Claude'a oy verdirir. Döner: {oy, guven, gerekce, haber_riski, tanitim, hata?}

    claude: ClaudeService (backend cli|api). direction: model/forecast yönü.
    mtf_summary: çoklu zaman dilimi özeti (geniş pencere). news: haber listesi.
    model_prob: meta-modelin olasılığı (0-1) veya None. session_ctx: seans bağlamı.
    """
    if not getattr(claude, "available", False):
        return {"oy": "çekimser", "guven": 0,
                "gerekce": "Claude erişimi yok — oy verilemedi (model tek başına karar verir).",
                "haber_riski": "yok", "hata": "claude_yok"}

    haber_txt = "\n".join(
        f"- {n.get('title', '')}" for n in (news or [])[:config.SIGNAL_NEWS_LIMIT]
    ) or "Güncel önemli haber yok."

    prob_txt = (f"%{model_prob*100:.0f}" if isinstance(model_prob, (int, float))
                else "henüz yok")

    prompt = f"""Kendini KISACA tanıt (1 cümle), sonra aşağıdaki veriyi değerlendirip OYUNU ver.

# MODELİN ÖN DEĞERLENDİRMESİ
Meta-model (sayı beyni) bu işlemin yönünü {direction} olarak gördü, kazanma olasılığı: {prob_txt}.

# GENİŞ PENCERE (çoklu zaman dilimi analizi)
{json.dumps(mtf_summary, ensure_ascii=False, indent=1, default=str)}

# SEANS / LİKİDİTE
{json.dumps(session_ctx, ensure_ascii=False, default=str)}

# GÜNCEL HABERLER (piyasa tepkisini değerlendir)
{haber_txt}

# GÖREVİN
Geniş pencereyi, haberleri ve makroyu sentezle. Topladığın veriden ne ÖNGÖRÜYORSUN
ve NEDEN? Oyunu ver:
- 'yükseliş' = fiyat yukarı, LONG yönüne oy
- 'düşüş' = fiyat aşağı, SHORT yönüne oy
- 'çekimser' = emin değilim (sonucu etkilemez — yanlış orduya oy vermekten iyidir)
Gerekçeni 2-4 somut cümleyle yaz. Haber riski varsa belirt."""

    try:
        if claude.backend == "cli":
            envelope = claude.cli.run(
                prompt=prompt, system_prompt=prompts.VOTE_SYSTEM,
                json_schema=prompts.VOTE_SCHEMA, model=model,
                timeout=config.CLAUDE_CLI_VOTE_TIMEOUT_SEC,  # asılırsa çekimser düşsün — sistem durmasın, model karar verir
            )
            data = _extract_structured(envelope)
        else:
            raw = claude.vote_raw(prompt, prompts.VOTE_SYSTEM, prompts.VOTE_SCHEMA, model)  # api yolu
            data = json.loads(raw) if isinstance(raw, str) else raw
        return {
            "oy": data.get("oy", "çekimser"),
            "guven": int(data.get("guven", 0)),
            "gerekce": data.get("gerekce", ""),
            "haber_riski": data.get("haber_riski", "yok"),
        }
    except Exception as e:
        return {"oy": "çekimser", "guven": 0,
                "gerekce": f"Claude oyu alınamadı ({type(e).__name__}). Model tek başına karar verir.",
                "haber_riski": "yok", "hata": str(e)[:120]}
