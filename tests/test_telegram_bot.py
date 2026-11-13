import unittest
from unittest.mock import Mock

from telegram_bot.__main__ import TelegramClient, TelegramAPIError, TradingAssistantBot, _format_daily

AUTHORIZED_ID = 7872565699


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeBinance:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = 0

    def get_spot_symbol_status(self):
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("provider unavailable")
        return {"BTCUSDT": {"status": "TRADING"}}


class FakeFeed:
    def __init__(self, client=None):
        self.client = client or FakeBinance()


class FakeService:
    financialdata_client = None
    alphavantage_client = None
    eodhd_client = None

    def __init__(self, feed=None):
        self.feed = feed or FakeFeed()

    def crypto_overview(self, symbols, limit=200):
        return {"generated_at": "test", "summary": {"requested": len(symbols), "with_both_timeframes": len(symbols)}, "instruments": [], "unavailable": []}

    def daily_multi_asset_overview(self, symbols, limit=120):
        return {"generated_at": "test", "summary": {"requested": len(symbols), "returned": len(symbols), "data_quality_eligible": len(symbols), "entitlement_verified": 0}, "instruments": [], "unavailable": []}


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeTelegram()
        self.service = FakeService()
        self.bot = TradingAssistantBot(self.client, self.service, AUTHORIZED_ID)

    def update(self, *, sender=AUTHORIZED_ID, chat_id=AUTHORIZED_ID, chat_type="private", text="/help"):
        return {"message": {"from": {"id": sender}, "chat": {"id": chat_id, "type": chat_type}, "text": text}}

    def test_rejects_other_user_without_reply(self):
        self.bot.handle(self.update(sender=1, chat_id=1))
        self.assertEqual(self.client.sent, [])

    def test_rejects_group_even_when_sender_is_authorized(self):
        self.bot.handle(self.update(chat_type="group", chat_id=-100123))
        self.assertEqual(self.client.sent, [])

    def test_rejects_channel_even_when_sender_is_authorized(self):
        self.bot.handle(self.update(chat_type="channel", chat_id=-100123))
        self.assertEqual(self.client.sent, [])

    def test_rejects_private_chat_id_mismatch(self):
        self.bot.handle(self.update(chat_id=1))
        self.assertEqual(self.client.sent, [])

    def test_authorized_private_user_can_get_help(self):
        self.bot.handle(self.update())
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn("/crypto", self.client.sent[0][1])

    def test_unknown_symbol_fails_closed(self):
        result = self.bot.dispatch("/analyze", "XAUUSD")
        self.assertIn("no està habilitat", result)

    def test_crypto_and_daily_commands_call_read_only_service(self):
        self.assertIn("CRIPTO", self.bot.dispatch("/crypto", "BTCUSD"))
        self.assertIn("ACCIONS", self.bot.dispatch("/markets", "NVDA"))


    def test_daily_formatter_displays_latest_close_and_analysis_status(self):
        report = {
            "generated_at": "test",
            "summary": {"requested": 1, "returned": 1, "data_quality_eligible": 1, "entitlement_verified": 0},
            "instruments": [{
                "symbol": "NVDA",
                "provider": "financialdata.net",
                "coverage_status": "adapter_available_unverified_entitlement",
                "analysis": {
                    "status": "fresh",
                    "latest_close": 182.45,
                    "indicators": {"rsi_14": 25.99},
                },
            }],
            "unavailable": [],
        }
        result = _format_daily(report)
        self.assertIn("tancament diari 182.45", result)
        self.assertIn("estat fresh", result)
        self.assertIn("RSI 25.99", result)
        self.assertNotIn("): — |", result)

    def test_status_checks_live_binance_connectivity(self):
        result = self.bot.dispatch("/status")
        self.assertIn("Binance Spot: connectat", result)
        self.assertEqual(self.service.feed.client.calls, 1)

    def test_status_reports_binance_unavailable(self):
        self.service.feed.client = FakeBinance(should_fail=True)
        result = self.bot.dispatch("/status")
        self.assertIn("Binance Spot: no disponible", result)

    def test_telegram_client_requires_token(self):
        with self.assertRaises(ValueError):
            TelegramClient("")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TelegramClientTests(unittest.TestCase):
    def test_send_splits_long_messages_below_telegram_limit(self):
        session = Mock()
        session.post.return_value = FakeResponse({"ok": True, "result": True})
        client = TelegramClient("test-token", session=session)
        client.send(AUTHORIZED_ID, "x" * 8000)
        self.assertEqual(session.post.call_count, 3)
        for call in session.post.call_args_list:
            self.assertLessEqual(len(call.kwargs["json"]["text"]), 4096)
            self.assertTrue(call.kwargs["json"]["protect_content"])

    def test_api_failure_is_sanitized(self):
        session = Mock()
        session.post.return_value = FakeResponse({"ok": False, "description": "bad token"})
        client = TelegramClient("test-token", session=session)
        with self.assertRaises(TelegramAPIError):
            client.call("getMe")


if __name__ == "__main__":
    unittest.main()
