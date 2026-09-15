import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout


import config


class BinanceUnreachable(Exception):
    """Binance API'ye ağ seviyesinde ulaşılamadığında fırlatılır."""
    pass


class BinanceService:
    """
    BTC/USDT Futures piyasa verisi servisi.

    Not: Bu makineden Binance spot endpoint'leri (api.binance.com,
    *.binance.vision) bağlantıyı sıfırlıyor; yalnızca futures testnet
    (testnet.binancefuture.com) erişilebilir. Bu yüzden:
    - İstemci tembel (lazy) kurulur ve açılışta ping atılmaz —
      Binance erişilemez olsa bile backend ayağa kalkar.
    - Tüm piyasa verisi futures endpoint'lerinden çekilir (uygulama
      zaten futures odaklı).
    """

    def __init__(self):
        self._client = None
        self._api_key = config.BINANCE_API_KEY
        self._api_secret = config.BINANCE_SECRET_KEY
        self.use_testnet = config.BINANCE_TESTNET

    @property
    def client(self) -> Client:
        if self._client is None:
            # ping=False: kurucu spot API'ye ping atmasın (spot engelli olabilir)
            self._client = Client(
                self._api_key,
                self._api_secret,
                testnet=self.use_testnet,
                ping=False,
            )
        return self._client

    def _call(self, fn, *args, **kwargs):
        """Ağ hatalarını anlaşılır tek bir hata tipine çevirir."""
        try:
            return fn(*args, **kwargs)
        except (RequestsConnectionError, Timeout) as e:
            raise BinanceUnreachable(
                "Binance API'ye ulaşılamıyor (bağlantı reddedildi/zaman aşımı). "
                "Bu makineden Binance erişimi engellenmiş olabilir — "
                "BINANCE_TESTNET=true (futures testnet) ayarını ve ağ/VPN durumunu kontrol edin."
            ) from e

    _INTERVAL_MAP = {
        "1m": Client.KLINE_INTERVAL_1MINUTE,
        "5m": Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
        "1h": Client.KLINE_INTERVAL_1HOUR,
        "4h": Client.KLINE_INTERVAL_4HOUR,
        "1d": Client.KLINE_INTERVAL_1DAY,
    }

    @staticmethod
    def _parse_klines(raw: list) -> pd.DataFrame:
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        df.set_index("open_time", inplace=True)

        return df[["open", "high", "low", "close", "volume"]]

    def get_klines(self, symbol: str, interval: str,
                   limit: int = config.BROADCAST_KLINE_LIMIT) -> pd.DataFrame:
        """Belirtilen sembol ve zaman dilimine ait OHLCV mum verisini futures piyasasından çeker."""
        binance_interval = self._INTERVAL_MAP.get(interval, Client.KLINE_INTERVAL_1HOUR)

        raw = self._call(
            self.client.futures_klines,
            symbol=symbol, interval=binance_interval, limit=limit,
        )
        return self._parse_klines(raw)

    def get_klines_history(self, symbol: str, interval: str, total: int = 6000) -> pd.DataFrame:
        """
        Tek istek limitinin (1500) ötesinde tarihsel veri — endTime ile geriye
        doğru sayfalayarak `total` bara kadar çeker (backfill/eğitim için).
        Borsanın tuttuğu tarih biterse eldekiyle döner.
        """
        binance_interval = self._INTERVAL_MAP.get(interval, Client.KLINE_INTERVAL_1HOUR)
        frames: list[pd.DataFrame] = []
        end_time: int | None = None
        remaining = total

        while remaining > 0:
            params = {"symbol": symbol, "interval": binance_interval,
                      "limit": min(remaining, config.BINANCE_MAX_KLINES_PER_CALL)}
            if end_time is not None:
                params["endTime"] = end_time
            raw = self._call(self.client.futures_klines, **params)
            if not raw:
                break
            frames.append(self._parse_klines(raw))
            remaining -= len(raw)
            end_time = int(raw[0][0]) - 1  # en eski barın hemen öncesi
            if len(raw) < params["limit"]:
                break  # tarih başına ulaşıldı

        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.concat(frames)
        return df[~df.index.duplicated(keep="first")].sort_index()

    def get_orderbook(self, symbol: str, limit: int = config.ORDERBOOK_LIMIT) -> dict:
        """Futures emir defterinden en büyük alım/satım emirlerini getirir."""
        try:
            book = self._call(self.client.futures_order_book, symbol=symbol, limit=limit)
            return {
                "bids": [[float(p), float(q)] for p, q in book["bids"]],
                "asks": [[float(p), float(q)] for p, q in book["asks"]],
            }
        except (BinanceAPIException, BinanceUnreachable) as e:
            return {"error": str(e), "bids": [], "asks": []}

    def get_ticker(self, symbol: str) -> dict:
        """Güncel fiyat, 24s değişim ve hacim bilgisi (futures)."""
        try:
            ticker = self._call(self.client.futures_ticker, symbol=symbol)
            return {
                "symbol": ticker["symbol"],
                "price": float(ticker["lastPrice"]),
                "change_pct": float(ticker["priceChangePercent"]),
                "volume_24h": float(ticker["volume"]),
                "high_24h": float(ticker["highPrice"]),
                "low_24h": float(ticker["lowPrice"]),
            }
        except (BinanceAPIException, BinanceUnreachable) as e:
            return {"error": str(e)}

    def get_funding_rate(self, symbol: str) -> dict:
        """
        Funding rate — pozitif değer long ağırlıklı (short avantajlı),
        negatif değer short ağırlıklı (long avantajlı) anlamına gelir.
        """
        try:
            rates = self._call(self.client.futures_funding_rate, symbol=symbol, limit=1)
            if rates:
                r = rates[-1]
                return {
                    "symbol": r["symbol"],
                    "funding_rate": float(r["fundingRate"]),
                    "funding_time": r["fundingTime"],
                }
            return {"funding_rate": 0.0}
        except (BinanceAPIException, BinanceUnreachable):
            # Testnet funding rate desteklemeyebilir
            return {"funding_rate": 0.0, "note": "testnet limitation"}

    def get_open_interest(self, symbol: str) -> dict:
        """Açık pozisyon hacmi — yüksek OI daha büyük volatilite anlamına gelebilir."""
        try:
            oi = self._call(self.client.futures_open_interest, symbol=symbol)
            return {
                "symbol": oi["symbol"],
                "open_interest": float(oi["openInterest"]),
            }
        except (BinanceAPIException, BinanceUnreachable):
            return {"open_interest": 0.0, "note": "testnet limitation"}
