import React, { useState, useCallback, useEffect } from 'react';
import axios from 'axios';
import './SciencePanel.css';
import { t, tv } from '../i18n';

/**
 * Bilimsel Veri Paneli — rastgeleliğin matematiği + örüntü çözme.
 * GET /api/analysis/stochastic/{symbol} çıktısını kullanıcı-dostu
 * yorumlarla gösterir. Her metrik: ne olduğu + ne anlama geldiği.
 */

// 0-1 skoru çubuk olarak göster (öngörülebilirlik, olasılık vb.)
function Bar({ value, color = 'var(--info)' }) {
  const pct = Math.max(0, Math.min(100, (value || 0) * 100));
  return (
    <div className="sci-bar">
      <div className="sci-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

// Rapor satırı (etiket: değer)
function RepRow({ l, v, cls }) {
  return (
    <div className="sci-rep-row">
      <span className="sci-rep-l">{l}</span>
      <span className={`sci-rep-v ${cls || ''}`}>{v}</span>
    </div>
  );
}

function Metric({ label, value, hint, children }) {
  return (
    <div className="sci-metric">
      <div className="sci-metric-head">
        <span className="sci-metric-label">{label}</span>
        {value != null && <span className="sci-metric-value">{value}</span>}
      </div>
      {children}
      {hint && <div className="sci-metric-hint">{hint}</div>}
    </div>
  );
}

function SciencePanel({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [interval, setIntervalSel] = useState('1h');
  const [trainer, setTrainer] = useState(null);
  const [training, setTraining] = useState(null);   // eğitim durumu
  const [report, setReport] = useState(null);       // durdurma raporu
  const [trainBusy, setTrainBusy] = useState(false);
  const [cpcv, setCpcv] = useState(null);           // CPCV kanıt testi
  const [cpcvBusy, setCpcvBusy] = useState(false);

  const fetchScience = useCallback(async (iv) => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(
        `${apiBase}/api/analysis/stochastic/BTCUSDT?interval=${iv}&limit=500`,
        { timeout: 60000 }
      );
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || t("Bilimsel veri alınamadı"));
    }
    setLoading(false);
  }, [apiBase]);

  // Eğitim/model durumu — panel açılınca + 60 sn'de bir tazele
  const fetchTrainer = useCallback(async () => {
    try {
      const res = await axios.get(`${apiBase}/api/meta/trainer-status`, { timeout: 20000 });
      setTrainer(res.data);
    } catch { /* sessiz */ }
  }, [apiBase]);

  // Eğitim durumu — çalışırken sık tazele (canlı tur sayısı görünsün)
  const fetchTraining = useCallback(async () => {
    try {
      const res = await axios.get(`${apiBase}/api/meta/training/status`, { timeout: 20000 });
      setTraining(res.data);
      if (res.data?.son_rapor && !res.data.calisiyor) setReport(res.data.son_rapor);
    } catch { /* sessiz */ }
  }, [apiBase]);

  useEffect(() => {
    fetchTrainer();
    fetchTraining();
    // Sabit 8 sn — eğitim durumu canlı görünsün (endpoint hafif)
    const t = window.setInterval(() => { fetchTrainer(); fetchTraining(); }, 8000);
    return () => window.clearInterval(t);
  }, [fetchTrainer, fetchTraining]);

  const runCpcv = async () => {
    if (cpcvBusy) return;
    setCpcvBusy(true);
    try {
      const res = await axios.post(`${apiBase}/api/meta/cpcv`, {}, { timeout: 240000 });
      setCpcv(res.data);
    } catch { /* sessiz */ }
    setCpcvBusy(false);
  };

  // Otomatik eğitim zaten arka planda çalışır. Bu buton sadece "sabırsızlar için"
  // bir turu HEMEN tetikler — gerekmez ama isteyene anında geri bildirim verir.
  const [challengeMsg, setChallengeMsg] = useState(null);
  const runChallengeNow = async () => {
    if (trainBusy) return;
    setTrainBusy(true);
    setChallengeMsg(null);
    try {
      const res = await axios.post(`${apiBase}/api/meta/challenge`, {}, { timeout: 60000 });
      const d = res.data || {};
      if (d.terfi) {
        setChallengeMsg(t("✅ TERFİ ETTİ — {neden}", { neden: tv(d.neden) || tv("yeni nesil daha iyi") }));
      } else if (d.calisti) {
        setChallengeMsg(t("Şampiyon korundu — {neden}",
          { neden: tv(d.neden) || tv("yeni nesil kanıtlayamadı (normal)") }));
      } else {
        setChallengeMsg(t("Tur çalıştı, değişiklik yok."));
      }
      await fetchTrainer();
    } catch {
      setChallengeMsg(t("Tur başlatılamadı (backend?)."));
    }
    setTrainBusy(false);
  };

  const rw = data?.random_walk_testi || {};
  const dist = data?.getiri_dagilimi || {};
  const garch = data?.garch || {};
  const garchFc = data?.garch_tahmin || {};
  const rejim = data?.volatilite_rejimi || {};
  const dif = data?.difuzyon_projeksiyonu || {};
  const cozme = data?.cozme || {};
  const cyc = cozme?.baskin_donguler || {};
  const acf = cozme?.otokorelasyon || {};
  const pe = cozme?.ongorulebilirlik || {};
  const enGuclu = (cyc.baskin_donguler || [])[0];

  // renk yardımcıları
  const hurstColor = rw.rejim === 'trend' ? 'var(--up)'
    : rw.rejim === 'ortalama_donus' ? 'var(--info)' : 'var(--ink-faint)';
  const entColor = pe.seviye === 'yapısal' ? 'var(--up)'
    : pe.seviye === 'gürültü' ? 'var(--down)' : 'var(--amber)';

  return (
    <div className="science-panel">
      <div className="sci-header">
        <div>
          <h2 className="sci-title">{t("Bilimsel Veri — Rastgeleliğin Matematiği")}</h2>
          <p className="sci-subtitle">
            {t("Fiyatı tahmin etmez; piyasanın")} <b>{t("ne kadar tahmin edilebilir, ne kadar oynak, hangi rejimde")}</b> {t("olduğunu bilimsel olarak ölçer. Bachelier · Einstein · GARCH · Fourier · Shannon.")}
          </p>
        </div>
        <div className="sci-controls">
          <div className="sci-iv-group">
            {['15m', '1h', '4h', '1d'].map(iv => (
              <button
                key={iv}
                className={`sci-iv-btn ${interval === iv ? 'active' : ''}`}
                onClick={() => { setIntervalSel(iv); }}
              >{iv.toUpperCase()}</button>
            ))}
          </div>
          <button className="sci-run-btn" onClick={() => fetchScience(interval)} disabled={loading}>
            {loading ? t('HESAPLANIYOR…') : t('ANALİZ ET')}
          </button>
        </div>
      </div>

      {/* Model öğrenme durumu — şampiyon-meydan okuyan */}
      {trainer && (
        <div className="sci-trainer">
          <div className="sci-trainer-head">
            <span className="sci-trainer-title">{t("🧠 KENDİNİ EĞİTEN MODEL (Nesil Sistemi)")}</span>
            <span className="sci-gen-badge">{t("NESİL")} {trainer.nesil ?? 0}</span>
            <span className={`sci-trainer-dot ${trainer.model_hazir ? 'on' : 'off'}`}>
              {trainer.model_hazir ? t('AKTİF') : t('HENÜZ EĞİTİLMEDİ')}
            </span>
          </div>
          <div className="sci-trainer-grid">
            <div className="sci-tr-item">
              <span className="sci-tr-label">{t("Şampiyon Kalite (AUC)")}</span>
              <span className="sci-tr-value">{trainer.sampiyon_auc ?? '—'}</span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">{t("Toplanan Veri")}</span>
              <span className="sci-tr-value">{trainer.toplanan_veri?.toLocaleString() ?? '—'}</span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">{t("Ebeveyn Nesil (yedek)")}</span>
              <span className="sci-tr-value">
                {trainer.ebeveyn_nesil != null
                  ? `N${trainer.ebeveyn_nesil} · ${trainer.ebeveyn_auc ?? '—'}`
                  : t('yok')}
              </span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">{t("Model Sağlığı")}</span>
              <span className={`sci-tr-value ${trainer.saglik?.saglikli === false ? 'down' : 'up'}`}>
                {trainer.saglik ? (trainer.saglik.saglikli ? t('✓ sağlıklı') : t('⚠ riskli')) : '—'}
              </span>
            </div>
          </div>

          {/* Nesil ilerleyişi — her terfide AUC */}
          {trainer.nesil_gecmisi?.length > 0 && (
            <div className="sci-gen-history">
              <span className="sci-gen-history-label">{t("NESİL İLERLEYİŞİ:")}</span>
              {trainer.nesil_gecmisi.map((g, i) => (
                <span key={i} className="sci-gen-step" title={`AUC ${g.auc}`}>
                  N{g.nesil}<b>{g.auc}</b>
                </span>
              ))}
            </div>
          )}
          {/* Otomatik eğitim durumu (artık elle başlatmaya GEREK YOK) */}
          <div className="sci-train-control">
            <span className="sci-auto-train">
              <span className="sci-auto-dot">●</span> {t("OTOMATİK EĞİTİM AÇIK")}
              <span className="sci-auto-detail">
                {t("— sistem saatlik kontrol eder, yeterli yeni veri birikince kendini sınar, KANITLARSA terfi eder. Elle başlatmaya gerek yok.")}
              </span>
            </span>
            <button className="sci-challenge-btn" onClick={runChallengeNow} disabled={trainBusy}>
              {trainBusy ? t('DENENİYOR…') : t('⟳ ŞİMDİ BİR TUR DENE')}
            </button>
            <button className="sci-cpcv-btn" onClick={runCpcv} disabled={cpcvBusy}>
              {cpcvBusy ? t('KANIT TESTİ…') : t('🔬 KANIT TESTİ (CPCV)')}
            </button>
          </div>
          {challengeMsg && <div className="sci-challenge-msg">{challengeMsg}</div>}

          {/* CPCV kanıt testi sonucu */}
          {cpcv?.yeterli_veri && (
            <div className="sci-cpcv">
              <div className="sci-cpcv-head">
                {t("🔬 KANIT TESTİ — Gerçek kenar mı, şans mı?")}
              </div>
              <div className={`sci-verdict-banner ${
                cpcv.deflated_sharpe >= 0.9 && cpcv.pozitif_oran >= 0.8 ? 'good'
                : cpcv.pozitif_oran >= 0.7 ? 'mid' : 'bad'}`}>
                <b>{t("{a}/{b} dönem pozitif", { a: cpcv.pozitif_yol, b: cpcv.yol_sayisi })}</b> · {tv(cpcv.huküm)}
              </div>
              <div className="sci-cpcv-grid">
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">{t("Gerçeklik olasılığı")}</span>
                  <span className="sci-cpcv-v" title={t("Deflated Sharpe — 1'e yakınsa kenar gerçek, 0.5'e yakınsa şans")}>
                    %{Math.round(cpcv.deflated_sharpe * 100)}
                  </span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">{t("Ortalama getiri")}</span>
                  <span className="sci-cpcv-v up">{cpcv.ortalama_getiri_R}R</span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">{t("En kötü yol")}</span>
                  <span className={`sci-cpcv-v ${cpcv.en_kotu_R >= 0 ? 'up' : 'down'}`}>{cpcv.en_kotu_R}R</span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">{t("En iyi yol")}</span>
                  <span className="sci-cpcv-v up">{cpcv.en_iyi_R}R</span>
                </div>
              </div>
              <div className="sci-report-honest">
                {t("CPCV (López de Prado): {n} farklı eğitim/test kombinasyonu denenir. \"Gerçeklik olasılığı\" = bu kadar deneme yapınca en iyi sonucun şans olmama ihtimali. %50 = yazı-tura, %90+ = güçlü kanıt.", { n: cpcv.yol_sayisi })}
              </div>
            </div>
          )}

          <div className="sci-trainer-note">
            {t("Model")} <b>{t("kendini otomatik eğitir")}</b> {t("— sistem saatlik kontrol eder, yeterli yeni veri birikince meydan-okuyan modeli sınar; testte bir önceki nesli")} <b>{t("kanıtlanmış biçimde")}</b> {t("geçerse")} <b>{t("nesil +1")}</b> {t("olur. Bir önceki nesil (")}<b>{t("ebeveyn")}</b>{t(") yedekte tutulur — yeni nesil zehirlenir/çökerse ona geri dönülür. Sağlıksız model AUC iyi görünse bile terfi edemez (zehirlenme koruması).")} <b>{t("Elle başlatmaya gerek yok")}</b>{t("; bilgisayarı her açtığında kaçırılan eğitim otomatik yakalanır. \"Şimdi bir tur dene\" sadece anında görmek isteyenler için.")}
          </div>

          {/* Durdurma raporu — ÇOKLU-PENCERE (sağlam) */}
          {report?.yeterli_veri && report.donemler && (
            <div className="sci-report">
              <div className="sci-report-title">{t("📊 ÇOKLU-PENCERE HAYALİ İŞLEM RAPORU (maliyet dahil)")}</div>
              <div className="sci-report-method">{tv(report.yontem)}</div>

              {/* Tutarlılık hükmü */}
              <div className={`sci-verdict-banner ${
                report.tutarlilik >= 0.8 ? 'good' : report.tutarlilik >= 0.6 ? 'mid' : 'bad'}`}>
                <b>{t("{a}/{b} dönem pozitif", { a: report.pozitif_donem, b: report.donem_sayisi })}</b> · {tv(report.huküm)}
              </div>

              {/* Dönem dönem sonuç */}
              <div className="sci-periods">
                {report.donemler.map((d) => (
                  <div key={d.donem} className="sci-period">
                    <span className="sci-period-date">{d.tarih_ilk} → {d.tarih_son}</span>
                    <span className="sci-period-trades">{t("{n} işlem · %{pct}", { n: d.islem, pct: (d.basari_orani * 100).toFixed(0) })}</span>
                    <span className={`sci-period-r ${d.net_getiri_R >= 0 ? 'up' : 'down'}`}>
                      {d.net_getiri_R >= 0 ? '+' : ''}{d.net_getiri_R}R
                    </span>
                  </div>
                ))}
              </div>

              {/* Birleşik karşılaştırma */}
              <div className="sci-report-cols">
                <div className="sci-report-col">
                  <div className="sci-report-col-head">{t("FİLTRESİZ (model kapalı)")}</div>
                  <RepRow l={t("Toplam işlem")} v={report.birlesik_ham.islem?.toLocaleString()} />
                  <RepRow l={t("Başarı")} v={`%${(report.birlesik_ham.basari_orani * 100).toFixed(1)}`} />
                  <RepRow l={t("Net getiri")} v={`${report.birlesik_ham.toplam_getiri_R}R`} cls="down" />
                </div>
                <div className="sci-report-col highlight">
                  <div className="sci-report-col-head">{t("FİLTRELİ (model açık)")}</div>
                  <RepRow l={t("Toplam işlem")} v={report.birlesik_filtreli.islem?.toLocaleString()} />
                  <RepRow l={t("Başarı")} v={`%${(report.birlesik_filtreli.basari_orani * 100).toFixed(1)}`} cls="up" />
                  <RepRow l={t("Net getiri")} v={`${report.birlesik_filtreli.toplam_getiri_R}R`}
                    cls={report.birlesik_filtreli.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                </div>
              </div>

              <div className="sci-report-honest">
                {t("⚠ Bu rakamlar gerçekçidir: çoklu dönem testi (model tek döneme şanslı mı diye bakar) + işlem başı {cost}R maliyet (komisyon+funding+slipaj) düşülmüştür. \"R\" = riske ettiğin birim. Tek-pencere testindeki yüksek rakamlar bu yüzden düşer — gerçek tablo budur.", { cost: report.maliyet_R })}
              </div>
            </div>
          )}

          {/* Eski tek-pencere format (az veri durumunda) */}
          {report?.yeterli_veri && !report.donemler && report.ham && (
            <div className="sci-report">
              <div className="sci-report-title">{t("📊 HAYALİ İŞLEM RAPORU (tek pencere)")}</div>
              <div className="sci-report-method">{tv(report.yontem)}</div>
              <div className="sci-report-cols">
                <div className="sci-report-col">
                  <div className="sci-report-col-head">{t("FİLTRESİZ")}</div>
                  <RepRow l={t("İşlem")} v={report.ham.islem?.toLocaleString()} />
                  <RepRow l={t("Başarı")} v={`%${(report.ham.basari_orani * 100).toFixed(1)}`} />
                  <RepRow l={t("Getiri")} v={`${report.ham.toplam_getiri_R}R`}
                    cls={report.ham.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                </div>
                <div className="sci-report-col highlight">
                  <div className="sci-report-col-head">{t("FİLTRELİ")}</div>
                  {report.filtreli?.islem ? (
                    <>
                      <RepRow l={t("İşlem")} v={report.filtreli.islem?.toLocaleString()} />
                      <RepRow l={t("Başarı")} v={`%${(report.filtreli.basari_orani * 100).toFixed(1)}`} cls="up" />
                      <RepRow l={t("Getiri")} v={`${report.filtreli.toplam_getiri_R}R`}
                        cls={report.filtreli.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                    </>
                  ) : <div className="sci-report-empty">{tv(report.filtreli?.neden)}</div>}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <div className="sci-error">{error}</div>}

      {!data && !loading && !error && (
        <div className="sci-empty">
          {t("Zaman dilimini seçip")} <b>{t("ANALİZ ET")}</b> {t("'e basın — sistem son 500 mumun stokastik matematiğini ve gizli örüntülerini çözecek.")}
        </div>
      )}

      {data && (
        <>
          <div className="sci-price-row">
            <span className="sci-price-label">BTC/USDT · {data.interval}</span>
            <span className="sci-price num">${data.fiyat?.toLocaleString()}</span>
          </div>

          <div className="sci-grid">
            {/* GRUP 1: Tahmin edilebilirlik */}
            <div className="sci-card">
              <div className="sci-card-title">{t("① Tahmin Edilebilirlik")}</div>

              <Metric label={t("Hurst Üssü")} value={rw.hurst ?? '—'}
                hint={tv(rw.yorum)}>
                <Bar value={rw.hurst} color={hurstColor} />
                <div className="sci-scale">
                  <span>{t("0 · dönüş")}</span><span>{t("0.5 · rastgele")}</span><span>{t("1 · trend")}</span>
                </div>
              </Metric>

              <Metric label={t("Öngörülebilirlik (Entropi)")} value={pe.ongorulebilirlik ?? '—'}
                hint={tv(pe.yorum)}>
                <Bar value={pe.ongorulebilirlik} color={entColor} />
                <div className="sci-scale">
                  <span>{t("0 · gürültü")}</span><span>{t("1 · yapısal")}</span>
                </div>
              </Metric>

              <Metric label={t("Yön Hafızası")} value={acf.yon_hafizasi || '—'}
                hint={tv(acf.yorum)} />
            </div>

            {/* GRUP 2: Volatilite */}
            <div className="sci-card">
              <div className="sci-card-title">{t("② Volatilite (GARCH)")}</div>

              <Metric label={t("Yarının Oynaklığı")}
                value={garchFc.yon ? `${tv(garchFc.yon)} (${garchFc.sonraki_bar_vol_yuzde}%)` : '—'}
                hint={tv(garchFc.yorum)} />

              <Metric label={t("Kalıcılık (α+β)")} value={garch.kalicilik ?? '—'}
                hint={tv(garch.yorum)}>
                <Bar value={garch.kalicilik} color="var(--amber)" />
              </Metric>

              <Metric label={t("Mevcut Rejim")} value={tv(rejim.mevcut_rejim)?.replace('_', ' ') || '—'}
                hint={tv(rejim.yorum)}>
                {rejim.olasiliklar && (
                  <div className="sci-regime">
                    <span className="reg-low">{t("düşük %{pct}", { pct: Math.round((rejim.olasiliklar['düşük'] || 0) * 100) })}</span>
                    <span className="reg-mid">{t("orta %{pct}", { pct: Math.round((rejim.olasiliklar['orta'] || 0) * 100) })}</span>
                    <span className="reg-high">{t("yüksek %{pct}", { pct: Math.round((rejim.olasiliklar['yüksek'] || 0) * 100) })}</span>
                  </div>
                )}
              </Metric>
            </div>

            {/* GRUP 3: Dağılım & Risk */}
            <div className="sci-card">
              <div className="sci-card-title">{t("③ Dağılım & Kuyruk Riski")}</div>

              <Metric label={t("Kuyruk")} value={tv(dist.kuyruk) || '—'}
                hint={tv(dist.yorum)} />

              <Metric label={t("Basıklık (fazla)")} value={dist.basiklik_fazlasi ?? '—'}
                hint={t("0'dan büyük = kalın kuyruk: aşırı hareketler normalden sık.")} />

              <Metric label={t("Çarpıklık")} value={dist.carpiklik ?? '—'}
                hint={t("Negatif = ani çöküş eğilimi (sol kuyruk uzun).")} />
            </div>

            {/* GRUP 4: Örüntü çözme */}
            <div className="sci-card">
              <div className="sci-card-title">{t("④ Örüntü Çözme (Deşifre)")}</div>

              <Metric label={t("Baskın Döngü")}
                value={enGuclu ? `${enGuclu.periyot_bar} bar` : '—'}
                hint={tv(cyc.yorum)}>
                {enGuclu && (
                  <div className="sci-snr">
                    SNR <b className={enGuclu.snr >= 3 ? 'good' : 'weak'}>{enGuclu.snr}</b>
                    {enGuclu.snr >= 3 ? t('(net sinyal)') : t('(gürültüde)')}
                  </div>
                )}
              </Metric>

              <Metric label={t("Difüzyon Bandı (±1σ, ~%68)")}
                hint={t("Fiyatın ~%68 olasılıkla kalacağı aralık (Brown hareketi).")}>
                {dif.bant_1sigma && (
                  <div className="sci-band num">
                    <span className="down">{dif.bant_1sigma.alt?.toLocaleString()}</span>
                    <span className="sci-band-arrow">↔</span>
                    <span className="up">{dif.bant_1sigma.ust?.toLocaleString()}</span>
                  </div>
                )}
              </Metric>
            </div>
          </div>

          {/* Bütünsel yorum */}
          <div className="sci-verdict">
            <div className="sci-verdict-title">{t("⚖ BÜTÜNSEL OKUMA")}</div>
            <p>{buildVerdict(rw, pe, garchFc, rejim, dist)}</p>
            <div className="sci-refs">{tv(data._referanslar)}</div>
          </div>
        </>
      )}
    </div>
  );
}

// Tüm metrikleri tek bir insan-okunur karara sentezler
function buildVerdict(rw, pe, garchFc, rejim, dist) {
  const parts = [];
  // tahmin edilebilirlik
  if (pe.seviye === 'gürültü' || rw.rejim === 'random_walk') {
    parts.push(t("Piyasa şu an büyük ölçüde RASTGELE — yön tahminine düşük güven verin, küçük pozisyon."));
  } else if (rw.rejim === 'trend' && pe.seviye === 'yapısal') {
    parts.push(t("Yapısal + trendli rejim — yön tahmini için elverişli ortam, trend takibi anlamlı."));
  } else if (rw.rejim === 'ortalama_donus') {
    parts.push(t("Ortalamaya dönüş eğilimi — aşırılıklardan kontra-trend fırsatları aranabilir."));
  } else {
    parts.push(t("Karışık rejim — net bir kenar yok, seçici olun."));
  }
  // volatilite
  if (garchFc.yon === 'yükseliyor') {
    parts.push(t("Volatilite ARTIYOR: pozisyonu küçült, stop'u genişlet, kaldıracı düşür."));
  } else if (garchFc.yon === 'düşüyor') {
    parts.push(t("Volatilite sönüyor: sakin piyasa, normal boyutlandırma."));
  }
  // kuyruk
  if (dist.kuyruk === 'çok_kalın' || dist.kuyruk === 'kalın') {
    parts.push(t("Kalın kuyruk: aşırı hareket riski yüksek, stop'lar geniş olmalı."));
  }
  return parts.join(' ');
}

export default SciencePanel;
