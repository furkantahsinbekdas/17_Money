import React from 'react';
import ReactDOM from 'react-dom/client';
import axios from 'axios';
import './index.css';
import App from './App';
import { getLang, subscribeLang } from './i18n';
import reportWebVitals from './reportWebVitals';

// Backend'e her istekte seçili arayüz dilini bildir (backend/i18n.py: X-Lang).
// Böylece sunucu üretimi düz metinler (yorum/hüküm/sebep) de çevrilir.
axios.defaults.headers.common['X-Lang'] = getLang();
subscribeLang((lang) => {
  axios.defaults.headers.common['X-Lang'] = lang;
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
