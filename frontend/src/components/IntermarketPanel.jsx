import React from 'react';
import './IntermarketPanel.css';
import { t } from '../i18n';

/* VantagePoint tarzı intermarket görünümü:
   BTC'nin ilişkili piyasalarla 90 günlük getiri korelasyonu */

function CorrBar({ value }) {
  if (value === null || value === undefined) {
    return <div className="corr-bar"><div className="corr-mid" /></div>;
  }
  const pct = Math.min(50, Math.abs(value) * 50);
  const positive = value >= 0;
  return (
    <div className="corr-bar">
      <div className="corr-mid" />
      <div
        className={`corr-fill ${positive ? 'pos' : 'neg'}`}
        style={positive ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
      />
    </div>
  );
}

function fmt(v, digits = 2) {
  if (v === null || v === undefined) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: digits });
}

function IntermarketPanel({ data }) {
  const markets = data?.piyasalar;

  return (
    <div className="panel intermarket-panel">
      <div className="panel-head">
        <span className="panel-title">{t("Intermarket · 90g Korelasyon")}</span>
      </div>

      {!markets ? (
        <div className="panel-empty">{t("Intermarket verisi yükleniyor…")}</div>
      ) : (
        <div className="im-table">
          <div className="im-row im-head">
            <span>{t("PİYASA")}</span>
            <span className="im-r">{t("DEĞER")}</span>
            <span className="im-r">{t("GÜN%")}</span>
            <span className="im-c">{t("KORELASYON")}</span>
            <span className="im-r">r</span>
          </div>
          {Object.entries(markets).map(([key, m]) => {
            const chg = m.degisim_yuzde;
            return (
              <div className="im-row" key={key}>
                <span className="im-name">{m.ad}</span>
                <span className="im-r num">{fmt(m.deger)}</span>
                <span className={`im-r num ${chg > 0 ? 'up' : chg < 0 ? 'down' : ''}`}>
                  {chg !== null && chg !== undefined ? `${chg > 0 ? '+' : ''}${chg.toFixed(2)}` : '—'}
                </span>
                <CorrBar value={m.korelasyon_90g} />
                <span className={`im-r num ${m.korelasyon_90g > 0.15 ? 'up' : m.korelasyon_90g < -0.15 ? 'down' : ''}`}>
                  {m.korelasyon_90g !== null && m.korelasyon_90g !== undefined ? m.korelasyon_90g.toFixed(2) : '—'}
                </span>
              </div>
            );
          })}
          <div className="im-note">
            {t("Pozitif korelasyonlu piyasa düşerken BTC long = ters rüzgar.")}
          </div>
        </div>
      )}
    </div>
  );
}

export default IntermarketPanel;
