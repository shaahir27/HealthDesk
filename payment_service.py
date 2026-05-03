import hashlib
import hmac
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import razorpay
except ImportError:
    razorpay = None


if load_dotenv:
    load_dotenv()


def payments_configured():
    return bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"))


def get_razorpay_key_id():
    return os.environ.get("RAZORPAY_KEY_ID", "").strip()


def create_payment_order(amount_rupees, receipt, notes=None):
    if not payments_configured():
        return False, "Payments are not configured.", None
    if razorpay is None:
        return False, "The razorpay package is not installed.", None

    try:
        amount_paise = int(round(float(amount_rupees) * 100))
    except (TypeError, ValueError):
        return False, "Invalid bill amount.", None

    if amount_paise <= 0:
        return False, "Bill amount must be greater than zero.", None

    try:
        client = razorpay.Client(
            auth=(os.environ["RAZORPAY_KEY_ID"].strip(), os.environ["RAZORPAY_KEY_SECRET"].strip())
        )
        order = client.order.create(data={
            "amount": amount_paise,
            "currency": "INR",
            "receipt": str(receipt)[:40],
            "notes": notes or {}
        })
        return True, "", order
    except Exception as exc:
        return False, str(exc), None


def verify_webhook_signature(raw_body, signature):
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not secret or not signature:
        return False
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


def create_advance_order(amount_rupees, advance_id, patient_name, notes=None):
    """
    Creates a Razorpay order for advance payment.
    Returns (ok: bool, error: str, order: dict|None).
    """
    if not payments_configured():
        return False, "Payments are not configured.", None
    if razorpay is None:
        return False, "The razorpay package is not installed.", None
    try:
        amount_paise = int(round(float(amount_rupees) * 100))
    except (TypeError, ValueError):
        return False, "Invalid advance amount.", None
    if amount_paise <= 0:
        return False, "Advance amount must be greater than zero.", None
    try:
        client = razorpay.Client(
            auth=(os.environ["RAZORPAY_KEY_ID"].strip(), os.environ["RAZORPAY_KEY_SECRET"].strip())
        )
        order = client.order.create(data={
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"adv_{advance_id}"[:40],
            "notes": notes or {"type": "advance", "patient": patient_name}
        })
        return True, "", order
    except Exception as exc:
        return False, str(exc), None


def initiate_refund(payment_id, amount_rupees):
    """
    Initiates a Razorpay refund.
    Used for BOTH advance refunds and bill refunds.
    Returns (ok: bool, error: str).
    RULE: Only update flat-file records AFTER this returns ok=True.
    """
    if not payments_configured():
        return False, "Payments not configured - refund manually in Razorpay dashboard."
    if razorpay is None:
        return False, "razorpay package not installed."
    try:
        amount_paise = int(round(float(amount_rupees) * 100))
    except (TypeError, ValueError):
        return False, "Invalid refund amount."
    if amount_paise <= 0:
        return False, "Refund amount must be greater than zero."
    try:
        client = razorpay.Client(
            auth=(os.environ["RAZORPAY_KEY_ID"].strip(), os.environ["RAZORPAY_KEY_SECRET"].strip())
        )
        client.payment.refund(str(payment_id), {"amount": amount_paise})
        return True, ""
    except Exception as exc:
        return False, str(exc)


def payments_in_test_mode():
    """Returns True if the configured key is a Razorpay test key."""
    return os.environ.get("RAZORPAY_KEY_ID", "").startswith("rzp_test_")
