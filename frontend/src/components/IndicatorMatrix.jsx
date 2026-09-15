import React from 'react';
import './IndicatorMatrix.css';

/* Gösterge Konsensüs Matrisi — her göstergenin her zaman dilimindeki yönü.
   Hücre rengi skora göre: yeşil (boğa) / kırmızı (ayı) / gri (nötr). */

const INDICATOR_LABELS = {
  ema_dizilimi: 'EMA Dizilimi',
  macd: 'MACD',
  adx_yon: 'ADX Yönü',
  yapi: 'Yapı (BOS/CHoCH)',
  divergence: 'RSI Uyumsuzluk',
  rsi: 'RSI',
  obv: 'OBV Hacim',
  bollinger: 'Bollinger',
  stoch_rsi: 'Stoch RSI',
  vwap: 'VWAP',
  premium_discount: 'Prem / Disc',
};

const TFS = ['15m', '1h', '4h', '1d'];

function cellClass(skor) {
  if (skor === null || skor === undefined) return 'na';
  if (skor >= 0.6) return 'up-2';
  if (skor > 0.05) return 'up-1';
  if (skor <= -0.6) return 'down-2';
  if (skor < -0.05) return 'down-1';
  return 'zero';
}

function IndicatorMatrix({ forecast }) {
  const detail = forecast?.zaman_dilimi_detay;

  if (!detail) {
    return (
      <div className="panel matrix-panel">
        <div className="panel-head"><span className="panel-title">Gösterge Konsensüsü</span></div>
        <div className="panel-empty">Veri bekleniyor…</div>
      </div>
    );
  }

  // tf -> {gosterge -> katkı}
  const byTf = {};
  for (const tf of TFS) {
    byTf[tf] = {};
    for (const k of detail[tf]?.katkilar || []) {
      byTf[tf][k.gosterge] = k;
    }
  }

  return (
    <div className="panel matrix-panel">
      <div className="panel-head">
        <span className="panel-title">Gösterge Konsensüsü</span>
        <div className="matrix-legend">
          <span className="lg-cell up-2" /> boğa
          <span className="lg-cell zero" /> nötr
          <span className="lg-cell down-2" /> ayı
        </div>
      </div>

      <div className="matrix-grid">
        <div className="mx-row mx-head">
          <span className="mx-name" />
          {TFS.map(tf => <span key={tf} className="mx-tf">{tf.toUpperCase()}</span>)}
          <span className="mx-tf mx-endeks">ENDEKS</span>
        </div>

        {Object.entries(INDICATOR_LABELS).map(([key, label]) => (
          <div className="mx-row" key={key}>
            <span className="mx-name">{label}</span>
            {TFS.map(tf => {
              const k = byTf[tf]?.[key];
              return (
                <span
                  key={tf}
                  className={`mx-cell ${cellClass(k?.skor)}`}
                  title={k ? `${label} · ${tf}\nskor: ${k.skor}\n${k.detay}` : '—'}
                />
              );
            })}
            <span className="mx-endeks-spacer" />
          </div>
        ))}

        {/* TF toplam endeks satırı */}
        <div className="mx-row mx-total">
          <span className="mx-name">TF ENDEKSİ</span>
          {TFS.map(tf => {
            const e = detail[tf]?.endeks;
            const cls = e >= 55 ? 'up' : e <= 45 ? 'down' : 'flat';
            return <span key={tf} className={`mx-total-val num ${cls}`}>{e?.toFixed(0) ?? '—'}</span>;
          })}
          <span className={`mx-total-val mx-endeks num ${forecast.yon_endeksi >= 55 ? 'up' : forecast.yon_endeksi <= 45 ? 'down' : 'flat'}`}>
            {forecast.yon_endeksi?.toFixed(0)}
          </span>
        </div>
      </div>
    </div>
  );
}

export default IndicatorMatrix;
