# Agent: cache

## Goal

Verify all `PriceCache` tests pass: thread-safe update/get/remove, version
counter, direction inference, and convenience accessors.

## Scope

- **Test file:** `backend/tests/market/test_cache.py`
- **Module under test:** `backend/app/market/cache.py`
- **Test class:** `TestPriceCache` (13 tests)

## Key scenarios

- First update: `direction == "flat"`, `previous_price == price`
- Direction up/down on subsequent updates
- `remove()` clears ticker; `remove()` on missing key is a no-op
- `get_all()` returns a shallow copy (snapshot)
- `version` increments on every `update()` call
- `get_price()` returns float or None
- `__len__` and `__contains__` protocol methods
- Custom timestamp passthrough
- Price rounding to 2 decimal places

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_cache.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_cache.md`
