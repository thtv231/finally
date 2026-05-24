# Massive API Reference (formerly Polygon.io)

Reference documentation for the Massive (formerly Polygon.io) REST and WebSocket API as used in FinAlly.

## Overview

Polygon.io rebranded as **Massive** on October 30, 2025. Existing API keys, accounts, and integrations continue to work without changes. The API now defaults to `api.massive.com` while `api.polygon.io` remains supported indefinitely.

- **Base URL**: `https://api.massive.com` (legacy `https://api.polygon.io` still resolves)
- **Python package**: `massive` (install via `uv add massive` / `pip install -U massive`)
- **Min Python**: 3.9+
- **Auth**: API key via `MASSIVE_API_KEY` env var or passed directly to `RESTClient`
- **Auth header**: `Authorization: Bearer <API_KEY>` (handled automatically by the client)
- **Official docs**: https://massive.com/docs
- **Python client repo**: https://github.com/massive-com/client-python

---

## Pricing Tiers & Rate Limits

| Tier | Price | Data | Rate Limit |
|------|-------|------|------------|
| **Free** | $0 | Delayed (15 min) | 5 requests/minute |
| **Starter** | $29/month | 15-min delayed | Unlimited |
| **Developer** | $79/month | Real-time | Unlimited |
| **Advanced** | $199/month | Real-time + WebSocket streaming | Unlimited |

Annual billing gives 2 months free. Free trial available for business plans.

**For FinAlly**: The Starter or Developer tier is recommended for a working demo. On the Free tier, use a 15-second poll interval to stay within the 5 req/min limit. On paid tiers, a 2–5 second interval is appropriate.

---

## Python Client Installation

```bash
# Using uv (recommended for this project)
uv add massive

# Or pip
pip install -U massive
```

---

## Client Initialization

```python
from massive import RESTClient

# Reads MASSIVE_API_KEY from environment automatically
client = RESTClient()

# Or pass explicitly
client = RESTClient(api_key="your_key_here")

# Legacy polygon.io base URL still works
client = RESTClient(api_key="your_key_here", base="https://api.polygon.io")
```

---

## Endpoints Used in FinAlly

### 1. Snapshot — All Tickers (Primary Polling Endpoint)

Gets current market data for multiple tickers in a **single API call**. This is the main endpoint for the Massive poller — one call covers the entire watchlist regardless of size.

**REST**: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,GOOGL,MSFT`

**Python client**:
```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient()

# Single call fetches all watched tickers
snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"],
)

for snap in snapshots:
    print(f"{snap.ticker}: ${snap.last_trade.price:.2f}")
    print(f"  Day change: {snap.day.change_percent:.2f}%")
    print(f"  Day OHLC: O={snap.day.open} H={snap.day.high} L={snap.day.low} C={snap.day.close}")
    print(f"  Volume: {snap.day.volume:,}")
    print(f"  Prev close: ${snap.day.previous_close:.2f}")
```

**Response structure** (per ticker in the `tickers` array):
```json
{
  "ticker": "AAPL",
  "day": {
    "open": 189.50,
    "high": 191.20,
    "low": 188.80,
    "close": 190.75,
    "volume": 52341200,
    "volume_weighted_average_price": 190.10,
    "previous_close": 188.90,
    "change": 1.85,
    "change_percent": 0.98
  },
  "last_trade": {
    "price": 190.75,
    "size": 100,
    "exchange": "XNYS",
    "timestamp": 1707580800000
  },
  "last_quote": {
    "bid_price": 190.74,
    "ask_price": 190.76,
    "bid_size": 300,
    "ask_size": 500,
    "spread": 0.02,
    "timestamp": 1707580800500
  },
  "prev_daily_bar": {
    "open": 187.20,
    "high": 189.80,
    "low": 186.50,
    "close": 188.90,
    "volume": 48100000
  }
}
```

**Fields we extract for FinAlly**:
| Field | Use |
|-------|-----|
| `last_trade.price` | Current price for display, trading, portfolio valuation |
| `last_trade.timestamp` | Timestamp for the PriceUpdate (milliseconds → divide by 1000 for Unix seconds) |
| `day.previous_close` | Day change calculation (not used in the cache directly, but useful for UI) |
| `day.change_percent` | Day % change shown in the watchlist |

### 2. Single Ticker Snapshot

Detailed snapshot for one ticker. Useful when a user clicks a ticker for the detail view.

**Python client**:
```python
snapshot = client.get_snapshot_ticker(
    market_type=SnapshotMarketType.STOCKS,
    ticker_symbol="AAPL",
)

print(f"Price:     ${snapshot.last_trade.price:.2f}")
print(f"Bid/Ask:   ${snapshot.last_quote.bid_price:.2f} / ${snapshot.last_quote.ask_price:.2f}")
print(f"Day range: ${snapshot.day.low:.2f} – ${snapshot.day.high:.2f}")
print(f"Volume:    {snapshot.day.volume:,}")
```

### 3. Previous Close (End-of-Day OHLCV)

Previous trading day's OHLC and volume for a ticker. Useful as a seed price source when starting up with real market data.

**REST**: `GET /v2/aggs/ticker/{ticker}/prev`

**Python client**:
```python
prev = client.get_previous_close_agg(ticker="AAPL")

for agg in prev:
    print(f"Previous close: ${agg.close:.2f}")
    print(f"OHLC: O={agg.open:.2f} H={agg.high:.2f} L={agg.low:.2f} C={agg.close:.2f}")
    print(f"Volume: {agg.volume:,}")
    print(f"VWAP: ${agg.vwap:.2f}")
```

**Response**:
```json
{
  "ticker": "AAPL",
  "results": [
    {
      "o": 188.20,
      "h": 190.05,
      "l": 187.10,
      "c": 189.50,
      "v": 48123000,
      "vw": 188.95,
      "t": 1707494400000
    }
  ]
}
```

### 4. Aggregates (Historical Bars)

Historical OHLCV bars over a date range. Used for the main chart if historical data is needed. The client handles pagination automatically via the iterator pattern.

**REST**: `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`

**Python client**:
```python
from datetime import date

aggs = list(client.list_aggs(
    ticker="AAPL",
    multiplier=1,
    timespan="day",           # "minute", "hour", "day", "week", "month"
    from_="2025-01-01",
    to="2025-01-31",
    adjusted=True,            # Split/dividend adjusted prices
    sort="asc",
    limit=50000,              # Max per page; client auto-paginates
))

for a in aggs:
    # a.timestamp is Unix milliseconds
    dt = date.fromtimestamp(a.timestamp / 1000)
    print(f"{dt}: O={a.open:.2f} H={a.high:.2f} L={a.low:.2f} C={a.close:.2f} V={a.volume:,}")
```

**Timespans**: `second`, `minute`, `hour`, `day`, `week`, `month`, `quarter`, `year`

### 5. Last Trade

Most recent trade for a single ticker.

```python
trade = client.get_last_trade(ticker="AAPL")
print(f"Price: ${trade.price:.2f}")
print(f"Size:  {trade.size} shares")
print(f"Time:  {trade.participant_timestamp}")
```

### 6. Last NBBO Quote

Current best bid and ask.

```python
quote = client.get_last_quote(ticker="AAPL")
print(f"Bid: ${quote.bid_price:.2f} x {quote.bid_size}")
print(f"Ask: ${quote.ask_price:.2f} x {quote.ask_size}")
```

---

## WebSocket API (Advanced Tier)

Available on the Advanced plan ($199/month). Provides true real-time streaming without polling — ideal for production. FinAlly uses REST polling by default, but the WebSocket client is available if needed.

**WebSocket endpoint**: `wss://socket.massive.com/stocks`

**Python client**:
```python
from massive import WebSocketClient
from massive.websocket.models import WebSocketStock

def handle_message(messages: list[WebSocketStock]) -> None:
    for msg in messages:
        if msg.event_type == "T":  # Trade
            print(f"{msg.symbol}: ${msg.price:.2f} x {msg.size}")
        elif msg.event_type == "A":  # Aggregate (per second)
            print(f"{msg.symbol}: OHLC {msg.open}/{msg.high}/{msg.low}/{msg.close}")

client = WebSocketClient(subscriptions=["T.AAPL", "T.GOOGL", "A.MSFT"])
client.run(handle_message)
```

**Subscription channels**:
| Channel | Data |
|---------|------|
| `T.<ticker>` | Tick-level trades |
| `Q.<ticker>` | NBBO quote updates |
| `A.<ticker>` | Per-second OHLCV aggregates |
| `AM.<ticker>` | Per-minute OHLCV aggregates |

**Why FinAlly uses REST polling instead**: The WebSocket API requires the Advanced tier. REST polling with the snapshot endpoint costs one API call regardless of watchlist size, works on all tiers, and is simpler to implement and test.

---

## How FinAlly Uses the API

The `MassiveDataSource` runs as a background asyncio task:

1. Reads all active watchlist tickers
2. Calls `get_snapshot_all()` with those tickers — **one API call for all tickers**
3. Extracts `last_trade.price` and `last_trade.timestamp` from each snapshot
4. Writes to the shared in-memory `PriceCache`
5. Sleeps for the poll interval, then repeats

```python
import asyncio
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

async def poll_loop(api_key: str, get_tickers, price_cache, interval: float = 15.0):
    """Full poll loop used by MassiveDataSource."""
    client = RESTClient(api_key=api_key)

    # Poll once immediately so cache has data right away
    await poll_once(client, get_tickers(), price_cache)

    while True:
        await asyncio.sleep(interval)
        tickers = get_tickers()
        if tickers:
            await poll_once(client, tickers, price_cache)


async def poll_once(client: RESTClient, tickers: list[str], price_cache) -> None:
    """Single poll: fetch snapshots and update cache."""
    if not tickers:
        return

    # RESTClient is synchronous — run in a thread to avoid blocking the event loop
    snapshots = await asyncio.to_thread(
        client.get_snapshot_all,
        market_type=SnapshotMarketType.STOCKS,
        tickers=tickers,
    )

    for snap in snapshots:
        price_cache.update(
            ticker=snap.ticker,
            price=snap.last_trade.price,
            timestamp=snap.last_trade.timestamp / 1000.0,  # ms → seconds
        )
```

---

## Error Handling

The `RESTClient` raises standard Python exceptions for HTTP errors. The Massive poller catches all exceptions per-cycle so a transient error doesn't kill the background task.

| HTTP Status | Cause | FinAlly Behavior |
|-------------|-------|-----------------|
| **401** Unauthorized | Invalid API key | Log error, keep retrying |
| **403** Forbidden | Plan doesn't include endpoint | Log error, keep retrying |
| **429** Rate Limited | Too many requests (free tier) | Log error, retry after `poll_interval` |
| **5xx** Server Error | Massive outage | Log error, retry automatically |
| Network timeout | Connection issue | Log error, retry on next cycle |

```python
try:
    snapshots = await asyncio.to_thread(
        client.get_snapshot_all,
        market_type=SnapshotMarketType.STOCKS,
        tickers=tickers,
    )
    for snap in snapshots:
        price_cache.update(
            ticker=snap.ticker,
            price=snap.last_trade.price,
            timestamp=snap.last_trade.timestamp / 1000.0,
        )
except Exception as e:
    logger.error("Massive poll failed: %s", e)
    # Cache retains last-known prices; SSE keeps streaming stale data
    # This is intentional — stale prices > no prices for a trading dashboard
```

---

## Important Notes

- **Single call for all tickers**: `get_snapshot_all()` with a list of tickers counts as one API call regardless of list length. This is why even the free tier (5 req/min) can support a 10-ticker watchlist with a 15-second poll interval.
- **Timestamps are Unix milliseconds**: Divide by 1000 to convert to the Unix seconds used in `PriceUpdate`.
- **Market hours**: During pre-market and after-hours, `last_trade.price` reflects the most recent trade (may be from extended hours). The `day` OHLCV resets at market open.
- **Fractional shares**: The API supports fractional share volumes via `fractional_volume` and `fractional_size` fields added in 2025. FinAlly already supports fractional quantities in its portfolio schema.
- **The `massive` package is a production dependency**: Unlike the simulator (which needs only numpy), the Massive path requires the `massive` package. It is included in `pyproject.toml` regardless so both code paths are always installed.
