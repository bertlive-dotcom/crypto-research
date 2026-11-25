import unittest
from unittest.mock import Mock

from assistant.strategy_validation_feed import (
    StrategyValidationReadService,
    normalize_closed_trade,
)


class StrategyValidationFeedTests(unittest.TestCase):
    def trade(self, **overrides):
        row = {
            "position_id": "position-1",
            "asset": "BTC",
            "direction": "long",
            "quantity": 0.01,
            "entry_reference_price": 100000.0,
            "exit_reference_price": 101000.0,
            "realized_pnl_usd": 8.0,
            "closed_at": "2026-11-25T12:00:00+00:00",
        }
        row.update(overrides)
        return row

    def test_normalizes_long_trade_and_reconstructs_costs(self):
        result = normalize_closed_trade(self.trade())
        self.assertEqual(result["symbol"], "BTCUSDT")
        self.assertEqual(result["gross_pnl"], 10.0)
        self.assertEqual(result["total_cost"], 2.0)
        self.assertEqual(result["net_pnl"], 8.0)
        self.assertEqual(result["cost_status"], "complete")

    def test_normalizes_short_trade_direction(self):
        result = normalize_closed_trade(self.trade(
            direction="short", entry_reference_price=100000.0,
            exit_reference_price=99000.0, realized_pnl_usd=8.0,
        ))
        self.assertEqual(result["gross_pnl"], 10.0)
        self.assertEqual(result["total_cost"], 2.0)

    def test_missing_execution_cost_inputs_remain_unknown(self):
        result = normalize_closed_trade(self.trade(exit_reference_price=None))
        self.assertIsNone(result["gross_pnl"])
        self.assertIsNone(result["total_cost"])
        self.assertEqual(result["cost_status"], "incomplete")
        self.assertIn("execution_costs_unavailable", result["data_quality_issues"])

    def test_inconsistent_cost_relationship_is_blocked(self):
        result = normalize_closed_trade(self.trade(realized_pnl_usd=12.0))
        self.assertIsNone(result["total_cost"])
        self.assertIn("inconsistent_gross_net_cost_relationship", result["data_quality_issues"])

    def test_naive_timestamp_is_rejected(self):
        result = normalize_closed_trade(self.trade(closed_at="2026-11-25T12:00:00"))
        self.assertIsNone(result["closed_at"])
        self.assertIn("missing_or_invalid_closed_at", result["data_quality_issues"])

    def test_dataset_is_read_only_and_filters_symbol(self):
        store = Mock()
        store.load_state.return_value = {"closed_trades": [self.trade(), self.trade(asset="ETH")]}
        store.latest_candidates.return_value = [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]
        service = StrategyValidationReadService(store_factory=lambda: store)
        result = service.dataset(symbol="BTCUSDT", limit=100)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["mode"], "simulation_only")
        self.assertEqual([row["symbol"] for row in result["trades"]], ["BTCUSDT"])
        self.assertEqual([row["symbol"] for row in result["candidates"]], ["BTCUSDT"])
        store.load_state.assert_called_once_with()
        store.latest_candidates.assert_called_once_with(limit=100)

    def test_invalid_symbol_and_limit_are_rejected(self):
        service = StrategyValidationReadService(store_factory=Mock())
        with self.assertRaises(ValueError):
            service.dataset(symbol="BTCUSD")
        with self.assertRaises(ValueError):
            service.dataset(limit=0)


if __name__ == "__main__":
    unittest.main()
