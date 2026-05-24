# Agent: simulator

## Goal

Verify that `GBMSimulator` unit tests pass: GBM math correctness, ticker
management, Cholesky correlation matrix, seed prices, and price rounding.

## Scope

- **Test file:** `backend/tests/market/test_simulator.py`
- **Module under test:** `backend/app/market/simulator.py` (`GBMSimulator` class)
- **Test class:** `TestGBMSimulator` (17 tests)

## Key scenarios

- `step()` returns all tracked tickers
- Prices always positive (GBM exp() property, 10,000 iterations)
- Initial prices match `SEED_PRICES` constants
- Dynamic `add_ticker` / `remove_ticker` (duplicates/missing are no-ops)
- Unknown tickers get random seed in [50, 300]
- Empty ticker list returns empty dict
- Prices drift from seed after 1,000 steps
- Cholesky matrix built for ≥2 tickers, None for single ticker
- `_pairwise_correlation` logic: tech=0.6, finance=0.5, TSLA=0.3, cross=0.3
- `DEFAULT_DT` is a small positive fraction (~8.48e-8)
- Prices rounded to 2 decimal places

## Commands

```bash
cd /home/runner/work/finally/finally/backend
python -m pytest tests/market/test_simulator.py -v --tb=short
```

## Output path

`/home/runner/work/finally/finally/.agents/results/result_simulator.md`
