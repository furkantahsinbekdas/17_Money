import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './PaperPanel.css';

/**
 * Paper Trading Paneli — Aşama 5: canlı kanıt (GERÇEK PARA YOK).
 * Sistem arka planda çözülen sinyalleri sanal hesaba işler; bu panel
 * sermaye, getiri, açık/kapalı istatistik ve son işlemleri gösterir.
 * Amaç: "geçmişteki performans canlıda tutuyor mu?" sorusunu gözle görmek.
 */
export default function PaperPanel({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${apiBase}/api/paper/status`);
      setData(r.data);
      setErr(null);
    } catch (e) {
      setErr('Paper hesap durumu alınamadı (backend kapalı olabilir).');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 15000); // 15 sn'de bir tazele
    return () => clearInterval(t);
  }, [fetchStatus]);

  const reset = async () => {
    if (!window.confirm('Paper hesabı sıfırlamak istediğine emin misin? Tüm sanal işlemler silinir.')) return;
    try {
      await axios.post(`${apiBase}/api/paper/reset`, {});
      fetchStatus();
    } catch (e) {
      setErr('Sıfırlama başarısız.');
    }
  };

  const breakerReset = async () => {
    if (!window.confirm(
      'Devre kesiciyi yeniden etkinleştirmek istediğine emin misin?\n\n' +
      'Sistem büyük bir düşüş yüzünden kendini durdurdu. Devam etmeden önce ' +
      'ne olduğuna bakmış olman önerilir. Onaylarsan tepe sermaye mevcut ' +
      'sermayeye çekilir (temiz sayfa) ve yeni işlemler tekrar açılır.')) return;
    try {
      await axios.post(`${apiBase}/api/paper/breaker/reset`, {});
      fetchStatus();
    } catch (e) {
      setErr('Devre kesici sıfırlanamadı.');
    }
  };

  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState(null);
  const [trace, setTrace] = useState(null);
  const [oylama, setOylama] = useState(null);
  const [interval, setIntervalSel] = useState('1h');
  const [withVote, setWithVote] = useState(false);
  const runOnce = async () => {
    setRunning(true);
    setRunMsg(null);
    setOylama(null);
    try {
      const r = await axios.post(
        `${apiBase}/api/paper/run-once?interval=${interval}&with_vote=${withVote}`,
        {}, { timeout: withVote ? 120000 : 60000 });
      const d = r.data;
      const parcalar = [];
      if (d.yeni_sinyal_uretildi) parcalar.push('1 yeni sinyal üretildi');
      else parcalar.push('piyasa yatay — yeni sinyal yok');
      if (d.cozulen) parcalar.push(`${d.cozulen} sinyal çözüldü`);
      if (d.paper_yeni_islem) parcalar.push(`${d.paper_yeni_islem} işlem hesaba geçti`);
      if (d.hala_acik) parcalar.push(`${d.hala_acik} pozisyon hâlâ açık (sonuç bekliyor)`);
      setRunMsg(parcalar.join(' · '));
      setTrace(d.karar_izi || null);
      setOylama(d.oylama || null);
      fetchStatus();
    } catch (e) {
      setRunMsg('Çalıştırma başarısız (backend/Binance erişimi?).');
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <div className="paper-wrap"><div className="paper-loading">Paper hesap yükleniyor…</div></div>;
  if (err) return <div className="paper-wrap"><div className="paper-error">{err}</div></div>;

  const d = data || {};
  const kar = (d.getiri_yuzde || 0) >= 0;
  const sermaye = d.sermaye ?? 0;

  return (
    <div className="paper-wrap">
      <div className="paper-head">
        <div>
          <h2 className="paper-title">PAPER TRADING — CANLI KANIT</h2>
          <p className="paper-sub">Gerçek para yok. Sistem her çözülen sinyali sanal hesaba işler. Asıl soru: geçmişteki kenar canlıda tutuyor mu?</p>
        </div>
        <div className="paper-actions">
          <div className="paper-iv-sel">
            {['15m', '1h', '4h', '1d'].map((iv) => (
              <button
                key={iv}
                className={`paper-iv-btn ${interval === iv ? 'active' : ''}`}
                onClick={() => setIntervalSel(iv)}
                disabled={running}
              >{iv.toUpperCase()}</button>
            ))}
          </div>
          <button
            className={`paper-vote-toggle ${withVote ? 'on' : ''}`}
            onClick={() => setWithVote(!withVote)}
            disabled={running}
            title="Claude'a danış (oylama) — kredi yakar"
          >{withVote ? '🗳 CLAUDE OYU: AÇIK' : '🗳 CLAUDE OYU: KAPALI'}</button>
          <button className="paper-run" onClick={runOnce} disabled={running}>
            {running ? '● ÇALIŞIYOR…' : '▶ MODELİ ÇALIŞTIR'}
          </button>
          <button className="paper-reset" onClick={reset}>⟲ SIFIRLA</button>
        </div>
      </div>
      {/* DEVRE KESİCİ — güvenlik ağı bandı */}
      {d.devre_kesici?.tetiklendi && (
        <div className="paper-breaker tripped">
          <div className="paper-breaker-text">
            <span className="paper-breaker-title">🛑 DEVRE KESİCİ TETİKLENDİ</span>
            <span className="paper-breaker-reason">{d.devre_kesici.sebep}</span>
          </div>
          <button className="paper-breaker-btn" onClick={breakerReset}>
            ✓ ONAYLIYORUM — YENİDEN ETKİNLEŞTİR
          </button>
        </div>
      )}
      {!d.devre_kesici?.tetiklendi && d.devre_kesici?.sogumada && (
        <div className="paper-breaker cooldown">
          <span className="paper-breaker-title">⚠ SOĞUMA MODU</span>
          <span className="paper-breaker-reason">
            {d.devre_kesici.ardisik_kayip} ardışık kayıp — risk yarıya indirildi
            (şu an %{d.devre_kesici.efektif_risk_yuzde}). 2 ardışık kazançla normale döner.
          </span>
        </div>
      )}

      {runMsg && <div className="paper-runmsg">{runMsg}</div>}

      {trace && (
        <div className="paper-trace">
          <div className="paper-trace-head">
            <span>KARAR İZİ — arkada ne oldu</span>
            <span className={`paper-trace-karar ${trace.karar === 'İŞLE' ? 'pos' : 'neg'}`}>{trace.karar}</span>
          </div>
          {trace.adimlar?.map((a) => (
            <div className="paper-trace-step" key={a.no}>
              <div className="paper-trace-num">{a.no}</div>
              <div className="paper-trace-body">
                <div className="paper-trace-ad">{a.ad} <span className="paper-trace-sonuc">{a.sonuc}</span></div>
                <div className="paper-trace-aciklama">{a.aciklama}</div>
              </div>
            </div>
          ))}
          <div className="paper-trace-ozet">{trace.ozet}</div>
        </div>
      )}

      {oylama && (
        <div className="paper-vote">
          <div className="paper-vote-head">
            <span>🗳 OYLAMA — model + Claude (Seventeen AI)</span>
            <span className={`paper-vote-karar ${oylama.karar === 'İŞLE' ? 'pos' : 'neg'}`}>
              {oylama.karar} · {oylama.uzlasma}
            </span>
          </div>
          <div className="paper-vote-grid">
            <VoteCard who="MODEL (sayı)" v={oylama.oylar?.model} />
            <VoteCard who="CLAUDE (dil)" v={oylama.oylar?.claude} claude />
          </div>
          <div className="paper-vote-ozet">{oylama.gerekce}</div>
        </div>
      )}

      {/* Üst metrik kartları */}
      <div className="paper-cards">
        <div className="paper-card">
          <div className="paper-card-l">Başlangıç</div>
          <div className="paper-card-v">${(d.baslangic ?? 0).toLocaleString()}</div>
        </div>
        <div className="paper-card">
          <div className="paper-card-l">Güncel sermaye</div>
          <div className={`paper-card-v ${kar ? 'pos' : 'neg'}`}>${sermaye.toLocaleString()}</div>
        </div>
        <div className="paper-card">
          <div className="paper-card-l">Getiri</div>
          <div className={`paper-card-v ${kar ? 'pos' : 'neg'}`}>{kar ? '+' : ''}{d.getiri_yuzde ?? 0}%</div>
        </div>
        <div className="paper-card">
          <div className="paper-card-l">Max düşüş</div>
          <div className="paper-card-v neg">{d.dusus_yuzde ?? 0}%</div>
        </div>
      </div>

      {/* İstatistik şeridi */}
      <div className="paper-stats">
        <Stat l="İşlem" v={d.islem_sayisi ?? 0} />
        <Stat l="Kazanan" v={d.kazanan ?? 0} cls="pos" />
        <Stat l="Kaybeden" v={d.kaybeden ?? 0} cls="neg" />
        <Stat l="Kazanma oranı" v={d.kazanma_orani != null ? `${(d.kazanma_orani * 100).toFixed(1)}%` : '—'} />
        <Stat l="Risk/işlem" v={`${d.risk_yuzde ?? 2}%`} />
        <Stat l="Model eşiği" v={d.esik ?? '—'} />
      </div>

      {/* Açık pozisyonlar — sonuç bekleyenler (sinyal başlatmasan da görünür) */}
      {d.acik_pozisyonlar && d.acik_pozisyonlar.length > 0 && (
        <div className="paper-open">
          <div className="paper-open-head">
            AÇIK POZİSYONLAR — model onayladı, sonuç bekliyor ({d.acik_pozisyonlar.length})
          </div>
          {d.acik_pozisyonlar.map((p, i) => (
            <div className="paper-open-row" key={i}>
              <span className={`paper-dir ${p.yon === 'LONG' ? 'pos' : 'neg'}`}>{p.yon}</span>
              <span className="paper-open-iv">{p.interval}</span>
              <span className="paper-open-px">giriş {p.giris?.toLocaleString()}</span>
              <span className="paper-open-px pos">hedef {p.hedef?.toLocaleString()}</span>
              <span className="paper-open-px neg">stop {p.stop?.toLocaleString()}</span>
              {p.anlik_durum ? (
                <span className={`paper-open-durum ${p.anlik_durum === 'kârda' ? 'pos' : 'neg'}`}>
                  {p.anlik_durum === 'kârda' ? '▲' : '▼'} {p.anlik_yuzde > 0 ? '+' : ''}{p.anlik_yuzde}%
                </span>
              ) : <span className="paper-open-durum">—</span>}
              <span className="paper-open-time">{p.zaman}</span>
            </div>
          ))}
        </div>
      )}

      {d.islem_sayisi === 0 && (!d.acik_pozisyonlar || d.acik_pozisyonlar.length === 0) && (
        <div className="paper-empty">
          Henüz işlenmiş sanal işlem yok. Sistem canlı sinyal üretip çözdükçe (model onaylayan
          sinyaller) bu hesap dolacak. Sinyal üretmek için TERMİNAL'den SİNYAL'e bas veya saatlik
          otomatik toplama döngüsünü bekle.
        </div>
      )}

      {/* Son işlemler */}
      {d.son_islemler && d.son_islemler.length > 0 && (
        <div className="paper-trades">
          <div className="paper-trades-head">SON İŞLEMLER</div>
          {d.son_islemler.map((t, i) => (
            <div className="paper-trade-row" key={i}>
              <span className={`paper-dir ${t.yon === 'LONG' ? 'pos' : 'neg'}`}>{t.yon}</span>
              <span className={`paper-res ${t.sonuc === 'kazanç' ? 'pos' : 'neg'}`}>{t.sonuc}</span>
              <span className={`paper-pnl ${t.kar_dolar >= 0 ? 'pos' : 'neg'}`}>
                {t.kar_dolar >= 0 ? '+' : ''}${t.kar_dolar}
              </span>
              <span className="paper-bal">${t.sermaye?.toLocaleString()}</span>
              <span className="paper-time">{t.zaman}</span>
            </div>
          ))}
        </div>
      )}

      <div className="paper-note">
        Dürüstlük notu: Bu sonuçlar gerçekçi maliyet ({d.maliyet_r ?? 0.06}R/işlem) dahil, her işlemde
        sermayenin %{d.risk_yuzde ?? 2}'si riske atılarak hesaplanır. Bileşik (kar tekrar yatırılır).
        Paper iyi gitse bile gerçek parada slipaj ve duygu eklenir — bu bir prova, garanti değil.
      </div>
    </div>
  );
}

function Stat({ l, v, cls }) {
  return (
    <div className="paper-stat">
      <span className="paper-stat-l">{l}</span>
      <span className={`paper-stat-v ${cls || ''}`}>{v}</span>
    </div>
  );
}

function VoteCard({ who, v, claude }) {
  if (!v) return null;
  const oy = v.oy || 'çekimser';
  const cls = oy === 'yükseliş' ? 'pos' : oy === 'düşüş' ? 'neg' : 'cek';
  return (
    <div className={`paper-vote-card ${claude ? 'claude' : ''}`}>
      <div className="paper-vote-who">{who}</div>
      <div className={`paper-vote-oy ${cls}`}>
        {oy === 'yükseliş' ? '▲ YÜKSELİŞ' : oy === 'düşüş' ? '▼ DÜŞÜŞ' : '○ ÇEKİMSER'}
        {v.guven != null && <span className="paper-vote-guven"> · güven {v.guven}</span>}
      </div>
      {v.gerekce && <div className="paper-vote-gerekce">{v.gerekce}</div>}
      {v.haber_riski && v.haber_riski !== 'yok' && (
        <div className="paper-vote-haber">⚠ haber riski: {v.haber_riski}</div>
      )}
    </div>
  );
}
