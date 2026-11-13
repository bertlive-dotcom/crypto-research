import unittest

from telegram_bot.__main__ import TradingAssistantBot


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeService:
    financialdata_client = None
    alphavantage_client = None
    eodhd_client = None

    def crypto_overview(self, symbols, limit=200):
        return {"generated_at": "test", "summary": {"requested": len(symbols), "with_both_timeframes": len(symbols)}, "instruments": [], "unavailable": []}

    def daily_multi_asset_overview(self, symbols, limit=120):
        return {"generated_at": "test", "summary": {"requested": len(symbols), "returned": len(symbols), "data_quality_eligible": len(symbols), "entitlement_verified": 0}, "instruments": [], "unavailable": []}


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeTelegram()
        self.bot = TradingAssistantBot(self.client, FakeService(), 7872565699)

    def test_rejects_other_user_without_reply(self):
        self.bot.handle({"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/help"}})
        self.assertEqual(self.client.sent, [])

    def test_authorized_user_can_get_help(self):
        self.bot.handle({"message": {"from": {"id": 7872565699}, "chat": {"id": 7872565699}, "text": "/help"}})
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn("/crypto", self.client.sent[0][1])

    def test_unknown_symbol_fails_closed(self):
        result = self.bot.dispatch("/analyze", "XAUUSD")
        self.assertIn("no està habilitat", result)

    def test_crypto_and_daily_commands_call_read_only_service(self):
        self.assertIn("CRIPTO", self.bot.dispatch("/crypto", "BTCUSD"))
        self.assertIn("ACCIONS", self.bot.dispatch("/markets", "NVDA"))


if __name__ == "__main__":
    unittest.main()
