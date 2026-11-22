# AI Platform integration boundary

This directory defines the versioned, side-effect-free contract between
Crypto Research and the future AI Research & Autonomous Systems platform.

## Current status

- Contract version: 1.0
- Network integration: not enabled
- Runtime imports from the Streamlit app or scanner worker: none
- Trading authority: none
- Database access: none

## Design rules

1. Crypto Research remains the system of record for market analysis, strategy
   validation, risk controls and paper-trading state.
2. The future AI Core may submit research and analysis tasks through a separate
   authenticated service boundary.
3. Results must include a task ID, status, evidence, metrics and errors.
4. The AI Core cannot bypass Crypto Research eligibility checks or risk rules.
5. Live exchange execution is outside this contract and remains disabled.
6. Schema changes require an explicit version increment and compatibility tests.

The next integration increment will add an opt-in HTTP adapter only after the
central AI Core API contract, authentication model and deployment endpoint are
implemented and reviewed. No environment variable or deployment setting is
required for this contract-only increment.

## Tests

    python -m unittest discover -s tests -p 'test_ai_platform_contracts.py' -v
