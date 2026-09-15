import React from 'react';
import './ModelPicker.css';
import { t, tv } from '../i18n';

/**
 * Araç bazlı model seçici. `models` = {id: aciklama} (status'tan gelir).
 * `disabled` çağrı sırasında kilitler. Etiketsiz, kompakt.
 *
 * Model listesi ve açıklamaları BACKEND'den gelir (backend/config.py →
 * CLAUDE_CHAT_MODELS); burada sabit model listesi TUTULMAZ. Kısa etiket,
 * açıklamanın tire öncesi kısmından üretilir: "Fable 5 — en güçlü" → "FABLE 5".
 */
export function shortLabel(id, desc) {
  const head = (desc || '').split('—')[0].trim();
  return (head || id).toUpperCase();
}

function ModelPicker({ models, value, onChange, disabled, label = 'MODEL' }) {
  const entries = Object.entries(models || { [value]: '' });
  return (
    <label className="model-picker" title={tv(models?.[value]) || t('Model seç')}>
      <span className="model-picker-label">{label}</span>
      <select
        className="model-picker-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {entries.map(([id, desc]) => (
          <option key={id} value={id} title={tv(desc)}>{shortLabel(id, desc)}</option>
        ))}
      </select>
    </label>
  );
}

export default ModelPicker;
