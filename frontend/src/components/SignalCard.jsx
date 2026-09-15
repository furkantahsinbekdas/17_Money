import React, { useState } from 'react';
import './SignalCard.css';
import { t, tv } from '../i18n';

const YON_DOT = { 'boğa': 'up', 'ayı': 'down', 'nötr': 'flat' };

function fmtPrice(v) {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number'
    ? `$${v.toLocaleString('en-US', { maximumFractionDigits: 1 })}`
    : v;
}

function SignalCard({ signal, technicalData }) {
  const [showIndicators, setShowIndicators] = useState(false);

  if (!signal) {
    return (
      <div className="signal-card empty">
        <div className="signal-empty-text">
          {t("Uzman analiz için \"SİNYAL\" veya web araştırmalı \"DERİN\" butonunu kullanın.")}
        </div>
        {technicalData && (
          <div className="quick-analysis">
            <QuickRow label="Order Blocks" value={t('{n} tespit', { n: technicalData.order_blocks?.length || 0 })} />
            <QuickRow label="FVG" value={t('{n} tespit', { n: technicalData.fvg?.length || 0 })} />
            <QuickRow
              label={t("Yapısal")}
              value={
                technicalData.structure?.choch
                  ? `CHoCH ${technicalData.structure.choch.direction}`
                  : technicalData.structure?.bos
                    ? `BOS ${technicalData.structure.bos.direction}`
                    : '—'
              }
            />
          </div>
        )}
      </div>
    );
  }

  if (signal.error) {
    return (
      <div className="signal-card error-card">
        <div className="signal-badge bekle">{t("HATA")}</div>
        <div className="signal-analysis">{signal.analiz}</div>
      </div>
    );
  }

  const sinyalType = (signal.sinyal || 'BEKLE').toUpperCase();
  const badgeClass = sinyalType === 'LONG' ? 'long' : sinyalType === 'SHORT' ? 'short' : 'bekle';
  const guven = signal.guven_skoru ?? 0;
  const hedefler = signal.hedefler?.length ? signal.hedefler : (signal.hedef ? [signal.hedef] : []);

  return (
    <div className="signal-card">
      {/* Üst satır: sinyal + rejim + güven */}
      <div className="signal-top">
        <div className={`signal-badge ${badgeClass}`}>{t(sinyalType)}</div>
        {signal.piyasa_rejimi && (
          <span className="regime-tag">{tv(signal.piyasa_rejimi)?.replace(/_/g, ' ')}</span>
        )}
        <div className="signal-confidence">
          <div className="conf-bar">
            <div
              className={`conf-fill ${guven >= 70 ? 'high' : guven >= 40 ? 'mid' : 'low'}`}
              style={{ width: `${guven}%` }}
            />
          </div>
          <span className="conf-value num">%{guven}</span>
        </div>
      </div>

      {signal.trend_ozet && <div className="signal-trend">{signal.trend_ozet}</div>}

      {/* Seviyeler */}
      <div className="signal-levels">
        <LevelRow label={t("GİRİŞ")} value={fmtPrice(signal.giris)} cls="entry" />
        <LevelRow label="STOP" value={fmtPrice(signal.stop_loss)} cls="stop" />
        {hedefler.map((h, i) => (
          <LevelRow key={i} label={`TP${i + 1}`} value={fmtPrice(h)} cls="target" />
        ))}
      </div>

      {/* Risk parametreleri */}
      <div className="risk-strip">
        {signal.risk_odul && <span className="risk-chip">{t("R/Ö")} {signal.risk_odul}</span>}
        {signal.kaldirac_onerisi && <span className="risk-chip">{t("KALDIRAÇ")} {signal.kaldirac_onerisi}</span>}
        {signal.pozisyon_riski_yuzde != null && (
          <span className="risk-chip">{t("RİSK %")}{signal.pozisyon_riski_yuzde}</span>
        )}
      </div>

      {signal.analiz && <div className="signal-analysis">{signal.analiz}</div>}

      {/* Senaryolar */}
      {signal.senaryolar && (
        <div className="scenarios">
          <div className="scenario bull">
            <span className="sc-title">{t("▲ BOĞA")}</span>
            <p>{signal.senaryolar.boga}</p>
          </div>
          <div className="scenario bear">
            <span className="sc-title">{t("▼ AYI")}</span>
            <p>{signal.senaryolar.ayi}</p>
          </div>
        </div>
      )}

      {/* Geçersizlik */}
      {signal.gecersizlik_kosulu && (
        <div className="invalidation">
          <span className="inv-label">{t("GEÇERSİZLİK")}</span>
          <span>{signal.gecersizlik_kosulu}</span>
        </div>
      )}

      {/* Gösterge davranış analizi */}
      {signal.gosterge_analizi?.length > 0 && (
        <div className="ind-analysis">
          <button className="ind-toggle" onClick={() => setShowIndicators(s => !s)}>
            {t('GÖSTERGE ANALİZİ ({n})', { n: signal.gosterge_analizi.length })} {showIndicators ? '▾' : '▸'}
          </button>
          {showIndicators && (
            <div className="ind-list">
              {signal.gosterge_analizi.map((g, i) => (
                <div className="ind-item" key={i}>
                  <div className="ind-head">
                    <span className={`ind-dot ${YON_DOT[g.yon] || 'flat'}`} />
                    <span className="ind-name">{g.gosterge}</span>
                    <span className="ind-state">{tv(g.durum)}</span>
                  </div>
                  <p className="ind-behavior">{g.davranis}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Kritik seviyeler + uyarılar */}
      {signal.kritik_seviyeler?.length > 0 && (
        <div className="signal-levels-list">
          {signal.kritik_seviyeler.map((s, i) => (
            <span key={i} className="level-tag num">{s}</span>
          ))}
        </div>
      )}

      {signal.uyarilar?.length > 0 && (
        <div className="warnings">
          {signal.uyarilar.map((u, i) => (
            <div key={i} className="warning-row">⚠ {u}</div>
          ))}
        </div>
      )}

      {/* Derin araştırma raporu (deep=true ile geldiyse) */}
      {signal.arastirma?.rapor && (
        <details className="research-details">
          <summary>{t("DERİN ARAŞTIRMA RAPORU")}</summary>
          <div className="research-body">{signal.arastirma.rapor}</div>
          {signal.arastirma.kaynaklar?.length > 0 && (
            <div className="research-sources">
              {signal.arastirma.kaynaklar.map((k, i) => (
                <a key={i} href={k.url} target="_blank" rel="noreferrer">{k.title}</a>
              ))}
            </div>
          )}
        </details>
      )}
    </div>
  );
}

function LevelRow({ label, value, cls }) {
  if (!value || value === '—') return null;
  return (
    <div className={`level-row ${cls}`}>
      <span className="level-label">{label}</span>
      <span className="level-value num">{value}</span>
    </div>
  );
}

function QuickRow({ label, value }) {
  return (
    <div className="quick-row">
      <span className="quick-label">{label}</span>
      <span className="quick-value">{value}</span>
    </div>
  );
}

export default SignalCard;
