"""
Thin wrapper around Paystack's REST API. Views call these two functions;
nothing else in the codebase should talk to Paystack directly, so tests
can mock this module instead of the network.

Docs: https://paystack.com/docs/api/transaction/
"""

import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = "https://api.paystack.co"
REQUEST_TIMEOUT = 15  # seconds


class PaystackError(Exception):
    """Raised when Paystack can't be reached or returns an unexpected
    shape of response. Callers should catch this and treat it exactly
    like a failed payment - never assume success on error."""


def initialize_transaction(*, email, amount_naira, reference, callback_url, metadata=None):
    """
    Starts a Paystack transaction and returns the checkout URL to redirect
    the customer to. amount_naira is converted to kobo here (Paystack's
    API is kobo-denominated) so callers never have to remember that.
    """
    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            json={
                "email": email,
                "amount": amount_naira * 100,
                "reference": reference,
                "callback_url": callback_url,
                "metadata": metadata or {},
            },
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc

    if not response.ok or not data.get("status"):
        raise PaystackError(f"Paystack initialize failed: {data.get('message', response.text)}")

    return data["data"]["authorization_url"]


def verify_transaction(reference):
    """
    Verifies a transaction by reference. Returns the Paystack response's
    `data` dict on success (caller still must check data['status'] ==
    'success' - a 200 here just means the API call worked, not that the
    payment did). Raises PaystackError if the API call itself fails.
    """
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc

    if not response.ok or not data.get("status"):
        raise PaystackError(f"Paystack verify failed: {data.get('message', response.text)}")

    return data["data"]


def verify_webhook_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Confirms a webhook POST actually came from Paystack, per their docs:
    HMAC-SHA512 of the raw request body, keyed with the secret key, must
    match the x-paystack-signature header exactly.
    """
    if not signature_header:
        return False
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        request_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
