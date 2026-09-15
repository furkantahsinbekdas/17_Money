"""
Sinyal deposu — Sprint 4 meta-labeling altyapısının kalbi.

Her sinyal (canlı Claude sinyali veya backfill) sinyal anındaki özellik
vektörüyle birlikte SQLite'a yazılır. Sonuç etiketi triple-barrier
yöntemiyle belirlenir (López de Prado):

  - Kâr bariyeri:  giriş ± TP_ATR_MULT × ATR   → label 1 (win)
  - Zarar bariyeri: giriş ∓ SL_ATR_MULT × ATR  → label 0 (loss)
  - Zaman bariyeri: HORIZON_BARS bar           → kapanış getirisinin işaretine göre

Etiketleme kuralları:
  - Bariyerler sinyal ANINDAKİ piyasa fiyatından (close) kurulur — limit emir
    dolum simülasyonu yapılmaz, tüm kayıtlar tutarlı etiketlenir.
  - Aynı bar içinde iki bariyer de kesilirse TUTUCU varsayım: loss sayılır.
  - BEKLE sinyalleri bariyersiz loglanır (status='skipped') — sistemin ne
    sıklıkla beklediğini izlemek için.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

import config

DB_PATH = config.SIGNALS_DB_PATH

# Triple-barrier parametreleri (TP 1.5R : SL 1R → rastgele yürüyüşte ~%40 taban
# kazanma oranı; meta-modelin işi bunu seçicilikle yukarı çekmek)
TP_ATR_MULT = config.TP_ATR_MULT
SL_ATR_MULT = config.SL_ATR_MULT
HORIZON_BARS = config.HORIZON_BARS

_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL,
    entry_price REAL,
    atr REAL,
    tp_price REAL,
    sl_price REAL,
    deadline TEXT,
    features TEXT NOT NULL,
    signal_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    label INTEGER,
    exit_price REAL,
    exited_at TEXT,
    meta_prob REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_unique
    ON signals (source, symbol, interval, created_at, direction);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status);
"""


class SignalStore:

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def log_signal(
        self,
        *,
        created_at: datetime,
        source: str,
        symbol: str,
        interval: str,
        direction: str,
        features: dict,
        confidence: float | None = None,
        entry_price: float | None = None,
        atr: float | None = None,
        signal_json: dict | None = None,
        meta_prob: float | None = None,
    ) -> int | None:
        """
        Sinyali loglar. LONG/SHORT için ATR bariyerleri kurulur (status=open),
        BEKLE için bariyersiz status=skipped yazılır.
        Aynı (source, symbol, interval, created_at, direction) varsa atlanır.
        """
        tp = sl = deadline = None
        status = "skipped"

        if direction in ("LONG", "SHORT") and entry_price and atr:
            sign = 1 if direction == "LONG" else -1
            tp = entry_price + sign * TP_ATR_MULT * atr
            sl = entry_price - sign * SL_ATR_MULT * atr
            minutes = _INTERVAL_MINUTES.get(interval, 60) * HORIZON_BARS
            deadline = (created_at + timedelta(minutes=minutes)).isoformat()
            status = "open"

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO signals
                   (created_at, source, symbol, interval, direction, confidence,
                    entry_price, atr, tp_price, sl_price, deadline, features,
                    signal_json, status, meta_prob)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    created_at.isoformat(), source, symbol, interval, direction,
                    confidence, entry_price, atr, tp, sl, deadline,
                    json.dumps(features, ensure_ascii=False, default=str),
                    json.dumps(signal_json, ensure_ascii=False, default=str) if signal_json else None,
                    status, meta_prob,
                ),
            )
            return cur.lastrowid if cur.rowcount else None

    def set_outcome(self, signal_id: int, status: str, label: int | None,
                    exit_price: float | None, exited_at: datetime | None):
        with self._conn() as conn:
            conn.execute(
                "UPDATE signals SET status=?, label=?, exit_price=?, exited_at=? WHERE id=?",
                (status, label, exit_price,
                 exited_at.isoformat() if exited_at else None, signal_id),
            )

    # ------------------------------------------------------------------
    # Triple-barrier çözümleme
    # ------------------------------------------------------------------

    @staticmethod
    def walk_barriers(
        direction: str,
        entry_price: float,
        tp: float,
        sl: float,
        bars: pd.DataFrame,
        deadline: datetime | None = None,
    ) -> tuple[str, int, float, datetime] | None:
        """
        Sinyal SONRASI barları yürüyerek hangi bariyerin önce kesildiğini bulur.
        bars: open_time indeksli OHLC DataFrame (sinyal barından SONRAKİ barlar).
        Dönüş: (status, label, exit_price, exited_at) veya None (henüz açık).
        Aynı bar içinde iki bariyer de kesilirse tutucu olarak LOSS sayılır.
        """
        sign = 1 if direction == "LONG" else -1

        for ts, bar in bars.iterrows():
            hit_tp = bar["high"] >= tp if sign == 1 else bar["low"] <= tp
            hit_sl = bar["low"] <= sl if sign == 1 else bar["high"] >= sl
            if hit_sl:  # tutucu: SL önce kontrol edilir (ikisi aynı barda kesilirse loss)
                return "loss", 0, sl, ts.to_pydatetime()
            if hit_tp:
                return "win", 1, tp, ts.to_pydatetime()
            if deadline is not None and ts.to_pydatetime() >= deadline:
                ret = sign * (bar["close"] - entry_price)
                label = 1 if ret > 0 else 0
                return ("timeout_win" if label else "timeout_loss"), label, float(bar["close"]), ts.to_pydatetime()

        return None

    def resolve_open_signals(self, binance_service) -> dict:
        """
        Açık (status=open) canlı sinyallerin sonuçlarını günceller.
        Aynı (symbol, interval) için klines BİR kez çekilir.
        """
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM signals WHERE status='open' ORDER BY created_at"
            )]

        if not rows:
            return {"resolved": 0, "still_open": 0}

        resolved = 0
        klines_cache: dict[tuple, pd.DataFrame] = {}

        for row in rows:
            key = (row["symbol"], row["interval"])
            if key not in klines_cache:
                # rows zaman sıralı → bu anahtar için ilk görülen kayıt en eskisidir
                oldest = datetime.fromisoformat(row["created_at"])
                minutes = _INTERVAL_MINUTES.get(row["interval"], 60)
                needed = int((datetime.utcnow() - oldest).total_seconds() / 60 / minutes) + 3
                klines_cache[key] = binance_service.get_klines(
                    row["symbol"], row["interval"], min(max(needed, 10), 1000)
                )

            df = klines_cache[key]
            created = datetime.fromisoformat(row["created_at"])
            # Sinyal barından SONRA AÇILAN ve KAPANMIŞ barlar
            minutes = _INTERVAL_MINUTES.get(row["interval"], 60)
            after = df[(df.index > pd.Timestamp(created)) &
                       (df.index + pd.Timedelta(minutes=minutes) <= pd.Timestamp(datetime.utcnow()))]
            if after.empty:
                continue

            deadline = datetime.fromisoformat(row["deadline"]) if row["deadline"] else None
            outcome = self.walk_barriers(
                row["direction"], row["entry_price"], row["tp_price"],
                row["sl_price"], after, deadline,
            )
            if outcome:
                status, label, exit_price, exited_at = outcome
                self.set_outcome(row["id"], status, label, exit_price, exited_at)
                resolved += 1

        return {"resolved": resolved, "still_open": len(rows) - resolved}

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def labeled_dataset(self) -> tuple[pd.DataFrame, pd.Series]:
        """Etiketlenmiş LONG/SHORT kayıtlarını (X, y) olarak döndürür (zaman sıralı)."""
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT created_at, features, label FROM signals
                   WHERE label IS NOT NULL AND direction IN ('LONG','SHORT')
                   ORDER BY created_at"""
            )]
        if not rows:
            return pd.DataFrame(), pd.Series(dtype=int)

        feats = pd.DataFrame([json.loads(r["features"]) for r in rows])
        y = pd.Series([r["label"] for r in rows], name="label")
        return feats, y

    def stats(self) -> dict:
        with self._conn() as conn:
            by_status = {r["status"]: r["n"] for r in conn.execute(
                "SELECT status, COUNT(*) n FROM signals GROUP BY status")}
            by_source = {r["source"]: r["n"] for r in conn.execute(
                "SELECT source, COUNT(*) n FROM signals GROUP BY source")}
            labeled = conn.execute(
                "SELECT COUNT(*) n, AVG(label) wr FROM signals WHERE label IS NOT NULL"
            ).fetchone()
            by_dir = {r["direction"]: {"n": r["n"], "kazanma_orani": round(r["wr"], 3) if r["wr"] is not None else None}
                      for r in conn.execute(
                          """SELECT direction, COUNT(*) n, AVG(label) wr FROM signals
                             WHERE label IS NOT NULL GROUP BY direction""")}

        return {
            "toplam_etiketli": labeled["n"],
            "genel_kazanma_orani": round(labeled["wr"], 3) if labeled["wr"] is not None else None,
            "durum_dagilimi": by_status,
            "kaynak_dagilimi": by_source,
            "yon_dagilimi": by_dir,
            "bariyer_parametreleri": {
                "tp_atr": TP_ATR_MULT, "sl_atr": SL_ATR_MULT, "ufuk_bar": HORIZON_BARS,
            },
        }

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,))]
        for r in rows:
            r.pop("features", None)  # API yanıtını şişirmesin
            r.pop("signal_json", None)
        return rows
