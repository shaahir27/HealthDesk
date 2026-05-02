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
