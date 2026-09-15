import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import SignalCard from './SignalCard';
import ModelPicker, { shortLabel } from './ModelPicker';
import './Terminal.css';
import { t, tv } from '../i18n';

const welcome = () => ({
  role: 'assistant',
  content: t('17Money uzman terminali aktif. Piyasa, kurulum veya risk hakkında soru sorun — gerekirse web araştırması yaparım.'),
});

function Terminal({ technicalData, apiBase, aiStatus, refreshStatus, model, setModel }) {
  const [messages, setMessages] = useState([welcome()]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [signal, setSignal] = useState(null);
  const [signalLoading, setSignalLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [loginBusy, setLoginBusy] = useState(false);
  const [resetting, setResetting] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const flagIfAuth = (detail) => {
    // Backend TR veya EN dönebilir (X-Lang) — iki dildeki işaretleri tara.
    if (/giriş|login|kullanım hakkı|credit|access|api[_ -]?key/i.test(detail || '')) setNeedsLogin(true);
  };

  const fetchSignal = async (deep = false) => {
    if (deep) setDeepLoading(true); else setSignalLoading(true);
    try {
      const url = `${apiBase}/api/ai/signal?model=${encodeURIComponent(model)}${deep ? '&deep=true' : ''}`;
      const res = await axios.get(url, { timeout: deep ? 360000 : 240000 });
      setSignal(res.data);
      setNeedsLogin(false);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      flagIfAuth(detail);
      setSignal({ sinyal: 'BEKLE', guven_skoru: 0, analiz: detail, error: true });
    }
    setSignalLoading(false);
    setDeepLoading(false);
  };

  const sendMessage = async () => {
    if (!input.trim() || sending) return;

    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setSending(true);

    try {
      const history = messages.slice(-10).map(m => ({ role: m.role, content: m.content }));
      const res = await axios.post(`${apiBase}/api/ai/chat`, {
        message: userMsg,
        history: history,
        model: model,
      }, { timeout: 240000 });
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.response }]);
      setNeedsLogin(false);
    } catch (err) {
      const detail = err.response?.data?.detail || t('Bağlantı hatası');
      flagIfAuth(detail);
      setMessages(prev => [...prev, { role: 'assistant', content: `${t('[Hata]')} ${detail}`, error: true }]);
    }
    setSending(false);
  };

  const resetChat = async () => {
    if (resetting || sending) return;
    setResetting(true);
    try {
      await axios.post(`${apiBase}/api/ai/chat/reset`, {}, { timeout: 30000 });
    } catch { /* oturum yoksa da sorun değil */ }
    setMessages([welcome()]);
    setInput('');
    setResetting(false);
  };

  const handleLogin = async () => {
    if (loginBusy) return;
    const email = window.prompt(
      t("Claude aboneliğinizin olduğu e-posta (giriş sayfasında ön-doldurulur):"),
      'furkantahsinb@gmail.com'
    );
    if (email === null) return;

    setLoginBusy(true);
    const startEmail = aiStatus?.giris?.email || null;
    try {
      const res = await axios.post(`${apiBase}/api/ai/login`,
        { email: email.trim() || null }, { timeout: 30000 });
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.aciklama }]);

      let done = false;
      for (let i = 0; i < 36; i++) {
        await new Promise(r => setTimeout(r, 5000));
        const st = await refreshStatus?.();
        const g = st?.giris;
        if (g?.girisli && (g.abonelik || (g.email && g.email !== startEmail))) {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: g.abonelik
              ? t('Giriş algılandı: {email} ({plan}). Artık mesaj gönderebilirsiniz.', { email: g.email, plan: g.abonelik })
              : t("Hesap değişti: {email} — ancak bu hesapta abonelik görünmüyor. Abonelikli hesabınız farklıysa tekrar CLAUDE GİRİŞİ'ne basın.", { email: g.email }),
          }]);
          if (g.abonelik) setNeedsLogin(false);
          done = true;
          break;
        }
      }
      if (!done) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: t('Giriş hâlâ algılanmadı. Açılan konsol penceresinde "Login successful" gördüyseniz bir mesaj göndererek deneyin; görmediyseniz tarayıcıdaki Authorize adımını tamamlayıp tekrar deneyin.'),
        }]);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || t('Giriş başlatılamadı');
      setMessages(prev => [...prev, { role: 'assistant', content: `[Hata] ${detail}`, error: true }]);
    }
    setLoginBusy(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const busy = signalLoading || deepLoading;
  const giris = aiStatus?.giris;
  const authState = aiStatus == null ? null
    : aiStatus.saglayici === 'api' ? 'ok'
    : giris?.girisli ? (giris?.abonelik ? 'ok' : 'warn')
    : 'bad';
  const authText = aiStatus == null ? '—'
    : aiStatus.saglayici === 'api' ? t('API anahtarı')
    : giris?.girisli
      ? `${giris.email || t('girişli')} · ${giris.abonelik ? tv(giris.abonelik) : t('abonelik yok')}`
      : t('giriş yok');
  const signalLabel = shortLabel(model, aiStatus?.modeller?.[model]);
  const isCli = aiStatus?.saglayici !== 'api';

  return (
    <div className="terminal">
      {/* Uzman Sinyal — SİNYAL + DERİN, altında model seçici */}
      <div className="panel terminal-section">
        <div className="panel-head">
          <span className="panel-title">{t("Uzman Sinyal")}</span>
          <div className="signal-btns">
            <button className="signal-btn" onClick={() => fetchSignal(false)} disabled={busy}>
              {signalLoading ? `${signalLabel}…` : t('SİNYAL')}
            </button>
            <button className="signal-btn deep" onClick={() => fetchSignal(true)} disabled={busy}
              title={t("Önce web araştırması yapar, bulguları sinyale besler")}>
              {deepLoading ? t('ARAŞTIRIYOR…') : t('DERİN')}
            </button>
          </div>
        </div>
        <div className="signal-body">
          <SignalCard signal={signal} technicalData={technicalData} />
          <div className="tool-modelbar">
            <ModelPicker
              models={aiStatus?.modeller}
              value={model}
              onChange={setModel}
              disabled={busy}
              label="MODEL"
            />
          </div>
        </div>
      </div>

      {/* Sohbet */}
      <div className="panel terminal-section chat-section">
        <div className="panel-head">
          <span className="panel-title">Terminal</span>
          <button
            className="reset-btn"
            onClick={resetChat}
            disabled={resetting || sending}
            title={t("Sohbeti ve kalıcı oturumu sıfırla")}
          >
            {resetting ? t('SIFIRLANIYOR…') : t('⟲ SOHBETİ SIFIRLA')}
          </button>
        </div>
        <div className="chat-messages">
          {messages.map((msg, i) => (
            <div key={i} className={`chat-msg ${msg.role} ${msg.error ? 'error' : ''}`}>
              <span className="msg-prefix">{msg.role === 'user' ? '>' : '17M'}</span>
              <span className="msg-content">{msg.content}</span>
            </div>
          ))}
          {sending && (
            <div className="chat-msg assistant">
              <span className="msg-prefix">17M</span>
              <span className="msg-content typing">{t("düşünüyor…")}</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        <div className="chat-input-wrapper">
          <span className="input-prefix">{'>'}</span>
          <input
            type="text"
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("Soru sor — uzman gerekirse web'de araştırır…")}
            disabled={sending}
          />
          <button className="send-btn" onClick={sendMessage} disabled={sending || !input.trim()}>
            →
          </button>
        </div>
        <div className="chat-footer">
          <ModelPicker
            models={aiStatus?.modeller}
            value={model}
            onChange={setModel}
            disabled={sending}
            label="MODEL"
          />
          <span className={`auth-chip ${authState || ''}`} title={tv(aiStatus?.aciklama) || ''}>
            {authText}
          </span>
          {isCli && (
            <button
              className={`login-btn ${needsLogin ? 'attention' : ''}`}
              onClick={handleLogin}
              disabled={loginBusy}
              title={t("Masaüstünde 'claude auth login' penceresi açar — abonelikli hesabı seçin")}
            >
              {loginBusy ? t('BEKLENİYOR…') : t('CLAUDE GİRİŞİ')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default Terminal;
