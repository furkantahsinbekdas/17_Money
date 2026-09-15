# 17Money Algorithm

> **Production-grade AI-native trading partner for BTC/USDT Futures.**  
> Integrates multi-timeframe technical analysis, a deterministic forecast engine, stochastic mathematics (Hurst/GARCH), live macro/news context, and a champion-challenger meta-model with Claude LLM reasoning.

---

### Disclaimer
*This project is built strictly for research and educational purposes. It does NOT constitute financial or investment advice. The engine runs in paper trading mode (simulated funds) by default.*

---

## 1. System Architecture

```text
config/            .env (SECRETS — git-ignored) + .env.example
backend/
  config.py        ★ Single Source of Truth (168 environment variables & settings)
  prompts.py       ★ Production LLM System Prompts & Structured JSON Schemas
  main.py          FastAPI core + async background execution cycles (lifespan)
  routers/         market · analysis · ai · meta · paper
  services/        binance · technical · forecast · stochastic · news ·
                   claude_service · claude_cli · claude_vote · signal_store ·
                   meta_model · trainer_service · backfill · history_downloader ·
                   paper_account · session_filter · alert_service · feature
  data/            Local SQLite stores & parquet tick cache (git-ignored)
frontend/          React dashboard (Lightweight Charts, Terminal, Science & Paper panels)
ml/                Model artifacts & training data directories (git-ignored)

```

### Core Design Rules

1. **Zero Hardcoded Secrets & Constants:** Every URL, model identifier, timeout, and trading parameter lives inside `backend/config.py` and can be overridden via environment variables.
2. **Byte-Exact Prompt Isolation:** System prompts and JSON response schemas are strictly encapsulated in `backend/prompts.py` to maintain Anthropic prompt cache efficiency without accidental cache invalidation.

---

## 2. Core Philosophy & Engineering Principles

* **Dual-Brain Architecture:** Combines a deterministic quantitative engine that calculates mathematical edge with Claude's semantic reasoning on real-time news/macro signals. Final trade signals require multi-agent consensus voting.
* **Evidence-Driven ML Pipeline:** Implements triple-barrier labeling, walk-forward testing, Combinatorial Purged Cross-Validation (CPCV), and Deflated Sharpe Ratio. Challenger models only replace the active champion if they demonstrate statistically significant outperformance.
* **Autonomous Capital Protection:** Includes an automated circuit breaker with strict drawdown limits (default: -25%), dynamic cooldown modes reducing risk scale on consecutive losses, and low-liquidity session filters (e.g., Asian night sessions).

---

## 3. Quick Start

### 3.1 Environment Configuration

```bash
# Copy template configuration
cp config/.env.example config/.env

```

Populate the following keys in `config/.env`:

| Variable | Required | Description |
| --- | --- | --- |
| `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` | Recommended | Live/historical market data and paper execution. Testnet keys supported. |
| `CLAUDE_API_KEY` | Optional | Direct Anthropic API access. If unset, fallback uses authenticated local Claude CLI. |
| `NEWS_API_KEY` / `CRYPTOPANIC_KEY` | Optional | News sentiment aggregation. If missing, the engine gracefully disables news layers. |

### 3.2 Backend Service

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

```

### 3.3 Frontend Dashboard

```bash
cd frontend
npm install
npm start

```

*Frontend runs on `http://localhost:3000` and reads parameters dynamically from `frontend/.env`.*

---

## 4. Key API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Service uptime and diagnostic health check |
| `GET` | `/api/ai/status` | Active LLM runtime (API vs CLI), current model, and fallback chain |
| `GET` | `/api/market/btc?interval=1h` | Technical package: multi-timeframe EMA, RSI, ADX, ATR, and market structure |
| `GET` | `/api/analysis/forecast/{symbol}` | Deterministic multi-factor directional index (0–100 score) |
| `GET` | `/api/analysis/stochastic/{symbol}` | Hurst exponent, GARCH volatility, tail-risk, and diffusion dynamics |
| `GET` | `/api/ai/signal?interval=1h` | Full multi-modal Claude reasoning trade signal generation |
| `POST` | `/api/meta/challenge` | Triggers champion vs challenger model evaluation pipeline |
| `GET` | `/api/paper/status` | Simulated account equity, active positions, PnL, and circuit breaker metrics |

---

## 5. Security & Deployment Checklist

* [x] Secrets isolated in `config/.env` and excluded from git tracking.
* [x] Runtime databases (`.db`), parquet cache (`.parquet`), and model files (`.joblib`) excluded via `.gitignore`.
* [x] Cross-validated with zero syntax errors (`compileall`) and zero missing symbol imports.
