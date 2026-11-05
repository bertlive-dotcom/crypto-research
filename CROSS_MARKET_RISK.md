# Cross-market risk monitor v1

## Scope
- Compares BTCUSDT (Binance Spot) with SPY (S&P 500 ETF proxy) and QQQ (Nasdaq-100 ETF proxy).
- Uses synchronized, fully closed 15-minute candles only.
- Calculates latest 15-minute and 1-hour returns, plus rolling Pearson correlations of 15-minute returns (up to 24 common observations).
- Displays descriptive regimes: synchronized risk-on, synchronized risk-off, equity/BTC divergence, or mixed.
- Does not create trading entries, change stops, modify paper portfolios, or submit exchange orders.

## Data sources
- BTCUSDT: Binance public Spot klines endpoint, no account key required.
- SPY and QQQ: Twelve Data `time_series` at `15min`, explicitly requested in UTC.
- The Twelve Data API key is read from the existing `TWELVE_DATA_API_KEY` Streamlit secret. No key is committed.
- The scan is user-triggered and cached for five minutes. It makes one Binance request and two Twelve Data requests.

## Quality gates
- Only closed candles are included.
- At least five closed observations per market are required for returns.
- At least eight synchronized observations are required for correlation.
- Latest observations must be no more than 35 minutes old and no more than 30 minutes apart across sources.
- Missing, stale or unsynchronized series produce an unavailable/insufficient status rather than a guessed regime.
- Correlation is descriptive, not causal, and is not a standalone trading signal.

## Initial regime thresholds
The 1-hour reading uses the latest four closed 15-minute bars:
- Risk-off: BTC <= -0.8%, SPY <= -0.35%, QQQ <= -0.45%.
- Risk-on: BTC >= +0.8%, SPY >= +0.35%, QQQ >= +0.45%.
- Other combinations are labelled as divergence or mixed.

These are initial diagnostic thresholds, not calibrated predictors. They must be evaluated against historical data before being used in any strategy.

## Validation
Run:
```bash
python -m py_compile app.py global_markets/*.py global_markets/providers/*.py
python -m unittest discover -s tests -p 'test_global_market_*.py' -v
```

A GitHub Actions pull-request run validates compilation and the global market unit-test suite. Live Twelve Data intraday entitlement and current data freshness still require runtime verification from the deployed dashboard.
