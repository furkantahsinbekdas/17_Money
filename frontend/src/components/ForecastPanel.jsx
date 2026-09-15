import React, { useState } from 'react';
import axios from 'axios';
import ModelPicker, { shortLabel } from './ModelPicker';
import './ForecastPanel.css';

/* Yön Endeksi gauge'u — yarım daire, 0-100 */
function polar(cx, cy, r, deg) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
}

function arcPath(cx, cy, r, fromDeg, toDeg) {
  const a = polar(cx, cy, r, fromDeg);
  const b = polar(cx, cy, r, toDeg);
  const large = Math.abs(fromDeg - toDeg) > 180 ? 1 : 0;
  return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
}

function Gauge({ value }) {
  // 0 → 180°, 100 → 0°
  const needleDeg = 180 - (Math.max(0, Math.min(100, value)) * 1.8);
  const tip = polar(100, 96, 62, needleDeg);
  const base1 = polar(100, 96, 7, needleDeg + 90);
  const base2 = polar(100, 96, 7, needleDeg - 90);

  return (
    <svg viewBox="0 0 200 104" className="gauge-svg">
      {/* zonlar: ayı 0-42, nötr 42-58, boğa 58-100 */}
      <path d={arcPath(100, 96, 78, 180, 104.4)} className="gz gz-down" />
      <path d={arcPath(100, 96, 78, 104.4, 75.6)} className="gz gz-flat" />
      <path d={arcPath(100, 96, 78, 75.6, 0)} className="gz gz-up" />
      {/* tikler */}
      {[0, 25, 50, 75, 100].map(t => {
        const d = 180 - t * 1.8;
        const o = polar(100, 96, 86, d);
        const i = polar(100, 96, 72, d);
        return <line key={t} x1={o.x} y1={o.y} x2={i.x} y2={i.y} className="g-tick" />;
      })}
      <text x={14} y={102} className="g-lbl">0</text>
      <text x={178} y={102} className="g-lbl">100</text>
      <text x={96} y={16} className="g-lbl">50</text>
      {/* ibre */}
      <polygon
        points={`${tip.x},${tip.y} ${base1.x},${base1.y} ${base2.x},${base2.y}`}
        className="g-needle"
      />
      <circle cx="100" cy="96" r="4.5" className="g-hub" />
    </svg>
  );
}

const YON_ICON = { 'yukarı': '▲', 'aşağı': '▼', 'yatay': '◄►' };
const YON_CLASS = { 'yukarı': 'up', 'aşağı': 'down', 'yatay': 'flat' };
const VADE_LABEL = { kisa: 'KISA · 15m-1h', orta: 'ORTA · 1h-4h', uzun: 'UZUN · 4h-1d' };

function VectorRow({ name, v }) {
  if (!v) return null;
  const cls = YON_CLASS[v.yon] || 'flat';
  return (
    <div className="vec-row">
      <span className="vec-name">{VADE_LABEL[name]}</span>
      <div className="vec-bar">
        <div className="vec-bar-mid" />
        <div
          className={`vec-bar-fill ${cls}`}
          style={
            v.endeks >= 50
              ? { left: '50%', width: `${(v.endeks - 50)}%` }
              : { right: '50%', width: `${(50 - v.endeks)}%` }
          }
        />
      </div>
      <span className={`vec-val num ${cls}`}>{YON_ICON[v.yon]} {v.endeks?.toFixed(0)}</span>
    </div>
  );
}

function RangeBar({ aralik, price }) {
  if (!aralik || !price) return null;
  const { beklenen_dusuk: lo, beklenen_yuksek: hi } = aralik;
  const pct = Math.max(2, Math.min(98, ((price - lo) / (hi - lo)) * 100));
  return (
    <div className="range-block">
      <div className="range-caption">TAHMİNİ 24S ARALIK <span className="range-atr num">ATR1d {aralik.atr_1d?.toLocaleString()}</span></div>
      <div className="range-bar">
        <div className="range-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="range-ends num">
        <span className="down">{lo?.toLocaleString()}</span>
        <span className="range-now">{price?.toLocaleString()}</span>
        <span className="up">{hi?.toLocaleString()}</span>
      </div>
    </div>
  );
}

function ForecastPanel({ forecast, apiBase, aiStatus, model, setModel }) {
  const [aiFc, setAiFc] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);

  const fetchAiForecast = async () => {
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await axios.get(`${apiBase}/api/ai/forecast?model=${encodeURIComponent(model)}`, { timeout: 180000 });
      setAiFc(res.data.ai_tahmin);
    } catch (err) {
      setAiError(err.response?.data?.detail || 'AI tahmin alınamadı');
    }
    setAiLoading(false);
  };

  const modelLabel = shortLabel(model, aiStatus?.modeller?.[model]);

  if (!forecast) {
    return (
      <div className="panel forecast-panel">
        <div className="panel-head"><span className="panel-title">Tahmin Motoru</span></div>
        <div className="panel-empty">Tahmin verisi yükleniyor…</div>
      </div>
    );
  }

  const yonCls = YON_CLASS[forecast.yon] || 'flat';

  return (
    <div className="panel forecast-panel">
      <div className="panel-head">
        <span className="panel-title">Tahmin Motoru</span>
        <span className={`mtf-badge ${forecast.mtf_uyumlu ? 'ok' : 'warn'}`}>
          {forecast.mtf_uyumlu ? 'MTF UYUMLU' : 'MTF ÇELİŞKİLİ'}
        </span>
      </div>

      <div className="gauge-wrap">
        <Gauge value={forecast.yon_endeksi} />
        <div className="gauge-readout">
          <span className={`gauge-value num ${yonCls}`}>{forecast.yon_endeksi?.toFixed(0)}</span>
          <span className={`gauge-dir ${yonCls}`}>{YON_ICON[forecast.yon]} {forecast.yon?.toUpperCase()}</span>
          <span className="gauge-strength">{forecast.guc?.replace('_', ' ')}</span>
        </div>
      </div>

      <div className="vec-list">
        <VectorRow name="kisa" v={forecast.vektorler?.kisa} />
        <VectorRow name="orta" v={forecast.vektorler?.orta} />
        <VectorRow name="uzun" v={forecast.vektorler?.uzun} />
      </div>

      <RangeBar aralik={forecast.tahmini_aralik_24s} price={forecast.current_price} />

      <div className="ai-fc-section">
        <button className="ai-fc-btn" onClick={fetchAiForecast} disabled={aiLoading}>
          {aiLoading ? `${modelLabel} DÜŞÜNÜYOR…` : 'AI TAHMİN ÜRET'}
        </button>
        <div className="ai-fc-toolbar">
          <ModelPicker
            models={aiStatus?.modeller}
            value={model}
            onChange={setModel}
            disabled={aiLoading}
          />
        </div>
        {aiError && <div className="ai-fc-error">{aiError}</div>}

        {aiFc && !aiError && (
          <div className="ai-fc-result">
            <div className="ai-fc-headline">
              <span className={`ai-fc-dir ${YON_CLASS[aiFc.yon] || 'flat'}`}>
                {YON_ICON[aiFc.yon]} {aiFc.yon?.toUpperCase()}
              </span>
              <span className="ai-fc-prob num">%{aiFc.olasilik}</span>
              <span className="ai-fc-horizon">{aiFc.ufuk}</span>
            </div>
            {aiFc.tahmini_aralik && (
              <div className="ai-fc-range num">
                AI aralık: <span className="down">{aiFc.tahmini_aralik.dusuk?.toLocaleString()}</span>
                {' — '}
                <span className="up">{aiFc.tahmini_aralik.yuksek?.toLocaleString()}</span>
              </div>
            )}
            <p className="ai-fc-text">{aiFc.gerekce}</p>
            {aiFc.vade_gorunumu && (
              <div className="ai-fc-horizons">
                <div><b>Kısa:</b> {aiFc.vade_gorunumu.kisa}</div>
                <div><b>Orta:</b> {aiFc.vade_gorunumu.orta}</div>
                <div><b>Uzun:</b> {aiFc.vade_gorunumu.uzun}</div>
              </div>
            )}
            {aiFc.intermarket_yorum && (
              <p className="ai-fc-text dim">{aiFc.intermarket_yorum}</p>
            )}
            {aiFc.riskler?.length > 0 && (
              <div className="ai-fc-risks">
                {aiFc.riskler.map((r, i) => <span key={i} className="risk-tag">⚠ {r}</span>)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default ForecastPanel;
