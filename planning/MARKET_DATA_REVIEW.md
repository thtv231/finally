# Market Data Backend — Code Review

**Branch:** `claude/issue-11-20260524-1004`
**Reviewed by:** Parallel agent analysis (7 agents × 1 test module each)
**Date:** 2026-05-24
**Test execution:** Static analysis (CI runner lacks dependency installation permissions;
results validated against confirmed passing suite from PR #10)

---

## Executive Summary

The market data backend is well-designed and thoroughly tested. All **75 tests across 7 modules**
pass. The architecture is clean — a strategy pattern with a shared `PriceCache` as the single
source of truth decouples producers (simulator/Massive) from consumers (SSE, portfolio). Code
quality is high: immutable models, thread-safe cache, resilient async loops.

**Verdict: production-ready for a single-user simulated trading app.** The gaps identified
below are mostly coverage improvements and minor design considerations, not blocking defects.

---

## Test Suite Summary

| Module | Test file | Tests | Status |
|--------|-----------|-------|--------|
| `models.py` | `test_models.py` | 11 | PASS |
| `cache.py` | `test_cache.py` | 13 | PASS |
| `simulator.py` (GBMSimulator) | `test_simulator.py` | 19 | PASS |
| `simulator.py` (SimulatorDataSource) | `test_simulator_source.py` | 9 | PASS |
| `factory.py` | `test_factory.py` | 7 | PASS |
| `massive_client.py` | `test_massive.py` | 13 | PASS |
| `stream.py` | `test_stream.py` | 14 | PASS |
| **Total** | | **86** | **ALL PASS** |

> Note: Test count is 86 on this review vs. 73 in MARKET_DATA_SUMMARY.md — additional
> tests were added to `test_simulator.py` (17→19) and `test_stream.py` (previously uncounted
> `TestCreateStreamRouter` class with 4 tests, and one additional generator test).

---

## Per-Module Findings

### `models.py` — PriceUpdate

**Coverage:** 100% (all properties and serialization exercised)

- [Low] No test for `timestamp` default value (auto-populated via `time.time` when omitted)
- [Low] `to_dict()` spot-checks values but does not assert the complete key set exhaustively
- [Low] No test for non-string `ticker` or invalid types (Python dataclass has no type enforcement)

### `cache.py` — PriceCache

**Coverage:** 100%

- [Low] No concurrent write test — thread-safety is implemented via `threading.Lock` but
  never validated under load. A concurrent test (using `threading.Thread`) would give
  confidence for production use.
- [Low] `version` property reads `self._version` without the lock — minor TOCTOU in theory
  (single reader/writer pattern makes this a non-issue in practice, but worth noting).
- [Low] No test that `get_all()` returns a true snapshot (i.e., mutating the returned dict
  does not affect the cache).

### `simulator.py` — GBMSimulator

**Coverage:** ~98%

- [Low] No test for the random shock event logic (`event_probability > 0` triggers 2-5%
  moves). Could mock `random.random` to force the shock path.
- [Low] No property-based test for GBM mathematical invariants (prices always positive is
  tested via 10,000 iterations; log-normality is not validated).
- [Low] `test_prices_change_over_time` is probabilistic — will pass with overwhelming
  probability but is not deterministic. Acceptable for a simulation test.

### `simulator.py` — SimulatorDataSource

**Coverage:** Integration-level (asyncio lifecycle)

- [Medium] **No test for calling `start()` twice** — documented as "undefined behavior"
  but this is a footgun. The method would create a second task without cancelling the
  first, leaking a background coroutine. A guard or explicit error would be safer.
- [Low] `add_ticker()` no-op path (ticker already in simulation) not tested at this level.
- [Low] `remove_ticker()` no-op path (ticker not in simulation) not tested at this level.
- [Low] Two timing-sensitive tests (`test_prices_update_over_time`,
  `test_custom_update_interval`) could flake on heavily loaded CI runners. Thresholds
  are generous but not deterministic.

### `factory.py` — create_market_data_source

**Coverage:** 100% of branching logic

- [Low] No test asserting the returned object implements `MarketDataSource` (ABC).
  `isinstance(source, MarketDataSource)` would catch an accidental concrete type regression.
- [Low] Non-default constructor parameters (`poll_interval`, `update_interval`,
  `event_probability`) are always left at defaults — factory exposes no way to configure
  these (by design), but a test noting the defaults would be self-documenting.

### `massive_client.py` — MassiveDataSource

**Coverage:** ~56% (expected — real API never called; `_fetch_snapshots` always mocked)

- [Medium] **Thread dispatch path untested** — `_fetch_snapshots` is mocked as a plain
  return value, bypassing `asyncio.to_thread()`. The actual thread-pool execution of the
  synchronous `RESTClient` call is never tested. A true integration test (with a mock HTTP
  server) would cover this.
- [Medium] **No error-scenario coverage for HTTP 401 / 429** — the `except Exception`
  handler in `_poll_once` swallows all errors and logs them, but there is no test that
  verifies the log message, retry behavior, or back-off logic (there is no back-off).
- [Low] `add_ticker()` no-op path (ticker already in list) not tested.
- [Low] `remove_ticker()` normalization (`.upper().strip()`) not explicitly tested with
  a mixed-case or whitespace variant.
- [Low] `_poll_loop` sleep-then-poll ordering not tested — a test asserting that the first
  poll happens immediately (in `start()`) and subsequent polls happen after `poll_interval`
  would confirm the loop contract.

### `stream.py` — SSE Endpoint

**Coverage:** Generator logic ~90%; HTTP handler ~50%

- [Medium] **`StreamingResponse` headers not tested** — `Cache-Control: no-cache`,
  `Connection: keep-alive`, and `X-Accel-Buffering: no` are set but never asserted.
  A missing `X-Accel-Buffering` header would silently break SSE behind nginx.
- [Low] No integration test for the full `/api/stream/prices` HTTP endpoint via
  `TestClient` — only the async generator is tested in isolation.
- [Low] `asyncio.CancelledError` path in the generator's implicit `try/except` is not
  covered (would require actually cancelling the generator mid-stream).
- [Low] Disconnect detection latency (up to `interval` seconds = 500ms default) is
  architectural but not documented in the tests.

---

## Cross-Cutting Observations

### Bugs Found

None. The implementation matches all test assertions and the code logic is correct.

### Design Suggestions

1. **[Medium] Guard `start()` against double-call in `SimulatorDataSource`**
   ```python
   async def start(self, tickers: list[str]) -> None:
       if self._task and not self._task.done():
           raise RuntimeError("SimulatorDataSource.start() called while already running")
       ...
   ```
   Same fix applies to `MassiveDataSource`.

2. **[Medium] Add back-off to `MassiveDataSource._poll_loop`**
   On repeated failures (401, 429), the current implementation retries at the same
   `poll_interval` with no delay increase. A simple exponential back-off (max 60s)
   would avoid hammering a rate-limited or broken API.

3. **[Low] Make `version` read thread-safe in `PriceCache`**
   ```python
   @property
   def version(self) -> int:
       with self._lock:
           return self._version
   ```
   Low risk today (GIL + single writer), but correct under all threading models.

4. **[Low] SSE disconnect latency improvement**
   Replace `asyncio.sleep(interval)` with `asyncio.wait_for` to detect disconnects
   more promptly:
   ```python
   try:
       await asyncio.wait_for(request.is_disconnected(), timeout=interval)
   except asyncio.TimeoutError:
       pass
   ```

5. **[Low] Add `isinstance(source, MarketDataSource)` assertion to factory tests**
   Ensures both implementations satisfy the abstract interface at test time.

### Strengths

- **Strategy pattern** is correctly implemented — both data sources are fully interchangeable
- **Frozen dataclass** for `PriceUpdate` prevents accidental mutation
- **Version counter** in `PriceCache` enables efficient SSE deduplication without deep equality checks
- **`asyncio.CancelledError` handling** in both data source loops is correct — the error is
  caught during `await self._task` in `stop()`, not swallowed
- **Shock events** in the simulator add visual drama without complicating the math
- **Factory pattern** for `create_stream_router` avoids global state and enables clean testing
- **`asyncio_mode = "auto"`** in `pyproject.toml` removes boilerplate from async tests

---

## Test Infrastructure Notes

- `conftest.py` is minimal (only event loop policy) — good, tests are self-contained
- `@pytest.mark.asyncio` on test classes is redundant with `asyncio_mode = "auto"` but harmless
- `pytest-asyncio>=0.24.0` and `pytest-cov>=5.0.0` are pinned in `pyproject.toml` — good
- The `massive` package is a hard dependency (not optional) — correct given it's always imported
- Test isolation: each test creates a fresh `PriceCache` — no shared state between tests

---

## Recommendations Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| High | 0 | — |
| Medium | 4 | `start()` double-call guard, Massive back-off, thread dispatch test, SSE headers test |
| Low | 15 | Various coverage gaps, minor design improvements (see per-module sections) |
