import asyncio

import httpx
import pandas as pd

import config

NEWS_API_KEY = config.NEWS_API_KEY
CRYPTOPANIC_KEY = config.CRYPTOPANIC_KEY
FEAR_GREED_API = config.FEAR_GREED_API


class NewsService:

    async def get_crypto_news(self) -> list:
        """CryptoPanic'ten kripto haberleri çeker. Fallback: NewsAPI."""
        if CRYPTOPANIC_KEY:
            return await self._get_cryptopanic()
        elif NEWS_API_KEY:
            return await self._get_newsapi()
        return []

    async def _get_cryptopanic(self) -> list:
        url = (f"{config.CRYPTOPANIC_API}?auth_token={CRYPTOPANIC_KEY}"
                   f"&currencies=BTC&kind=news&public=true")
        try:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SEC) as client:
                r = await client.get(url)
                data = r.json()
                results = data.get("results", [])
                return [
                    {
                        "title": item.get("title", ""),
                        "source": item.get("source", {}).get("title", ""),
                        "url": item.get("url", ""),
                        "sentiment": item.get("votes", {}).get("positive", 0) - item.get("votes", {}).get("negative", 0),
                    }
                    for item in results[:config.NEWS_ITEM_LIMIT]
                ]
        except Exception:
            return []

    async def _get_newsapi(self) -> list:
        url = (
            f"{config.NEWSAPI_URL}?"
            f"q={config.NEWS_QUERY}&language={config.NEWS_LANGUAGE}"
            f"&sortBy=publishedAt&pageSize={config.NEWSAPI_PAGE_SIZE}"
            f"&apiKey={NEWS_API_KEY}"
        )
        try:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SEC) as client:
                r = await client.get(url)
                data = r.json()
                articles = data.get("articles", [])
                return [
                    {
                        "title": a.get("title", ""),
                        "source": a.get("source", {}).get("name", ""),
                        "url": a.get("url", ""),
                        "sentiment": 0,
                    }
                    for a in articles
                ]
        except Exception:
            return []

    async def get_fear_greed(self) -> dict:
        """alternative.me Fear & Greed Index — ücretsiz, API key gerektirmez."""
        try:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SEC) as client:
                r = await client.get(f"{FEAR_GREED_API}?limit=1")
                data = r.json()
                entry = data.get("data", [{}])[0]
                return {
                    "value": int(entry.get("value", 50)),
                    "label": entry.get("value_classification", "Neutral"),
                }
        except Exception:
            return {"value": 50, "label": "Neutral"}

    # Tahmin motoru için takip edilen piyasalar — VantagePoint tarzı intermarket analiz
    # Takipteki piyasalar config.py'de (INTERMARKET_TICKERS ile ezilebilir)
    INTERMARKET_TICKERS = config.INTERMARKET_TICKERS

    async def get_intermarket(self, btc_daily_closes: pd.Series) -> dict:
        """
        VantagePoint tarzı intermarket analizi: BTC'nin ilişkili piyasalarla
        son ~90 günlük getiri korelasyonunu hesaplar. Pozitif korelasyonlu
        piyasa düşerken BTC long açmak ters rüzgara girmektir — AI bu veriyi
        konfluens olarak kullanır.
        """
        btc = btc_daily_closes.copy()
        btc.index = pd.to_datetime(btc.index).date
        btc_ret = pd.Series(btc.values, index=btc.index).pct_change().dropna()

        results = {}
        async with httpx.AsyncClient(timeout=config.YAHOO_TIMEOUT_SEC) as client:
            for key, (ticker, ad, beklenen) in self.INTERMARKET_TICKERS.items():
                entry = {"ad": ad, "deger": None, "degisim_yuzde": None,
                         "korelasyon_90g": None, "beklenen_iliski": beklenen}
                try:
                    url = (f"{config.YAHOO_CHART_URL}/{ticker}"
                           f"?interval=1d&range={config.CORRELATION_RANGE}")
                    r = await client.get(url, headers={"User-Agent": config.HTTP_USER_AGENT})
                    data = r.json()
                    result = data.get("chart", {}).get("result", [{}])[0]
                    meta = result.get("meta", {})
                    ts = result.get("timestamp", [])
                    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

                    entry["deger"] = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose")
                    if entry["deger"] and prev:
                        entry["degisim_yuzde"] = round((entry["deger"] - prev) / prev * 100, 2)

                    if ts and closes:
                        dates = [pd.Timestamp(t, unit="s").date() for t in ts]
                        ser = pd.Series(closes, index=dates).dropna()
                        ret = ser.pct_change().dropna()
                        aligned = pd.concat([btc_ret, ret], axis=1, join="inner").dropna()
                        if len(aligned) >= config.CORRELATION_MIN_POINTS:
                            corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                            entry["korelasyon_90g"] = round(float(corr), 3)
                except Exception:
                    pass
                results[key] = entry

        return results

    async def get_macro_data(self) -> dict:
        """
        DXY, VIX, Altın, S&P için fallback değerler döndürür.
        Gerçek entegrasyon için Yahoo Finance veya Alpha Vantage kullanılabilir.
        """
        # Ücretsiz Yahoo Finance query
        results = {}
        tickers = config.MACRO_TICKERS
        try:
            async with httpx.AsyncClient(timeout=config.YAHOO_TIMEOUT_SEC) as client:
                for key, ticker in tickers.items():
                    url = f"{config.YAHOO_CHART_URL}/{ticker}?interval=1d&range=1d"
                    r = await client.get(url, headers={"User-Agent": config.HTTP_USER_AGENT})
                    data = r.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    results[key] = meta.get("regularMarketPrice", None)
        except Exception:
            pass

        return results
