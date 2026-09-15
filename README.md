# 17Money Algorithm

BTC/USDT Futures için **AI destekli trading partneri**: çoklu zaman dilimi teknik
analiz, deterministik tahmin motoru, stokastik matematik katmanı, haber/makro
bağlamı, meta-model (şampiyon–meydan okuyan) eğitimi, paper trading ve Claude
uzman yorumu tek bir panelde.

> **Uyarı:** Bu yazılım yalnızca **eğitim/araştırma** amaçlıdır. Yatırım tavsiyesi
> değildir. Varsayılan olarak **paper trading** (gerçek para yok) çalışır.

---

## 1. Mimari (kısa)

```
config/            .env (SIRLAR — sürüm kontrolüne girmez) + .env.example
backend/
  config.py        ★ TÜM ayarlar ve gizliler (tek doğruluk kaynağı)
  prompts.py       ★ TÜM sistem promptları + JSON şemaları
  main.py          FastAPI uygulaması + arka plan döngüleri (lifespan)
  routers/         market · analysis · ai · meta · paper
  services/        binance · technical · forecast · stochastic · news ·
                   claude_service · claude_cli · claude_vote · signal_store ·
                   meta_model · trainer_service · backfill · history_downloader ·
                   paper_account · session_filter · alert_service · feature
  data/            yerel SQLite + parquet (sürüm kontrolüne girmez)
frontend/          React paneli (Chart, Terminal, SciencePanel, PaperPanel…)
ml/                model/veri klasörleri (içerikleri takip edilmez)
```

**İki kural:**
1. Kodun hiçbir yerinde sabit sayı, URL, model adı veya anahtar **bulunmaz** —
   hepsi `backend/config.py`'de yaşar ve ortam değişkeniyle ezilebilir.
2. Sistem promptları ve şemalar **yalnızca** `backend/prompts.py`'dedir
   (Anthropic prompt cache'i metnin bit-bit sabit kalmasına bağlıdır).

---

## 2. Kurulum

### 2.1 Sırları hazırlayın (ZORUNLU adım)

```powershell
copy config\.env.example config\.env      # macOS/Linux: cp config/.env.example config/.env
```

`config/.env` içindeki yer tutucuları doldurun:

| Değişken | Zorunlu mu | Not |
|---|---|---|
| `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` | Piyasa verisi + işlem için | **Testnet** anahtarı kullanın (`BINANCE_TESTNET=true`) |
| `CLAUDE_API_KEY` | Hayır | Boşsa bu makinede oturum açılmış **Claude Code CLI** kullanılır |
| `NEWS_API_KEY` / `CRYPTOPANIC_KEY` | Hayır | Biri dolu olmalı; yoksa haber katmanı sessizce devre dışı kalır |

`your_...` ile başlayan ya da boş bırakılan anahtarlar "yapılandırılmamış"
sayılır: uygulama **çökmez**, sadece ilgili özellik devre dışı kalır.
Kontrol: `GET /api/ai/status` ve (açıksa) `CONFIG_DIAGNOSTICS=true` açılış satırı.

> ⚠️ `config/.env` asla commit edilmez (`.gitignore`) ve asla paylaşılmaz.
> Anahtar sızıntısı şüphesinde derhal anahtarları yenileyin.

### 2.2 Backend

```powershell
cd backend
python -m pip install -r ..\requirements.txt   # (varsa)
$env:PYTHONPATH = "C:\dev\17_money\backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2.3 Frontend

```powershell
cd frontend
npm install
npm start        # http://localhost:3000
```

Frontend ayarları `frontend/.env`'den okunur (örnek: `frontend/.env.example`):
`REACT_APP_API_BASE`, `REACT_APP_WS_URL`, `REACT_APP_SYMBOL`,
`REACT_APP_DEFAULT_INTERVAL`, `REACT_APP_DEFAULT_MODEL`.
**Not:** tarayıcıya gömüldüğü için buraya API anahtarı yazmayın.

Windows'ta tek tuşla başlatma: `BASLAT.bat` / `start.bat`.

---

## 3. Sık kullanılan uçlar

| Uç | Ne yapar |
|---|---|
| `GET /health` | Sağlık kontrolü |
| `GET /api/ai/status` | Claude sağlayıcısı (api/cli/yok), model, seçilebilir model listesi |
| `GET /api/market/btc?interval=1h` | Teknik analiz paketi (fiyat, EMA/RSI/ADX/ATR, yapı) |
| `GET /api/analysis/forecast/{symbol}` | Deterministik tahmin motoru (Yön Endeksi 0-100) |
| `GET /api/analysis/stochastic/{symbol}` | Hurst/GARCH/kuyruk/difüzyon + örüntü çözme |
| `GET /api/ai/signal?interval=1h` | Claude sinyali (kredi yakar) |
| `POST /api/meta/backfill` → `POST /api/meta/train` | Meta-model eğitimi (şampiyon–meydan okuyan) |
| `POST /api/paper/run-once?interval=1h&with_vote=true` | Paper turu (+ model/Claude oylaması) |
| `GET /api/paper/status` | Sermaye, işlemler, devre kesici durumu |

---

## 4. Güvenlik / yayın kontrol listesi

- [x] `config/.env` `.gitignore` içinde; depoda sadece `.env.example` var
- [x] Sırlar yalnızca `config/.env`'den okunur (`backend/config.py`)
- [x] `backend/data/`, `*.db`, `*.joblib`, `*.parquet`, `*.log`, `ml/data|models`
      takip edilmez
- [x] `.claude/settings.local.json` (yerel araç ayarları) takip edilmez
- [x] Yayın öncesi öneri: `git status --porcelain` + `gitleaks detect` ile
      ikinci bir sır taraması yapın
- [ ] **Anahtarları yenileyin:** Depo herkese açıldıysa Binance/Anthropic
      anahtarlarını iptal edip yenisini üretin

---

## 5. Felsefe (neden böyle)

- **Sayı beyni + dil beyni:** deterministik motor kanıt ölçer, Claude bağlam
  sentezler; karar **eşit oylama** ile birleşir.
- **Kanıt odaklı:** triple-barrier etiketleme, walk-forward test, CPCV +
  Deflated Sharpe; şampiyon model ancak istatistiksel olarak kanıtlarsa terfi eder.
- **Kendini koruyan sistem:** devre kesici (drawdown limiti), soğuma modu,
  düşük likidite seansında güven kırıcı, meta-model eşiği.
- **Tek doğruluk kaynağı:** ayar `config.py`, prompt `prompts.py`, özellik
  pencereleri `feature_service.py` (model sözleşmesi).
