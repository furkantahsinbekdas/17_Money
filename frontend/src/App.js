import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import Chart from './components/Chart';
import Terminal from './components/Terminal';
import MarketBar from './components/MarketBar';
import ForecastPanel from './components/ForecastPanel';
import IntermarketPanel from './components/IntermarketPanel';
import IndicatorMatrix from './components/IndicatorMatrix';
import SciencePanel from './components/SciencePanel';
import PaperPanel from './components/PaperPanel';
import './App.css';

// Bağlantı/sembol ayarları ortam değişkenlerinden gelir (frontend/.env.example).
// Varsayılanlar yerel geliştirme içindir: backend http://localhost:8000.
const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:8000';
const WS_URL = process.env.REACT_APP_WS_URL
  || `${API_BASE.replace(/^http/, 'ws')}/ws/market`;
const SYMBOL = process.env.REACT_APP_SYMBOL || 'BTCUSDT';
const DEFAULT_MODEL = process.env.REACT_APP_DEFAULT_MODEL || 'claude-fable-5';
const DEFAULT_INTERVAL = process.env.REACT_APP_DEFAULT_INTERVAL || '1h';
const INTERVALS = (process.env.REACT_APP_INTERVALS || '15m,1h,4h,1d').split(',');

function App() {
  const [marketData, setMarketData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [intermarket, setIntermarket] = useState(null);
  const [klines, setKlines] = useState([]);
  const [interval, setInterval_] = useState(DEFAULT_INTERVAL);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [tab, setTab] = useState('terminal'); // 'terminal' | 'bilim' | 'paper'
  const [model, setModel] = useState(DEFAULT_MODEL); // TÜM araçlar paylaşır

  // AI sağlayıcı + model listesi + giriş durumu (tüm araçlar paylaşır)
  const fetchAiStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/ai/status`, { timeout: 30000 });
      setAiStatus(res.data);
      return res.data;
    } catch {
      return null;
    }
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [marketRes, klinesRes, analysisRes] = await Promise.all([
        axios.get(`${API_BASE}/api/market/btc?interval=${interval}`),
        axios.get(`${API_BASE}/api/market/klines?interval=${interval}&limit=200`),
        axios.get(`${API_BASE}/api/analysis/full/${SYMBOL}?interval=${interval}`),
      ]);

      setMarketData(marketRes.data);
      setKlines(klinesRes.data);
      setAnalysisData(analysisRes.data);
      setLastUpdate(new Date());
      setError(null);
      setLoading(false);
    } catch (err) {
      setError('Backend bağlantısı kurulamadı. start.bat çalıştırın.');
      setLoading(false);
    }
  }, [interval]);

  // Tahmin motoru — 2 dakikada bir (4 TF hesabı daha ağır)
  const fetchForecast = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/analysis/forecast/${SYMBOL}`, { timeout: 120000 });
      setForecast(res.data);
    } catch (err) { /* panel "yükleniyor" gösterir */ }
  }, []);

  // Intermarket — 5 dakikada bir (Yahoo verisi yavaş değişir)
  const fetchIntermarket = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/analysis/intermarket/${SYMBOL}`, { timeout: 120000 });
      setIntermarket(res.data);
    } catch (err) { /* panel "yükleniyor" gösterir */ }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = window.setInterval(fetchData, 60000);
    return () => window.clearInterval(timer);
  }, [fetchData]);

  useEffect(() => {
    fetchForecast();
    fetchIntermarket();
    const t1 = window.setInterval(fetchForecast, 120000);
    const t2 = window.setInterval(fetchIntermarket, 300000);
    return () => { window.clearInterval(t1); window.clearInterval(t2); };
  }, [fetchForecast, fetchIntermarket]);

  useEffect(() => { fetchAiStatus(); }, [fetchAiStatus]);

  // Model listesi gelince seçili modeli geçerli bir id'ye sabitle
  useEffect(() => {
    const ids = Object.keys(aiStatus?.modeller || {});
    if (ids.length) {
      setModel(m => (ids.includes(m) ? m : (ids.includes(aiStatus?.model) ? aiStatus.model : ids[0])));
    }
  }, [aiStatus]);

  useEffect(() => {
    let ws;
    try {
      ws = new WebSocket(WS_URL);
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'market_update') {
          setMarketData(prev => prev ? { ...prev, technical: data.technical, ticker: data.ticker } : prev);
          setLastUpdate(new Date());
        }
      };
      ws.onerror = () => {};
      ws.onclose = () => {};
    } catch (e) {}

    return () => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    };
  }, []);

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-logo">17MONEY</div>
        <div className="loading-sub">FORECAST TERMINAL</div>
        <div className="loading-text">Piyasa verileri yükleniyor…</div>
        <div className="loading-spinner"></div>
      </div>
    );
  }

  if (error && !marketData) {
    return (
      <div className="loading-screen">
        <div className="loading-logo">17MONEY</div>
        <div className="error-text">{error}</div>
        <button className="retry-btn" onClick={fetchData}>TEKRAR DENE</button>
      </div>
    );
  }

  const tech = marketData?.technical;

  return (
    <div className="app">
      <MarketBar
        ticker={marketData?.ticker}
        analysisData={analysisData}
        lastUpdate={lastUpdate}
      />

      <div className="tab-bar">
        <button className={`tab-btn ${tab === 'terminal' ? 'active' : ''}`}
          onClick={() => setTab('terminal')}>TERMİNAL</button>
        <button className={`tab-btn ${tab === 'bilim' ? 'active' : ''}`}
          onClick={() => setTab('bilim')}>BİLİM · MATEMATİK</button>
        <button className={`tab-btn ${tab === 'paper' ? 'active' : ''}`}
          onClick={() => setTab('paper')}>PAPER TRADING</button>
      </div>

      {tab === 'bilim' ? (
        <SciencePanel apiBase={API_BASE} />
      ) : tab === 'paper' ? (
        <PaperPanel apiBase={API_BASE} />
      ) : (
      <div className="workspace">
        {/* Sol: grafik + gösterge matrisi */}
        <section className="col-chart">
          <div className="panel chart-panel">
            <div className="chart-header">
              <span className="chart-symbol">
                {`${SYMBOL.replace(/USDT$/, '')}/USDT PERP`}
              </span>
              <div className="interval-selector">
                {INTERVALS.map(iv => (
                  <button
                    key={iv}
                    className={`interval-btn ${interval === iv ? 'active' : ''}`}
                    onClick={() => setInterval_(iv)}
                  >
                    {iv.toUpperCase()}
                  </button>
                ))}
              </div>
              <div className="chart-quick num">
                <span className={(tech?.rsi || 50) > 70 ? 'down' : (tech?.rsi || 50) < 30 ? 'up' : ''}>
                  RSI {tech?.rsi?.toFixed(1) || '—'}
                </span>
                <span className={tech?.adx?.adx >= 25 ? 'amber' : ''}>
                  ADX {tech?.adx?.adx?.toFixed(0) || '—'}
                </span>
                <span>ATR% {tech?.atr?.atr_yuzde ?? '—'}</span>
                <span className={tech?.trend?.includes('yükseliş') ? 'up' : tech?.trend?.includes('düşüş') ? 'down' : ''}>
                  {tech?.trend?.replace(/_/g, ' ') || '—'}
                </span>
              </div>
            </div>
            <Chart
              klines={klines}
              technicalData={tech}
              interval={interval}
            />
          </div>

          <IndicatorMatrix forecast={forecast} />
        </section>

        {/* Sağ: tahmin + intermarket + sinyal + sohbet */}
        <aside className="col-right">
          <ForecastPanel
            forecast={forecast}
            apiBase={API_BASE}
            aiStatus={aiStatus}
            model={model}
            setModel={setModel}
          />
          <IntermarketPanel data={intermarket} />
          <Terminal
            technicalData={tech}
            apiBase={API_BASE}
            aiStatus={aiStatus}
            refreshStatus={fetchAiStatus}
            model={model}
            setModel={setModel}
          />
        </aside>
      </div>
      )}
    </div>
  );
}

export default App;
