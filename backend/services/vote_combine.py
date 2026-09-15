"""
Oylama birleştirme — eşit uzlaşma kuralı (kullanıcı tarifi).

Model (sayı beyni) + Claude (dil beyni) EŞİT oy verir:
  - İkisi AYNI yön → İŞLE (uzlaşma var).
  - Çelişki (biri yükseliş biri düşüş) → BEKLE (uzlaşma yok, temkinli).
  - Çekimser oy SAYILMAZ — diğer oy belirler (çekimser sonucu etkilemez).
  - İki çekimser / ikisi de zayıf → BEKLE.

Model oyu: meta_prob eşiği geçtiyse forecast yönüne oy; geçmediyse çekimser.
Claude oyu: claude_vote.build_vote çıktısı (yükseliş/düşüş/çekimser).
"""

from __future__ import annotations


def _yon_to_oy(direction: str) -> str:
    return "yükseliş" if direction == "LONG" else "düşüş"


def model_vote(direction: str, meta_prob, esik: float) -> dict:
    """Modelin oyu: olasılık eşiği geçtiyse yöne oy, geçmediyse çekimser."""
    if meta_prob is None:
        return {"oy": "çekimser", "guven": 0,
                "gerekce": "Model henüz eğitilmemiş — oy yok."}
    if meta_prob >= esik:
        return {"oy": _yon_to_oy(direction),
                "guven": round(float(meta_prob) * 100),
                "gerekce": f"Model kazanma olasılığını %{meta_prob*100:.0f} hesapladı "
                           f"(eşik %{esik*100:.0f} üstü) → {direction} yönüne oy."}
    return {"oy": "çekimser", "guven": round(float(meta_prob) * 100),
            "gerekce": f"Model olasılığı %{meta_prob*100:.0f} < eşik %{esik*100:.0f} "
                       "→ zayıf, çekimser."}


def combine(model_oy: dict, claude_oy: dict, direction: str) -> dict:
    """
    İki oyu eşit uzlaşma kuralıyla birleştirir.
    Döner: {karar: İŞLE/BEKLE, yon, gerekce, oylar, uzlasma}
    """
    mo = model_oy.get("oy", "çekimser")
    co = claude_oy.get("oy", "çekimser")
    hedef_oy = _yon_to_oy(direction)  # işlemin yönüne karşılık gelen oy

    # Çekimser olmayan oyları topla
    aktif = [o for o in (mo, co) if o != "çekimser"]

    if not aktif:
        karar, uzlasma, neden = "BEKLE", "iki çekimser", \
            "İkisi de çekimser — net sinyal yok, BEKLE."
    elif mo != "çekimser" and co != "çekimser" and mo != co:
        karar, uzlasma, neden = "BEKLE", "çelişki", \
            f"Model '{mo}', Claude '{co}' dedi — çelişki var, temkinli BEKLE."
    elif hedef_oy in aktif:
        # En az bir aktif oy işlemin yönünü destekliyor, çelişki yok → İŞLE
        destek = []
        if mo == hedef_oy:
            destek.append("model")
        if co == hedef_oy:
            destek.append("Claude")
        karar, uzlasma = "İŞLE", "uzlaşma" if len(destek) == 2 else f"{destek[0]} tek başına"
        neden = (f"{' ve '.join(destek)} {direction} yönünde hemfikir → İŞLE."
                 if len(destek) == 2 else
                 f"{destek[0]} {direction} dedi, diğeri çekimser → İŞLE (çekimser engellemez).")
    else:
        # Aktif oy var ama işlemin yönüne ters (ör. model SHORT ama Claude yükseliş dedi
        # ve forecast LONG'du) — güvenli taraf BEKLE
        karar, uzlasma, neden = "BEKLE", "yön desteklenmedi", \
            "Aktif oy işlemin yönünü desteklemiyor — BEKLE."

    return {
        "karar": karar,
        "yon": direction if karar == "İŞLE" else None,
        "uzlasma": uzlasma,
        "gerekce": neden,
        "oylar": {
            "model": {"oy": mo, "guven": model_oy.get("guven"),
                      "gerekce": model_oy.get("gerekce")},
            "claude": {"oy": co, "guven": claude_oy.get("guven"),
                       "gerekce": claude_oy.get("gerekce"),
                       "haber_riski": claude_oy.get("haber_riski")},
        },
    }
