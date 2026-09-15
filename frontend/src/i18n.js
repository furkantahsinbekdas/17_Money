/**
 * Hafif i18n katmanı — kaynak dil Türkçe, ikinci dil İngilizce.
 *
 * Tasarım:
 *  - Modül düzeyinde tek bir dil durumu (`currentLang`) tutulur; bu yüzden `t()`
 *    hem React bileşenlerinde hem de yardımcı fonksiyonlarda doğrudan çağrılabilir.
 *  - `t('Türkçe metin')` → TR modunda metnin kendisini döndürür (kaynak = TR),
 *    EN modunda sözlükteki karşılığını döndürür. Sözlükte olmayan metin aynen kalır.
 *  - `tv(deger)` → backend'den gelen Türkçe DEĞERLERİ (yön, güç, rejim, kuyruk...)
 *    çevirir; TR modunda dokunmaz.
 *  - Dil seçimi localStorage'da saklanır; ilk açılışta REACT_APP_DEFAULT_LANG,
 *    yoksa tarayıcı dili (tr → TR, diğer → EN) kullanılır.
 *
 * Kullanım:
 *   import { t, tv, LanguageToggle, useLang } from '../i18n';
 *   ... t('SİNYAL') ... tv(forecast.guc) ...
 *   <LanguageToggle />
 */
import React from 'react';
import EN from './i18n/en.json';
import VALUES from './i18n/values.json';
import './i18n.css';

export const LANG_KEY = '17money.lang';
export const LANGS = ['tr', 'en'];
export const LANG_LABEL = { tr: 'TR', en: 'EN' };

/* Sözlükler JSON dosyalarında tutulur (araçlarla okunabilsin diye):
 *   - i18n/en.json     : TR → EN arayüz metinleri
 *   - i18n/values.json : backend'den gelen Türkçe DEĞER/etiket çevirileri
 */

function normalize(value) {
  return String(value).trim().toLowerCase().replace(/\s+/g, ' ');
}

function detectLang() {
  const env = (process.env.REACT_APP_DEFAULT_LANG || '').trim().toLowerCase();
  try {
    const saved = window.localStorage.getItem(LANG_KEY);
    if (LANGS.includes(saved)) return saved;
  } catch (e) { /* localStorage kapalı olabilir */ }
  if (LANGS.includes(env)) return env;
  try {
    if ((navigator.language || '').toLowerCase().startsWith('tr')) return 'tr';
  } catch (e) { /* navigator yok */ }
  return 'en';
}

let currentLang = detectLang();
const listeners = new Set();

export function getLang() {
  return currentLang;
}

export function setLang(lang) {
  if (!LANGS.includes(lang) || lang === currentLang) return;
  currentLang = lang;
  try { window.localStorage.setItem(LANG_KEY, lang); } catch (e) { /* yok */ }
  try { document.documentElement.lang = lang; } catch (e) { /* yok */ }
  listeners.forEach((fn) => fn(lang));
}

export function toggleLang() {
  setLang(currentLang === 'tr' ? 'en' : 'tr');
}

export function subscribeLang(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Dil değişiminde yeniden render için: const [lang, toggle] = useLang(); */
export function useLang() {
  const [lang, set] = React.useState(currentLang);
  React.useEffect(() => subscribeLang(set), []);
  return [lang, toggleLang];
}

/** Arayüz metni çevirisi. t('Son {n} işlem', { n: 3 }) */
export function t(text, vars) {
  if (text === null || text === undefined) return text;
  const key = String(text);
  let out = key;
  if (currentLang === 'en') {
    out = Object.prototype.hasOwnProperty.call(EN, key) ? EN[key] : key;
  }
  if (!vars) return out;
  return out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** Backend'den gelen değer/etiket çevirisi (ör. yön: 'aşağı' → 'down'). */
export function tv(value) {
  if (value === null || value === undefined) return value;
  if (currentLang !== 'en') return value;
  if (typeof value !== 'string') return value;
  const hit = VALUES[value] || VALUES[normalize(value)];
  return hit === undefined ? value : hit;
}

/** Görünen dil değiştirme düğmesi (TR | EN). */
export function LanguageToggle({ className = '' }) {
  const [lang] = useLang();
  return (
    <div className={`lang-toggle ${className}`.trim()} role="group"
      aria-label={t('Arayüz dili')} title={lang === 'tr' ? t('Switch to English') : t('Türkçeye geç')}>
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          className={`lang-btn ${lang === l ? 'active' : ''}`}
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
        >
          {LANG_LABEL[l]}
        </button>
      ))}
    </div>
  );
}

export default { t, tv, useLang, LanguageToggle, getLang, setLang, toggleLang };
