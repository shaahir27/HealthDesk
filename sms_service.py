import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import requests
except ImportError:
    requests = None


if load_dotenv:
    load_dotenv()


FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"
_last_error = ""


def _set_last_error(message):
    global _last_error
    _last_error = str(message or "").strip()
    return False


def get_last_sms_error():
    return _last_error


def _normalize_numbers(phone):
    if isinstance(phone, (list, tuple, set)):
        candidates = phone
    else:
        candidates = str(phone or "").split(",")

    numbers = []
    for item in candidates:
        digits = "".join(ch for ch in str(item or "") if ch.isdigit())
        if len(digits) == 10:
            numbers.append(digits)
    return numbers


def send_sms(phone, message):
    global _last_error
    _last_error = ""
    numbers = _normalize_numbers(phone)
    clean_message = str(message or "").strip()
    if not numbers or not clean_message:
        error = "missing phone number or message"
        print(f"[HealthDesk SMS] skipped: {error}")
        return _set_last_error(error)

    api_key = os.environ.get("FAST2SMS_API_KEY", "").strip()
    if not api_key:
        print(f"[HealthDesk DEV SMS] {','.join(numbers)}: {clean_message}")
        return True

    if requests is None:
        error = "requests package is not installed"
        print(f"[HealthDesk SMS] failed: {error}")
        return _set_last_error(error)

    try:
        response = requests.post(
            FAST2SMS_URL,
            headers={
                "authorization": api_key,
                "Content-Type": "application/json"
            },
            json={
                "route": os.environ.get("FAST2SMS_ROUTE", "q"),
                "message": clean_message,
                "language": "english",
                "flash": 0,
                "numbers": ",".join(numbers)
            },
            timeout=8
        )
        if response.status_code >= 400:
            error = f"Fast2SMS returned {response.status_code} {response.text[:180]}"
            print(f"[HealthDesk SMS] failed: {error}")
            return _set_last_error(error)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if payload and payload.get("return") is False:
            provider_message = payload.get("message") or payload.get("error") or response.text[:180]
            if isinstance(provider_message, list):
                provider_message = "; ".join(str(item) for item in provider_message)
            error = f"Fast2SMS rejected the SMS: {provider_message}"
            print(f"[HealthDesk SMS] failed: {error}")
            return _set_last_error(error)
        return True
    except Exception as exc:
        print(f"[HealthDesk SMS] failed: {exc}")
        return _set_last_error(exc)
