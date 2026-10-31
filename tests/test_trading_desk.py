import unittest
from trading_desk import Signal, evaluate_signal, new_portfolio, paper_entry, paper_exit, portfolio_summary, size_position, update_position_mark

class TradingDeskTests(unittest.TestCase):
    def valid_solana(self):
        return Signal(asset="TEST", market="solana", price_usd=0.01, liquidity_usd=50000,
                      top10_holder_pct=25, dev_wallet_pct=2, bundled_buys_first_60s=False,
                      gain_45m_pct=12, source_wallet_sold=False, source="unit-test")
    def test_solana_rejects_concentrated_holders(self):
        s=self.valid_solana(); s.top10_holder_pct=45
        result=evaluate_signal(s)
        self.assertFalse(result["approved"])
        self.assertTrue(any("Top-10" in r for r in result["reasons"]))
    def test_solana_missing_onchain_data_fails_closed(self):
        self.assertFalse(evaluate_signal(Signal(asset="TEST",market="solana",price_usd=0.01))["approved"])
    def test_major_asset_requires_volume(self):
        s=Signal(asset="BTC",market="major",price_usd=65000,volume_24h_usd=10000000)
        self.assertTrue(evaluate_signal(s)["approved"])
        s.volume_24h_usd=100
        self.assertFalse(evaluate_signal(s)["approved"])
    def test_position_size_respects_risk_and_exposure(self):
        self.assertEqual(size_position(80,10),8.0)
        self.assertEqual(size_position(80,10,open_exposure_usd=19),1.0)
    def test_stop_loss_closes_paper_position(self):
        p=new_portfolio(80)
        paper_entry(p,self.valid_solana(),stop_loss_pct=10)
        pos=p["open_positions"][0]
        trade=update_position_mark(p,"TEST",pos["stop_price"]*0.99)
        self.assertEqual(trade["exit_reason"],"stop_loss")
        self.assertEqual(len(p["open_positions"]),0)
        self.assertLess(trade["realized_pnl_usd"],0)

    def test_take_profit_closes_paper_position_automatically(self):
        p = new_portfolio(80)
        paper_entry(p, self.valid_solana(), stop_loss_pct=10, take_profit_pct=20)
        pos = p["open_positions"][0]
        trade = update_position_mark(p, "TEST", pos["take_profit_price"] * 1.01)
        self.assertEqual(trade["exit_reason"], "take_profit")
        self.assertEqual(len(p["open_positions"]), 0)
        self.assertEqual(len(p["closed_trades"]), 1)
        self.assertGreater(trade["realized_pnl_usd"], 0)

    def test_short_position_profit_when_price_falls_and_take_profit_triggers(self):
        p = new_portfolio(80)
        paper_entry(p, self.valid_solana(), stop_loss_pct=10, take_profit_pct=20, direction="short")
        pos = p["open_positions"][0]
        self.assertGreater(pos["stop_price"], pos["entry_fill_price"])
        self.assertLess(pos["take_profit_price"], pos["entry_fill_price"])
        trade = update_position_mark(p, "TEST", pos["take_profit_price"] * 0.99)
        self.assertEqual(trade["exit_reason"], "take_profit")
        self.assertEqual(trade["direction"], "short")
        self.assertGreater(trade["realized_pnl_usd"], 0)
        self.assertEqual(len(p["open_positions"]), 0)

    def test_legacy_position_without_take_profit_fields_is_migrated(self):
        p = new_portfolio(80)
        paper_entry(p, self.valid_solana(), stop_loss_pct=10)
        position = p["open_positions"][0]
        position.pop("take_profit_price", None)
        position.pop("take_profit_pct", None)
        trade = update_position_mark(p, "TEST", position["entry_fill_price"] * 1.01)
        self.assertIsNone(trade)
        self.assertIn("take_profit_price", position)
        self.assertEqual(position["take_profit_pct"], 20.0)

    def test_short_stop_loss_triggers_when_price_rises(self):
        p = new_portfolio(80)
        paper_entry(p, self.valid_solana(), stop_loss_pct=10, take_profit_pct=20, direction="short")
        pos = p["open_positions"][0]
        trade = update_position_mark(p, "TEST", pos["stop_price"] * 1.01)
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertLess(trade["realized_pnl_usd"], 0)

    def test_paper_trade_round_trip_accounts_for_costs(self):
        p=new_portfolio(80); paper_entry(p,self.valid_solana(),stop_loss_pct=10)
        self.assertEqual(len(p["open_positions"]),1)
        trade=paper_exit(p,"TEST",0.012,reason="test")
        self.assertGreater(trade["realized_pnl_usd"],0)
        self.assertEqual(len(p["open_positions"]),0)
        self.assertEqual(len(p["closed_trades"]),1)
        self.assertGreater(portfolio_summary(p)["equity_usd"],80)

if __name__ == "__main__":
    unittest.main()
