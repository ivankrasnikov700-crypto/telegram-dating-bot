# utils/cryptobot.py
# Wrapper for Telegram CryptoPay API (https://pay.crypt.bot/api)

import requests
from config import CRYPTO_PAY_TOKEN

_BASE = "https://pay.crypt.bot/api"
_HEADERS = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}


def _call(method: str, **params) -> dict:
    r = requests.post(_BASE + "/" + method, json=params, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError("CryptoPay error: " + str(data.get("error", data)))
    return data["result"]


def is_configured() -> bool:
    return bool(CRYPTO_PAY_TOKEN)


def get_me() -> dict:
    return _call("getMe")


def create_invoice(asset: str, amount: float, description: str, payload: str = "") -> dict:
    """
    Creates a CryptoPay invoice.
    Returns dict with: invoice_id, pay_url, status, asset, amount, payload
    """
    return _call(
        "createInvoice",
        asset=asset,
        amount=str(round(amount, 2)),
        description=description,
        payload=payload,
        expires_in=3600,
    )


def get_invoices(status: str = None, invoice_ids: list = None) -> list:
    """
    Returns list of invoices filtered by status and/or IDs.
    Statuses: 'active', 'paid', 'expired'
    """
    params = {}
    if status:
        params["status"] = status
    if invoice_ids:
        params["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
    result = _call("getInvoices", **params)
    return result.get("items", [])


def get_invoice(invoice_id: int) -> dict | None:
    """Returns a single invoice by ID, or None if not found."""
    items = get_invoices(invoice_ids=[invoice_id])
    return items[0] if items else None


def transfer(user_id: int, asset: str, amount: float, spend_id: str, comment: str = "") -> dict:
    """
    Sends crypto from the bot's CryptoPay wallet to a Telegram user's CryptoPay wallet.
    spend_id is a unique idempotency key (e.g. 'withdrawal_42').
    Raises RuntimeError on failure.
    """
    params = {
        "user_id": user_id,
        "asset": asset,
        "amount": str(round(amount, 2)),
        "spend_id": spend_id,
    }
    if comment:
        params["comment"] = comment
    return _call("transfer", **params)


def get_exchange_rates() -> list:
    """Returns list of {source, target, rate} for converting between assets and USD."""
    return _call("getExchangeRates")


def usd_to_asset(amount_usd: float, asset: str) -> float:
    """Converts USD amount to the given crypto asset using CryptoPay exchange rates."""
    rates = get_exchange_rates()
    for r in rates:
        if r.get("source") == "USD" and r.get("target") == asset and r.get("is_valid"):
            return round(amount_usd * float(r["rate"]), 6)
    # Fallback: USDT ≈ 1:1
    if asset == "USDT":
        return round(amount_usd, 2)
    raise ValueError("No exchange rate found for USD → " + asset)
