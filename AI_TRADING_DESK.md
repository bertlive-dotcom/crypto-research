# AI Crypto Trading Desk â simulation-only MVP

## Scope
- Virtual starting capital: USD 80.
- Markets: Solana tokens/memecoins and major cripto assets.
- No live trading, exchange order endpoints, wallet signing, seed phrases, or private keys.
- The five roles are deterministic software stages in this MVP, not autonomous LLM agents:
  1. Scout: accepts a manually entered or externally sourced candidate signal.
  2. Filter: applies hard eligibility rules.
  3. Analyst: displays rule outcomes and risk assumptions.
  4. Sniper: opens a simulated position only.
  5. Guard: requires a stop-loss percentage and enforces position/exposure limits.

## Filters
For Solana candidates, missing on-chain inputs fail closed:
- liquidity >= USD 30,000;
- top-10 holder concentration <= 40%;
- developer wallet share <= 8%;
- no bundled buys in first 60 seconds;
- 45-minute gain <= 80%;
- source wallet has not sold.

For major assets, wallet/holder checks are not applicable. The MVP requires 24-hour volume >= USD 1,000,000 and rejects an indicated 45-minute gain above 80%. This is a separate ruleset, not equivalent to the Solana checks.

## Risk model
- Default risk budget: 1% of current virtual cash per trade.
- Maximum position: 10% of virtual cash.
- Maximum aggregate open exposure: 25% of virtual cash.
- Entry and exit simulation includes adverse slippage (0.30% per side) and fees (0.10% per sideÿ¤¸(´Õ±ÐÍÑ½Àè¡½Í¸äÑ¡ÕÍÈÁÈÍ¥¹°ìÑ¡ÁÀ½Ì¹½ÐÕÉ¹ÑÍÑ½ÀáÕÑ¥½¸¸((ÕÉÉ¹Ð±¥µ¥ÑÑ¥½¹Ì(´9¼ÕÑ½µÑ¥ØÐÀµÝ±±ÐÑÉ­È½ÈÝ±±ÐÁÉ½Éµ¹É¹­¥¹¸(´9¼ÕÑ½µÑ¥M½±¹Ñ½­¸¥Í½ÙÉä¼½¸µ¡¥¸¡½±È¹±åÑ¥ÌåÐ¸(´¹¥ÑÍ¥¹±ÌÉµ¹Õ±±ä¹ÑÉ¥¸Ñ¡U$¥¸Ñ¡¥Ì¥ÉÍÐ¥¹Éµ¹Ð¸(´A½ÉÑ½±¥¼ÍÑÑ¥Ì¡±¥¸MÑÉµ±¥ÐÍÍÍ¥½¸ÍÑÑ¹¥Ì¹½ÐÕÉ±°É½ÍÌµÙ¥±È¸(´AÉ¥ÕÁÑÌÉÕÍÈµ¹ÑÉ½ÈÁÁÈÁ½Í¥Ñ¥½¹Ì¥¸Ñ¡¥Ì¥¹Éµ¹Ð¸(´9¼±¥´½$µ¹ÉÑ¹±åÍ¥Ì½ÈÁÉ½Ù¸ÁÉ½¥Ñ¥±¥ÑäìÕÉÉ¹Ð¹ÑÌÉÑÉµ¥¹¥ÍÑ¥ÉÕ±µÍ½µÁ½¹¹ÑÌ¸((Y±¥Ñ¥½¸ÑÌ½É¹ä±¥ÙµÑÉ¥¹¥ÍÕÍÍ¥½¸(Ä¸U¹¥ÐÑÍÑÌÁÍÌ½ÈÑ¡ÉÍ¡½±Ì°µ¥ÍÍ¥¹µÑÉ©Ñ¥½¸°Á½Í¥Ñ¥½¸Í¥é¥¹°½ÍÑÌ°¹@0¸(È¸!¥ÍÑ½É¥°½­ÑÍÐ¹ÁÁÈµÑÉ¥¹±½Ì¥¹±ÕÑ¥µÍÑµÁÌ°Í½ÕÉ¥¹Ñ¥¥ÉÌ°Ì°Í±¥ÁÁ°¹É©ÑÍ¥¹±Ì¸(Ì¸Ð±ÍÐÌÀåÌ½½ÉÝÉÍ¥µÕ±Ñ¥½¸¹µ¹¥¹Õ°ÍµÁ±½ÑÉÌÉÉÙ¥Ý¸(Ð¸IÍÕ±ÑÌÉµÍÕÉ¹Ð½Ì½Í±¥ÁÁ¹¥¹±ÕµàÉÝ½Ý¸°áÁÑ¹ä°ÁÉ½¥ÐÑ½È°Ý¥¸ÉÑ°¹½¹¹ÑÉÑ¥½¸¸(Ô¸%¹Á¹¹ÐÉÙ¥Ü½ÑÅÕ±¥Ñä°áÕÑ¥½¸ÍÍÕµÁÑ¥½¹Ì°¹ÍÕÉ¥Ñä¸(Ø¸ÍÁÉÑáÁ±¥¥ÐÕÍÈ¥Í¥½¸¹ÍÁÉÑÍÕÉ¥ÑäÉÙ¥ÜÝ½Õ±ÉÅÕ¥É½É¹ä±¥ÙáÕÑ¥½¸ÑÕÉ¥ÌÍ¥¹¸((MÕÉ¥Ñä)9ÙÈÁÕÐA$­åÌ°ÁÍÍÝ½ÉÌ°Ý±±ÐÍÁ¡ÉÍÌ°ÁÉ¥ÙÑ­åÌ°½È¹ÍÑÉµ±¥Ð½ÍÉÑÌ¹Ñ½µ±¥¸¥Ð¸