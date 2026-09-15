import React, { useState, useCallback, useEffect } from 'react';
import axios from 'axios';
import './SciencePanel.css';

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
      setError(err.response?.data?.detail || 'Bilimsel veri alınamadı');
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
        setChallengeMsg(`✅ TERFİ ETTİ — ${d.neden || 'yeni nesil daha iyi'}`);
      } else if (d.calisti) {
        setChallengeMsg(`Şampiyon korundu — ${d.neden || 'yeni nesil kanıtlayamadı (normal)'}`);
      } else {
        setChallengeMsg('Tur çalıştı, değişiklik yok.');
      }
      await fetchTrainer();
    } catch {
      setChallengeMsg('Tur başlatılamadı (backend?).');
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
          <h2 className="sci-title">Bilimsel Veri — Rastgeleliğin Matematiği</h2>
          <p className="sci-subtitle">
            Fiyatı tahmin etmez; piyasanın <b>ne kadar tahmin edilebilir, ne kadar oynak,
            hangi rejimde</b> olduğunu bilimsel olarak ölçer. Bachelier · Einstein · GARCH · Fourier · Shannon.
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
            {loading ? 'HESAPLANIYOR…' : 'ANALİZ ET'}
          </button>
        </div>
      </div>

      {/* Model öğrenme durumu — şampiyon-meydan okuyan */}
      {trainer && (
        <div className="sci-trainer">
          <div className="sci-trainer-head">
            <span className="sci-trainer-title">🧠 KENDİNİ EĞİTEN MODEL (Nesil Sistemi)</span>
            <span className="sci-gen-badge">NESİL {trainer.nesil ?? 0}</span>
            <span className={`sci-trainer-dot ${trainer.model_hazir ? 'on' : 'off'}`}>
              {trainer.model_hazir ? 'AKTİF' : 'HENÜZ EĞİTİLMEDİ'}
            </span>
          </div>
          <div className="sci-trainer-grid">
            <div className="sci-tr-item">
              <span className="sci-tr-label">Şampiyon Kalite (AUC)</span>
              <span className="sci-tr-value">{trainer.sampiyon_auc ?? '—'}</span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">Toplanan Veri</span>
              <span className="sci-tr-value">{trainer.toplanan_veri?.toLocaleString() ?? '—'}</span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">Ebeveyn Nesil (yedek)</span>
              <span className="sci-tr-value">
                {trainer.ebeveyn_nesil != null
                  ? `N${trainer.ebeveyn_nesil} · ${trainer.ebeveyn_auc ?? '—'}`
                  : 'yok'}
              </span>
            </div>
            <div className="sci-tr-item">
              <span className="sci-tr-label">Model Sağlığı</span>
              <span className={`sci-tr-value ${trainer.saglik?.saglikli === false ? 'down' : 'up'}`}>
                {trainer.saglik ? (trainer.saglik.saglikli ? '✓ sağlıklı' : '⚠ riskli') : '—'}
              </span>
            </div>
          </div>

          {/* Nesil ilerleyişi — her terfide AUC */}
          {trainer.nesil_gecmisi?.length > 0 && (
            <div className="sci-gen-history">
              <span className="sci-gen-history-label">NESİL İLERLEYİŞİ:</span>
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
              <span className="sci-auto-dot">●</span> OTOMATİK EĞİTİM AÇIK
              <span className="sci-auto-detail">
                — sistem saatlik kontrol eder, yeterli yeni veri birikince kendini
                sınar, KANITLARSA terfi eder. Elle başlatmaya gerek yok.
              </span>
            </span>
            <button className="sci-challenge-btn" onClick={runChallengeNow} disabled={trainBusy}>
              {trainBusy ? 'DENENİYOR…' : '⟳ ŞİMDİ BİR TUR DENE'}
            </button>
            <button className="sci-cpcv-btn" onClick={runCpcv} disabled={cpcvBusy}>
              {cpcvBusy ? 'KANIT TESTİ…' : '🔬 KANIT TESTİ (CPCV)'}
            </button>
          </div>
          {challengeMsg && <div className="sci-challenge-msg">{challengeMsg}</div>}

          {/* CPCV kanıt testi sonucu */}
          {cpcv?.yeterli_veri && (
            <div className="sci-cpcv">
              <div className="sci-cpcv-head">
                🔬 KANIT TESTİ — Gerçek kenar mı, şans mı?
              </div>
              <div className={`sci-verdict-banner ${
                cpcv.deflated_sharpe >= 0.9 && cpcv.pozitif_oran >= 0.8 ? 'good'
                : cpcv.pozitif_oran >= 0.7 ? 'mid' : 'bad'}`}>
                <b>{cpcv.pozitif_yol}/{cpcv.yol_sayisi} yol pozitif</b> · {cpcv.huküm}
              </div>
              <div className="sci-cpcv-grid">
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">Gerçeklik olasılığı</span>
                  <span className="sci-cpcv-v" title="Deflated Sharpe — 1'e yakınsa kenar gerçek, 0.5'e yakınsa şans">
                    %{Math.round(cpcv.deflated_sharpe * 100)}
                  </span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">Ortalama getiri</span>
                  <span className="sci-cpcv-v up">{cpcv.ortalama_getiri_R}R</span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">En kötü yol</span>
                  <span className={`sci-cpcv-v ${cpcv.en_kotu_R >= 0 ? 'up' : 'down'}`}>{cpcv.en_kotu_R}R</span>
                </div>
                <div className="sci-cpcv-item">
                  <span className="sci-cpcv-l">En iyi yol</span>
                  <span className="sci-cpcv-v up">{cpcv.en_iyi_R}R</span>
                </div>
              </div>
              <div className="sci-report-honest">
                CPCV (López de Prado): {cpcv.yol_sayisi} farklı eğitim/test kombinasyonu denenir.
                "Gerçeklik olasılığı" = bu kadar deneme yapınca en iyi sonucun şans olmama ihtimali.
                %50 = yazı-tura, %90+ = güçlü kanıt.
              </div>
            </div>
          )}

          <div className="sci-trainer-note">
            Model <b>kendini otomatik eğitir</b> — sistem saatlik kontrol eder, yeterli yeni veri
            birikince meydan-okuyan modeli sınar; testte bir önceki nesli <b>kanıtlanmış biçimde</b>
            geçerse <b>nesil +1</b> olur. Bir önceki nesil (<b>ebeveyn</b>) yedekte tutulur — yeni nesil
            zehirlenir/çökerse ona geri dönülür. Sağlıksız model AUC iyi görünse bile terfi edemez
            (zehirlenme koruması). <b>Elle başlatmaya gerek yok</b>; bilgisayarı her açtığında kaçırılan
            eğitim otomatik yakalanır. "Şimdi bir tur dene" sadece anında görmek isteyenler için.
          </div>

          {/* Durdurma raporu — ÇOKLU-PENCERE (sağlam) */}
          {report?.yeterli_veri && report.donemler && (
            <div className="sci-report">
              <div className="sci-report-title">📊 ÇOKLU-PENCERE HAYALİ İŞLEM RAPORU (maliyet dahil)</div>
              <div className="sci-report-method">{report.yontem}</div>

              {/* Tutarlılık hükmü */}
              <div className={`sci-verdict-banner ${
                report.tutarlilik >= 0.8 ? 'good' : report.tutarlilik >= 0.6 ? 'mid' : 'bad'}`}>
                <b>{report.pozitif_donem}/{report.donem_sayisi} dönem pozitif</b> · {report.huküm}
              </div>

              {/* Dönem dönem sonuç */}
              <div className="sci-periods">
                {report.donemler.map((d) => (
                  <div key={d.donem} className="sci-period">
                    <span className="sci-period-date">{d.tarih_ilk} → {d.tarih_son}</span>
                    <span className="sci-period-trades">{d.islem} işlem · %{(d.basari_orani * 100).toFixed(0)}</span>
                    <span className={`sci-period-r ${d.net_getiri_R >= 0 ? 'up' : 'down'}`}>
                      {d.net_getiri_R >= 0 ? '+' : ''}{d.net_getiri_R}R
                    </span>
                  </div>
                ))}
              </div>

              {/* Birleşik karşılaştırma */}
              <div className="sci-report-cols">
                <div className="sci-report-col">
                  <div className="sci-report-col-head">FİLTRESİZ (model kapalı)</div>
                  <RepRow l="Toplam işlem" v={report.birlesik_ham.islem?.toLocaleString()} />
                  <RepRow l="Başarı" v={`%${(report.birlesik_ham.basari_orani * 100).toFixed(1)}`} />
                  <RepRow l="Net getiri" v={`${report.birlesik_ham.toplam_getiri_R}R`} cls="down" />
                </div>
                <div className="sci-report-col highlight">
                  <div className="sci-report-col-head">FİLTRELİ (model açık)</div>
                  <RepRow l="Toplam işlem" v={report.birlesik_filtreli.islem?.toLocaleString()} />
                  <RepRow l="Başarı" v={`%${(report.birlesik_filtreli.basari_orani * 100).toFixed(1)}`} cls="up" />
                  <RepRow l="Net getiri" v={`${report.birlesik_filtreli.toplam_getiri_R}R`}
                    cls={report.birlesik_filtreli.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                </div>
              </div>

              <div className="sci-report-honest">
                ⚠ Bu rakamlar gerçekçidir: çoklu dönem testi (model tek döneme şanslı mı diye bakar)
                + işlem başı {report.maliyet_R}R maliyet (komisyon+funding+slipaj) düşülmüştür.
                "R" = riske ettiğin birim. Tek-pencere testindeki yüksek rakamlar bu yüzden düşer — gerçek tablo budur.
              </div>
            </div>
          )}

          {/* Eski tek-pencere format (az veri durumunda) */}
          {report?.yeterli_veri && !report.donemler && report.ham && (
            <div className="sci-report">
              <div className="sci-report-title">📊 HAYALİ İŞLEM RAPORU (tek pencere)</div>
              <div className="sci-report-method">{report.yontem}</div>
              <div className="sci-report-cols">
                <div className="sci-report-col">
                  <div className="sci-report-col-head">FİLTRESİZ</div>
                  <RepRow l="İşlem" v={report.ham.islem?.toLocaleString()} />
                  <RepRow l="Başarı" v={`%${(report.ham.basari_orani * 100).toFixed(1)}`} />
                  <RepRow l="Getiri" v={`${report.ham.toplam_getiri_R}R`}
                    cls={report.ham.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                </div>
                <div className="sci-report-col highlight">
                  <div className="sci-report-col-head">FİLTRELİ</div>
                  {report.filtreli?.islem ? (
                    <>
                      <RepRow l="İşlem" v={report.filtreli.islem?.toLocaleString()} />
                      <RepRow l="Başarı" v={`%${(report.filtreli.basari_orani * 100).toFixed(1)}`} cls="up" />
                      <RepRow l="Getiri" v={`${report.filtreli.toplam_getiri_R}R`}
                        cls={report.filtreli.toplam_getiri_R >= 0 ? 'up' : 'down'} />
                    </>
                  ) : <div className="sci-report-empty">{report.filtreli?.neden}</div>}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <div className="sci-error">{error}</div>}

      {!data && !loading && !error && (
        <div className="sci-empty">
          Zaman dilimini seçip <b>ANALİZ ET</b>'e basın — sistem son 500 mumun
          stokastik matematiğini ve gizli örüntülerini çözecek.
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
              <div className="sci-card-title">① Tahmin Edilebilirlik</div>

              <Metric label="Hurst Üssü" value={rw.hurst ?? '—'}
                hint={rw.yorum}>
                <Bar value={rw.hurst} color={hurstColor} />
                <div className="sci-scale">
                  <span>0 · dönüş</span><span>0.5 · rastgele</span><span>1 · trend</span>
                </div>
              </Metric>

              <Metric label="Öngörülebilirlik (Entropi)" value={pe.ongorulebilirlik ?? '—'}
                hint={pe.yorum}>
                <Bar value={pe.ongorulebilirlik} color={entColor} />
                <div className="sci-scale">
                  <span>0 · gürültü</span><span>1 · yapısal</span>
                </div>
              </Metric>

              <Metric label="Yön Hafızası" value={acf.yon_hafizasi || '—'}
                hint={acf.yorum} />
            </div>

            {/* GRUP 2: Volatilite */}
            <div className="sci-card">
              <div className="sci-card-title">② Volatilite (GARCH)</div>

              <Metric label="Yarının Oynaklığı"
                value={garchFc.yon ? `${garchFc.yon} (${garchFc.sonraki_bar_vol_yuzde}%)` : '—'}
                hint={garchFc.yorum} />

              <Metric label="Kalıcılık (α+β)" value={garch.kalicilik ?? '—'}
                hint={garch.yorum}>
                <Bar value={garch.kalicilik} color="var(--amber)" />
              </Metric>

              <Metric label="Mevcut Rejim" value={rejim.mevcut_rejim?.replace('_', ' ') || '—'}
                hint={rejim.yorum}>
                {rejim.olasiliklar && (
                  <div className="sci-regime">
                    <span className="reg-low">düşük %{Math.round((rejim.olasiliklar['düşük'] || 0) * 100)}</span>
                    <span className="reg-mid">orta %{Math.round((rejim.olasiliklar['orta'] || 0) * 100)}</span>
                    <span className="reg-high">yüksek %{Math.round((rejim.olasiliklar['yüksek'] || 0) * 100)}</span>
                  </div>
                )}
              </Metric>
            </div>

            {/* GRUP 3: Dağılım & Risk */}
            <div className="sci-card">
              <div className="sci-card-title">③ Dağılım & Kuyruk Riski</div>

              <Metric label="Kuyruk" value={dist.kuyruk || '—'}
                hint={dist.yorum} />

              <Metric label="Basıklık (fazla)" value={dist.basiklik_fazlasi ?? '—'}
                hint="0'dan büyük = kalın kuyruk: aşırı hareketler normalden sık." />

              <Metric label="Çarpıklık" value={dist.carpiklik ?? '—'}
                hint="Negatif = ani çöküş eğilimi (sol kuyruk uzun)." />
            </div>

            {/* GRUP 4: Örüntü çözme */}
            <div className="sci-card">
              <div className="sci-card-title">④ Örüntü Çözme (Deşifre)</div>

              <Metric label="Baskın Döngü"
                value={enGuclu ? `${enGuclu.periyot_bar} bar` : '—'}
                hint={cyc.yorum}>
                {enGuclu && (
                  <div className="sci-snr">
                    SNR <b className={enGuclu.snr >= 3 ? 'good' : 'weak'}>{enGuclu.snr}</b>
                    {enGuclu.snr >= 3 ? ' (net sinyal)' : ' (gürültüde)'}
                  </div>
                )}
              </Metric>

              <Metric label="Difüzyon Bandı (±1σ, ~%68)"
                hint="Fiyatın ~%68 olasılıkla kalacağı aralık (Brown hareketi).">
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
            <div className="sci-verdict-title">⚖ BÜTÜNSEL OKUMA</div>
            <p>{buildVerdict(rw, pe, garchFc, rejim, dist)}</p>
            <div className="sci-refs">{data._referanslar}</div>
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
    parts.push('Piyasa şu an büyük ölçüde RASTGELE — yön tahminine düşük güven verin, küçük pozisyon.');
  } else if (rw.rejim === 'trend' && pe.seviye === 'yapısal') {
    parts.push('Yapısal + trendli rejim — yön tahmini için elverişli ortam, trend takibi anlamlı.');
  } else if (rw.rejim === 'ortalama_donus') {
    parts.push('Ortalamaya dönüş eğilimi — aşırılıklardan kontra-trend fırsatları aranabilir.');
  } else {
    parts.push('Karışık rejim — net bir kenar yok, seçici olun.');
  }
  // volatilite
  if (garchFc.yon === 'yükseliyor') {
    parts.push('Volatilite ARTIYOR: pozisyonu küçült, stop\'u genişlet, kaldıracı düşür.');
  } else if (garchFc.yon === 'düşüyor') {
    parts.push('Volatilite sönüyor: sakin piyasa, normal boyutlandırma.');
  }
  // kuyruk
  if (dist.kuyruk === 'çok_kalın' || dist.kuyruk === 'kalın') {
    parts.push('Kalın kuyruk: aşırı hareket riski yüksek, stop\'lar geniş olmalı.');
  }
  return parts.join(' ');
}

export default SciencePanel;
