# Market Simulator Design

Approach and complete code structure for simulating realistic stock prices when no `MASSIVE_API_KEY` is configured. Zero external dependencies beyond `numpy`.

---

## Overview

The simulator uses **Geometric Brownian Motion (GBM)** to generate realistic stock price paths. GBM is the standard model underlying Black-Scholes option pricing — prices evolve continuously with random noise, can never go negative, and exhibit the lognormal distribution seen in real markets.

Updates run at 500ms intervals, producing a continuous stream of small price changes that feel alive. Correlated moves across sector-grouped tickers and occasional random "event" shocks add realism and visual drama.

---

## GBM Mathematics

At each time step, a stock price evolves as:

```
S(t+dt) = S(t) * exp((mu - sigma²/2) * dt + sigma * sqrt(dt) * Z)
```

Where:

| Symbol | Meaning | Typical value |
|--------|---------|---------------|
| `S(t)` | Current price | e.g. $190.00 |
| `mu` | Annualized drift (expected return) | 0.05 (5%) |
| `sigma` | Annualized volatility | 0.20–0.50 |
| `dt` | Time step as fraction of a trading year | ~8.5e-8 |
| `Z` | Standard normal random variable N(0,1) | drawn each tick |

**Computing `dt`** for 500ms ticks over a trading year:
```
Trading seconds/year = 252 days × 6.5 hours/day × 3600 s/hour = 5,896,800 s
dt = 0.5 / 5,896,800 ≈ 8.48e-8
```

This tiny `dt` produces sub-cent moves per tick (~$0.001 for a $190 stock at sigma=0.22). They accumulate naturally over time to produce realistic intraday ranges.

**Why GBM**:
- Prices are always positive (`exp()` is always positive)
- Returns are normally distributed (matches empirical data)
- Closed-form implementation — no numerical ODE solver needed
- The exponential formulation (`exp(drift + diffusion)`) is numerically stable

---

## Correlated Moves

Real stocks don't move independently — tech stocks tend to move together. We use **Cholesky decomposition** of a correlation matrix to generate correlated random draws from uncorrelated normals.

Given correlation matrix `C`, compute lower-triangular `L` such that `C = L @ Lᵀ` (Cholesky factorization). Then for independent standard normals `Z_independent`:

```
Z_correlated = L @ Z_independent
```

`Z_correlated` has the covariance structure of `C`. Each ticker gets its own correlated draw.

**Default correlation structure**:

| Pair | Correlation |
|------|-------------|
| Tech stocks with each other (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 |
| Finance stocks with each other (JPM, V) | 0.5 |
| TSLA with anything | 0.3 (it does its own thing) |
| Cross-sector (tech ↔ finance) | 0.3 |
| Unknown tickers | 0.3 |

The correlation matrix must be positive semi-definite for Cholesky to succeed. The above values satisfy this. When new tickers are added at runtime, the Cholesky matrix is rebuilt from scratch — O(n²) but n stays small (<50 tickers in practice).

---

## Random Event Shocks

Every step, each ticker has a small probability of a sudden 2–5% move. This adds drama and makes the dashboard look like real market action.

```python
if random.random() < event_probability:   # default: 0.001 (0.1%)
    shock_magnitude = random.uniform(0.02, 0.05)
    shock_sign = random.choice([-1, 1])
    price *= (1 + shock_magnitude * shock_sign)
```

**Expected frequency**: 0.001 × 2 ticks/sec = 1 event per 500 seconds per ticker. With 10 tickers, expect a shock somewhere in the watchlist roughly every 50 seconds — frequent enough to be interesting, rare enough to feel like news.

---

## Seed Prices & Per-Ticker Parameters

**File: `backend/app/market/seed_prices.py`**

Constants only — no logic, no imports beyond stdlib type hints. Shared by the simulator and potentially the Massive client (as fallback prices before the first poll).

```python
"""Seed prices and per-ticker GBM parameters for the market simulator."""

# Realistic starting prices for the default watchlist
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V":   280.00,
    "NFLX": 600.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = wider price swings per day)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},   # Stable large-cap tech
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},   # Lowest vol in tech
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},   # High vol; lower expected return
    "NVDA":  {"sigma": 0.40, "mu": 0.08},   # High vol; strong upward drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},   # Low vol (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},   # Lowest vol (payment network)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

# Default for tickers not in the list (dynamically added by the user)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Sector correlation groups
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

# Pairwise correlation coefficients
INTRA_TECH_CORR    = 0.6   # Tech ↔ tech
INTRA_FINANCE_CORR = 0.5   # Finance ↔ finance
CROSS_GROUP_CORR   = 0.3   # Tech ↔ finance, or unknown
TSLA_CORR          = 0.3   # TSLA with everything (in tech set but independent)
```

**Intraday range intuition** (sigma=0.22, S=$190, one trading day = 252 ticks @ 500ms over 6.5h):
- Daily sigma ≈ annualized sigma / sqrt(252) ≈ 0.22 / 15.87 ≈ 1.39%
- Expected daily range for AAPL ≈ $190 × 0.0139 ≈ $2.64 (realistic)
- TSLA (sigma=0.50): daily range ≈ $250 × 0.0315 ≈ $7.88 (high volatility, also realistic)

---

## Implementation

### GBMSimulator — The Math Engine

**File: `backend/app/market/simulator.py`** (first class)

Pure math engine. Stateful — holds current prices and advances them one step at a time. No I/O, no asyncio.

```python
from __future__ import annotations

import math
import random

import numpy as np

from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
    TICKER_PARAMS,
    TSLA_CORR,
)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - sigma²/2) * dt + sigma * sqrt(dt) * Z)

    The tiny dt (~8.5e-8 for 500ms over a trading year) produces sub-cent
    moves per tick that accumulate into realistic intraday ranges.
    """

    # 500ms as a fraction of a trading year
    # 252 days × 6.5 h/day × 3600 s/h = 5,896,800 trading seconds/year
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR   # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability

        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    # --- Public API ---

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        Called every 500ms — keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        # Independent standard normal draws
        z_independent = np.random.standard_normal(n)

        # Apply Cholesky to introduce inter-ticker correlation
        z = self._cholesky @ z_independent if self._cholesky is not None else z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            mu = self._params[ticker]["mu"]
            sigma = self._params[ticker]["sigma"]

            # GBM: S(t+dt) = S(t) * exp((mu - 0.5*sigma²)*dt + sigma*sqrt(dt)*Z)
            drift = (mu - 0.5 * sigma ** 2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event shock: ~0.1% chance per tick
            if random.random() < self._event_prob:
                magnitude = random.uniform(0.02, 0.05)
                sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + magnitude * sign

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker. Rebuilds the correlation matrix."""
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        """Current simulated price for a ticker, or None if not tracked."""
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        """Current list of tracked tickers."""
        return list(self._tickers)

    # --- Internal ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add a ticker without rebuilding Cholesky (used during batch init)."""
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition of the ticker correlation matrix.

        Called whenever tickers are added or removed. O(n²) but n < 50.
        With 0 or 1 tickers there is no correlation to apply, so _cholesky stays None.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Correlation between two tickers based on sector."""
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]

        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

---

### SimulatorDataSource — Async Wrapper

**File: `backend/app/market/simulator.py`** (second class, same file)

Wraps `GBMSimulator` in an asyncio task and implements the `MarketDataSource` interface. All I/O and async behavior lives here; `GBMSimulator` stays a pure sync math engine.

```python
import asyncio
import logging

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by GBMSimulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    update_interval seconds and writes results to the PriceCache.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)

        # Seed cache before loop starts so SSE has data on the very first push
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)

        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            # Seed cache immediately so the ticker has a price right away
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added ticker %s at $%.2f", ticker, price or 0)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed — continuing")
            await asyncio.sleep(self._interval)
```

**Key behaviors**:
- **Immediate seeding**: `start()` populates the cache with seed prices before the loop begins. The SSE endpoint has data to push on its very first tick — no blank-screen delay.
- **Graceful cancellation**: `stop()` cancels the task and awaits it with `CancelledError` caught. Clean shutdown during FastAPI lifespan teardown.
- **Exception resilience**: The loop wraps each step in `try/except` so a single bad tick doesn't kill the entire data feed.
- **add_ticker() seeds immediately**: When the user adds a ticker, it gets a simulated price in the cache instantly — trade execution won't see a "no price available" 400 error.

---

## File Structure

```
backend/
  app/
    market/
      seed_prices.py    # SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS, CORRELATION_GROUPS (constants)
      simulator.py      # GBMSimulator class + SimulatorDataSource class
```

`seed_prices.py` contains only constant dictionaries — no logic, no imports. `simulator.py` contains both classes; they're tightly coupled (SimulatorDataSource owns a GBMSimulator) and co-locating them avoids circular imports.

---

## Behavior Notes

| Property | Detail |
|----------|--------|
| Prices always positive | GBM is multiplicative (`exp()` > 0 always) |
| Per-tick move magnitude | ~$0.001–0.003 for typical stocks; accumulates to realistic intraday ranges |
| TSLA daily range | sigma=0.50 → ~3.15% daily → ~$7.88 range on a $250 stock |
| NVDA | sigma=0.40, mu=0.08 → high volatility with strong upward drift over time |
| Unknown tickers | Start at random price in $50–$300 range; use `DEFAULT_PARAMS` |
| Cholesky rebuild | O(n²) but n < 50 tickers; takes <1ms |
| Event frequency | ~1 shock per 500s per ticker; ~1 per 50s across a 10-ticker watchlist |

---

## Testing

**File: `backend/tests/market/test_simulator.py`**

```python
import pytest
from app.market.simulator import GBMSimulator
from app.market.seed_prices import SEED_PRICES


class TestGBMSimulator:

    def test_step_returns_all_tickers(self):
        sim = GBMSimulator(tickers=["AAPL", "GOOGL"])
        result = sim.step()
        assert set(result.keys()) == {"AAPL", "GOOGL"}

    def test_prices_always_positive(self):
        sim = GBMSimulator(tickers=["AAPL", "TSLA"])
        for _ in range(10_000):
            prices = sim.step()
            assert all(p > 0 for p in prices.values())

    def test_initial_prices_match_seeds(self):
        sim = GBMSimulator(tickers=["AAPL"])
        assert sim.get_price("AAPL") == SEED_PRICES["AAPL"]

    def test_prices_change_after_steps(self):
        sim = GBMSimulator(tickers=["AAPL"])
        seed = sim.get_price("AAPL")
        for _ in range(1000):
            sim.step()
        assert sim.get_price("AAPL") != seed

    def test_add_ticker(self):
        sim = GBMSimulator(tickers=["AAPL"])
        sim.add_ticker("TSLA")
        result = sim.step()
        assert "TSLA" in result

    def test_remove_ticker(self):
        sim = GBMSimulator(tickers=["AAPL", "GOOGL"])
        sim.remove_ticker("GOOGL")
        result = sim.step()
        assert "GOOGL" not in result
        assert "AAPL" in result

    def test_add_duplicate_is_noop(self):
        sim = GBMSimulator(tickers=["AAPL"])
        sim.add_ticker("AAPL")
        assert len(sim._tickers) == 1

    def test_remove_nonexistent_is_noop(self):
        sim = GBMSimulator(tickers=["AAPL"])
        sim.remove_ticker("ZZZZ")  # Should not raise

    def test_unknown_ticker_seed_in_range(self):
        sim = GBMSimulator(tickers=["ZZZZ"])
        price = sim.get_price("ZZZZ")
        assert 50.0 <= price <= 300.0

    def test_empty_step(self):
        sim = GBMSimulator(tickers=[])
        assert sim.step() == {}

    def test_cholesky_none_for_single_ticker(self):
        sim = GBMSimulator(tickers=["AAPL"])
        assert sim._cholesky is None

    def test_cholesky_built_for_two_tickers(self):
        sim = GBMSimulator(tickers=["AAPL"])
        sim.add_ticker("GOOGL")
        assert sim._cholesky is not None

    def test_cholesky_rebuilt_on_remove(self):
        sim = GBMSimulator(tickers=["AAPL", "GOOGL"])
        sim.remove_ticker("GOOGL")
        assert sim._cholesky is None  # Back to 1 ticker


import asyncio
import pytest
from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource


@pytest.mark.asyncio
class TestSimulatorDataSource:

    async def test_start_seeds_cache_immediately(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=60.0)
        await source.start(["AAPL", "GOOGL"])
        # Cache populated before loop starts — no wait needed
        assert cache.get("AAPL") is not None
        assert cache.get("GOOGL") is not None
        await source.stop()

    async def test_add_ticker_seeds_cache(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=60.0)
        await source.start(["AAPL"])
        await source.add_ticker("TSLA")
        assert cache.get("TSLA") is not None
        await source.stop()

    async def test_remove_ticker_clears_cache(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=60.0)
        await source.start(["AAPL", "GOOGL"])
        await source.remove_ticker("GOOGL")
        assert cache.get("GOOGL") is None
        await source.stop()

    async def test_stop_is_idempotent(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=60.0)
        await source.start(["AAPL"])
        await source.stop()
        await source.stop()  # Should not raise

    async def test_prices_update_over_time(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
        await source.start(["AAPL"])
        v0 = cache.version
        await asyncio.sleep(0.3)
        assert cache.version > v0   # Several updates must have happened
        await source.stop()
```
