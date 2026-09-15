import React from 'react';
import './MarketBar.css';
import { t, getLang, LanguageToggle } from '../i18n';

function MarketBar({ ticker, analysisData, lastUpdate }) {
  const price = ticker?.price;
  const changePct = ticker?.change_pct;
  const isUp = changePct >= 0;

  const fg = analysisData?.fear_greed;
  const macro = analysisData?.macro || {};
  const funding = analysisData?.funding_rate?.funding_rate;

  const fgColor = (fg?.value || 50) <= 25 ? 'down' : (fg?.value || 50) >= 75 ? 'up' : 'amber';
  const fundingPct = funding ? (funding * 100).toFixed(4) : '—';
  const fundingColor = funding > 0.0003 ? 'up' : funding < -0.0001 ? 'down' : '';

  return (
    <header className="market-bar">
      <div className="mb-left">
        <div className="brand">
          <span className="brand-name">17MONEY</span>
          <span className="brand-sub">FORECAST TERMINAL</span>
        </div>
        <div className="price-block">
          <span className="price-symbol">BTC/USDT·P</span>
          <span className="price-value num">
            {price ? `$${price.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}` : '—'}
          </span>
          <span className={`price-change num ${isUp ? 'up' : 'down'}`}>
            {isUp ? '▲' : '▼'} {changePct !== undefined && changePct !== null ? Math.abs(changePct).toFixed(2) : '0.00'}%
          </span>
        </div>
      </div>

      <div className="mb-center">
        <MarketItem label="DXY" value={macro.dxy?.toFixed(2)} />
        <MarketItem label="VIX" value={macro.vix?.toFixed(2)} />
        <MarketItem label={t("ALTIN")} value={macro.gold ? macro.gold.toFixed(0) : null} />
        <MarketItem label="S&P" value={macro.sp500?.toFixed(0)} />
        <div className={`mb-item ${fgColor}`}>
          <span className="mbi-label">F&G</span>
          <span className="mbi-value num">{fg?.value ?? '—'}</span>
        </div>
        <div className={`mb-item ${fundingColor}`}>
          <span className="mbi-label">FUNDING</span>
          <span className="mbi-value num">{fundingPct}%</span>
        </div>
      </div>

      <div className="mb-right">
        <span className="engine-badge">CLAUDE FABLE 5</span>
        <LanguageToggle />
        {lastUpdate && (
          <span className="last-update num">
            {lastUpdate.toLocaleTimeString(getLang() === 'tr' ? 'tr-TR' : 'en-US',
              { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
        <span className="status-dot" />
      </div>
    </header>
  );
}

function MarketItem({ label, value }) {
  return (
    <div className="mb-item">
      <span className="mbi-label">{label}</span>
      <span className="mbi-value num">{value || '—'}</span>
    </div>
  );
}

export default MarketBar;
