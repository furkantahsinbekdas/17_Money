"""
Paper trading hesap defteri — sistemin "canlı kanıt" aşaması (Aşama 5).

Felsefe: GERÇEK PARA YOK. Bu defter, mevcut sinyal→bariyer→çözüm zincirinin
üstüne ince bir muhasebe katmanıdır. Sıfırdan trade motoru DEĞİL — signal_store
zaten sinyali loglar, TP/SL bariyeri kurar, resolve_loop sonucu (win/loss) çözer.
Burada yapılan tek şey: çözülen her sinyali, eğer meta-model ONAYLADIYSA, dolar
cinsinden bir işleme çevirip sermayeyi güncellemek.

Dürüstlük kuralları (backtest ile AYNI matematik — tutarlılık şart):
  - Her işlemde sermayenin RISK_PCT'i (%2) riske atılır (1R = sermaye × %2).
  - Gerçek R:R fiyatlardan: r_win = |tp-entry|/atr, r_loss = |entry-sl|/atr
    (rejim-duyarlı etiketleme → her işlemin oranı farklı).
  - Maliyet COST_R (0.06R) her işlemden düşülür (komisyon+funding+slipaj).
  - SADECE meta-model onayı (meta_prob >= eşik) olan sinyaller işleme döner;
    gerisi atlanır — tıpkı canlı filtre gibi. Filtresiz işlem YOK.
  - Bileşik: kazanç/kayıp güncel sermayenin yüzdesi (sabit dolar değil).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import config

# Tüm varsayılan parametreler ve devre-kesici eşikleri config.py'de
# (PAPER_* / BREAKER_* / COOLDOWN_* ile ezilebilir).
DB_PATH = config.PAPER_DB_PATH

DEFAULT_START_BALANCE = config.DEFAULT_START_BALANCE
DEFAULT_RISK_PCT = config.DEFAULT_RISK_PCT
DEFAULT_COST_R = config.DEFAULT_COST_R
DEFAULT_META_THRESHOLD = config.DEFAULT_META_THRESHOLD

# DEVRE KESİCİ (kill switch) — gerçek quant fonlarının güvenlik ağı.
# Model üst üste kaybederse/hesap erirse sistem KENDİNİ durdurur; kör devam yok.
BREAKER_DD_LIMIT = config.BREAKER_DD_LIMIT
COOLDOWN_LOSSES = config.COOLDOWN_LOSSES
COOLDOWN_EXIT_WINS = config.COOLDOWN_EXIT_WINS
COOLDOWN_RISK_SCALE = config.COOLDOWN_RISK_SCALE

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_balance REAL NOT NULL,
    balance REAL NOT NULL,
    risk_pct REAL NOT NULL,
    cost_r REAL NOT NULL,
    meta_threshold REAL NOT NULL,
    peak_balance REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER UNIQUE,        -- aynı sinyali iki kez işleme almayı önler
    opened_at TEXT,
    closed_at TEXT,
    symbol TEXT,
    direction TEXT,
    entry_price REAL,
    exit_price REAL,
    r_win REAL,                      -- bu işlemin gerçek kazanç oranı (R)
    r_loss REAL,                     -- bu işlemin gerçek kayıp oranı (R)
    label INTEGER,                   -- 1=kazanç, 0=kayıp
    meta_prob REAL,                  -- modelin onay olasılığı
    risk_dollar REAL,                -- bu işlemde riske atılan dolar
    pnl_dollar REAL,                 -- dolar kâr/zarar (maliyet sonrası)
    pnl_r REAL,                      -- R cinsinden net sonuç
    balance_after REAL               -- işlem sonrası sermaye
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_closed ON paper_trades (closed_at);
"""


class PaperAccount:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            # Devre kesici kolonları — mevcut DB'ye güvenli geçiş (idempotent)
            mevcut = {r[1] for r in conn.execute("PRAGMA table_info(paper_state)")}
            for kolon, tanim in [
                ("breaker_tripped", "INTEGER DEFAULT 0"),
                ("breaker_reason", "TEXT"),
                ("breaker_time", "TEXT"),
                ("consec_losses", "INTEGER DEFAULT 0"),
                ("consec_wins", "INTEGER DEFAULT 0"),
                ("cooldown", "INTEGER DEFAULT 0"),
            ]:
                if kolon not in mevcut:
                    conn.execute(f"ALTER TABLE paper_state ADD COLUMN {kolon} {tanim}")
            row = conn.execute("SELECT id FROM paper_state WHERE id=1").fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO paper_state
                       (id, start_balance, balance, risk_pct, cost_r, meta_threshold,
                        peak_balance, created_at)
                       VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                    (DEFAULT_START_BALANCE, DEFAULT_START_BALANCE, DEFAULT_RISK_PCT,
                     DEFAULT_COST_R, DEFAULT_META_THRESHOLD, DEFAULT_START_BALANCE,
                     datetime.utcnow().isoformat()),
                )

    # ------------------------------------------------------------------
    def _state(self) -> dict:
        with self._conn() as conn:
            return dict(conn.execute("SELECT * FROM paper_state WHERE id=1").fetchone())

    @staticmethod
    def signal_rr(entry, tp, sl, atr) -> tuple[float, float]:
        """Sinyalin gerçek (r_win, r_loss) oranı — fiyatlardan, rejim-duyarlı.
        Eksik veride (1.5, 1.0) varsayımına düşer (eski sabit-bariyer uyumu)."""
        try:
            if atr and atr > 0 and entry is not None and tp is not None and sl is not None:
                return abs(tp - entry) / atr, abs(entry - sl) / atr
        except (TypeError, ZeroDivisionError):
            pass
        return 1.5, 1.0

    # ------------------------------------------------------------------
    def record_resolved_signal(self, sig: dict) -> dict | None:
        """
        Çözülmüş bir sinyali (label dolu) paper işlemine çevirir.
        sig: signals tablosundan bir satır (dict) — id, direction, label,
             entry_price, tp_price, sl_price, atr, exit_price, meta_prob...

        Sadece meta-model ONAYLADIYSA (meta_prob >= eşik) ve LONG/SHORT ise işler.
        İdempotent: aynı signal_id ikinci kez gelirse atlanır.
        Döner: işlenen trade sözlüğü veya None (atlandı).
        """
        if sig.get("label") is None:
            return None
        if sig.get("direction") not in ("LONG", "SHORT"):
            return None

        st = self._state()
        meta_prob = sig.get("meta_prob")
        # Filtre: model onayı yoksa veya eşik altındaysa işleme alma.
        # meta_prob None ise (model henüz yokken loglanmış) güvenli taraf: atla.
        if meta_prob is None or float(meta_prob) < st["meta_threshold"]:
            return None

        # DEVRE KESİCİ: tetiklendiyse, tetiklenme ANINDAN SONRA açılan sinyaller
        # işleme dönüşmez (insan onayı gerekir). Tetik ÖNCESİ açılmış pozisyonlar
        # normal çözülür — onlar zaten alınmıştı, dürüst muhasebe.
        # NOT: sinyal ÜRETİMİ durmaz (eğitim verisi birikmeye devam eder);
        # sadece paper işlemine dönüşüm kesilir.
        if st.get("breaker_tripped") and st.get("breaker_time"):
            if (sig.get("created_at") or "") > st["breaker_time"]:
                return None

        with self._conn() as conn:
            # İdempotent kontrol
            exists = conn.execute(
                "SELECT 1 FROM paper_trades WHERE signal_id=?", (sig["id"],)
            ).fetchone()
            if exists:
                return None

            r_win, r_loss = self.signal_rr(
                sig.get("entry_price"), sig.get("tp_price"),
                sig.get("sl_price"), sig.get("atr"),
            )
            label = int(sig["label"])
            cost_r = st["cost_r"]
            # Net R: kazançta +r_win, kayıpta -r_loss; her durumda maliyet düşülür
            pnl_r = (r_win - cost_r) if label == 1 else -(r_loss + cost_r)

            # SOĞUMA MODU: ardışık kayıp serisinde risk yarıya iner
            cooldown = bool(st.get("cooldown"))
            efektif_risk = st["risk_pct"] * (COOLDOWN_RISK_SCALE if cooldown else 1.0)

            balance = st["balance"]
            risk_dollar = balance * efektif_risk
            pnl_dollar = risk_dollar * pnl_r
            new_balance = balance + pnl_dollar
            peak = max(st["peak_balance"], new_balance)

            conn.execute(
                """INSERT INTO paper_trades
                   (signal_id, opened_at, closed_at, symbol, direction,
                    entry_price, exit_price, r_win, r_loss, label, meta_prob,
                    risk_dollar, pnl_dollar, pnl_r, balance_after)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sig["id"], sig.get("created_at"), sig.get("exited_at"),
                 sig.get("symbol"), sig["direction"],
                 sig.get("entry_price"), sig.get("exit_price"),
                 round(r_win, 3), round(r_loss, 3), label, float(meta_prob),
                 round(risk_dollar, 2), round(pnl_dollar, 2), round(pnl_r, 3),
                 round(new_balance, 2)),
            )

            # --- Ardışık sayaçlar + soğuma geçişleri ---
            wins = st.get("consec_wins") or 0
            losses = st.get("consec_losses") or 0
            if label == 1:
                wins, losses = wins + 1, 0
            else:
                wins, losses = 0, losses + 1
            if not cooldown and losses >= COOLDOWN_LOSSES:
                cooldown = True   # 5 ardışık kayıp → risk yarıya
            elif cooldown and wins >= COOLDOWN_EXIT_WINS:
                cooldown = False  # 2 ardışık kazanç → normale dön

            # --- Düşüş devre kesicisi: tepeden -%25 → yeni işlemleri DURDUR ---
            tripped = bool(st.get("breaker_tripped"))
            reason, trip_time = st.get("breaker_reason"), st.get("breaker_time")
            dd = new_balance / peak - 1 if peak > 0 else 0.0
            if not tripped and dd <= -BREAKER_DD_LIMIT:
                tripped = True
                reason = (f"Sermaye tepe noktasından %{abs(dd)*100:.0f} düştü "
                          f"(limit %{BREAKER_DD_LIMIT*100:.0f}) — yeni işlemler durduruldu, onayın gerekiyor.")
                trip_time = datetime.utcnow().isoformat()

            conn.execute(
                """UPDATE paper_state SET balance=?, peak_balance=?,
                   consec_wins=?, consec_losses=?, cooldown=?,
                   breaker_tripped=?, breaker_reason=?, breaker_time=? WHERE id=1""",
                (round(new_balance, 2), round(peak, 2), wins, losses, int(cooldown),
                 int(tripped), reason, trip_time),
            )
            return {
                "signal_id": sig["id"], "direction": sig["direction"],
                "label": label, "pnl_r": round(pnl_r, 3),
                "pnl_dollar": round(pnl_dollar, 2), "balance": round(new_balance, 2),
                "sogumada": cooldown, "devre_kesici": tripped,
            }

    # ------------------------------------------------------------------
    def status(self, recent: int = 15, store=None) -> dict:
        """Paper hesabın tam durumu — frontend kartı için.
        store verilirse AÇIK pozisyonlar (henüz çözülmemiş, sonuç bekleyen)
        da listelenir — kullanıcı 'sinyal başlatmadan görünmüyor' demişti."""
        st = self._state()
        with self._conn() as conn:
            trades = [dict(r) for r in conn.execute(
                "SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?", (recent,)
            )]
            agg = conn.execute(
                """SELECT COUNT(*) n,
                          SUM(CASE WHEN label=1 THEN 1 ELSE 0 END) wins,
                          SUM(pnl_dollar) total_pnl,
                          SUM(pnl_r) total_r
                   FROM paper_trades"""
            ).fetchone()

        n = agg["n"] or 0
        wins = agg["wins"] or 0
        start = st["start_balance"]
        bal = st["balance"]
        getiri_pct = (bal / start - 1) * 100 if start else 0.0
        drawdown_pct = (bal / st["peak_balance"] - 1) * 100 if st["peak_balance"] else 0.0

        return {
            "aktif": n > 0,
            "baslangic": round(start, 2),
            "sermaye": round(bal, 2),
            "getiri_yuzde": round(getiri_pct, 1),
            "tepe_sermaye": round(st["peak_balance"], 2),
            "dusus_yuzde": round(drawdown_pct, 1),
            "islem_sayisi": n,
            "kazanan": wins,
            "kaybeden": n - wins,
            "kazanma_orani": round(wins / n, 3) if n else None,
            "toplam_kar_dolar": round(agg["total_pnl"] or 0, 2),
            "toplam_r": round(agg["total_r"] or 0, 2),
            "risk_yuzde": round(st["risk_pct"] * 100, 1),
            "maliyet_r": st["cost_r"],
            "esik": st["meta_threshold"],
            "son_islemler": [
                {
                    "yon": t["direction"], "sonuc": "kazanç" if t["label"] == 1 else "kayıp",
                    "kar_dolar": t["pnl_dollar"], "sermaye": t["balance_after"],
                    "zaman": (t["closed_at"] or "")[:16],
                }
                for t in trades
            ],
            "acik_pozisyonlar": self._open_positions(store),
            # Devre kesici durumu (güvenlik ağı)
            "devre_kesici": {
                "tetiklendi": bool(st.get("breaker_tripped")),
                "sebep": st.get("breaker_reason"),
                "zaman": (st.get("breaker_time") or "")[:16] or None,
                "sogumada": bool(st.get("cooldown")),
                "ardisik_kayip": st.get("consec_losses") or 0,
                "ardisik_kazanc": st.get("consec_wins") or 0,
                "efektif_risk_yuzde": round(
                    st["risk_pct"] * (COOLDOWN_RISK_SCALE if st.get("cooldown") else 1.0) * 100, 2),
                "dd_limit_yuzde": round(BREAKER_DD_LIMIT * 100),
            },
        }

    def breaker_reset(self) -> dict:
        """
        Devre kesiciyi elle yeniden etkinleştir (insan onayı).
        ÖNEMLİ: tepe sermaye MEVCUT sermayeye çekilir — yoksa bir sonraki küçük
        kayıp aynı eski tepeye göre ölçülüp devreyi ANINDA yeniden tetiklerdi.
        Yeniden etkinleştirme = "buradan itibaren temiz sayfa" demektir.
        """
        with self._conn() as conn:
            st = dict(conn.execute("SELECT * FROM paper_state WHERE id=1").fetchone())
            conn.execute(
                """UPDATE paper_state SET breaker_tripped=0, breaker_reason=NULL,
                   breaker_time=NULL, consec_losses=0, consec_wins=0, cooldown=0,
                   peak_balance=? WHERE id=1""",
                (st["balance"],),
            )
        return {"yeniden_etkin": True, "yeni_tepe": st["balance"]}

    def _open_positions(self, store) -> list:
        """Açık (status=open) pozisyonlar — SADECE model-onaylı olanlar (paper'a
        giren işlemler). Model elediği sinyaller (meta_prob < eşik) gösterilmez —
        onlar zaten işleme dönüşmedi, 'açık işlem' sayılmaz (kullanıcı karışıklığı).
        Anlık fiyat verilirse her pozisyonun şu anki kâr/zarar durumu eklenir."""
        if store is None:
            return []
        esik = self._state()["meta_threshold"]
        try:
            with store._conn() as conn:
                rows = [dict(r) for r in conn.execute(
                    """SELECT direction, entry_price, tp_price, sl_price, created_at,
                              interval, meta_prob
                       FROM signals WHERE status='open' AND meta_prob >= ?
                       ORDER BY created_at DESC LIMIT 20""",
                    (esik,),
                )]
            # Anlık fiyat (kâr/zarar durumu için) — tek çağrı, hata sinyali bozmaz
            son_fiyat = None
            try:
                from main import binance_svc
                df = binance_svc.get_klines(config.SYMBOL, config.DEFAULT_INTERVAL, 2)
                son_fiyat = float(df["close"].iloc[-1])
            except Exception:
                pass
            out = []
            for r in rows:
                durum = None
                if son_fiyat and r["entry_price"]:
                    sign = 1 if r["direction"] == "LONG" else -1
                    # Şu anki kazanç/zarar yüzdesi (giriş→şimdiki fiyat, yöne göre)
                    yuzde = sign * (son_fiyat / r["entry_price"] - 1) * 100
                    durum = "kârda" if yuzde > 0 else "zararda"
                out.append({
                    "yon": r["direction"],
                    "giris": round(r["entry_price"], 1) if r["entry_price"] else None,
                    "hedef": round(r["tp_price"], 1) if r["tp_price"] else None,
                    "stop": round(r["sl_price"], 1) if r["sl_price"] else None,
                    "interval": r["interval"],
                    "meta_prob": r["meta_prob"],
                    "zaman": (r["created_at"] or "")[:16],
                    "anlik_fiyat": round(son_fiyat, 1) if son_fiyat else None,
                    "anlik_durum": durum,
                    "anlik_yuzde": round(yuzde, 2) if son_fiyat and r["entry_price"] else None,
                })
            return out
        except Exception:
            return []

    def sync_from_store(self, store) -> dict:
        """
        signal_store'daki ÇÖZÜLMÜŞ (label dolu) ve henüz paper'a işlenmemiş
        sinyalleri tarayıp hesaba işler. resolve_loop sonrası çağrılır.
        İdempotent: record_resolved_signal zaten signal_id tekilliğini korur.
        Sadece meta_prob >= eşik olan LONG/SHORT sinyaller işlenir.
        """
        with store._conn() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT * FROM signals
                   WHERE label IS NOT NULL AND direction IN ('LONG','SHORT')
                     AND meta_prob IS NOT NULL
                   ORDER BY created_at"""
            )]
        islenen = 0
        for sig in rows:
            if self.record_resolved_signal(sig):
                islenen += 1
        return {"yeni_islenen": islenen}

    def equity_curve(self) -> list[dict]:
        """Sermaye eğrisi — işlem işlem sermaye seyri (grafik için)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT closed_at, balance_after FROM paper_trades ORDER BY id"
            ).fetchall()
        start = self._state()["start_balance"]
        out = [{"zaman": "başlangıç", "sermaye": round(start, 2)}]
        out += [{"zaman": (r["closed_at"] or "")[:10], "sermaye": r["balance_after"]} for r in rows]
        return out

    # ------------------------------------------------------------------
    def reset(self, start_balance: float | None = None,
              risk_pct: float | None = None,
              cost_r: float | None = None,
              meta_threshold: float | None = None):
        """Hesabı sıfırla — tüm işlemleri sil, sermayeyi başa al, parametreleri ayarla."""
        st = self._state()
        sb = start_balance if start_balance is not None else st["start_balance"]
        rp = risk_pct if risk_pct is not None else st["risk_pct"]
        cr = cost_r if cost_r is not None else st["cost_r"]
        mt = meta_threshold if meta_threshold is not None else st["meta_threshold"]
        with self._conn() as conn:
            conn.execute("DELETE FROM paper_trades")
            conn.execute(
                """UPDATE paper_state SET start_balance=?, balance=?, risk_pct=?,
                   cost_r=?, meta_threshold=?, peak_balance=?, created_at=? WHERE id=1""",
                (sb, sb, rp, cr, mt, sb, datetime.utcnow().isoformat()),
            )
        return self.status()
