---
paths:
  - "tests/**"
  - "scripts/**"
---

# Testing Standards

## Test Categories

### Strategy Tests
- **Unit tests**: Signal generation logic correctness
- **Backtests**: Performance verification on historical data
- **Statistical tests**: Result statistical significance verification
- **Edge cases**: Missing data, outliers, market holidays

### Data Pipeline Tests
- **Integration tests**: Data fetch and storage with live API connections
- **Data quality tests**: Schema validation, missing value checks, range checks
- **Idempotency tests**: Re-fetching same period produces identical results

### EA Tests
- **MetaTrader Tester**: Visual mode + optimization mode
- **Demo account testing**: Real-time data behavior verification
- **Manual verification**: Visual confirmation of entry/exit conditions

### Risk Calculation Tests
- **Known-value verification**: Validate against textbook examples
- **Boundary value tests**: Zero, negative, extreme value behavior
- **Monte Carlo**: Reproducibility with fixed random seeds

## pytest Conventions

### File Structure
```
tests/
├── test_data/           # Data fetching and processing
│   ├── test_fetcher.py
│   └── test_cleaner.py
├── test_strategies/     # Strategy logic
│   ├── test_signals.py
│   └── test_backtest.py
├── test_risk/           # Risk calculations
│   ├── test_var.py
│   └── test_position_sizing.py
├── test_optimization/   # Optimization
│   └── test_walk_forward.py
├── conftest.py          # Shared fixtures
└── fixtures/            # Test data
    ├── sample_ohlcv.parquet
    └── sample_trades.csv
```

### Markers
```python
@pytest.mark.slow          # Long-running tests
@pytest.mark.integration   # Requires external API connection
@pytest.mark.backtest      # Backtest-related
```

## Commands
```bash
uv run pytest                              # All tests
uv run pytest -m "not slow"                # Fast tests only
uv run pytest -m "not integration"         # Offline tests only
uv run pytest --cov=src --cov-report=html  # Coverage report
```
