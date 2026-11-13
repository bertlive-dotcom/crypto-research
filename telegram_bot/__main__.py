"""Run the private Telegram long-polling worker.

This process is deployed separately from Streamlit Community Cloud. It reuses
assistant.service and provider adapters; it does not import Streamlit or mutate
paper portfolios, scanner state, exchange accounts, or live orders.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from assistant.service import ReadOnlyAssistantService
from global_markets.crypto_feed import CryptoWatchlistFeed
from global_markets.providers.alphavantage import AlphaVantageClient
from global_markets.providers.eodhd import EODHDClient
from global_markets.providers.financialdata import FinancialDataClient

LOG = logging.getLogger("crypto_research.telegram")
CRYPTO_DEFAULTS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "LINKUSD", "XLMUSD", "SUIUSD", "HYPEUSD",
    "XMRUSD", "LEOUSD", "BATUSD", "PEPEUSD", "BEAMUSD", "ANVLUSD",
]
DAILY_DEFAULTS = ["NVDA", "SPY", "EURUSD"]
PENDING_CLASSES = ["índexs", "matèries primeres i futurs"]


class TelegramAPIError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, *, session: requests.Session | None = None, timeout: int = 40):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = session or requests.Session()
        self.timeout = timeout

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            response = self.session.post(
                f"{self.base_url}/{method}", json=payload or {}, timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegramAPIError("Telegram API request failed") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramAPIError("Telegram API returned an unsuccessful response")
        return result.get("result")

    def get_updates(self, offset: int | None) -> list[dict]:
        payload: dict[str, Any] = {"timeout": 30, "limit": 50, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self.call("getUpdates", payload)
        return result if isinstance(result, list) else []

    def send(self, chat_id: int, text: str) -> None:
        # Telegram sendMessage accepts at most 4096 characters.
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [" "]
        for chunk in chunks:
            self.call("sendMessage", {
                "chat_id": chat_id, "text": chunk, "disable_web_page_preview": True,
                "protect_content": True,
            })


def build_service() -> ReadOnlyAssistantService:
    """Construct exactly the same provider-neutral service used by Streamlit."""
    financial_key = os.getenv("FINANCIALDATA_API_KEY", "").strip()
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    eodhd_key = os.getenv("EODHD_API_TOKEN", "").strip()
    return ReadOnlyAssistantService(
        feed=CryptoWatchlistFeed(),
        financialdata_client=(
            FinancialDataClient(financial_key, max_retries=1, max_pages=2)
            if financial_key else None
        ),
        alphavantage_client=AlphaVantageClient(alpha_key) if alpha_key else None,
        eodhd_client=EODHDClient(eodhd_key) if eodhd_key else None,
    )


def _format_crypto(report: dict) -> str:
    summary = report.get("summary", {})
    lines = [
        "CRIPTO · BINANCE SPOT · RESEARCH ONLY",
        f"Generat: {report.get('generated_at', '—')}",
        f"Actius: {summary.get('with_both_timeframes', 0)}/{summary.get('requested', 0)} amb 1d + 4h complets",
        "",
    ]
    for item in report.get("instruments", []):
        daily, tactical = item.get("daily", {}), item.get("tactical_4h", {})
        d_ind = daily.get("indicators", {})
        t_ind = tactical.get("indicators", {})
        structure = item.get("structure", {})
        lines.append(
            f"{item.get('symbol')}: estructura {structure.get('category', '—')} | "
            f"1d RSI {d_ind.get('rsi_14', '—')} | 4h RSI {t_ind.get('rsi_14', '—')} | "
            f"RS vs BTC 30d {item.get('relative_strength_vs_btc_30d_pp', '—')} pp"
        )
    if report.get("unavailable"):
        lines.extend(["", f"No disponibles: {len(report['unavailable'])}"])
    lines.extend(["", "RSI i estructura són eines de cribratge, no probabilitats ni ordres."])
    return "\n".join(lines)


def _format_daily(report: dict) -> str:
    summary = report.get("summary", {})
    lines = [
        "ACCIONS · ETF · FX · DADES DIÀRIES · RESEARCH ONLY",
        f"Generat: {report.get('generated_at', '—')}",
        f"Retornats: {summary.get('returned', 0)}/{summary.get('requested', 0)} | "
        f"Qualitat elegible: {summary.get('data_quality_eligible', 0)} | "
        f"Entitlement verificat: {summary.get('entitlement_verified', 0)}",
        "",
    ]
    for item in report.get("instruments", []):
        analysis = item.get("analysis", {})
        indicators = analysis.get("indicators", {})
        lines.append(
            f"{item.get('symbol')} ({item.get('provider')}): {analysis.get('structure', {}).get('category', analysis.get('label', '—'))} | "
            f"RSI {indicators.get('rsi_14', '—')} | cobertura {item.get('coverage_status', '—')}"
        )
    for item in report.get("unavailable", []):
        lines.append(f"{item.get('symbol')}: no disponible ({item.get('reason')})")
    lines.extend(["", "Dades diàries: no són cotitzacions en temps real."])
    return "\n".join(lines)


class TradingAssistantBot:
    def __init__(self, client: TelegramClient, service: ReadOnlyAssistantService, allowed_user_id: int):
        if not isinstance(allowed_user_id, int) or allowed_user_id <= 0:
            raise ValueError("TELEGRAM_ALLOWED_USER_ID must be a positive Telegram user ID")
        self.client, self.service, self.allowed_user_id = client, service, allowed_user_id

    @staticmethod
    def help_text() -> str:
        return (
            "CRYPTO-RESEARCH · ASSISTENT DE MERCAT\n\n"
            "/start — iniciar\n"
            "/help — ajuda\n"
            "/status — estat de connexions i cobertura\n"
            "/crypto — anàlisi dels 13 actius cripto\n"
            "/crypto BTCUSD ETHUSD — seleccionar actius cripto\n"
            "/markets — NVDA, SPY i EURUSD\n"
            "/markets NVDA — seleccionar actius diaris\n"
            "/analyze BTCUSD — anàlisi d'un actiu\n"
            "/report — informe combinat de tots els mercats disponibles\n\n"
            "L'assistent és de consulta i recerca. No envia ordres ni modifica carteres."
        )

    def handle(self, update: dict) -> None:
        message = update.get("message") or {}
        sender = (message.get("from") or {}).get("id")
        chat_id = (message.get("chat") or {}).get("id")
        text = str(message.get("text") or "").strip()
        if not text or not isinstance(sender, int) or not isinstance(chat_id, int):
            return
        chat = message.get("chat") or {}
        if sender != self.allowed_user_id:
            # Do not disclose bot capabilities or market data to unauthorized users.
            LOG.warning("Rejected Telegram message from a non-allowlisted user")
            return
        if chat.get("type") != "private" or chat_id != sender:
            # Never return private market research into groups or channels.
            LOG.warning("Rejected non-private Telegram chat for the authorized user")
            return
        command, _, args = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        try:
            answer = self.dispatch(command, args.strip())
        except (ValueError, LookupError) as exc:
            answer = f"Consulta no vàlida: {exc}"
        except Exception:
            LOG.exception("Telegram command failed")
            answer = "No s'ha pogut completar la consulta. Revisa els proveïdors i torna-ho a provar."
        self.client.send(chat_id, answer)

    def dispatch(self, command: str, args: str = "") -> str:
        if command in {"/start", "/help"}:
            return "Bot privat connectat a crypto-research.\n\n" + self.help_text()
        if command == "/status":
            feed = getattr(self.service, "feed", None)
            binance_client = getattr(feed, "client", None)
            if binance_client is None:
                binance_status = "no configurat"
            else:
                try:
                    binance_client.get_spot_symbol_status()
                    binance_status = "connectat"
                except Exception:
                    binance_status = "no disponible"
            providers = {
                "Binance Spot": binance_status,
                "FinancialData.Net": "configurat" if self.service.financialdata_client else "sense credencial",
                "Alpha Vantage": "configurat" if self.service.alphavantage_client else "sense credencial",
                "EODHD": "configurat" if self.service.eodhd_client else "sense credencial",
            }
            lines = ["ESTAT DEL SISTEMA", "Mode: read-only / research-only"]
            lines.extend(f"{name}: {status}" for name, status in providers.items())
            lines.append("Nota: configurat no equival a entitlement o llicència verificats.")
            lines.append("Cobertura pendent: " + ", ".join(PENDING_CLASSES) + ".")
            lines.append("Cap connexió d'ordres ni permisos de trading.")
            return "\\n".join(lines)
        if command == "/crypto":
            symbols = args.upper().split() if args else CRYPTO_DEFAULTS
            report = self.service.crypto_overview(symbols, limit=200)
            return _format_crypto(report)
        if command == "/markets":
            symbols = args.upper().split() if args else DAILY_DEFAULTS
            report = self.service.daily_multi_asset_overview(symbols, limit=120)
            return _format_daily(report)
        if command == "/analyze":
            symbol = args.upper().strip()
            if not symbol:
                return "Indica un símbol. Exemple: /analyze BTCUSD"
            if symbol in CRYPTO_DEFAULTS:
                return _format_crypto(self.service.crypto_overview([symbol], limit=200))
            if symbol in DAILY_DEFAULTS:
                return _format_daily(self.service.daily_multi_asset_overview([symbol], limit=120))
            return (
                f"{symbol} no està habilitat al registre de l'AI Trading Assistant. "
                "No s'inferiran símbols ni proveïdors."
            )
        if command == "/report":
            crypto = self.service.crypto_overview(CRYPTO_DEFAULTS, limit=200)
            daily = self.service.daily_multi_asset_overview(DAILY_DEFAULTS, limit=120)
            return _format_crypto(crypto) + "\n\n" + _format_daily(daily)
        return "Ordre desconeguda. Escriu /help per veure les consultes disponibles."


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    allowed = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if not token or not allowed:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID in the worker environment.")
    try:
        allowed_user_id = int(allowed)
    except ValueError as exc:
        raise SystemExit("TELEGRAM_ALLOWED_USER_ID must be numeric.") from exc

    client = TelegramClient(token)
    service = build_service()
    bot = TradingAssistantBot(client, service, allowed_user_id)
    client.call("getMe")
    LOG.info("Private Telegram assistant started; user allowlist enabled.")
    offset = None
    while True:
        try:
            for update in client.get_updates(offset):
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset or 0, update_id + 1)
                bot.handle(update)
        except KeyboardInterrupt:
            raise
        except Exception:
            LOG.exception("Telegram polling cycle failed")
            time.sleep(5)


if __name__ == "__main__":
    main()
