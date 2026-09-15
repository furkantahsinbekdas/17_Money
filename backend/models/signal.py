from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MarketData(BaseModel):
    symbol: str
    interval: str
    current_price: float
    ema_20: Optional[float]
    ema_50: Optional[float]
    ema_200: Optional[float]
    rsi: Optional[float]
    macd: dict
    trend: str
    order_blocks: list
    fvg: list
    liquidity: dict
    structure: dict
    timestamp: datetime = datetime.utcnow()


class TradingSignal(BaseModel):
    symbol: str
    sinyal: str  # LONG / SHORT / BEKLE
    giris: Optional[float]
    stop_loss: Optional[float]
    hedef: Optional[float]
    risk_odul: Optional[str]
    guven_skoru: int
    analiz: str
    trend_ozet: Optional[str]
    kritik_seviyeler: List[str] = []
    timestamp: datetime = datetime.utcnow()


class MarketContext(BaseModel):
    dxy: Optional[float]
    vix: Optional[float]
    gold: Optional[float]
    sp500: Optional[float]
    fear_greed_value: int = 50
    fear_greed_label: str = "Neutral"
    funding_rate: float = 0.0
    btc_price: Optional[float]
    trend: Optional[str]


class ChatMessage(BaseModel):
    role: str  # "user" veya "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    model: Optional[str] = None  # ALLOWED_CHAT_MODELS içinden; None → varsayılan
