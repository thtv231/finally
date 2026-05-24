# Market Data Interface Design

Unified Python interface for market data in FinAlly. Two concrete implementations — a GBM simulator and a Massive REST poller — sit behind one abstract base class. All downstream code (SSE streaming, portfolio valuation, trade execution, watchlist management) is source-agnostic.

---

## Architecture Overview

```
Environment variable MASSIVE_API_KEY
         │
         ▼
  create_market_data_source(price_cache)
         │
         ├── key set → MassiveDataSource   (REST polling, every 15s)
         └── key absent → SimulatorDataSource  (GBM, every 500ms)
                │
                ▼
           PriceCache  (thread-safe in-memory store)
                │
                ├──→ SSE stream (/api/stream/prices)
                ├──→ Trade execution (current price lookup)
                └──→ Portfolio valuation (P&L calculation)
```

The data source writes to the `PriceCache` on its own schedule. Everything downstream reads from the cache — there is no direct coupling between the data source and its consumers.

---

## File Structure

```
backend/
  app/
    market/
      __init__.py          # Re-exports public API
      models.py            # PriceUpdate — the only type that crosses the boundary
      cache.py             # PriceCache — thread-safe in-memory price store
      interface.py         # MarketDataSource — abstract base class
      seed_prices.py       # Seed prices, GBM params, correlation groups (constants only)
      simulator.py         # GBMSimulator + SimulatorDataSource
      massive_client.py    # MassiveDataSource
      factory.py           # create_market_data_source()
      stream.py            # SSE endpoint (FastAPI router factory)
```

Each file has a single responsibility. `__init__.py` re-exports the public API so callers import from `app.market` without reaching into submodules.

---

## Core Data Model

**File: `backend/app/market/models.py`**

`PriceUpdate` is the only data structure that leaves the market data layer. SSE streaming, trade execution, and portfolio valuation all work exclusively with this type.

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

**Design decisions**:
- `frozen=True` — price updates are immutable value objects, safe to share across async tasks
- `slots=True` — minor memory optimization; we create thousands of these per minute
- Computed properties (`change`, `direction`, `change_percent`) — derived from `price` and `previous_price`, so they can never be stale or inconsistent
- `to_dict()` — single serialization point used by the SSE endpoint and REST responses

---

## Price Cache

**File: `backend/app/market/cache.py`**

The shared data hub. Data sources write to it; the SSE endpoint and portfolio logic read from it. Thread-safe because the Massive poller runs in `asyncio.to_thread()` (a real OS thread) while SSE reads happen on the asyncio event loop.

```python
from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Bumped on every update; used for SSE change detection

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. Returns the PriceUpdate.

        First update for a ticker: previous_price == price, direction == 'flat'.
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Why `threading.Lock` and not `asyncio.Lock`**: The Massive client's synchronous `get_snapshot_all()` runs in `asyncio.to_thread()`, which operates in a real OS thread. `asyncio.Lock` would not protect against concurrent access from that thread. `threading.Lock` works correctly from both sync threads and the async event loop.

**Why a version counter**: The SSE loop polls the cache every 500ms. Without change detection, it would serialize and send all prices on every tick even when nothing changed (e.g., Massive API updates every 15s). The version counter lets the SSE loop skip sends:

```python
last_version = -1
while True:
    if price_cache.version != last_version:
        last_version = price_cache.version
        yield format_sse(price_cache.get_all())
    await asyncio.sleep(0.5)
```

---

## Abstract Interface

**File: `backend/app/market/interface.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source for prices — it
    reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task. Seeds the cache with initial prices before
        the loop begins so the SSE endpoint has data on its first tick.
        Call exactly once.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Safe to call multiple times."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and from the PriceCache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

**Why the source writes to the cache instead of returning prices**: Push decouples timing. The simulator ticks at 500ms; Massive polls at 15s; SSE always reads from the cache at its own 500ms cadence. The SSE layer doesn't need to know which source is active or what its update interval is.

---

## Factory Function

**File: `backend/app/market/factory.py`**

```python
from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Select the appropriate data source based on environment.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
    - Otherwise → SimulatorDataSource (GBM simulation, zero external dependencies)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        from .massive_client import MassiveDataSource
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        from .simulator import SimulatorDataSource
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

---

## Massive Implementation

**File: `backend/app/market/massive_client.py`**

Polls the Massive REST snapshot endpoint on a configurable interval. The synchronous `RESTClient` runs in `asyncio.to_thread()` to avoid blocking the event loop.

```python
from __future__ import annotations

import asyncio
import logging
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive REST API.

    Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all watched
    tickers in a single API call, then writes results to the PriceCache.

    Rate limits:
      - Free tier:  5 req/min  → use poll_interval=15.0 (default)
      - Paid tiers: unlimited  → use poll_interval=2.0–5.0
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._client = RESTClient(api_key=api_key)
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)
        # Poll immediately so cache has data before the first SSE push
        await self._poll_once()
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info("Massive poller started: %d tickers, %.1fs interval", len(tickers), self._interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added ticker %s (will appear on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _poll_loop(self) -> None:
        """Sleep, then poll. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers:
            return
        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    self._cache.update(
                        ticker=snap.ticker,
                        price=snap.last_trade.price,
                        timestamp=snap.last_trade.timestamp / 1000.0,  # ms → seconds
                    )
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning("Skipping snapshot for %s: %s", getattr(snap, "ticker", "???"), e)
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))
        except Exception as e:
            logger.error("Massive poll failed: %s", e)
            # Don't re-raise — cache retains last-known prices; loop retries next interval

    def _fetch_snapshots(self) -> list:
        """Synchronous Massive API call. Runs in a thread via asyncio.to_thread()."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

**Error handling policy**:

| Error | Behavior |
|-------|----------|
| 401 Unauthorized | Logged. Poller keeps running; fix key and restart. |
| 429 Rate Limited | Logged. Retries after `poll_interval` seconds. |
| Network timeout | Logged. Retries automatically next cycle. |
| Malformed snapshot | Individual ticker skipped with warning; others still processed. |
| All tickers fail | Cache retains stale prices. SSE keeps streaming (stale > nothing). |

---

## Simulator Implementation (Sketch)

Full detail in `MARKET_SIMULATOR.md`. The simulator wraps `GBMSimulator` in an async loop and seeds the cache immediately on `start()`.

```python
import asyncio
from .cache import PriceCache
from .interface import MarketDataSource


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM price simulator.

    Calls GBMSimulator.step() every update_interval seconds and writes
    results to the PriceCache. Zero external dependencies (only numpy).
    """

    def __init__(self, price_cache: PriceCache, update_interval: float = 0.5) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._sim = None   # GBMSimulator, created in start()
        self._task = None

    async def start(self, tickers: list[str]) -> None:
        from .simulator import GBMSimulator
        self._sim = GBMSimulator(tickers=tickers)
        # Seed cache with initial prices before loop starts
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

---

## SSE Streaming Endpoint

**File: `backend/app/market/stream.py`**

The SSE endpoint holds open a long-lived HTTP connection and pushes price updates to the browser's `EventSource`.

```python
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Factory returns a configured APIRouter for the SSE endpoint."""
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",   # Disable nginx buffering if proxied
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    yield "retry: 1000\n\n"  # Tell browser to reconnect after 1s if connection drops

    last_version = -1
    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            current_version = price_cache.version
            if current_version != last_version:
                last_version = current_version
                prices = price_cache.get_all()
                if prices:
                    data = {ticker: update.to_dict() for ticker, update in prices.items()}
                    yield f"data: {json.dumps(data)}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
```

**SSE wire format** (each event the browser receives):
```
data: {"AAPL":{"ticker":"AAPL","price":190.50,"previous_price":190.42,"timestamp":1707580800.5,"change":0.08,"change_percent":0.042,"direction":"up"},"GOOGL":{...}}

```

**Frontend usage**:
```javascript
const eventSource = new EventSource('/api/stream/prices');
eventSource.onmessage = (event) => {
    const prices = JSON.parse(event.data);
    // { "AAPL": { ticker, price, previous_price, change, change_percent, direction, timestamp }, ... }
};
eventSource.onerror = () => {
    // EventSource auto-reconnects after the retry: 1000ms directive
};
```

---

## FastAPI Lifecycle Integration

**In `backend/app/main.py`**:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source, create_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    price_cache = PriceCache()
    app.state.price_cache = price_cache

    source = create_market_data_source(price_cache)
    app.state.market_source = source

    initial_tickers = await load_watchlist_tickers()  # reads from SQLite
    await source.start(initial_tickers)

    stream_router = create_stream_router(price_cache)
    app.include_router(stream_router)

    yield  # App is running

    # SHUTDOWN
    await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)


def get_price_cache() -> PriceCache:
    return app.state.price_cache


def get_market_source():
    return app.state.market_source
```

**Dependency injection in route handlers**:

```python
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api")


@router.post("/portfolio/trade")
async def execute_trade(
    trade: TradeRequest,
    price_cache: PriceCache = Depends(get_price_cache),
):
    current_price = price_cache.get_price(trade.ticker)
    if current_price is None:
        raise HTTPException(400, f"No price available for {trade.ticker}. Please wait a moment.")
    # ... execute trade at current_price ...


@router.post("/watchlist")
async def add_to_watchlist(
    payload: WatchlistAdd,
    source = Depends(get_market_source),
    price_cache: PriceCache = Depends(get_price_cache),
):
    await db.insert_watchlist_entry(payload.ticker)
    await source.add_ticker(payload.ticker)
    price = price_cache.get_price(payload.ticker)
    return {"ticker": payload.ticker, "price": price}


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    source = Depends(get_market_source),
):
    await db.delete_watchlist_entry(ticker)
    # Keep tracking if the user still holds a position in this ticker
    position = await db.get_position(ticker)
    if position is None or position.quantity == 0:
        await source.remove_ticker(ticker)
    return {"status": "ok"}
```

---

## Package `__init__.py`

**File: `backend/app/market/__init__.py`**

```python
"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate              - Immutable price snapshot dataclass
    PriceCache               - Thread-safe in-memory price store
    MarketDataSource         - Abstract interface for data providers
    create_market_data_source - Factory: selects simulator or Massive
    create_stream_router      - FastAPI router factory for the SSE endpoint
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]
```

---

## Lifecycle Summary

| Phase | Action |
|-------|--------|
| **App startup** | Create `PriceCache` → `create_market_data_source(cache)` → `await source.start(tickers)` |
| **Watchlist add** | `await source.add_ticker(ticker)` |
| **Watchlist remove** | `await source.remove_ticker(ticker)` (if no open position) |
| **SSE streaming** | Reads `price_cache.get_all()` every 500ms via version check |
| **Trade execution** | Reads `price_cache.get_price(ticker)` for fill price |
| **Portfolio P&L** | Reads `price_cache.get_price(ticker)` for each position |
| **App shutdown** | `await source.stop()` |

---

## Configuration

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `MASSIVE_API_KEY` | Environment variable | `""` (empty) | Set to use real data; absent = simulator |
| `update_interval` | `SimulatorDataSource.__init__` | `0.5` s | Simulator tick rate |
| `poll_interval` | `MassiveDataSource.__init__` | `15.0` s | Massive API poll interval |
| SSE push interval | `_generate_events()` | `0.5` s | Frequency of SSE pushes to the client |
| SSE retry directive | `_generate_events()` | `1000` ms | Browser EventSource reconnection delay |
