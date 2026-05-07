from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for
import hashlib
import hmac
from io import BytesIO
import json
import os
import platform
import re
import secrets
import subprocess
import threading
from datetime import date, datetime, timedelta
from functools import wraps
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from payment_service import create_payment_order, get_razorpay_key_id, payments_configured, verify_webhook_signature
from sms_service import get_last_sms_error, send_sms
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMPL_DIR = os.path.join(BASE_DIR, "Frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "Frontend", "static")
BACKEND_DIR = os.path.join(BASE_DIR, "Backend")
DATA_DIR = os.path.join(BACKEND_DIR, "data")
USER_FILE = os.path.join(DATA_DIR, "users.txt")
BILLING_FILE = os.path.join(DATA_DIR, "billing.txt")
PRICING_FILE = os.path.join(DATA_DIR, "pricing_catalog.json")
APPOINTMENT_FILE = os.path.join(DATA_DIR, "appointment.txt")
QUEUE_FILE = os.path.join(DATA_DIR, "queue.txt")
DIAGNOSIS_FILE = os.path.join(DATA_DIR, "diagnosis.txt")
VITALS_FILE = os.path.join(DATA_DIR, "vitals.txt")
PRESCRIPTION_FILE = os.path.join(DATA_DIR, "prescriptions.txt")
PENDING_APPOINTMENTS_FILE = os.path.join(DATA_DIR, "pending_appointments.txt")
NEW_PATIENT_REQUESTS_FILE = os.path.join(DATA_DIR, "new_patient_requests.txt")
DOCTOR_STATUS_META_FILE = os.path.join(DATA_DIR, "doctor_status_meta.json")
_EXE_SUFFIX = ".exe" if platform.system() == "Windows" else ""
BILLING_EXE = os.path.join(BACKEND_DIR, "c_modules", f"billing{_EXE_SUFFIX}")
ADVANCE_EXE = os.path.join(BACKEND_DIR, "c_modules", f"advance{_EXE_SUFFIX}")
PENDING_REQUEST_EXE = os.path.join(BACKEND_DIR, "c_modules", f"pending_request{_EXE_SUFFIX}")
PATIENT_EXE = os.path.join(BACKEND_DIR, "c_modules", f"patient{_EXE_SUFFIX}")
DOCTOR_EXE = os.path.join(BACKEND_DIR, "c_modules", f"doctor{_EXE_SUFFIX}")
APPOINTMENT_EXE = os.path.join(BACKEND_DIR, "c_modules", f"appointment{_EXE_SUFFIX}")
QUEUE_EXE = os.path.join(BACKEND_DIR, "c_modules", f"queue{_EXE_SUFFIX}")
_UTILS_EXE = os.path.join(BACKEND_DIR, "c_modules", f"utils{_EXE_SUFFIX}")
VITALS_EXE = os.path.join(BACKEND_DIR, "c_modules", f"vitals{_EXE_SUFFIX}")
PRESCRIPTION_EXE = os.path.join(BACKEND_DIR, "c_modules", f"prescription{_EXE_SUFFIX}")
_appointment_lock = threading.Lock()
_pending_appointment_lock = threading.Lock()
_new_patient_request_lock = threading.Lock()
_billing_lock = threading.Lock()
_otp_lock = threading.Lock()
_advance_lock = threading.Lock()
_diagnosis_lock = threading.Lock()
_vitals_lock = threading.Lock()
_prescription_lock = threading.Lock()
_otp_store = {}
_login_lockout_store = {}   # username -> {"attempts": int, "locked_until": datetime|None}
_login_lockout_lock = threading.Lock()
ALLOWED_PAYMENT_STATUSES = {"PENDING", "INITIATED", "PAID", "WAIVED", "REFUNDED"}
ADVANCE_DATA_PATH = os.path.join(DATA_DIR, "advances.txt")
BOOKING_INTENT_PATH = os.path.join(DATA_DIR, "pending_booking_intents.txt")
ADVANCE_PERCENT = float(os.environ.get("ADVANCE_PERCENT", "20"))
OTP_EXPIRY_SECONDS = 5 * 60
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 3
LOGIN_MAX_ATTEMPTS = 3
LOGIN_LOCKOUT_SECONDS = 3 * 60
PENDING_REQUEST_EXPIRY_HOURS = 2
DEFAULT_CLINIC_PHONE = "+91 XXXXX XXXXX"

app = Flask(__name__,
            template_folder = TMPL_DIR,
            static_folder=STATIC_DIR)
app.secret_key = os.environ.get("HEALTHDESK_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production"
)
def clean_record_field(value, max_length=180):
    cleaned = str(value or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:max_length]

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def parse_appointment_line(line):
    data = line.strip().split("|")
    if len(data) < 6:
        return None
    try:
        return {
            "appointment_id": int(data[0]),
            "patient_id": int(data[1]),
            "doctor_id": int(data[2]),
            "date": data[3],
            "time_slot": data[4],
            "status": data[5]
        }
    except ValueError:
        return None


def parse_patient_record_line(line):
    data = line.strip().split("|")
    if len(data) < 10:
        return None
    try:
        return {
            "id": int(data[0]),
            "name": data[1],
            "age": data[2],
            "gender": data[3],
            "phone": data[4],
            "address": data[5],
            "symptoms": data[6],
            "visit_type": data[7],
            "priority": data[8],
            "department": data[9]
        }
    except ValueError:
        return None


def parse_patient_command_output(output):
    data = str(output or "").strip().split("|")
    if len(data) >= 11 and data[0] == "PATIENT":
        return {
            "id": int(data[1]),
            "name": data[2],
            "age": data[3],
            "gender": data[4],
            "phone": data[5],
            "address": data[6],
            "symptoms": data[7],
            "visit_type": data[8],
            "priority": data[9],
            "department": data[10]
        }
    return None


def parse_doctor_record_line(line):
    data = line.strip().split("|")
    if len(data) < 6:
        return None
    try:
        return {
            "id": int(data[0]),
            "name": data[1],
            "department": data[2],
            "experience": int(data[3]),
            "daily_status": data[4],
            "current_status": data[5]
        }
    except ValueError:
        return None

def read_appointment_file():
    appointments = {}
    result = run_appointment_command("list-all")
    if not result or result.returncode != 0:
        raise RuntimeError("appointment command failed: list-all")
    for line in result.stdout.splitlines():
        appointment = parse_appointment_line(line)
        if appointment:
            appointments[appointment["appointment_id"]] = appointment
    return sorted(appointments.values(), key=lambda item: item["appointment_id"])


def write_appointment_file(appointments):
    lines = []
    for appointment in appointments:
        lines.append(
            f"{int(appointment['appointment_id'])}|{int(appointment['patient_id'])}|"
            f"{int(appointment['doctor_id'])}|{clean_record_field(appointment['date'])}|"
            f"{clean_record_field(appointment['time_slot'])}|{clean_record_field(appointment['status'])}"
        )
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    result = subprocess.run(
        [APPOINTMENT_EXE, "write-all"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )
    if not result or result.returncode != 0:
        raise RuntimeError("appointment command failed: write-all")


def write_queue_file(rows):
    lines = []
    for row in rows:
        lines.append(
            f"{int(row['token'])}|{int(row['patient_id'])}|{int(row['doctor_id'])}|"
            f"{clean_record_field(row['priority'])}|{clean_record_field(row['status'])}"
        )
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    result = subprocess.run(
        [QUEUE_EXE, "write-all"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )
    if not result or result.returncode != 0:
        raise RuntimeError("queue command failed: write-all")

def is_authenticated():
    return session.get("logged_in", False)

def require_role(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if session.get("role") not in allowed_roles:
                return redirect("/")
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

def password_matches(stored_password, provided_password):
    if stored_password.startswith(("pbkdf2:", "scrypt:")):
        try:
            return check_password_hash(stored_password, provided_password)
        except ValueError:
            return False
    return hmac.compare_digest(stored_password, provided_password)

def authenticate_user(username, password):
    for account in read_user_accounts():
        if account["username"] != username:
            continue
        if password_matches(account["password"], password):
            return {
                "username": account["username"],
                "role": account["role"],
                "doctor_id": str(account["doctor_id"])
            }
    return None


def _run_utils_command(*args):
    try:
        return subprocess.run(
            [_UTILS_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def normalize_phone(phone):
    result = _run_utils_command("normalize-phone", str(phone or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: normalize-phone")


def is_valid_patient_phone(phone):
    result = _run_utils_command("valid-patient-phone", str(phone or ""))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("utils command failed: valid-patient-phone")


def mask_phone(phone):
    result = _run_utils_command("mask-phone", str(phone or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: mask-phone")


def hash_otp(otp):
    return hashlib.sha256(str(otp).encode("utf-8")).hexdigest()


def find_registered_patient_by_phone(phone):
    normalized = normalize_phone(phone)
    for patient in read_patients():
        if normalize_phone(patient.get("phone", "")) == normalized:
            return patient
    return None


def send_patient_otp(phone, otp):
    return send_sms(phone, f"Your HealthDesk OTP is {otp}. Valid 5 min. Do not share.")


def send_sms_notice(phone, message):
    sent = send_sms(phone, message)
    if not sent:
        detail = get_last_sms_error()
        suffix = f": {detail}" if detail else ""
        print(f"[HealthDesk SMS] notice not delivered to {mask_phone(phone)}{suffix}")
    return sent


def notify_receptionists(message):
    receptionist_phone = os.environ.get("RECEPTIONIST_PHONE", "")
    if not receptionist_phone:
        return False
    return send_sms_notice(receptionist_phone, message)


def generate_otp(phone, force=False):
    normalized = normalize_phone(phone)
    with _otp_lock:
        existing = _otp_store.get(normalized)
        # Enforce resend cooldown unless forced
        if not force and existing:
            last_sent = existing.get("sent_at")
            if last_sent and (datetime.now() - last_sent).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
                seconds_left = int(OTP_RESEND_COOLDOWN_SECONDS - (datetime.now() - last_sent).total_seconds())
                return False, seconds_left
    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = datetime.now() + timedelta(seconds=OTP_EXPIRY_SECONDS)
    with _otp_lock:
        _otp_store[normalized] = {
            "hash": hash_otp(otp),
            "expires_at": expires_at,
            "attempts": 0,
            "sent_at": datetime.now()
        }
    if not send_patient_otp(normalized, otp):
        with _otp_lock:
            _otp_store.pop(normalized, None)
        return False, 0
    return True, 0


def verify_otp(phone, entered):
    normalized = normalize_phone(phone)
    entered = normalize_phone(entered)
    if not is_valid_patient_phone(normalized):
        return False, "Please request a new OTP.", 0
    if not re.fullmatch(r"\d{6}", entered or ""):
        return False, "Enter the 6-digit OTP sent to your phone.", OTP_MAX_ATTEMPTS

    with _otp_lock:
        record = _otp_store.get(normalized)
        if not record:
            return False, "No OTP was requested. Please start again.", 0
        if datetime.now() > record["expires_at"]:
            _otp_store.pop(normalized, None)
            return False, "OTP expired. Please request a new one.", 0
        if hmac.compare_digest(record["hash"], hash_otp(entered)):
            _otp_store.pop(normalized, None)
            return True, "OTP verified.", OTP_MAX_ATTEMPTS - record["attempts"]

        record["attempts"] += 1
        attempts_left = OTP_MAX_ATTEMPTS - record["attempts"]
        if attempts_left <= 0:
            _otp_store.pop(normalized, None)
            return False, "Too many incorrect attempts. Request a new OTP.", 0
        return False, f"Incorrect OTP. {attempts_left} attempt(s) left.", attempts_left


def read_user_accounts():
    _auth_exe = os.path.join(BACKEND_DIR, "c_modules", "auth.exe")
    try:
        result = subprocess.run(
            [_auth_exe, "list"],
            capture_output=True, text=True, cwd=BASE_DIR
        )
    except FileNotFoundError:
        return []
    accounts = []
    if not result or result.returncode != 0:
        return accounts
    for line in result.stdout.splitlines():
        data = line.strip().split("|")
        if len(data) < 5:
            continue
        try:
            accounts.append({
                "id": int(data[0]),
                "username": data[1],
                "password": data[2],
                "role": data[3],
                "doctor_id": int(data[4] or 0)
            })
        except ValueError:
            continue
    return accounts


def next_user_id():
    _auth_exe = os.path.join(BACKEND_DIR, "c_modules", "auth.exe")
    try:
        result = subprocess.run([_auth_exe, "next-id"], capture_output=True, text=True, cwd=BASE_DIR)
        if result and result.returncode == 0:
            return safe_int(result.stdout.strip(), 0) or \
                   max((a["id"] for a in read_user_accounts()), default=0) + 1
    except FileNotFoundError:
        pass
    return max((a["id"] for a in read_user_accounts()), default=0) + 1



def strip_doctor_title(name):
    result = _run_utils_command("strip-title", str(name or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: strip-title")


def build_doctor_username(name, existing_usernames):
    result = run_doctor_command("build-username", strip_doctor_title(name))
    if not result or result.returncode != 0:
        raise RuntimeError("doctor command failed: build-username")
    candidate = result.stdout.strip() or "dr.doctor"
    if not candidate.startswith("dr."):
        candidate = f"dr.{candidate}"
    base = candidate[3:] if candidate.startswith("dr.") else candidate
    suffix = 2
    while candidate in existing_usernames:
        candidate = f"dr.{base}{suffix}"
        suffix += 1
    return candidate


def build_doctor_password(doctor_id):
    result = run_doctor_command("build-password", int(doctor_id))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("doctor command failed: build-password")


def save_user_account(username, password, role, doctor_id):
    _auth_exe = os.path.join(BACKEND_DIR, "c_modules", "auth.exe")
    user_id = next_user_id()
    stored_password = generate_password_hash(password)
    line = (
        f"{user_id}|{clean_record_field(username)}|{clean_record_field(stored_password, 260)}|"
        f"{clean_record_field(role)}|{int(doctor_id or 0)}"
    )
    subprocess.run([_auth_exe, "save", line], capture_output=True, text=True, cwd=BASE_DIR)



def generate_staff_password(role, doctor_id=0):
    role_prefix = "DOC" if str(role).lower() == "doctor" else "STAFF"
    suffix = f"{doctor_id}" if int(doctor_id or 0) > 0 else ""
    return f"HD{role_prefix}{suffix}-{secrets.randbelow(900000) + 100000}!"


def reset_staff_password(account_id):
    _auth_exe = os.path.join(BACKEND_DIR, "c_modules", "auth.exe")
    account_id = safe_int(account_id)
    accounts = read_user_accounts()
    for account in accounts:
        if account["id"] != account_id:
            continue
        if str(account.get("role", "")).lower() == "patient":
            return None
        new_password = generate_staff_password(account.get("role", ""), account.get("doctor_id", 0))
        new_hash = generate_password_hash(new_password)
        result = subprocess.run(
            [_auth_exe, "update", str(account["id"]), new_hash],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        if not result or result.returncode != 0:
            return None
        account["password"] = new_hash   # keep in-memory copy consistent
        return {
            "account_id": account["id"],
            "username": account["username"],
            "role": account["role"],
            "doctor_id": account["doctor_id"],
            "password": new_password,
        }
    return None


def load_pricing_catalog():
    with open(PRICING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_pricing_maps():
    catalog = load_pricing_catalog()
    return (
        catalog,
        {item["code"]: item for item in catalog.get("treatments", [])},
        {item["code"]: item for item in catalog.get("lab_tests", [])}
    )


def build_bill_items(raw_value):
    items = []
    for chunk in (raw_value or "").split("^"):
        if not chunk:
            continue
        name, _, amount = chunk.partition("~")
        try:
            parsed_amount = float(amount)
        except ValueError:
            parsed_amount = 0.0
        items.append({"name": name, "price": parsed_amount})
    return items


def serialize_bill_items(items):
    return "^".join(f"{item['name']}~{item['price']:.0f}" for item in items)


def run_billing_command(*args):
    try:
        return subprocess.run(
            [BILLING_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def run_advance_command(*args):
    try:
        return subprocess.run(
            [ADVANCE_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def run_patient_command(*args):
    try:
        return subprocess.run(
            [PATIENT_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def run_doctor_command(*args):
    try:
        return subprocess.run(
            [DOCTOR_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def run_queue_command(*args):
    try:
        return subprocess.run(
            [QUEUE_EXE, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def generate_bill_id():
    result = run_billing_command("next-id")
    if result and result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except ValueError:
            raise RuntimeError("invalid output from billing next-id")
    raise RuntimeError("billing command failed: next-id")


def parse_bill_line(line):
    data = line.strip().split("|")
    if len(data) >= 19:
        bill = {
            "bill_id": int(data[0]),
            "date": data[1],
            "patient_id": int(data[2]),
            "name": data[3],
            "age": int(data[4]),
            "gender": data[5],
            "doctor": data[6],
            "department": data[7],
            "doctor_fee": float(data[8]),
            "treatment_total": float(data[9]),
            "lab_total": float(data[10]),
            "medicine_total": float(data[11]),
            "total": float(data[12]),
            "status": data[13],
            "doctor_id": int(data[14]),
            "treatments": build_bill_items(data[15]),
            "lab_tests": build_bill_items(data[16]),
            "medicine_notes": data[17],
            "appointment_id": int(data[18] or 0),
            "razorpay_order_id": data[19] if len(data) > 19 else "",
            "razorpay_payment_id": data[20] if len(data) > 20 else "",
            "payment_method": data[21] if len(data) > 21 else "",
            "paid_at": data[22] if len(data) > 22 else "",
            "initiated_at": data[23] if len(data) > 23 else (data[22] if len(data) > 22 and data[13] == "INITIATED" else ""),
            "advance_id": safe_int(data[24]) if len(data) > 24 else 0,
            "advance_amount": float(data[25]) if len(data) > 25 and data[25].strip() else 0.0,
            "advance_credited_at": data[26].strip() if len(data) > 26 else "",
        }
        bill["total"] = recalculate_bill_total(bill)
        return bill
    if len(data) >= 18:
        bill = {
            "bill_id": int(data[0]),
            "date": data[1],
            "patient_id": int(data[2]),
            "name": data[3],
            "age": int(data[4]),
            "gender": data[5],
            "doctor": data[6],
            "department": data[7],
            "doctor_fee": float(data[8]),
            "treatment_total": float(data[9]),
            "lab_total": float(data[10]),
            "medicine_total": float(data[11]),
            "total": float(data[12]),
            "status": data[13],
            "doctor_id": int(data[14]),
            "treatments": build_bill_items(data[15]),
            "lab_tests": build_bill_items(data[16]),
            "medicine_notes": data[17],
            "appointment_id": 0,
            "razorpay_order_id": "",
            "razorpay_payment_id": "",
            "payment_method": "",
            "paid_at": "",
            "initiated_at": "",
            "advance_id": 0,
            "advance_amount": 0.0,
            "advance_credited_at": "",
        }
        bill["total"] = recalculate_bill_total(bill)
        return bill
    if len(data) >= 13:
        doctor_fee = float(data[8])
        medicine_total = float(data[9])
        lab_total = float(data[10])
        bill = {
            "bill_id": int(data[0]),
            "date": data[1],
            "patient_id": int(data[2]),
            "name": data[3],
            "age": int(data[4]),
            "gender": data[5],
            "doctor": data[6],
            "department": data[7],
            "doctor_fee": doctor_fee,
            "treatment_total": 0.0,
            "lab_total": lab_total,
            "medicine_total": medicine_total,
            "total": float(data[11]),
            "status": data[12],
            "doctor_id": 0,
            "treatments": [],
            "lab_tests": [{"name": "Lab Tests", "price": lab_total}] if lab_total else [],
            "medicine_notes": "",
            "appointment_id": 0,
            "razorpay_order_id": "",
            "razorpay_payment_id": "",
            "payment_method": "",
            "paid_at": "",
            "initiated_at": "",
            "advance_id": 0,
            "advance_amount": 0.0,
            "advance_credited_at": "",
        }
        bill["total"] = recalculate_bill_total(bill)
        return bill
    return None


def recalculate_bill_total(bill):
    result = run_billing_command(
        "recalc-total",
        bill.get("doctor_fee", 0) or 0,
        bill.get("treatment_total", 0) or 0,
        bill.get("lab_total", 0) or 0,
        bill.get("medicine_total", 0) or 0,
    )
    if result and result.returncode == 0:
        try:
            return float(result.stdout.strip())
        except ValueError:
            raise RuntimeError("invalid output from billing recalc-total")
    raise RuntimeError("billing command failed: recalc-total")


def read_bills():
    bills = []
    result = run_billing_command("list")
    if not result or result.returncode != 0:
        raise RuntimeError("billing command failed: list")
    lines = [line for line in result.stdout.splitlines() if line.strip()]

    for line in lines:
        bill = parse_bill_line(line)
        if bill:
            bills.append(bill)
    return bills


def find_bill_by_id(bill_id):
    result = run_billing_command("find-id", bill_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_bill_line(result.stdout.strip())
    return next((bill for bill in read_bills() if bill["bill_id"] == int(bill_id)), None)


def find_bill_by_appointment_id(appointment_id):
    result = run_billing_command("find-appointment", appointment_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_bill_line(result.stdout.strip())
    return next(
        (
            bill for bill in read_bills()
            if int(bill.get("appointment_id", 0) or 0) == int(appointment_id)
        ),
        None
    )

def patient_owns_bill(bill, patient_id):
    return bool(bill) and int(bill.get("patient_id", 0) or 0) == int(patient_id)


def serialize_bill_record(bill):
    return "|".join([
        str(int(bill["bill_id"])),
        clean_record_field(bill["date"]),
        str(int(bill["patient_id"])),
        clean_record_field(bill["name"]),
        str(int(bill["age"])),
        clean_record_field(bill["gender"]),
        clean_record_field(bill["doctor"]),
        clean_record_field(bill["department"]),
        f"{float(bill['doctor_fee']):.0f}",
        f"{float(bill['treatment_total']):.0f}",
        f"{float(bill['lab_total']):.0f}",
        f"{float(bill['medicine_total']):.0f}",
        f"{float(bill['total']):.0f}",
        clean_record_field(bill["status"]),
        str(int(bill.get("doctor_id", 0) or 0)),
        serialize_bill_items(bill.get("treatments", [])),
        serialize_bill_items(bill.get("lab_tests", [])),
        clean_record_field(bill.get("medicine_notes", "")),
        str(int(bill.get("appointment_id", 0) or 0)),
        clean_record_field(bill.get("razorpay_order_id", ""), 80),
        clean_record_field(bill.get("razorpay_payment_id", ""), 80),
        clean_record_field(bill.get("payment_method", ""), 40),
        clean_record_field(bill.get("paid_at", ""), 40),
        clean_record_field(bill.get("initiated_at", ""), 40),
        str(int(bill.get("advance_id", 0) or 0)),
        f"{float(bill.get('advance_amount', 0) or 0):.2f}",
        clean_record_field(bill.get("advance_credited_at", ""), 40),
    ])


def save_bill_record(bill):
    line = serialize_bill_record(bill)
    with _billing_lock:
        result = run_billing_command("save", line)
        return bool(result and result.returncode == 0)


# ---------------- ADVANCE RECORD HELPERS ----------------

def parse_advance_line(line):
    line = line.strip()
    if not line:
        return None
    data = line.split("|")
    if len(data) < 13:
        data += [""] * (13 - len(data))
    return {
        "advance_id": safe_int(data[0]),
        "patient_id": safe_int(data[1]),
        "appointment_id": safe_int(data[2]),
        "doctor_id": safe_int(data[3]),
        "appointment_date": data[4].strip(),
        "amount": float(data[5]) if data[5].strip() else 0.0,
        "status": data[6].strip().upper(),
        "razorpay_order_id": data[7].strip(),
        "razorpay_payment_id": data[8].strip(),
        "created_at": data[9].strip(),
        "paid_at": data[10].strip(),
        "settled_at": data[11].strip(),
        "pending_request_id": safe_int(data[12]),
    }


def serialize_advance_record(adv):
    return "|".join([
        str(adv.get("advance_id", 0)),
        str(adv.get("patient_id", 0)),
        str(adv.get("appointment_id", 0)),
        str(adv.get("doctor_id", 0)),
        str(adv.get("appointment_date", "")),
        str(adv.get("amount", 0.0)),
        str(adv.get("status", "PENDING_PAYMENT")),
        str(adv.get("razorpay_order_id", "")),
        str(adv.get("razorpay_payment_id", "")),
        str(adv.get("created_at", "")),
        str(adv.get("paid_at", "")),
        str(adv.get("settled_at", "")),
        str(adv.get("pending_request_id", 0)),
    ])


def _read_advances_unlocked():
    result = run_advance_command("list")
    if not result or result.returncode != 0:
        return []
    return [r for r in (parse_advance_line(l) for l in result.stdout.splitlines() if l.strip()) if r]


def read_advances():
    with _advance_lock:
        return _read_advances_unlocked()



def next_advance_id():
    with _advance_lock:
        result = run_advance_command("next-id")
        if result and result.returncode == 0:
            return safe_int(result.stdout.strip(), 1)
        return 1



def find_advance_by_id(advance_id):
    with _advance_lock:
        result = run_advance_command("find-id", advance_id)
        if result and result.returncode == 0 and result.stdout.strip():
            return parse_advance_line(result.stdout.strip())
        return None



def find_advance_by_appointment_id(appointment_id):
    with _advance_lock:
        result = run_advance_command("find-appointment", appointment_id)
        if result and result.returncode == 0 and result.stdout.strip():
            return parse_advance_line(result.stdout.strip())
        return None



def find_advance_by_order_id(order_id):
    order_id = str(order_id or "").strip()
    if not order_id:
        return None
    with _advance_lock:
        result = run_advance_command("find-order", order_id)
        if result and result.returncode == 0 and result.stdout.strip():
            return parse_advance_line(result.stdout.strip())
        return None



def update_advance_record(updated):
    line = serialize_advance_record(updated)
    with _advance_lock:
        result = run_advance_command("update", updated["advance_id"], line)
        return bool(result and result.returncode == 0)


def create_advance_record(patient_id, doctor_id, appointment_date, amount, pending_request_id=0):
    with _advance_lock:
        result = run_advance_command("next-id")
        next_id = safe_int(result.stdout.strip(), 0) if result and result.returncode == 0 else 1
        adv = {
            "advance_id": next_id,
            "patient_id": int(patient_id),
            "appointment_id": 0,
            "doctor_id": int(doctor_id),
            "appointment_date": str(appointment_date),
            "amount": float(amount),
            "status": "PENDING_PAYMENT",
            "razorpay_order_id": "",
            "razorpay_payment_id": "",
            "created_at": iso_now(),
            "paid_at": "",
            "settled_at": "",
            "pending_request_id": int(pending_request_id),
        }
        line = serialize_advance_record(adv)
        result = run_advance_command("save", line)
        if not result or result.returncode != 0:
            raise RuntimeError("advance.exe save failed")
    return adv



def get_advance_amount_for_department(department):
    catalog = load_pricing_catalog()
    fee = catalog.get("doctor_fees", {}).get(department, 0)
    return round(float(fee) * ADVANCE_PERCENT / 100, 2)


# ---------------- BOOKING INTENT HELPERS ----------------
# Webhooks have no Flask session. Booking intent (slot, reason, visit_type,
# triage) is persisted server-side in a flat file keyed by advance_id.

def parse_booking_intent_line(line):
    parts = line.strip().split("|")
    if len(parts) < 7:
        return None
    return {
        "advance_id": safe_int(parts[0]),
        "doctor_id": safe_int(parts[1]),
        "requested_date": parts[2],
        "requested_slot": parts[3],
        "reason": parts[4],
        "visit_type": parts[5],
        "triage": parts[6],
    }


def serialize_booking_intent(advance_id, doctor_id, requested_date, requested_slot, reason, visit_type, triage):
    return "|".join([
        str(int(advance_id)),
        str(int(doctor_id)),
        clean_record_field(requested_date, 20),
        clean_record_field(requested_slot, 32),
        clean_record_field(reason, 220),
        clean_record_field(visit_type, 32),
        clean_record_field(triage, 32),
    ])


def save_booking_intent(advance_id, doctor_id, requested_date, requested_slot, reason, visit_type, triage):
    serialized = serialize_booking_intent(
        advance_id, doctor_id, requested_date, requested_slot, reason, visit_type, triage
    )
    result = run_advance_command("intent-save", serialized)
    return bool(result and result.returncode == 0)


def pop_booking_intent(advance_id):
    result = run_advance_command("intent-pop", advance_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_booking_intent_line(result.stdout.strip())
    return None


# ── VITALS HELPERS ──

def run_vitals_command(*args):
    try:
        return subprocess.run(
            [VITALS_EXE, *[str(a) for a in args]],
            capture_output=True, text=True, cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def parse_vitals_line(line):
    """Parse a pipe-delimited vitals record into a dict. Returns None on failure."""
    data = line.strip().split("|")
    if len(data) < 15:
        data += [""] * (15 - len(data))
    try:
        return {
            "vitals_id":          safe_int(data[0]),
            "patient_id":         safe_int(data[1]),
            "doctor_id":          safe_int(data[2]),
            "token":              safe_int(data[3]),
            "recorded_at":        data[4].strip(),
            "temperature":        data[5].strip(),
            "bp_systolic":        data[6].strip(),
            "bp_diastolic":       data[7].strip(),
            "pulse_rate":         data[8].strip(),
            "weight":             data[9].strip(),
            "oxygen_level":       data[10].strip(),
            "sugar_level":        data[11].strip(),
            "allergy_conditions": data[12].strip(),
            "health_conditions":  data[13].strip(),
            "notes":              data[14].strip(),
            "smoking_habit":      data[15].strip() if len(data) > 15 else "",
            "drinking_habit":     data[16].strip() if len(data) > 16 else "",
        }
    except (IndexError, ValueError):
        return None


def serialize_vitals_record(v):
    """Serialise a vitals dict to pipe-delimited string (safe for flat-file storage)."""
    return "|".join([
        str(v.get("vitals_id", 0)),
        str(v.get("patient_id", 0)),
        str(v.get("doctor_id", 0)),
        str(v.get("token", 0)),
        clean_record_field(v.get("recorded_at", ""), 40),
        clean_record_field(v.get("temperature", ""), 20),
        clean_record_field(v.get("bp_systolic", ""), 20),
        clean_record_field(v.get("bp_diastolic", ""), 20),
        clean_record_field(v.get("pulse_rate", ""), 20),
        clean_record_field(v.get("weight", ""), 20),
        clean_record_field(v.get("oxygen_level", ""), 20),
        clean_record_field(v.get("sugar_level", ""), 20),
        clean_record_field(v.get("allergy_conditions", ""), 200),
        clean_record_field(v.get("health_conditions", ""), 200),
        clean_record_field(v.get("notes", ""), 200),
        clean_record_field(v.get("smoking_habit", ""), 50),
        clean_record_field(v.get("drinking_habit", ""), 50),
    ])


def next_vitals_id():
    with _vitals_lock:
        result = run_vitals_command("next-id")
        return safe_int(result.stdout.strip(), 1) if result and result.returncode == 0 else 1


def save_vitals_record(v):
    line = serialize_vitals_record(v)
    with _vitals_lock:
        result = run_vitals_command("save", line)
        return bool(result and result.returncode == 0)


def find_vitals_for_patient_doctor(patient_id, doctor_id):
    """
    Return the most recent vitals for this patient.
    Vitals are patient-level history — tries the specific doctor pair first
    (most relevant for current consultation), then falls back to any prior
    vitals for the patient regardless of doctor.
    This ensures the receptionist form is always pre-filled with real data.
    """
    with _vitals_lock:
        result = run_vitals_command("find-patient-doctor", patient_id, doctor_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_vitals_line(result.stdout.strip())
    # Fallback: return the most recent vitals for this patient from any doctor visit
    return find_vitals_for_patient(patient_id)

def find_vitals_for_patient(patient_id):
    """Return the most recent vitals record for this patient (any doctor), or None."""
    with _vitals_lock:
        result = run_vitals_command("find-patient", patient_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_vitals_line(result.stdout.strip())
    return None

def get_all_vitals_dict():
    """
    Returns a dict mapping patient_id -> vitals_dict (latest record for each patient).

    Vitals are patient-level health history — a patient's blood pressure, temperature,
    weight and other measurements are relevant regardless of which doctor they are
    currently seeing. The receptionist should see 'Update Vitals' for any patient
    who has had vitals recorded in any prior visit, not just visits to the same doctor.

    The vitals record still stores doctor_id for consultation reference, but the
    'has vitals' check is patient-scoped.
    """
    mapping = {}
    with _vitals_lock:
        result = run_vitals_command("list-all")
    if result and result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if not line.strip(): continue
            v = parse_vitals_line(line)
            # Keep latest record per patient (list-all is ordered by vitals_id ascending,
            # so later entries overwrite earlier ones — last write wins = most recent)
            if v: mapping[v["patient_id"]] = v
    return mapping

def get_doctor_vitals_dict(doctor_id):
    """
    Returns a dict mapping patient_id -> vitals_dict for patients in this doctor's queue.
    Vitals are patient-level history — fetches the latest record per patient regardless
    of which doctor previously recorded it, since measurements like BP and temperature
    are clinically relevant across all consultations.
    """
    mapping = {}
    with _vitals_lock:
        result = run_vitals_command("list-all")
    if result and result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if not line.strip(): continue
            v = parse_vitals_line(line)
            # Keep latest record per patient (ascending vitals_id, so last wins)
            if v: mapping[v["patient_id"]] = v
    return mapping


# ── PRESCRIPTION HELPERS ──

def run_prescription_command(*args):
    try:
        return subprocess.run(
            [PRESCRIPTION_EXE, *[str(a) for a in args]],
            capture_output=True, text=True, cwd=BASE_DIR
        )
    except FileNotFoundError:
        return None


def parse_prescription_header_line(line):
    """Parse a header line (not starting with MED|). Returns dict or None."""
    line = line.strip()
    if not line or line.startswith("MED|"):
        return None
    data = line.split("|")
    if len(data) < 5:
        return None
    return {
        "prescription_id":   safe_int(data[0]),
        "appointment_id":    safe_int(data[1]),
        "patient_id":        safe_int(data[2]),
        "doctor_id":         safe_int(data[3]),
        "date":              data[4].strip(),
        "diagnosis_summary": data[5].strip() if len(data) > 5 else "",
        "advice_notes":      data[6].strip() if len(data) > 6 else "",
    }


def parse_medicine_line(line):
    """Parse a MED| prefixed line. Returns dict or None."""
    line = line.strip()
    if not line.startswith("MED|"):
        return None
    data = line.split("|")
    if len(data) < 8:
        data += [""] * (8 - len(data))
    return {
        "prescription_id": safe_int(data[1]),
        "medicine_name":   data[2].strip(),
        "morning":         data[3].strip(),
        "afternoon":       data[4].strip(),
        "night":           data[5].strip(),
        "days":            data[6].strip(),
        "instructions":    data[7].strip(),
    }


def serialize_prescription_header(rx):
    """Serialise prescription header (without MED| prefix) for C save command."""
    return "|".join([
        str(rx.get("prescription_id", 0)),
        str(rx.get("appointment_id", 0)),
        str(rx.get("patient_id", 0)),
        str(rx.get("doctor_id", 0)),
        clean_record_field(rx.get("date", ""), 20),
        clean_record_field(rx.get("diagnosis_summary", ""), 400),
        clean_record_field(rx.get("advice_notes", ""), 400),
    ])


def serialize_medicine_row(med, prescription_id):
    """Serialise one medicine row. C will prepend MED| when saving."""
    return "|".join([
        str(prescription_id),
        clean_record_field(med.get("medicine_name", ""), 100),
        clean_record_field(med.get("morning", "No"), 8),
        clean_record_field(med.get("afternoon", "No"), 8),
        clean_record_field(med.get("night", "No"), 8),
        clean_record_field(str(med.get("days", "1")), 8),
        clean_record_field(med.get("instructions", ""), 200),
    ])


def next_prescription_id():
    with _prescription_lock:
        result = run_prescription_command("next-id")
        return safe_int(result.stdout.strip(), 1) if result and result.returncode == 0 else 1


def save_prescription(appointment_id, patient_id, doctor_id, date,
                      diagnosis_summary, advice_notes, medicines):
    """
    Save a full prescription: one header + N medicine rows.
    Returns the new prescription_id on success, or 0 on failure.
    medicines: list of dicts with keys: medicine_name, morning, afternoon,
               night, days, instructions
    """
    rx_id = next_prescription_id()
    header = {
        "prescription_id":   rx_id,
        "appointment_id":    appointment_id,
        "patient_id":        patient_id,
        "doctor_id":         doctor_id,
        "date":              date,
        "diagnosis_summary": diagnosis_summary,
        "advice_notes":      advice_notes,
    }
    header_line = serialize_prescription_header(header)
    with _prescription_lock:
        result = run_prescription_command("save-header", header_line)
        if not result or result.returncode != 0:
            return 0
        for med in (medicines or []):
            med_line = serialize_medicine_row(med, rx_id)
            run_prescription_command("save-med", med_line)
    return rx_id


def find_prescription_by_appointment(appointment_id):
    """Return (header_dict, [medicine_dicts]) or (None, [])."""
    with _prescription_lock:
        result = run_prescription_command("find-appointment", appointment_id)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return None, []
    header = parse_prescription_header_line(result.stdout.strip())
    if not header:
        return None, []
    meds = []
    with _prescription_lock:
        result2 = run_prescription_command("find-meds", header["prescription_id"])
    if result2 and result2.returncode == 0:
        for line in result2.stdout.splitlines():
            med = parse_medicine_line(line)
            if med:
                meds.append(med)
    return header, meds


def _find_prescription_by_id(prescription_id):
    """
    Find a prescription header and its medicines by prescription_id.
    Returns (header_dict, [medicine_dicts]) or (None, []).
    """
    with _prescription_lock:
        result = run_prescription_command("find-meds", prescription_id)
    meds = []
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            med = parse_medicine_line(line)
            if med:
                meds.append(med)
    # Scan prescriptions.txt for the header matching this prescription_id
    try:
        with _prescription_lock:
            with open(PRESCRIPTION_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("MED|"):
                        continue
                    header = parse_prescription_header_line(line)
                    if header and header["prescription_id"] == int(prescription_id):
                        return header, meds
    except FileNotFoundError:
        pass
    return None, []


# ── PRESCRIPTION PDF ──

def build_prescription_pdf(rx_header, rx_medicines, patient, doctor, vitals=None):
    """
    Build a formatted prescription PDF using ReportLab.
    Returns bytes of the PDF.
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    story = []

    # ── Clinic header ──
    clinic_style = ParagraphStyle('ClinicHeader', fontSize=18, fontName='Helvetica-Bold',
                                   textColor=colors.HexColor('#1E3A5F'), spaceAfter=4)
    story.append(Paragraph("HEALTHDESK CLINIC", clinic_style))
    story.append(Paragraph("Prescription", styles['Normal']))
    story.append(Spacer(1, 0.4*cm))

    # ── Horizontal rule ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#2563EB')))
    story.append(Spacer(1, 0.3*cm))

    # ── Date + Prescription ID ──
    date_str = rx_header.get("date", "")
    parsed_date = parse_iso_date(date_str)
    printable_date = parsed_date.strftime("%d-%m-%Y") if parsed_date else date_str
    story.append(Paragraph(f"Date: {printable_date}    |    Prescription #: {rx_header.get('prescription_id', '')}", styles['Normal']))
    story.append(Spacer(1, 0.4*cm))

    # ── Patient details ──
    story.append(Paragraph("PATIENT DETAILS", ParagraphStyle('SectionHead', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#0D7377'), spaceAfter=4)))
    pat_data = [
        ["Name", patient.get("name", ""), "Age", patient.get("age", "")],
        ["Gender", patient.get("gender", ""), "Dept.", patient.get("department", "")],
    ]
    pat_table = Table(pat_data, colWidths=[3*cm, 7*cm, 2.5*cm, 5*cm])
    pat_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(pat_table)
    story.append(Spacer(1, 0.3*cm))

    # ── Doctor details ──
    story.append(Paragraph("CONSULTING DOCTOR", ParagraphStyle('SectionHead2', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#0D7373'), spaceAfter=4)))
    doc_data = [["Name", doctor.get("name", ""), "Dept.", doctor.get("department", "")]]
    doc_table = Table(doc_data, colWidths=[3*cm, 7*cm, 2.5*cm, 5*cm])
    doc_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(doc_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.3*cm))

    # ── Vitals (if available) ──
    if vitals:
        story.append(Paragraph("VITALS", ParagraphStyle('VitalsHead', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#B45309'), spaceAfter=4)))
        vitals_data = [
            ["Temp.", vitals.get("temperature", "\u2014") + " \u00b0F",
             "BP", f"{vitals.get('bp_systolic','\u2014')}/{vitals.get('bp_diastolic','\u2014')} mmHg"],
            ["Pulse", vitals.get("pulse_rate", "\u2014") + " bpm",
             "SpO2", vitals.get("oxygen_level", "\u2014") + " %"],
            ["Weight", vitals.get("weight", "\u2014") + " kg",
             "Sugar", vitals.get("sugar_level", "\u2014") or "Not recorded"],
        ]
        vt = Table(vitals_data, colWidths=[2.5*cm, 5*cm, 2.5*cm, 7.5*cm])
        vt.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(vt)

        if vitals.get("allergy_conditions"):
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(
                f"ALLERGIES: {vitals['allergy_conditions']}",
                ParagraphStyle('Allergy', fontSize=10, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#B91C1C'), backColor=colors.HexColor('#FEF2F2'),
                               borderPadding=4)
            ))

        if vitals.get("health_conditions"):
            story.append(Paragraph(
                f"Existing Conditions: {vitals['health_conditions']}",
                ParagraphStyle('HealthCond', fontSize=10, fontName='Helvetica')
            ))

        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.3*cm))

    # ── Diagnosis ──
    story.append(Paragraph("DIAGNOSIS", ParagraphStyle('DiagHead', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#1E3A5F'), spaceAfter=4)))
    story.append(Paragraph(rx_header.get("diagnosis_summary", ""), styles['Normal']))
    story.append(Spacer(1, 0.4*cm))

    # ── Medicines table ──
    if rx_medicines:
        story.append(Paragraph("MEDICINES", ParagraphStyle('MedsHead', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#1E3A5F'), spaceAfter=4)))
        med_header = [["#", "Medicine", "Morning", "Afternoon", "Night", "Days", "Instructions"]]
        med_rows = [
            [str(i+1), m.get("medicine_name",""), m.get("morning",""),
             m.get("afternoon",""), m.get("night",""),
             m.get("days",""), m.get("instructions","")]
            for i, m in enumerate(rx_medicines)
        ]
        med_data = med_header + med_rows
        med_table = Table(med_data, colWidths=[1*cm, 5*cm, 2*cm, 2*cm, 2*cm, 1.5*cm, 4*cm])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A5F')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F2F4F7')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D1D5DB')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(med_table)
        story.append(Spacer(1, 0.4*cm))

    # ── Advice ──
    if rx_header.get("advice_notes"):
        story.append(Paragraph("ADVICE / NOTES", ParagraphStyle('AdviceHead', fontSize=11, fontName='Helvetica-Bold', textColor=colors.HexColor('#1E3A5F'), spaceAfter=4)))
        story.append(Paragraph(rx_header["advice_notes"], styles['Normal']))
        story.append(Spacer(1, 0.4*cm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#2563EB')))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph("Doctor's Signature: _______________________", styles['Normal']))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("Thank you for visiting HealthDesk Clinic.", ParagraphStyle('Footer', fontSize=9, fontName='Helvetica', textColor=colors.grey)))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def _write_all_bill_records_unlocked(bills):
    lines = [serialize_bill_record(bill) for bill in bills]
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    result = subprocess.run(
        [BILLING_EXE, "write-all"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )
    if not result or result.returncode != 0:
        raise RuntimeError("billing command failed: write-all")


def write_all_bill_records(bills):
    with _billing_lock:
        _write_all_bill_records_unlocked(bills)


def update_bill_record(updated_bill):
    with _billing_lock:
        line = serialize_bill_record(updated_bill)
        result = run_billing_command("update", updated_bill["bill_id"], line)
        return bool(result and result.returncode == 0)


def find_bill_by_razorpay_order_id(order_id):
    order_id = str(order_id or "").strip()
    if not order_id:
        return None
    result = run_billing_command("find-order", order_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_bill_line(result.stdout.strip())
    return next(
        (bill for bill in read_bills() if bill.get("razorpay_order_id") == order_id),
        None
    )


def build_bill_preview_text(bill):
    line = serialize_bill_record(bill)
    result = run_billing_command("preview", line)
    if result and result.returncode == 0:
        return result.stdout.rstrip("\n")
    raise RuntimeError("billing command failed: preview")


def build_bill_pdf(bill):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 40
    right = width - 40
    y = height - 48

    def ensure_space(lines_needed=1):
        nonlocal y
        if y < 70 + (lines_needed * 16):
            pdf.showPage()
            y = height - 48

    def text_line(value="", size=10, bold=False, gap=14):
        nonlocal y
        ensure_space()
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(left, y, str(value))
        y -= gap

    def rule():
        nonlocal y
        ensure_space()
        pdf.setLineWidth(0.6)
        pdf.line(left, y, right, y)
        y -= 12

    printable_date = bill["date"]
    parsed_date = parse_iso_date(bill["date"])
    if parsed_date:
        printable_date = parsed_date.strftime("%d-%m-%Y")

    line_items = [{"name": "Doctor Fee", "price": bill["doctor_fee"]}]
    line_items.extend(bill["treatments"])
    line_items.extend(bill["lab_tests"])
    if bill["medicine_total"]:
        line_items.append({"name": "Medicines", "price": bill["medicine_total"]})

    pdf.setTitle(f"HealthDesk Bill {bill['bill_id']}")
    text_line("HEALTHDESK CLINIC", size=16, bold=True, gap=18)
    text_line("Billing Summary", size=11, gap=18)
    rule()
    text_line(f"Bill ID: {bill['bill_id']}", bold=True)
    text_line(f"Date: {printable_date}")
    text_line(f"Patient ID: {bill['patient_id']}")
    text_line(f"Patient Name: {bill['name']}")
    text_line(f"Age / Gender: {bill['age']} / {bill['gender']}")
    text_line(f"Doctor: {bill['doctor']}")
    text_line(f"Department: {bill['department']}")
    rule()
    text_line("Bill Details", size=11, bold=True, gap=18)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Description")
    pdf.drawRightString(right, y, "Amount (Rs)")
    y -= 14
    pdf.setFont("Helvetica", 10)
    for item in line_items:
        ensure_space()
        pdf.drawString(left, y, item["name"])
        pdf.drawRightString(right, y, f"{item['price']:.0f}")
        y -= 14
    rule()
    text_line(f"Total: Rs {bill['total']:.0f}", size=12, bold=True, gap=18)
    text_line(f"Payment Status: {bill['status']}", bold=True)
    payment_status = str(bill.get("status", "")).upper()
    if payment_status in {"PAID", "REFUNDED"} and bill.get("payment_method"):
        method_label = "Payment Method" if payment_status == "PAID" else "Original Payment Method"
        text_line(f"{method_label}: {payment_method_label(bill.get('payment_method'))}")
        if bill.get("razorpay_payment_id"):
            text_line(f"Payment Reference: {bill['razorpay_payment_id']}")
        if bill.get("paid_at"):
            text_line(f"Paid On: {payment_timestamp_label(bill.get('paid_at'))}")
    if payment_status == "WAIVED":
        text_line("This bill was waived by the clinic.")
    elif payment_status == "REFUNDED":
        text_line("This bill was refunded by the clinic.")
    if bill["medicine_notes"]:
        text_line("Medicine Notes:", bold=True)
        for note_line in re.findall(r".{1,85}(?:\s+|$)", bill["medicine_notes"]) or [bill["medicine_notes"]]:
            cleaned = note_line.strip()
            if cleaned:
                text_line(cleaned)
    rule()
    text_line("Thank you for visiting HealthDesk.", size=10)
    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def create_bill_record(patient, doctor, bill_date, treatment_codes=None, lab_test_codes=None,
                       medicine_amount=0, medicine_notes="", payment_status="PENDING",
                       appointment_id=0):
    catalog, treatment_map, lab_test_map = get_pricing_maps()
    selected_treatments = [
        {
            "name": treatment_map[code]["name"],
            "price": float(treatment_map[code]["price"])
        }
        for code in (treatment_codes or [])
        if code in treatment_map
    ]
    selected_lab_tests = [
        {
            "name": lab_test_map[code]["name"],
            "price": float(lab_test_map[code]["price"])
        }
        for code in (lab_test_codes or [])
        if code in lab_test_map
    ]
    doctor_fee = float(catalog.get("doctor_fees", {}).get(doctor["department"], 0))
    medicine_total = float(medicine_amount or 0)
    treatment_total = sum(item["price"] for item in selected_treatments)
    lab_total = sum(item["price"] for item in selected_lab_tests)

    safe_medicine_notes = clean_record_field(medicine_notes)
    payment_status = clean_record_field(payment_status).upper()
    if payment_status not in ALLOWED_PAYMENT_STATUSES:
        payment_status = "PENDING"

    return {
        "bill_id": generate_bill_id(),
        "date": bill_date,
        "patient_id": int(patient["id"]),
        "name": patient["name"],
        "age": int(patient["age"]),
        "gender": patient["gender"],
        "doctor": doctor["name"],
        "department": doctor["department"],
        "doctor_fee": doctor_fee,
        "treatment_total": treatment_total,
        "lab_total": lab_total,
        "medicine_total": medicine_total,
        "total": doctor_fee + treatment_total + lab_total + medicine_total,
        "status": payment_status,
        "doctor_id": int(doctor["id"]),
        "treatments": selected_treatments,
        "lab_tests": selected_lab_tests,
        "medicine_notes": safe_medicine_notes,
        "appointment_id": int(appointment_id or 0),
        "razorpay_order_id": "",
        "razorpay_payment_id": "",
        "payment_method": "counter" if payment_status == "PAID" else "",
        "paid_at": iso_now() if payment_status == "PAID" else "",
        "initiated_at": ""
    }

def is_valid_phone(phone):
    result = _run_utils_command("valid-phone", str(phone or ""))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("utils command failed: valid-phone")

def is_valid_age(age):
    result = _run_utils_command("valid-age", str(age or ""))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("utils command failed: valid-age")

def load_appointment_slots(doctor_id, selected_date):
    slots = []
    if not doctor_id or not selected_date:
        return slots

    result = run_appointment_command("slots", str(doctor_id), selected_date)
    if not result:
        return slots

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        data = line.strip().split("|")
        if len(data) == 3 and data[0] == "SLOT":
            slots.append({"time": data[1], "state": data[2]})

    if doctor_is_blocked_for_date(doctor_id, selected_date):
        slots = [
            {
                "time": slot["time"],
                "state": "Blocked" if slot["state"] == "Available" else slot["state"]
            }
            for slot in slots
        ]

    adjusted_slots = []
    for slot in slots:
        state = slot["state"]
        if state == "Available" and is_slot_in_past(selected_date, slot["time"]):
            state = "Elapsed"
        adjusted_slots.append({"time": slot["time"], "state": state})

    return adjusted_slots


def slot_is_available(doctor_id, selected_date, time_slot):
    return any(
        slot["time"] == time_slot and slot["state"] == "Available"
        for slot in load_appointment_slots(doctor_id, selected_date)
    )

def run_appointment_command(*args):
    with _appointment_lock:
        try:
            return subprocess.run(
                [APPOINTMENT_EXE, *[str(arg) for arg in args]],
                capture_output=True,
                text=True,
                cwd=BASE_DIR
            )
        except FileNotFoundError:
            return None


def parse_reschedule_result(result):
    if not result or result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    parts = output.split("|")
    if len(parts) >= 5 and parts[0] == "RESCHEDULED":
        return {
            "old_appointment_id": safe_int(parts[1], 0),
            "new_appointment_id": safe_int(parts[2], 0),
            "new_date": parts[3],
            "new_time": parts[4],
        }
    return None

def parse_iso_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def slot_datetime(selected_date, time_slot):
    parsed_date = parse_iso_date(selected_date)
    parsed_time = parse_slot_time(time_slot)
    if not parsed_date or parsed_time == datetime.min.time():
        return None
    return datetime.combine(parsed_date, parsed_time)


def is_slot_in_past(selected_date, time_slot):
    result = run_appointment_command("slot-in-past", selected_date, time_slot)
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("appointment command failed: slot-in-past")

def is_future_or_today(date_str):
    result = _run_utils_command("future-or-today", str(date_str or ""))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("utils command failed: future-or-today")


def format_human_date(date_str):
    result = _run_utils_command("format-date", str(date_str or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: format-date")


def format_human_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = None
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                parsed = datetime.strptime(str(value or ""), pattern)
                break
            except ValueError:
                continue
    if not parsed:
        return value or ""
    return parsed.strftime("%A, %d %B %Y at %I:%M %p").replace(" 0", " ")


def format_amount(amount):
    try:
        return f"Rs {float(amount):,.0f}"
    except (TypeError, ValueError):
        return "Rs 0"


def payment_method_label(method):
    labels = {
        "upi": "Paid via UPI",
        "card": "Paid by Card",
        "netbanking": "Paid by Netbanking",
        "wallet": "Paid by Wallet",
        "counter": "Paid at counter",
        "razorpay": "Paid online"
    }
    method = str(method or "").lower()
    return labels.get(method, method.replace("_", " ").title() if method else "Payment recorded")


def payment_timestamp_label(value):
    return format_human_datetime(value) if value else ""


def preview_text(value, length=80):
    text = str(value or "").strip()
    if len(text) <= length:
        return text
    return f"{text[:length].rstrip()}..."


def remaining_time_label(expires_at):
    result = _run_utils_command("remaining-time", str(expires_at or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: remaining-time")


def parse_iso_datetime(value):
    if isinstance(value, datetime):
        return value
    result = _run_utils_command("parse-datetime", str(value or ""))
    if result and result.returncode == 0:
        text = result.stdout.strip()
        if not text:
            return None
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    raise RuntimeError("utils command failed: parse-datetime")


def iso_now():
    result = _run_utils_command("iso-now")
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: iso-now")


def revert_stale_initiated_payments():
    result = run_billing_command("revert-stale")
    if result and result.returncode == 0:
        return safe_int(result.stdout.strip(), 0) > 0
    raise RuntimeError("billing command failed: revert-stale")


def apply_reception_bill_status_update(bill, target_status):
    target_status = str(target_status or "").upper()
    current_status = str(bill.get("status", "")).upper()

    if target_status == "WAIVED":
        if current_status != "PENDING":
            return False, "Only pending bills can be waived."
        bill["status"] = "WAIVED"
        bill["razorpay_order_id"] = ""
        bill["razorpay_payment_id"] = ""
        bill["payment_method"] = ""
        bill["paid_at"] = ""
        bill["initiated_at"] = ""
        return True, f"Bill #{bill['bill_id']} was marked as waived."

    if target_status == "REFUNDED":
        if current_status != "PAID":
            return False, "Only paid bills can be marked as refunded."
        payment_id = bill.get("razorpay_payment_id", "")
        if payment_id:
            from payment_service import initiate_refund
            ok_refund, err_refund = initiate_refund(payment_id, bill.get("total", 0))
            if not ok_refund:
                return False, (f"Razorpay refund failed: {err_refund}. "
                               "Refund manually in Razorpay dashboard, then mark as refunded here.")
        bill["status"] = "REFUNDED"
        bill["razorpay_order_id"] = ""
        bill["initiated_at"] = ""
        return True, f"Bill #{bill['bill_id']} marked as refunded and refund initiated."

    return False, "Unsupported bill status update."


def parse_booked_appointment_id(result):
    if not result or result.returncode != 0:
        return 0
    data = result.stdout.strip().split("|")
    if len(data) >= 2 and data[0] == "BOOKED":
        return safe_int(data[1])
    return 0


def is_clinic_hours_now():
    start_hour = safe_int(os.environ.get("CLINIC_HOURS_START", "9"), 9)
    end_hour = safe_int(os.environ.get("CLINIC_HOURS_END", "18"), 18)
    current_hour = datetime.now().hour
    return start_hour <= current_hour < end_hour


def get_alternative_doctor_for_slot(department, appointment_date, time_slot, excluded_doctor_id):
    for doctor in suggest_doctors_by_department(department):
        if int(doctor["id"]) == int(excluded_doctor_id):
            continue
        slots = load_appointment_slots(doctor["id"], appointment_date)
        if any(slot["time"] == time_slot and slot["state"] == "Available" for slot in slots):
            return doctor
    return None

def reassign_appointment_to_alternative(appointment):
    patient = find_patient_by_id(appointment["patient_id"])
    if not patient:
        return None

    alt_doctor = get_alternative_doctor_for_slot(
        patient["department"],
        appointment["date"],
        appointment["time_slot"],
        appointment["doctor_id"]
    )
    if not alt_doctor:
        return None

    cancel_result = run_appointment_command("cancel", appointment["appointment_id"])
    if cancel_result.returncode != 0:
        return None

    book_result = run_appointment_command(
        "book",
        appointment["patient_id"],
        alt_doctor["id"],
        appointment["date"],
        appointment["time_slot"]
    )
    output = book_result.stdout.strip().split("|")
    if book_result.returncode == 0 and len(output) >= 2 and output[0] == "BOOKED":
        return {
            "old_appointment_id": appointment["appointment_id"],
            "new_appointment_id": output[1],
            "new_doctor_id": alt_doctor["id"],
            "new_doctor_name": alt_doctor["name"]
        }
    return None

def auto_reassign_unavailable_doctor_appointments(doctor_id):
    result = run_appointment_command("auto-reassign", int(doctor_id))
    if not result or result.returncode != 0:
        raise RuntimeError("appointment command failed: auto-reassign")
    reassigned = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 5 and parts[0] == "REASSIGNED":
            reassigned.append({
                "old_appointment_id": safe_int(parts[1]),
                "new_appointment_id": safe_int(parts[2]),
                "new_doctor_id": safe_int(parts[3]),
                "new_doctor_name": parts[4],
            })
    return reassigned

def enrich_appointment_workflow_status(appointment):
    updated = dict(appointment)
    if appointment["status"] == "Booked":
        appointment_day = parse_iso_date(appointment["date"])
        if appointment_day and appointment_day <= date.today():
            updated["workflow_status"] = "Waiting"
        else:
            updated["workflow_status"] = "Booked"
    else:
        updated["workflow_status"] = appointment["status"]
    return updated

def get_suggested_doctors(selected_department, selected_doctor, selected_date):
    suggested_doctors = []

    if not selected_department:
        return suggested_doctors

    for doc in suggest_doctors_by_department(selected_department):
        if str(doc["id"]) == str(selected_doctor):
            continue

        available_count = len([
            slot for slot in load_appointment_slots(doc["id"], selected_date)
            if slot["state"] == "Available"
        ])

        if available_count > 0:
            suggested_doctors.append({
                "id": doc["id"],
                "name": doc["name"],
                "department": doc["department"],
                "available_slots": available_count
            })

    return suggested_doctors


def doctor_available_slots_for_date(doctor_id, selected_date):
    return [
        slot["time"]
        for slot in load_appointment_slots(doctor_id, selected_date)
        if slot["state"] == "Available" and not pending_slot_exists(doctor_id, selected_date, slot["time"])
    ]


def get_reassignment_candidates(department, selected_date, excluded_doctor_id=None):
    candidates = []
    if not department or not selected_date:
        return candidates

    for doctor in get_doctors():
        if department and doctor["department"] != department:
            continue
        if excluded_doctor_id is not None and int(doctor["id"]) == int(excluded_doctor_id):
            continue

        available_slots = doctor_available_slots_for_date(doctor["id"], selected_date)
        if not available_slots:
            continue

        candidates.append({
            "id": doctor["id"],
            "name": doctor["name"],
            "department": doctor["department"],
            "daily_status": doctor["daily_status"],
            "current_status_label": doctor["current_status_label"],
            "available_slots": available_slots
        })

    candidates.sort(key=lambda item: (item["name"], item["id"]))
    return candidates

def add_patient_to_queue(patient_id, doctor_id=None):
    command = [str(patient_id)]
    if doctor_id is not None:
        command.append(str(doctor_id))
    result = run_queue_command(*command)
    if not result:
        return None

    output = result.stdout.strip().split("|")
    if len(output) >= 3 and result.returncode == 0:
        return {
            "token": output[0],
            "doctor_id": output[1],
            "priority": output[2]
        }

    return None

def update_waiting_queue_status(patient_id, doctor_id=None, status="Completed"):
    patient_id = safe_int(patient_id)
    doctor_id = safe_int(doctor_id, 0) if doctor_id is not None else 0
    result = run_queue_command("update-waiting", patient_id, doctor_id, status)
    return bool(result and result.returncode == 0)




def reconcile_waiting_queue_entries():
    """
    Reconciles all Waiting queue entries against the appointment file.
    Uses the fixed queue.exe reconcile which correctly keeps Waiting entries
    when a Booked appointment exists, only applying terminal status if no
    Booked appointment is found for that patient+doctor pair.
    """
    result = run_queue_command("reconcile")
    if not result or result.returncode != 0:
        return read_queue()  # Fallback to raw read if reconcile fails
    rows = []
    for line in result.stdout.splitlines():
        data = line.strip().split("|")
        if len(data) < 5:
            continue
        rows.append({
            "token": int(data[0]),
            "patient_id": int(data[1]),
            "doctor_id": int(data[2]),
            "priority": data[3],
            "status": data[4],
        })
    return rows

@app.before_request
def require_login():
    public_endpoints = {"dashboard", "login", "patient_login", "patient_request_otp", "patient_verify_otp", "new_patient_request", "new_patient_slots", "new_patient_submit", "payment_webhook", "payment_webhook_advance", "static"}
    if request.endpoint in public_endpoints:
        return
    if not is_authenticated():
        if request.endpoint and request.endpoint.startswith("patient_"):
            return redirect(url_for("patient_login"))
        return redirect(url_for("login"))

@app.before_request
def verify_csrf_token():
    if request.endpoint in {"payment_webhook", "payment_webhook_advance"}:
        return
    if request.method != "POST":
        return
    token = session.get("_csrf_token", "")
    submitted = request.form.get("_csrf_token", "")
    if not token or not submitted or not hmac.compare_digest(token, submitted):
        return "Invalid or expired form token.", 400

@app.before_request
def sync_doctor_statuses_before_request():
    if request.endpoint == "static":
        return
    expire_doctor_status_overrides()
    public_endpoints = {"login", "patient_login", "patient_request_otp", "patient_verify_otp", "new_patient_request", "new_patient_slots", "new_patient_submit", "payment_webhook"}
    if request.endpoint in public_endpoints or not is_authenticated():
        return
    sync_doctor_busy_statuses()

@app.context_processor
def inject_auth_state():
    return {
        "is_logged_in": is_authenticated(),
        "current_role": session.get("role", ""),
        "current_user": session.get("username", ""),
        "csrf_token": get_csrf_token,
        "payment_method_label": payment_method_label
    }


def read_queue():
    queue = []
    result = run_queue_command("list")
    if not result or result.returncode != 0:
        raise RuntimeError("queue command failed: list")
    for line in result.stdout.splitlines():
        data = line.strip().split("|")
        if len(data) < 5:
            continue
        queue.append({
            "token": int(data[0]),
            "patient_id": int(data[1]),
            "doctor_id": int(data[2]),
            "priority": data[3],
            "status": data[4]
        })
    return queue


def write_doctor_file(doctors):
    lines = []
    for doctor in doctors:
        lines.append(
            f"{int(doctor['id'])}|{clean_record_field(doctor['name'])}|"
            f"{clean_record_field(doctor['department'])}|{int(doctor['experience'])}|"
            f"{clean_record_field(doctor['daily_status'])}|{clean_record_field(doctor['current_status'])}"
        )
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    result = subprocess.run(
        [DOCTOR_EXE, "write-all"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )
    if not result or result.returncode != 0:
        raise RuntimeError("doctor command failed: write-all")


def load_doctor_status_meta():
    try:
        with open(DOCTOR_STATUS_META_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_doctor_status_meta(meta):
    os.makedirs(os.path.dirname(DOCTOR_STATUS_META_FILE), exist_ok=True)
    with open(DOCTOR_STATUS_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def normalize_doctor_statuses(daily_status, current_status):
    result = run_doctor_command("normalize-status", str(daily_status or ""), str(current_status or ""))
    if result and result.returncode == 0:
        parts = result.stdout.strip().split("|")
        if len(parts) == 2:
            return parts[0], parts[1]
    raise RuntimeError("doctor command failed: normalize-status")


def doctor_current_status_view(daily_status, current_status):
    result = run_doctor_command("status-view", str(daily_status or ""), str(current_status or ""))
    if result and result.returncode == 0:
        parts = result.stdout.strip().split("|")
        if len(parts) == 2:
            return {"current_status_label": parts[0], "current_status_badge": parts[1]}
    raise RuntimeError("doctor command failed: status-view")


def doctor_status_end_date(doctor_id, meta=None):
    meta = meta or load_doctor_status_meta()
    key = str(safe_int(doctor_id))
    expires_on = str((meta.get(key) or {}).get("expires_on", "")).strip()
    return expires_on if parse_iso_date(expires_on) else ""


def doctor_is_blocked_for_date(doctor_id, selected_date, doctor=None, meta=None):
    result = run_doctor_command("is-blocked", int(doctor_id), str(selected_date or ""))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("doctor command failed: is-blocked")


def update_doctor_status_meta(doctor_id, daily_status, current_status, expires_on=None):
    meta = load_doctor_status_meta()
    key = str(safe_int(doctor_id))

    if daily_status in {"Unavailable", "Off"} or current_status == "Emergency":
        effective_expiry = expires_on if parse_iso_date(expires_on) else date.today().isoformat()
        meta[key] = {
            "expires_on": effective_expiry,
            "daily_status": daily_status,
            "current_status": current_status,
            "updated_at": datetime.now().isoformat(timespec="seconds")
        }
    else:
        meta.pop(key, None)

    save_doctor_status_meta(meta)


def expire_doctor_status_overrides():
    meta = load_doctor_status_meta()
    if not meta:
        return False

    today_str = date.today().isoformat()
    expired_ids = [
        safe_int(doctor_id)
        for doctor_id, info in meta.items()
        if str((info or {}).get("expires_on", "")) < today_str
    ]
    if not expired_ids:
        return False

    changed = False
    for doctor_id in expired_ids:
        result = run_doctor_command("status", doctor_id, "Available", "Free")
        if result and result.returncode == 0:
            changed = True

    if not changed:
        return False

    for doctor_id in expired_ids:
        meta.pop(str(doctor_id), None)
    save_doctor_status_meta(meta)
    return True

def process_queue(queue):

    queue.sort(key=lambda x: (x["priority"] != "Urgent", x["token"]))

    waiting = []
    completed = []

    for q in queue:
        if q["status"] == "Waiting":
            waiting.append(q)
        elif q["status"] == "Completed":
            completed.append(q)

    next_patient = waiting[0] if waiting else None

    return queue, next_patient, len(waiting), len(completed)





def build_appointment_action_groups(appointments, doctors):
    doctor_map = {doctor["id"]: doctor for doctor in doctors}
    groups = {}

    for appointment in appointments:
        doctor = doctor_map.get(appointment["doctor_id"])
        group_key = appointment["doctor_id"]
        if group_key not in groups:
            groups[group_key] = {
                "doctor_id": appointment["doctor_id"],
                "doctor_name": doctor["name"] if doctor else f"Doctor #{appointment['doctor_id']}",
                "department": doctor["department"] if doctor else "",
                "appointments": []
            }
        groups[group_key]["appointments"].append(appointment)

    ordered_groups = list(groups.values())
    for group in ordered_groups:
        group["appointments"].sort(key=lambda item: item["appointment_id"], reverse=True)

    ordered_groups.sort(key=lambda group: (group["department"], group["doctor_name"]))
    return ordered_groups

def count_patients():
    result = run_patient_command("count")
    if result and result.returncode == 0:
        return safe_int(result.stdout.strip(), 0)
    return len(read_patients())
    
def count_available_doctors():
    result = run_doctor_command("count-available")
    if result and result.returncode == 0:
        return safe_int(result.stdout.strip(), 0)
    return sum(
        1 for doctor in get_doctors()
        if doctor["daily_status"] == "Available" and doctor["current_status"] == "Free"
    )

def doctor_availability_view(daily_status, current_status):
    daily, current = normalize_doctor_statuses(daily_status, current_status)

    if daily == "Off":
        return {
            "availability_label": "Not On Duty",
            "availability_badge": "waived"
        }
    if daily == "Unavailable":
        return {
            "availability_label": "Unavailable Today",
            "availability_badge": "cancelled"
        }
    if current == "Emergency":
        return {
            "availability_label": "Emergency",
            "availability_badge": "cancelled"
        }
    if current == "Busy":
        return {
            "availability_label": "Busy",
            "availability_badge": "pending"
        }
    return {
        "availability_label": "Free",
        "availability_badge": "booked"
    }


def get_doctors():
    doctors = []
    meta = load_doctor_status_meta()
    result = run_doctor_command("view")
    try:
        lines = result.stdout.splitlines() if result and result.returncode == 0 else []
        if not lines:
            doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
            with open(doctor_file, "r", encoding="utf-8") as f:
                lines = list(f)
        for line in lines:
            record = parse_doctor_record_line(line)
            if not record:
                continue
            daily_status, current_status = normalize_doctor_statuses(record["daily_status"], record["current_status"])
            availability = doctor_availability_view(daily_status, current_status)
            current_view = doctor_current_status_view(daily_status, current_status)
            status_until = doctor_status_end_date(record["id"], meta=meta)
            doctors.append({
                "id": int(record["id"]),
                "name": record["name"],
                "department": record["department"],
                "experience": int(record["experience"]),
                "daily_status": daily_status,
                "current_status": current_status,
                "show_live_status": daily_status == "Available",
                "status_until": status_until,
                "status_until_label": format_human_date(status_until) if status_until else "",
                **availability,
                **current_view
            })
    except:
        pass
    return doctors


def doctor_has_live_workload(doctor_id):
    doctor_id = safe_int(doctor_id)
    if doctor_id <= 0:
        return False

    if any(
        item["doctor_id"] == doctor_id and item["status"] == "Waiting"
        for item in read_queue()
    ):
        return True

    return any(
        appointment["doctor_id"] == doctor_id
        and appointment["status"] in {"Booked", "No-show"}
        and is_consultation_day_reached(appointment)
        for appointment in read_appointments()
    )


def sync_doctor_busy_statuses():
    result = run_doctor_command("sync-busy")
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("doctor command failed: sync-busy")

def suggest_doctors_by_department(department):
    result = run_doctor_command("suggest", department)
    if not result:
        return []

    doctors = []
    for line in result.stdout.strip().split("\n"):
        if not line or line == "NoDoctorFound":
            continue

        record = parse_doctor_record_line(line)
        if not record:
            continue

        doctors.append({
            "id": record["id"],
            "name": record["name"],
            "department": record["department"],
            "experience": record["experience"],
            "daily_status": record["daily_status"],
            "current_status": record["current_status"]
        })

    return doctors

def read_appointments():
    return read_appointment_file()


def parse_appointment_datetime(appointment):
    try:
        return datetime.strptime(
            f"{appointment['date']} {appointment['time_slot']}",
            "%Y-%m-%d %I:%M %p"
        )
    except (KeyError, TypeError, ValueError):
        parsed_date = parse_iso_date(appointment.get("date"))
        if parsed_date:
            return datetime.combine(parsed_date, datetime.min.time())
        return datetime.min


def appointment_date_value(appointment):
    return parse_iso_date(appointment.get("date"))


def should_show_in_appointments_list(appointment):
    appointment_day = appointment_date_value(appointment)
    if not appointment_day:
        return False
    return date.today() - timedelta(days=1) <= appointment_day <= date.today() + timedelta(days=1)


def find_booked_appointment_for_patient_on_date(patient_id, appointment_date):
    patient_id = safe_int(patient_id)
    result = run_appointment_command("find-booked-patient-date", patient_id, appointment_date)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_appointment_line(result.stdout.strip())
    for appointment in read_appointments():
        if (
            appointment["patient_id"] == patient_id
            and appointment["date"] == appointment_date
            and appointment["status"] == "Booked"
        ):
            return appointment
    return None


def is_consultation_day_reached(appointment):
    appointment_day = parse_iso_date(appointment.get("date"))
    if not appointment_day:
        return False
    return appointment_day <= date.today()


def is_future_appointment(appointment):
    appointment_day = parse_iso_date(appointment.get("date"))
    if not appointment_day:
        return False
    return appointment_day > date.today()


def expire_stale_consultations():
    """
    Marks past-due Booked appointments as No-show and syncs their queue entries.
    Also reconciles any Waiting queue entries that no longer have a valid Booked appointment.
    Does NOT auto-add patients to the queue (use auto_queue_todays_appointments for that).
    """
    appointments = read_appointments()
    queue_rows = read_queue()
    appointments_changed = False
    queue_changed = False

    # Build a map of today-eligible Booked appointments per (patient, doctor) pair.
    # A queue entry is valid if there is ANY Booked appointment for that patient+doctor
    # where the consultation day has been reached (date <= today).
    # We do NOT use the absolute latest appointment because a future Booked appointment
    # would cause is_consultation_day_reached to return False, incorrectly cancelling
    # today's queue entry.
    today_booked_by_pd = {}   # (patient_id, doctor_id) → appointment (today-eligible Booked)
    latest_by_pd = {}         # (patient_id, doctor_id) → appointment (absolute latest, for status sync)

    for appointment in appointments:
        key = (appointment["patient_id"], appointment["doctor_id"])

        # Track absolute latest for status sync (used for non-Booked status propagation)
        cur_latest = latest_by_pd.get(key)
        if cur_latest is None or parse_appointment_datetime(appointment) > parse_appointment_datetime(cur_latest):
            latest_by_pd[key] = appointment

        appointment_day = parse_iso_date(appointment.get("date"))

        # Mark past-day Booked appointments as No-show
        if (
            appointment_day
            and appointment_day < date.today()
            and appointment["status"] == "Booked"
        ):
            result = run_appointment_command("noshow", appointment["appointment_id"])
            if result and result.returncode == 0:
                appointment["status"] = "No-show"
                appointments_changed = True

            for row in queue_rows:
                if (
                    row["patient_id"] == appointment["patient_id"]
                    and row["doctor_id"] == appointment["doctor_id"]
                    and row["status"] == "Waiting"
                ):
                    if update_waiting_queue_status(row["patient_id"], row["doctor_id"], "No-show"):
                        row["status"] = "No-show"
                        queue_changed = True

        # Track today-eligible Booked appointments for queue validation
        if (
            appointment_day
            and appointment["status"] == "Booked"
            and is_consultation_day_reached(appointment)
        ):
            today_booked_by_pd[key] = appointment

    # Reconcile Waiting queue entries
    for row in queue_rows:
        if row["status"] != "Waiting":
            continue

        key = (row["patient_id"], row["doctor_id"])
        today_appt = today_booked_by_pd.get(key)
        latest_appt = latest_by_pd.get(key)

        if today_appt:
            # There IS a today-eligible Booked appointment — keep Waiting, this is valid
            continue
        elif not latest_appt:
            # No appointment at all for this patient+doctor — cancel
            if update_waiting_queue_status(row["patient_id"], row["doctor_id"], "Cancelled"):
                row["status"] = "Cancelled"
                queue_changed = True
        elif latest_appt["status"] != "Booked":
            # Latest appointment has a terminal status — sync to that
            if update_waiting_queue_status(row["patient_id"], row["doctor_id"], latest_appt["status"]):
                row["status"] = latest_appt["status"]
                queue_changed = True
        else:
            # Latest is Booked but in the future (not today-eligible) — keep Waiting
            # The patient was explicitly added to the queue, don't cancel
            continue

    return {
        "appointments_changed": appointments_changed,
        "queue_changed": queue_changed
    }


def auto_queue_todays_appointments():
    """
    Idempotent: adds today's Booked appointments to the queue if not already Waiting.
    Uses a frozenset snapshot of current Waiting pairs — never mutates during iteration.
    Called once per dashboard/queue page load, not on every request.
    """
    queue_rows = read_queue()
    # Build an immutable set of (patient_id, doctor_id) already Waiting
    already_waiting = frozenset(
        (row["patient_id"], row["doctor_id"])
        for row in queue_rows
        if row["status"] == "Waiting"
    )
    appointments = read_appointments()
    today = date.today()
    for appointment in appointments:
        if appointment["status"] != "Booked":
            continue
        appt_day = parse_iso_date(appointment.get("date"))
        if appt_day != today:
            continue
        key = (appointment["patient_id"], appointment["doctor_id"])
        if key in already_waiting:
            continue
        add_patient_to_queue(appointment["patient_id"], doctor_id=appointment["doctor_id"])


def get_latest_patient_appointment(patient_id):
    result = run_appointment_command("list-for-patient", patient_id)
    if result and result.returncode == 0:
        appointments = [
            appointment for appointment in
            (parse_appointment_line(line) for line in result.stdout.splitlines())
            if appointment
        ]
    else:
        appointments = [
            appointment for appointment in read_appointments()
            if appointment["patient_id"] == int(patient_id)
        ]
    if not appointments:
        return None
    appointments.sort(key=parse_appointment_datetime, reverse=True)
    return appointments[0]

def get_latest_completed_patient_appointment(patient_id, doctor_id=None):
    result = run_appointment_command("list-for-patient", patient_id)
    source = (
        [
            appointment for appointment in
            (parse_appointment_line(line) for line in result.stdout.splitlines())
            if appointment
        ]
        if result and result.returncode == 0 else
        read_appointments()
    )
    appointments = [
        appointment for appointment in source
        if appointment["patient_id"] == int(patient_id)
        and appointment["status"] == "Completed"
        and (doctor_id is None or appointment["doctor_id"] == int(doctor_id))
    ]
    if not appointments:
        return None
    appointments.sort(key=parse_appointment_datetime, reverse=True)
    return appointments[0]

def find_appointment_by_id(appointment_id):
    appointment_id = safe_int(appointment_id)
    result = run_appointment_command("find-id", appointment_id)
    if result and result.returncode == 0 and result.stdout.strip():
        return parse_appointment_line(result.stdout.strip())
    return next(
        (
            appointment for appointment in read_appointments()
            if appointment["appointment_id"] == appointment_id
        ),
        None
    )

def doctor_owns_appointment(appointment, doctor_id):
    return bool(appointment) and appointment["doctor_id"] == int(doctor_id)


def get_latest_active_patient_appointment(patient_id, doctor_id=None):
    result = run_appointment_command("list-for-patient", patient_id)
    source = (
        [
            appointment for appointment in
            (parse_appointment_line(line) for line in result.stdout.splitlines())
            if appointment
        ]
        if result and result.returncode == 0 else
        read_appointments()
    )
    appointments = [
        appointment for appointment in source
        if appointment["patient_id"] == int(patient_id)
        and appointment["status"] in {"Booked", "No-show"}
        and (doctor_id is None or appointment["doctor_id"] == int(doctor_id))
    ]
    if not appointments:
        return None
    appointments.sort(key=parse_appointment_datetime, reverse=True)
    return appointments[0]


def resolve_consultation_appointment(patient_id, doctor_id, appointment_id=None):
    appointment = find_appointment_by_id(appointment_id) if appointment_id else None

    if appointment and (
        appointment["patient_id"] != int(patient_id)
        or appointment["doctor_id"] != int(doctor_id)
    ):
        return None

    if appointment and appointment["status"] in {"Booked", "No-show", "Completed"}:
        return appointment

    return get_latest_active_patient_appointment(patient_id, doctor_id=doctor_id)

def doctor_can_access_patient(patient_id, doctor_id):
    patient_id = safe_int(patient_id)
    doctor_id = safe_int(doctor_id)
    if not patient_id or not doctor_id:
        return False

    for appointment in read_appointments():
        if appointment["patient_id"] == patient_id and appointment["doctor_id"] == doctor_id:
            return True

    return any(
        item["patient_id"] == patient_id and item["doctor_id"] == doctor_id
        for item in read_queue()
    )


def get_doctor_patient_options(doctor_id):
    doctor_id = safe_int(doctor_id)
    if doctor_id <= 0:
        return []

    patients_by_id = {patient["id"]: patient for patient in read_patients()}
    doctor_appointments = [
        appointment for appointment in read_appointments()
        if appointment["doctor_id"] == doctor_id
    ]
    queue_by_patient = {
        item["patient_id"]: item
        for item in read_assigned_queue_patients(doctor_id)
    }

    patient_ids = {appointment["patient_id"] for appointment in doctor_appointments}
    patient_ids.update(queue_by_patient.keys())

    options = []
    for patient_id in patient_ids:
        patient = patients_by_id.get(patient_id)
        if not patient:
            continue

        patient_appointments = [
            appointment for appointment in doctor_appointments
            if appointment["patient_id"] == patient_id
        ]
        patient_appointments.sort(key=parse_appointment_datetime, reverse=True)
        latest_appointment = patient_appointments[0] if patient_appointments else None
        active_appointment = next(
            (
                appointment for appointment in patient_appointments
                if appointment["status"] in {"Booked", "No-show"}
            ),
            None
        )
        queue_item = queue_by_patient.get(patient_id)
        navigation_appointment = active_appointment or latest_appointment

        options.append({
            "id": patient["id"],
            "name": patient["name"],
            "phone": patient["phone"],
            "department": patient["department"],
            "priority": patient["priority"],
            "symptoms": patient["symptoms"],
            "latest_status": "Waiting" if queue_item else (latest_appointment["status"] if latest_appointment else ""),
            "latest_date": (navigation_appointment or {}).get("date", ""),
            "appointment_id": (navigation_appointment or {}).get("appointment_id", 0),
            "is_waiting": bool(queue_item),
            "has_active_consultation": bool(active_appointment or queue_item),
            "sort_timestamp": parse_appointment_datetime(navigation_appointment) if navigation_appointment else datetime.min
        })

    options.sort(
        key=lambda item: (
            not item["is_waiting"],
            not item["has_active_consultation"],
            -item["sort_timestamp"].timestamp() if item["sort_timestamp"] != datetime.min else float("inf"),
            item["name"].lower()
        )
    )

    for item in options:
        item.pop("sort_timestamp", None)

    return options


def get_doctor_by_id(doctor_id):
    result = run_doctor_command("get-by-id", doctor_id)
    if result and result.returncode == 0 and result.stdout.strip():
        record = parse_doctor_record_line(result.stdout.strip())
        if record:
            daily_status, current_status = normalize_doctor_statuses(record["daily_status"], record["current_status"])
            availability = doctor_availability_view(daily_status, current_status)
            current_view = doctor_current_status_view(daily_status, current_status)
            status_until = doctor_status_end_date(record["id"])
            return {
                "id": record["id"],
                "name": record["name"],
                "department": record["department"],
                "experience": record["experience"],
                "daily_status": daily_status,
                "current_status": current_status,
                "show_live_status": daily_status == "Available",
                "status_until": status_until,
                "status_until_label": format_human_date(status_until) if status_until else "",
                **availability,
                **current_view
            }
    return next((doctor for doctor in get_doctors() if doctor["id"] == int(doctor_id)), None)


def read_diagnosis_for_patient(patient_id):
    patient_id = int(patient_id)
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    records = []
    try:
        with _diagnosis_lock:
            with open(DIAGNOSIS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    data = line.strip().split("|")
                    if len(data) < 6:
                        continue
                    try:
                        record_patient_id = int(data[1])
                        doctor_id = int(data[2])
                    except ValueError:
                        continue
                    if record_patient_id != patient_id:
                        continue
                    doctor = doctor_map.get(doctor_id, {})
                    records.append({
                        "record_id": safe_int(data[0]),
                        "patient_id": record_patient_id,
                        "doctor_id": doctor_id,
                        "date": data[3],
                        "human_date": format_human_date(data[3]),
                        "doctor_name": doctor.get("name", "Doctor"),
                        "department": doctor.get("department", ""),
                        "diagnosis": data[4],
                        "diagnosis_preview": preview_text(data[4]),
                        "prescription": data[5]
                    })
    except FileNotFoundError:
        pass
    records.sort(key=lambda item: parse_iso_date(item["date"]) or date.min, reverse=True)
    return records


def parse_pending_request_line(line):
    data = line.strip().split("|")
    if len(data) < 12:
        return None
    try:
        return {
            "request_id": int(data[0]),
            "patient_id": int(data[1]),
            "doctor_id": int(data[2]),
            "requested_date": data[3],
            "requested_slot": data[4],
            "reason": data[5],
            "visit_type": data[6],
            "status": data[7],
            "submitted_at": data[8],
            "expires_at": data[9],
            "receptionist_note": data[10],
            "appointment_id": int(data[11] or 0)
        }
    except ValueError:
        return None


def run_pending_request_command(*args):
    return subprocess.run(
        [PENDING_REQUEST_EXE, *[str(arg) for arg in args]],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )


def serialize_pending_request(request_row):
    return "|".join([
        str(int(request_row["request_id"])),
        str(int(request_row["patient_id"])),
        str(int(request_row["doctor_id"])),
        clean_record_field(request_row["requested_date"]),
        clean_record_field(request_row["requested_slot"]),
        clean_record_field(request_row.get("reason", ""), 220),
        clean_record_field(request_row.get("visit_type", "New")),
        clean_record_field(request_row.get("status", "Pending")),
        clean_record_field(request_row.get("submitted_at", "")),
        clean_record_field(request_row.get("expires_at", "")),
        clean_record_field(request_row.get("receptionist_note", ""), 220),
        str(int(request_row.get("appointment_id", 0) or 0))
    ])


def read_all_pending_requests():
    rows = []
    result = run_pending_request_command("list-existing")
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] list-existing failed: {result.stderr or result.stdout}")
        return rows
    for line in result.stdout.splitlines():
        pending = parse_pending_request_line(line)
        if pending:
            rows.append(pending)
    return rows


def write_all_pending_requests(rows):
    # Pending request persistence is owned by pending_request.exe.
    # Keep this fallback helper only for legacy callers during migration.
    os.makedirs(os.path.dirname(PENDING_APPOINTMENTS_FILE), exist_ok=True)
    with _pending_appointment_lock:
        with open(PENDING_APPOINTMENTS_FILE, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(f"{serialize_pending_request(row)}\n")


def next_pending_request_id():
    return max((row["request_id"] for row in read_all_pending_requests()), default=0) + 1


def create_pending_request(patient_id, doctor_id, requested_date, requested_slot, reason, visit_type, status="Pending", appointment_id=0, note=""):
    result = run_pending_request_command(
        "add-existing",
        int(patient_id),
        int(doctor_id),
        clean_record_field(requested_date),
        clean_record_field(requested_slot),
        clean_record_field(reason, 220),
        visit_type if visit_type in {"New", "Follow-up"} else "New",
        clean_record_field(status),
        clean_record_field(note, 220),
        int(appointment_id or 0)
    )
    if result.returncode != 0 or not result.stdout.startswith("ADDED|"):
        raise RuntimeError(f"pending_request.exe add-existing failed: {result.stderr or result.stdout}")
    return parse_pending_request_line(result.stdout.split("|", 1)[1])


def update_pending_status(request_id, status, receptionist_note="", appointment_id=None):
    result = run_pending_request_command(
        "update-existing",
        int(request_id),
        clean_record_field(status),
        clean_record_field(receptionist_note, 220),
        int(appointment_id or 0)
    )
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] update-existing failed: {result.stderr or result.stdout}")
        return None
    if not result.stdout.startswith("UPDATED|"):
        return None
    return parse_pending_request_line(result.stdout.split("|", 1)[1])


def decorate_pending_request(pending, doctor_map=None, patient_map=None):
    doctor_map = doctor_map or {doctor["id"]: doctor for doctor in get_doctors()}
    patient_map = patient_map or {patient["id"]: patient for patient in read_patients()}
    doctor = doctor_map.get(pending["doctor_id"], {})
    patient = patient_map.get(pending["patient_id"], {})
    status_class = pending["status"].lower().replace("-", "")
    return {
        **pending,
        "patient_name": patient.get("name", ""),
        "patient_age": patient.get("age", ""),
        "patient_gender": patient.get("gender", ""),
        "patient_phone": patient.get("phone", ""),
        "doctor_name": doctor.get("name", "Doctor"),
        "department": doctor.get("department", ""),
        "human_date": format_human_date(pending["requested_date"]),
        "time_label": pending["requested_slot"],
        "time_remaining": remaining_time_label(pending["expires_at"]),
        "status_label": "Pending Confirmation" if pending["status"] == "Pending" else pending["status"],
        "status_class": status_class
    }


def read_pending_requests_for_patient(patient_id):
    patient_id = int(patient_id)
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    requests = []
    for pending in read_all_pending_requests():
        if pending["patient_id"] != patient_id:
            continue
        requests.append(decorate_pending_request(pending, doctor_map=doctor_map))
    requests.sort(
        key=lambda item: (
            parse_iso_date(item["requested_date"]) or date.min,
            item["requested_slot"]
        )
    )
    return requests


def read_pending_requests_for_reception():
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    patient_map = {patient["id"]: patient for patient in read_patients()}
    rows = [
        decorate_pending_request(row, doctor_map=doctor_map, patient_map=patient_map)
        for row in read_all_pending_requests()
        if row["status"] == "Pending"
    ]
    rows.sort(key=lambda item: parse_iso_datetime(item["submitted_at"]) or datetime.min)
    return rows


def pending_slot_exists(doctor_id, requested_date, requested_slot):
    result = run_pending_request_command(
        "soft-lock-exists",
        int(doctor_id),
        clean_record_field(requested_date),
        clean_record_field(requested_slot)
    )
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] soft-lock check failed: {result.stderr or result.stdout}")
        return False
    return result.stdout.strip() == "EXISTS"


def parse_new_patient_request_line(line):
    data = line.strip().split("|")
    if len(data) < 19:
        return None
    try:
        return {
            "request_id": int(data[0]),
            "name": data[1],
            "age": data[2],
            "gender": data[3],
            "phone": data[4],
            "address": data[5],
            "department": data[6],
            "doctor_id": int(data[7]),
            "requested_date": data[8],
            "requested_slot": data[9],
            "reason": data[10],
            "visit_type": data[11],
            "priority": data[12],
            "status": data[13],
            "submitted_at": data[14],
            "expires_at": data[15],
            "receptionist_note": data[16],
            "patient_id": int(data[17] or 0),
            "appointment_id": int(data[18] or 0)
        }
    except ValueError:
        return None


def serialize_new_patient_request(row):
    return "|".join([
        str(int(row["request_id"])),
        clean_record_field(row.get("name", "")),
        clean_record_field(row.get("age", "")),
        clean_record_field(row.get("gender", "")),
        clean_record_field(row.get("phone", "")),
        clean_record_field(row.get("address", "")),
        clean_record_field(row.get("department", "")),
        str(int(row.get("doctor_id", 0) or 0)),
        clean_record_field(row.get("requested_date", "")),
        clean_record_field(row.get("requested_slot", "")),
        clean_record_field(row.get("reason", ""), 220),
        clean_record_field(row.get("visit_type", "New")),
        clean_record_field(row.get("priority", "Normal")),
        clean_record_field(row.get("status", "Pending")),
        clean_record_field(row.get("submitted_at", "")),
        clean_record_field(row.get("expires_at", "")),
        clean_record_field(row.get("receptionist_note", ""), 220),
        str(int(row.get("patient_id", 0) or 0)),
        str(int(row.get("appointment_id", 0) or 0))
    ])


def read_all_new_patient_requests():
    rows = []
    result = run_pending_request_command("list-new")
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] list-new failed: {result.stderr or result.stdout}")
        return rows
    for line in result.stdout.splitlines():
        row = parse_new_patient_request_line(line)
        if row:
            rows.append(row)
    return rows


def write_all_new_patient_requests(rows):
    # Pending request persistence is owned by pending_request.exe.
    # Keep this fallback helper only for legacy callers during migration.
    os.makedirs(os.path.dirname(NEW_PATIENT_REQUESTS_FILE), exist_ok=True)
    with _new_patient_request_lock:
        with open(NEW_PATIENT_REQUESTS_FILE, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(f"{serialize_new_patient_request(row)}\n")


def next_new_patient_request_id():
    return max((row["request_id"] for row in read_all_new_patient_requests()), default=0) + 1


def create_new_patient_request(form):
    result = run_pending_request_command(
        "add-new",
        clean_record_field(form.get("name", "")),
        clean_record_field(form.get("age", "")),
        clean_record_field(form.get("gender", "")),
        normalize_phone(form.get("phone", "")),
        clean_record_field(form.get("address", ""), 220),
        clean_record_field(form.get("department", "")),
        safe_int(form.get("doctor_id", "0")),
        clean_record_field(form.get("requested_date", "")),
        clean_record_field(form.get("requested_slot", "")),
        clean_record_field(form.get("reason", ""), 220),
        clean_record_field(form.get("visit_type", "New")) or "New",
        "Normal"
    )
    if result.returncode != 0 or not result.stdout.startswith("ADDED|"):
        raise RuntimeError(f"pending_request.exe add-new failed: {result.stderr or result.stdout}")
    return parse_new_patient_request_line(result.stdout.split("|", 1)[1])


def update_new_patient_request_status(request_id, status, receptionist_note="", patient_id=None, appointment_id=None):
    result = run_pending_request_command(
        "update-new",
        int(request_id),
        clean_record_field(status),
        clean_record_field(receptionist_note, 220),
        int(patient_id or 0),
        int(appointment_id or 0)
    )
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] update-new failed: {result.stderr or result.stdout}")
        return None
    if not result.stdout.startswith("UPDATED|"):
        return None
    return parse_new_patient_request_line(result.stdout.split("|", 1)[1])


def decorate_new_patient_request(row, doctor_map=None):
    doctor_map = doctor_map or {doctor["id"]: doctor for doctor in get_doctors()}
    doctor = doctor_map.get(row["doctor_id"], {})
    return {
        **row,
        "doctor_name": doctor.get("name", "Doctor"),
        "human_date": format_human_date(row["requested_date"]),
        "time_label": row["requested_slot"],
        "time_remaining": remaining_time_label(row["expires_at"]),
        "status_class": row["status"].lower()
    }


def read_new_patient_requests_for_reception():
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    rows = [
        decorate_new_patient_request(row, doctor_map=doctor_map)
        for row in read_all_new_patient_requests()
        if row["status"] == "Pending"
    ]
    rows.sort(key=lambda item: parse_iso_datetime(item["submitted_at"]) or datetime.min)
    return rows


def run_expiry_check():
    pending_changed = False
    new_changed = False
    result = run_pending_request_command("expire")
    if result.returncode != 0:
        print(f"[HealthDesk Pending C] expire failed: {result.stderr or result.stdout}")
        return {"pending_changed": False, "new_changed": False}

    for line in result.stdout.splitlines():
        if line.startswith("EXPIRED_EXISTING|"):
            row = parse_pending_request_line(line.split("|", 1)[1])
            if not row:
                continue
            pending_changed = True
            patient = find_patient_by_id(row["patient_id"])
            if patient:
                send_sms_notice(patient["phone"], f"Your request for {format_human_date(row['requested_date'])}, {row['requested_slot']} expired before confirmation. Log in to rebook.")
                notify_receptionists(f"Booking request from {patient['name']} expired unreviewed.")
        elif line.startswith("EXPIRED_NEW|"):
            row = parse_new_patient_request_line(line.split("|", 1)[1])
            if not row:
                continue
            new_changed = True
            send_sms_notice(row["phone"], f"Your first-time request for {format_human_date(row['requested_date'])}, {row['requested_slot']} expired before confirmation. Please submit again or call the clinic.")
            notify_receptionists(f"First-time booking request from {row['name']} expired unreviewed.")

    _expire_stale_advances()
    return {"pending_changed": pending_changed, "new_changed": new_changed}


def _refund_advance_after_failure(adv, sms_message):
    """
    Initiates a Razorpay refund for a PAID advance that could not result in a booking.
    Updates the advance status to REFUNDED on success, or logs a warning on failure.
    This must never raise - it is called from within the webhook handler.
    """
    try:
        from payment_service import initiate_refund
        ok_refund, err_refund = initiate_refund(adv["razorpay_payment_id"], adv["amount"])
        if ok_refund:
            adv["status"] = "REFUNDED"
            adv["settled_at"] = iso_now()
            update_advance_record(adv)
        else:
            print(f"[HealthDesk] Auto-refund failed for advance {adv.get('advance_id')}: {err_refund}. Manual refund required.")
            sms_message = (
                "Your advance was received but the booking could not be completed. "
                "Please call the clinic - a refund will be processed manually."
            )
        patient = find_patient_by_id(adv["patient_id"])
        if patient:
            send_sms_notice(patient["phone"], sms_message)
    except Exception as exc:
        print(f"[HealthDesk] ERROR in _refund_advance_after_failure for advance {adv.get('advance_id')}: {exc}")


def _confirm_booking_after_advance(adv):
    """
    Called from payment_webhook_advance after payment.captured.
    Retrieves booking intent and runs the triage path.
    This function must not raise - a webhook crash causes Razorpay retries.
    On any booking failure after a successful payment, an automatic refund is initiated.
    """
    try:
        intent = pop_booking_intent(adv["advance_id"])
        if not intent:
            print(f"[HealthDesk] WARNING: No booking intent for advance {adv['advance_id']}")
            _refund_advance_after_failure(adv, "Your advance was received but we could not find your booking details. A refund has been initiated. Please call the clinic.")
            return

        patient = find_patient_by_id(adv["patient_id"])
        if not patient:
            print(f"[HealthDesk] WARNING: No patient found for advance {adv['advance_id']}")
            return

        if intent["triage"] == "auto":
            ok, message, row = auto_approve_booking(
                patient, intent["doctor_id"], intent["requested_date"],
                intent["requested_slot"], intent["reason"], intent["visit_type"]
            )
            if ok and row:
                appointment_id = safe_int(row.get("appointment_id", 0))
                if appointment_id:
                    adv["appointment_id"] = appointment_id
                    update_advance_record(adv)
                doctor = get_doctor_by_id(intent["doctor_id"]) or {}
                send_sms_notice(
                    patient["phone"],
                    f"Appointment confirmed! {doctor.get('name', 'Doctor')} on "
                    f"{format_human_date(intent['requested_date'])} at {intent['requested_slot']}. "
                    f"Advance paid: Rs.{adv['amount']:.0f}."
                )
            else:
                _refund_advance_after_failure(
                    adv,
                    f"Your advance was received but the slot is no longer available ({message}). "
                    "A full refund has been initiated and will arrive in 5-7 business days."
                )
        else:
            ok, _message, row = exception_queue_booking(
                patient, intent["doctor_id"], intent["requested_date"],
                intent["requested_slot"], intent["reason"], intent["visit_type"]
            )
            if ok and isinstance(row, dict):
                adv["pending_request_id"] = row.get("request_id", 0)
                update_advance_record(adv)
                send_sms_notice(
                    patient["phone"],
                    f"Advance of Rs.{adv['amount']:.0f} received. "
                    "Your booking request is under review - response within 2 hours."
                )
            else:
                _refund_advance_after_failure(
                    adv,
                    f"Your advance was received but we could not queue your request ({_message}). "
                    "A full refund has been initiated and will arrive in 5-7 business days."
                )
    except Exception as exc:
        print(f"[HealthDesk] ERROR confirming advance {adv.get('advance_id')}: {exc}")


def _expire_stale_advances():
    """
    Expires PENDING_PAYMENT advances past their payment window.
    Auto-approve: 30 min. Exception queue: 2 hours.
    Called from run_expiry_check().
    """
    now = datetime.now()
    with _advance_lock:
        records = _read_advances_unlocked()
        changed = False
        for adv in records:
            if adv["status"] != "PENDING_PAYMENT":
                continue
            created = parse_iso_datetime(adv.get("created_at", ""))
            if not created:
                continue
            window = timedelta(hours=2) if adv["pending_request_id"] else timedelta(minutes=30)
            if now - created <= window:
                continue
            adv["status"] = "EXPIRED"
            adv["settled_at"] = iso_now()
            result = run_advance_command("update", adv["advance_id"], serialize_advance_record(adv))
            if not result or result.returncode != 0:
                continue
            changed = True
            run_advance_command("intent-pop", adv["advance_id"])
            if adv["pending_request_id"]:
                update_pending_status(adv["pending_request_id"], "Expired")
            patient = find_patient_by_id(adv["patient_id"])
            if patient:
                send_sms_notice(
                    patient["phone"],
                    "Your HealthDesk booking was not confirmed - the payment window expired. "
                    "Please try booking again."
                )
        return changed


def patient_has_completed_visit_with_doctor(patient_id, doctor_id):
    """
    Returns True if the patient has at least one Completed appointment
    with this specific doctor. Required before allowing Follow-up visit type.
    """
    for appt in read_appointments():
        if (appt.get("patient_id") == int(patient_id)
                and appt.get("doctor_id") == int(doctor_id)
                and str(appt.get("status", "")).strip() == "Completed"):
            return True
    return False


def triage_booking_request(doctor_id, requested_date, visit_type):
    doctor = get_doctor_by_id(doctor_id)
    reasons = []
    if not is_clinic_hours_now():
        reasons.append("Submitted outside clinic review hours.")
    if not doctor or doctor.get("daily_status") != "Available" or doctor.get("current_status") not in {"Free", "Busy"}:
        reasons.append("Doctor availability needs receptionist review.")
    if visit_type != "New":
        reasons.append("Follow-up visits need receptionist review.")
    return ("exception" if reasons else "auto"), reasons


def auto_approve_booking(patient, doctor_id, requested_date, requested_slot, reason, visit_type):
    if find_booked_appointment_for_patient_on_date(patient["id"], requested_date):
        return False, "This patient already has a booked appointment for that date.", None
    if pending_slot_exists(doctor_id, requested_date, requested_slot):
        return False, "This slot is being processed for another request. Please choose another slot.", None
    if not slot_is_available(doctor_id, requested_date, requested_slot):
        return False, "This slot is no longer available. Please choose another slot.", None
    result = run_appointment_command("book", patient["id"], doctor_id, requested_date, requested_slot)
    appointment_id = parse_booked_appointment_id(result)
    if not appointment_id:
        return False, "The appointment could not be booked. Please choose another slot.", None
    audit_row = create_pending_request(
        patient["id"],
        doctor_id,
        requested_date,
        requested_slot,
        reason,
        visit_type,
        status="Approved",
        appointment_id=appointment_id,
        note="Auto-approved by triage"
    )
    doctor = get_doctor_by_id(doctor_id) or {}
    send_sms_notice(
        patient["phone"],
        f"Confirmed! {doctor.get('name', 'Doctor')}, {format_human_date(requested_date)}, {requested_slot}. Please arrive 10 min early."
    )
    return True, "Your appointment is confirmed.", audit_row


def exception_queue_booking(patient, doctor_id, requested_date, requested_slot, reason, visit_type, triage_reasons=None):
    if pending_slot_exists(doctor_id, requested_date, requested_slot):
        return False, "This slot is already being reviewed for another patient. Please choose another slot.", None
    if not slot_is_available(doctor_id, requested_date, requested_slot):
        return False, "This slot is no longer available. Please choose another slot.", None
    note = "; ".join(triage_reasons or [])
    row = create_pending_request(
        patient["id"],
        doctor_id,
        requested_date,
        requested_slot,
        reason,
        visit_type,
        status="Pending",
        note=note
    )
    doctor = get_doctor_by_id(doctor_id) or {}
    send_sms_notice(patient["phone"], f"Request for {doctor.get('name', 'Doctor')} on {format_human_date(requested_date)}, {requested_slot} received. Confirming within 2 hours during clinic hours.")
    notify_receptionists(f"New request from {patient['name']} ({patient['phone']}) for {doctor.get('name', 'Doctor')}, {format_human_date(requested_date)}, {requested_slot}. Review dashboard.")
    return True, "Your request has been sent for receptionist review.", row


def get_advances_needing_attention():
    """
    Returns advances that need manual receptionist attention:
    - PAID with appointment_id == 0: payment received but no booking linked
    - FORFEITED: no-show advance, may be disputed by patient
    """
    advances = read_advances()
    patients = {patient["id"]: patient for patient in read_patients()}
    doctors = {doctor["id"]: doctor for doctor in get_doctors()}

    def decorate(advance):
        patient = patients.get(int(advance.get("patient_id", 0) or 0), {})
        doctor = doctors.get(int(advance.get("doctor_id", 0) or 0), {})
        return {
            **advance,
            "patient_name": patient.get("name", f"Patient #{advance.get('patient_id', 0)}"),
            "patient_phone": patient.get("phone", ""),
            "doctor_name": doctor.get("name", f"Doctor #{advance.get('doctor_id', 0)}"),
            "department": doctor.get("department", patient.get("department", "")),
            "human_date": format_human_date(advance.get("appointment_date", "")),
            "amount_label": format_amount(advance.get("amount", 0))
        }

    stranded = [
        decorate(a) for a in advances
        if a["status"] == "PAID" and a["appointment_id"] == 0
    ]
    forfeited = [
        decorate(a) for a in advances
        if a["status"] == "FORFEITED"
    ]
    return {"stranded": stranded, "forfeited": forfeited}


def doctor_options_for_department(department):
    return [
        doctor for doctor in get_doctors()
        if not department or doctor["department"] == department
    ]


def choose_any_available_doctor(department, requested_date, requested_slot):
    for doctor in doctor_options_for_department(department):
        if slot_is_available(doctor["id"], requested_date, requested_slot) and not pending_slot_exists(doctor["id"], requested_date, requested_slot):
            return doctor
    return None


def build_patient_slot_payload(department, doctor_id, requested_date):
    slots_by_time = {}
    doctors = doctor_options_for_department(department)
    if doctor_id and str(doctor_id) != "any":
        doctors = [doctor for doctor in doctors if str(doctor["id"]) == str(doctor_id)]

    for doctor in doctors:
        for slot in load_appointment_slots(doctor["id"], requested_date):
            state = slot["state"]
            if state == "Available" and pending_slot_exists(doctor["id"], requested_date, slot["time"]):
                state = "Pending"
            existing = slots_by_time.get(slot["time"])
            candidate = {
                "time": slot["time"],
                "state": state,
                "doctor_id": doctor["id"],
                "doctor_name": doctor["name"]
            }
            if not existing:
                slots_by_time[slot["time"]] = candidate
            elif existing["state"] != "Available" and state == "Available":
                slots_by_time[slot["time"]] = candidate

    return [slots_by_time[key] for key in sorted(slots_by_time.keys(), key=lambda value: parse_slot_time(value))]


def parse_slot_time(value):
    try:
        return datetime.strptime(value, "%I:%M %p").time()
    except ValueError:
        return datetime.min.time()


def register_patient_from_request(row):
    existing = find_patient_by_phone(row["phone"])
    if existing:
        return existing
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "patient.exe")
    data_string = "|".join([
        clean_record_field(row["name"]),
        clean_record_field(row["age"]),
        clean_record_field(row["gender"]),
        clean_record_field(row["phone"]),
        clean_record_field(row["address"]),
        clean_record_field(row["reason"] or "First-time online request"),
        "New",
        clean_record_field(row.get("priority", "Normal") or "Normal"),
        clean_record_field(row["department"])
    ])
    result = subprocess.run(
        [exe_path, data_string],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )
    data = result.stdout.strip().split("|")
    if result.returncode == 0 and data and safe_int(data[0]):
        return find_patient_by_id(data[0])
    return None


def status_label_for_patient(status):
    result = _run_utils_command("status-label", str(status or ""))
    if result and result.returncode == 0:
        return result.stdout.strip()
    raise RuntimeError("utils command failed: status-label")


def status_sentence_for_patient(appointment, doctor_name):
    status = appointment.get("status", "")
    when = f"{format_human_date(appointment.get('date'))} at {appointment.get('time_slot', '')}"
    if status == "Booked":
        return f"Confirmed with {doctor_name} on {when}."
    if status == "Completed":
        return f"Visit completed on {format_human_date(appointment.get('date'))}."
    if status == "Cancelled":
        return f"This appointment was cancelled."
    if status == "No-show":
        return f"Appointment on {when} was not attended."
    if status == "Rescheduled":
        return "This appointment was rescheduled by the clinic."
    return status_label_for_patient(status)


def decorate_patient_appointments(patient_id):
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    rows = []
    for appointment in read_appointments():
        if appointment["patient_id"] != int(patient_id):
            continue
        doctor = doctor_map.get(appointment["doctor_id"], {})
        appointment_dt = parse_appointment_datetime(appointment)
        is_upcoming = appointment["status"] == "Booked" and appointment_dt >= datetime.now()
        can_cancel_online = is_upcoming and (appointment_dt - datetime.now()) > timedelta(hours=24)
        doctor_name = doctor.get("name", "Doctor")
        rows.append({
            **appointment,
            "doctor_name": doctor_name,
            "department": doctor.get("department", ""),
            "human_date": format_human_date(appointment["date"]),
            "time_label": appointment["time_slot"],
            "status_label": status_label_for_patient(appointment["status"]),
            "status_class": appointment["status"].lower().replace("-", ""),
            "status_sentence": status_sentence_for_patient(appointment, doctor_name),
            "is_upcoming": is_upcoming,
            "can_cancel_online": can_cancel_online,
            "cancel_note": (
                "You can cancel this appointment online."
                if can_cancel_online
                else "To cancel within 24 hours, please call the clinic."
            )
        })
    rows.sort(key=parse_appointment_datetime)
    upcoming = [row for row in rows if row["is_upcoming"]]
    history = [row for row in rows if not row["is_upcoming"]]
    history.sort(key=parse_appointment_datetime, reverse=True)
    return upcoming, history


def display_name_for_catalog_item(code_or_name, catalog_map):
    item = catalog_map.get(code_or_name)
    if item:
        return item.get("name", code_or_name)
    return str(code_or_name or "").replace("_", " ").strip().title()


def decorate_bill_for_patient(bill, treatment_map, lab_map):
    line_items = []
    if bill.get("doctor_fee"):
        line_items.append({
            "label": "Doctor consultation fee",
            "amount": format_amount(bill["doctor_fee"])
        })
    for item in bill.get("treatments", []):
        line_items.append({
            "label": display_name_for_catalog_item(item.get("name"), treatment_map),
            "amount": format_amount(item.get("price", 0))
        })
    for item in bill.get("lab_tests", []):
        line_items.append({
            "label": display_name_for_catalog_item(item.get("name"), lab_map),
            "amount": format_amount(item.get("price", 0))
        })
    if bill.get("medicine_total"):
        label = "Medicines"
        if bill.get("medicine_notes"):
            label = f"Medicines: {bill['medicine_notes']}"
        line_items.append({
            "label": label,
            "amount": format_amount(bill["medicine_total"])
        })
    status = str(bill.get("status", "")).upper()
    status_label = status.title() if status else "Pending"
    if status == "INITIATED":
        status_label = "Payment Processing"
    if status == "PAID" and bill.get("payment_method") and bill.get("payment_method") != "counter":
        status_label = "Paid Online"
    return {
        **bill,
        "human_date": format_human_date(bill.get("date")),
        "total_label": format_amount(bill.get("total", 0)),
        "status_label": status_label,
        "status_class": status.lower(),
        "line_items": line_items,
        "payment_method_label": payment_method_label(bill.get("payment_method")),
        "paid_at_label": payment_timestamp_label(bill.get("paid_at"))
    }


def read_bills_for_patient(patient_id):
    revert_stale_initiated_payments()
    _catalog, treatment_map, lab_map = get_pricing_maps()
    bills = [
        decorate_bill_for_patient(bill, treatment_map, lab_map)
        for bill in read_bills()
        if int(bill.get("patient_id", 0) or 0) == int(patient_id)
    ]
    pending = [bill for bill in bills if str(bill.get("status", "")).upper() in {"PENDING", "INITIATED"}]
    others = [bill for bill in bills if str(bill.get("status", "")).upper() not in {"PENDING", "INITIATED"}]
    pending.sort(key=lambda bill: parse_iso_date(bill.get("date")) or date.min, reverse=True)
    others.sort(key=lambda bill: parse_iso_date(bill.get("date")) or date.min, reverse=True)
    return pending + others


def has_blocking_unpaid_bill(patient_id):
    result = run_billing_command("has-blocking", int(patient_id))
    if result and result.returncode == 0:
        return result.stdout.strip() == "1"
    raise RuntimeError("billing command failed: has-blocking")


def get_patient_billing_context(patient_id, latest_appointment=None):
    patient = find_patient_by_id(patient_id)
    context = {
        "patient_id": int(patient_id),
        "can_bill": False,
        "warning": "",
        "doctor_id": 0,
        "doctor_name": "",
        "department": "",
        "appointment_id": 0,
        "appointment_status": "",
        "appointment_date": "",
        "existing_bill_id": 0
    }
    if not patient:
        context["warning"] = "Patient not found."
        return context

    latest_appointment = (
        latest_appointment
        or get_latest_completed_patient_appointment(patient_id)
        or get_latest_patient_appointment(patient_id)
    )
    if not latest_appointment:
        context["warning"] = "No appointment found for this patient."
        return context

    context["appointment_id"] = latest_appointment["appointment_id"]
    context["appointment_status"] = latest_appointment["status"]
    context["appointment_date"] = latest_appointment["date"]

    doctor = get_doctor_by_id(latest_appointment["doctor_id"])
    if doctor:
        context["doctor_id"] = doctor["id"]
        context["doctor_name"] = doctor["name"]
        context["department"] = doctor["department"]

    existing_bill = find_bill_by_appointment_id(latest_appointment["appointment_id"])
    if existing_bill:
        context["existing_bill_id"] = existing_bill["bill_id"]

    if latest_appointment["status"] != "Completed":
        context["warning"] = (
            f"Billing is available only after completion. Latest appointment status is "
            f"{latest_appointment['status']}."
        )
        return context

    if not doctor:
        context["warning"] = "Completed appointment found, but the linked doctor profile is missing."
        return context

    context["can_bill"] = True
    if existing_bill:
        context["warning"] = f"Bill #{existing_bill['bill_id']} already exists for the latest completed appointment."
    return context


def get_patient_billing_context_from_cache(patient, appointments, doctor_map, bills_by_appointment):
    context = {
        "patient_id": int(patient["id"]),
        "can_bill": False,
        "warning": "",
        "doctor_id": 0,
        "doctor_name": "",
        "department": "",
        "appointment_id": 0,
        "appointment_status": "",
        "appointment_date": "",
        "existing_bill_id": 0
    }
    patient_appointments = [
        appointment for appointment in appointments
        if appointment["patient_id"] == int(patient["id"])
    ]
    if not patient_appointments:
        context["warning"] = "No appointment found for this patient."
        return context

    completed = [
        appointment for appointment in patient_appointments
        if appointment["status"] == "Completed"
    ]
    selected = max(
        completed or patient_appointments,
        key=parse_appointment_datetime
    )

    context["appointment_id"] = selected["appointment_id"]
    context["appointment_status"] = selected["status"]
    context["appointment_date"] = selected["date"]

    doctor = doctor_map.get(selected["doctor_id"])
    if doctor:
        context["doctor_id"] = doctor["id"]
        context["doctor_name"] = doctor["name"]
        context["department"] = doctor["department"]

    existing_bill = bills_by_appointment.get(selected["appointment_id"])
    if existing_bill:
        context["existing_bill_id"] = existing_bill["bill_id"]

    if selected["status"] != "Completed":
        context["warning"] = (
            f"Billing is available only after completion. Latest appointment status is "
            f"{selected['status']}."
        )
        return context

    if not doctor:
        context["warning"] = "Completed appointment found, but the linked doctor profile is missing."
        return context

    context["can_bill"] = True
    if existing_bill:
        context["warning"] = f"Bill #{existing_bill['bill_id']} already exists for the latest completed appointment."
    return context


def build_billing_lookup(patients, appointments, doctors, bills):
    doctor_map = {doctor["id"]: doctor for doctor in doctors}
    bills_by_appointment = {
        int(bill.get("appointment_id", 0) or 0): bill
        for bill in bills
        if int(bill.get("appointment_id", 0) or 0) > 0
    }
    return {
        str(patient["id"]): get_patient_billing_context_from_cache(
            patient,
            appointments,
            doctor_map,
            bills_by_appointment
        )
        for patient in patients
    }

def read_patients():
    patients = []
    result = run_patient_command("list")
    try:
        lines = result.stdout.splitlines() if result and result.returncode == 0 else []
        if not lines:
            patient_file = os.path.join(BACKEND_DIR, "data", "patients.txt")
            with open(patient_file, "r", encoding="utf-8") as f:
                lines = list(f)
        for line in lines:
            patient = parse_patient_record_line(line)
            if patient:
                patients.append(patient)
    except FileNotFoundError:
        pass
    return patients

def find_patient_by_phone(phone):
    result = run_patient_command("search", phone)
    if result and result.returncode == 0:
        return parse_patient_command_output(result.stdout)
    return None

def find_patient_by_id(patient_id):
    result = run_patient_command("get-by-id", patient_id)
    if result and result.returncode == 0:
        patient = parse_patient_command_output(result.stdout)
        if patient:
            return patient
    for patient in read_patients():
        if patient["id"] == int(patient_id):
            return patient
    return None

def read_assigned_queue_patients(doctor_id):
    """
    Returns all patients currently Waiting in this doctor's queue.
    Shows every Waiting patient — appointment lookup is best-effort for extra context.
    The queue itself is the source of truth for who is waiting.
    """
    assigned = []
    patients = {patient["id"]: patient for patient in read_patients()}

    for item in read_queue():
        if item["doctor_id"] != doctor_id or item["status"] != "Waiting":
            continue

        patient = patients.get(item["patient_id"], {})
        # Best-effort: find a Booked or No-show appointment for this patient+doctor today
        active_appointment = get_latest_active_patient_appointment(item["patient_id"], doctor_id=doctor_id)
        appointment_for_queue = (
            active_appointment
            if active_appointment
            and active_appointment["doctor_id"] == doctor_id
            and is_consultation_day_reached(active_appointment)
            else None
        )

        assigned.append({
            "token": item["token"],
            "patient_id": item["patient_id"],
            "priority": item["priority"],
            "status": item["status"],
            "name": patient.get("name", ""),
            "department": patient.get("department", ""),
            "symptoms": patient.get("symptoms", ""),
            "appointment_id": appointment_for_queue["appointment_id"] if appointment_for_queue else 0,
            "appointment_date": appointment_for_queue["date"] if appointment_for_queue else "",
            "is_today_queue": True,  # By definition: they are Waiting in the queue right now
            "can_consult": True,
        })

    assigned.sort(key=lambda x: (x["priority"] != "Urgent", x["token"]))
    return assigned

def get_diagnosis_context(patient_id):
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "diagnosis.exe")
    result = subprocess.run(
        [exe_path, "history", str(patient_id)],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    output = result.stdout.strip().split("\n")
    patient = None
    diagnosis = []
    error_message = None

    for line in output:
        data = line.split("|")
        if not data or not data[0]:
            continue
        if data[0] == "PatientNotFound":
            error_message = "Patient ID not found."
        elif data[0] == "PATIENT" and len(data) >= 11:
            patient = {
                "id": data[1],
                "name": data[2],
                "age": data[3],
                "gender": data[4],
                "phone": data[5],
                "address": data[6],
                "symptoms": data[7],
                "visit_type": data[8],
                "priority": data[9],
                "department": data[10]
            }
        elif data[0] == "DIAGNOSIS" and len(data) >= 7:
            diagnosis.append({
                "record_id": data[1],
                "patient_id": data[2],
                "doctor_id": data[3],
                "date": data[4],
                "diagnosis": data[5],
                "prescription": data[6]
            })

    return patient, diagnosis, error_message

def auto_generate_bill(patient_id, doctor_id, bill_date, appointment_id=None):
    patient = find_patient_by_id(patient_id)
    latest_appointment = (
        find_appointment_by_id(appointment_id)
        if appointment_id
        else get_latest_completed_patient_appointment(patient_id, doctor_id=doctor_id)
    )
    context = get_patient_billing_context(patient_id, latest_appointment=latest_appointment)
    doctor = get_doctor_by_id(doctor_id) if doctor_id else None

    if not patient or not context["can_bill"] or not doctor:
        return None

    if int(context["doctor_id"] or 0) != int(doctor_id):
        return None

    if context["existing_bill_id"]:
        return find_bill_by_id(context["existing_bill_id"])

    existing_bill = next(
        (
            bill for bill in read_bills()
            if bill["patient_id"] == int(patient_id)
            and bill["doctor_id"] == int(doctor_id)
            and bill["date"] == bill_date
        ),
        None
    )
    if existing_bill:
        return existing_bill

    bill = create_bill_record(
        patient=patient,
        doctor=doctor,
        bill_date=bill_date,
        payment_status="PENDING",
        appointment_id=context["appointment_id"]
    )
    save_bill_record(bill)
    return bill


@app.route("/")
def dashboard():
    if not is_authenticated():
        return render_template("landing.html")
    role = session.get("role")
    if role == "Receptionist":
        return redirect("/receptionist_dashboard")
    if role == "Doctor":
        return redirect("/doctor")
    if role == "Patient":
        return redirect("/patient/dashboard")
    return redirect("/login")

@app.route("/patient/login", methods=["GET"])
def patient_login():
    if session.get("role") == "Patient":
        return redirect(url_for("patient_dashboard"))
    return render_template(
        "patient_login.html",
        step="phone",
        phone="",
        masked_phone="",
        error=None,
        message=None
    )

@app.route("/patient/request-otp", methods=["POST"])
def patient_request_otp():
    phone = normalize_phone(request.form.get("phone", ""))
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def respond_error(error, cooldown=0):
        if wants_json:
            return jsonify({"ok": False, "error": error, "cooldown": cooldown}), 400
        return render_template(
            "patient_login.html",
            step="phone",
            phone=phone,
            masked_phone="",
            error=error,
            message=None
        ), 400

    if not is_valid_patient_phone(phone):
        return respond_error("Enter a valid 10-digit phone number.")

    patient = find_registered_patient_by_phone(phone)
    if not patient:
        return respond_error("This phone number is not registered with us. Please visit the clinic to register.")

    ok, cooldown_left = generate_otp(phone)
    if not ok:
        if cooldown_left > 0:
            return respond_error(f"Please wait {cooldown_left} second(s) before requesting a new OTP.", cooldown=cooldown_left)
        detail = get_last_sms_error()
        if detail:
            print(f"[HealthDesk OTP] SMS provider detail: {detail}")
        return respond_error("OTP could not be sent. Please check the Fast2SMS setup or try again.")
    masked = mask_phone(phone)
    message = "OTP sent to your registered phone number."
    if wants_json:
        return jsonify({"ok": True, "phone": phone, "masked_phone": masked, "message": message, "cooldown": OTP_RESEND_COOLDOWN_SECONDS})
    return render_template(
        "patient_login.html",
        step="otp",
        phone=phone,
        masked_phone=masked,
        error=None,
        message=message
    )


@app.route("/patient/resend-otp", methods=["POST"])
def patient_resend_otp():
    """Resend OTP for a phone already in the OTP step. Enforces 60-second cooldown."""
    phone = normalize_phone(request.form.get("phone", ""))
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def respond_error(error, cooldown=0, status=400):
        if wants_json:
            return jsonify({"ok": False, "error": error, "cooldown": cooldown}), status
        return render_template(
            "patient_login.html",
            step="otp",
            phone=phone,
            masked_phone=mask_phone(phone),
            error=error,
            message=None
        ), status

    if not is_valid_patient_phone(phone):
        return respond_error("Invalid phone number.")
    patient = find_registered_patient_by_phone(phone)
    if not patient:
        return respond_error("Phone not registered.", status=404)

    ok, cooldown_left = generate_otp(phone)
    if not ok:
        if cooldown_left > 0:
            return respond_error(
                f"Please wait {cooldown_left} second(s) before requesting another OTP.",
                cooldown=cooldown_left
            )
        return respond_error("OTP could not be sent. Please try again.")

    masked = mask_phone(phone)
    if wants_json:
        return jsonify({"ok": True, "phone": phone, "masked_phone": masked,
                        "message": "A new OTP has been sent to your phone.",
                        "cooldown": OTP_RESEND_COOLDOWN_SECONDS})
    return render_template(
        "patient_login.html",
        step="otp",
        phone=phone,
        masked_phone=masked,
        error=None,
        message="A new OTP has been sent to your phone."
    )

@app.route("/patient/verify-otp", methods=["POST"])
def patient_verify_otp():
    phone = normalize_phone(request.form.get("phone", ""))
    entered_otp = request.form.get("otp", "")
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    verified, message, attempts_left = verify_otp(phone, entered_otp)
    if not verified:
        restart = "No OTP was requested" in message or "expired" in message.lower() or "Too many" in message
        if wants_json:
            return jsonify({
                "ok": False,
                "error": message,
                "restart": restart,
                "attempts_left": attempts_left
            }), 400
        return render_template(
            "patient_login.html",
            step="phone" if restart else "otp",
            phone=phone,
            masked_phone=mask_phone(phone),
            error=message,
            message=None
        ), 400

    patient = find_registered_patient_by_phone(phone)
    if not patient:
        if wants_json:
            return jsonify({"ok": False, "error": "Patient record could not be found. Please contact the clinic.", "restart": True}), 400
        return render_template(
            "patient_login.html",
            step="phone",
            phone=phone,
            masked_phone="",
            error="Patient record could not be found. Please contact the clinic.",
            message=None
        ), 400

    session.clear()
    session["logged_in"] = True
    session["role"] = "Patient"
    session["username"] = patient["name"]
    session["patient_id"] = patient["id"]
    session["patient_name"] = patient["name"]
    session["patient_phone"] = phone
    if wants_json:
        return jsonify({"ok": True, "redirect": url_for("patient_dashboard")})
    return redirect(url_for("patient_dashboard"))

@app.route("/patient/logout", methods=["POST"])
@require_role("Patient")
def patient_logout():
    session.clear()
    return redirect(url_for("patient_login"))

@app.route("/patient/dashboard")
@require_role("Patient")
def patient_dashboard():
    patient_id = session["patient_id"]
    run_expiry_check()
    patient = find_patient_by_id(patient_id)
    upcoming_appointments, appointment_history = decorate_patient_appointments(patient_id)
    pending_requests = read_pending_requests_for_patient(patient_id)
    medical_records = read_diagnosis_for_patient(patient_id)
    bills = read_bills_for_patient(patient_id)
    has_blocking_bill = has_blocking_unpaid_bill(patient_id)
    outstanding_total = sum(
        float(b.get("total", 0))
        for b in bills
        if str(b.get("status", "")).upper() in {"PENDING", "INITIATED"}
    )
    # NEW: load prescriptions for patient
    patient_prescriptions = []
    for appt in read_appointments():
        if appt.get("patient_id") != int(patient_id):
            continue
        if appt.get("status") != "Completed":
            continue
        rx_header, rx_meds = find_prescription_by_appointment(appt["appointment_id"])
        if rx_header:
            patient_prescriptions.append({
                "prescription_id": rx_header["prescription_id"],
                "date": rx_header["date"],
                "human_date": format_human_date(rx_header["date"]),
                "doctor_name": next((d["name"] for d in get_doctors() if d["id"] == rx_header["doctor_id"]), "Doctor"),
                "diagnosis_summary": rx_header.get("diagnosis_summary", ""),
                "medicine_count": len(rx_meds),
            })
    patient_prescriptions.sort(key=lambda x: parse_iso_date(x["date"]) or date.min, reverse=True)
    return render_template(
        "patient_dashboard.html",
        patient=patient,
        upcoming_appointments=upcoming_appointments,
        pending_requests=pending_requests,
        appointment_history=appointment_history,
        medical_records=medical_records,
        bills=bills,
        status_note=request.args.get("status_note", ""),
        clinic_phone=os.environ.get("CLINIC_PHONE", DEFAULT_CLINIC_PHONE),
        masked_phone=mask_phone(session.get("patient_phone", patient.get("phone", "") if patient else "")),
        has_blocking_bill=has_blocking_bill,
        outstanding_total=outstanding_total,
        patient_prescriptions=patient_prescriptions,
    )

@app.route("/patient/bills/<int:bill_id>/pdf")
@require_role("Patient")
def patient_bill_pdf(bill_id):
    bill = find_bill_by_id(bill_id)
    if not patient_owns_bill(bill, session["patient_id"]):
        return "Bill not found", 404

    response = make_response(build_bill_pdf(bill))
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=healthdesk-bill-{bill_id}.pdf"
    return response

@app.route("/patient/payment/create-order", methods=["POST"])
@require_role("Patient")
def patient_payment_create_order():
    if not payments_configured():
        return jsonify({"ok": False, "error": "Payments are not configured yet."}), 503

    revert_stale_initiated_payments()
    bill_id = safe_int(request.form.get("bill_id", "0"))
    bill = find_bill_by_id(bill_id)
    if not patient_owns_bill(bill, session["patient_id"]):
        return jsonify({"ok": False, "error": "Bill not found."}), 404

    status = str(bill.get("status", "")).upper()
    if status not in {"PENDING", "INITIATED"}:
        return jsonify({"ok": False, "error": "This bill is not payable online."}), 409
    if float(bill.get("total", 0) or 0) <= 0:
        return jsonify({"ok": False, "error": "This bill has no payable amount."}), 400

    if status == "INITIATED" and bill.get("razorpay_order_id"):
        if not bill.get("initiated_at") and bill.get("paid_at"):
            bill["initiated_at"] = bill["paid_at"]
            bill["paid_at"] = ""
            update_bill_record(bill)
        order = {
            "id": bill["razorpay_order_id"],
            "amount": int(round(float(bill["total"]) * 100)),
            "currency": "INR"
        }
    else:
        ok, error, order = create_payment_order(
            bill["total"],
            receipt=f"HDBILL{bill['bill_id']}",
            notes={
                "bill_id": str(bill["bill_id"]),
                "patient_id": str(bill["patient_id"]),
                "appointment_id": str(bill.get("appointment_id", 0) or 0)
            }
        )
        if not ok:
            print(f"[HealthDesk Payment] order creation failed: {error}")
            return jsonify({"ok": False, "error": "Could not start payment. Please try again or pay at the counter."}), 503
        bill["status"] = "INITIATED"
        bill["razorpay_order_id"] = order.get("id", "")
        bill["razorpay_payment_id"] = ""
        bill["payment_method"] = "razorpay"
        bill["paid_at"] = ""
        bill["initiated_at"] = iso_now()
        update_bill_record(bill)

    return jsonify({
        "ok": True,
        "key": get_razorpay_key_id(),
        "order_id": order.get("id"),
        "amount": order.get("amount"),
        "currency": order.get("currency", "INR"),
        "clinic_name": "HealthDesk Clinic",
        "description": f"Bill #{bill['bill_id']}",
        "patient_name": bill.get("name", session.get("patient_name", "")),
        "patient_phone": session.get("patient_phone", ""),
        "bill_id": bill["bill_id"]
    })

@app.route("/payment/webhook", methods=["POST"])
def payment_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(raw_body, signature):
        return "Invalid signature", 400

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except ValueError:
        return "Invalid payload", 400

    event = payload.get("event", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment.get("order_id", "")
    bill = find_bill_by_razorpay_order_id(order_id)
    if not bill:
        print(f"[HealthDesk Payment] webhook ignored: no bill for order {order_id}")
        return jsonify({"ok": True})

    patient = find_patient_by_id(bill.get("patient_id"))
    method = payment.get("method") or "razorpay"
    payment_id = payment.get("id", "")

    if event == "payment.captured":
        if str(bill.get("status", "")).upper() != "PAID":
            bill["status"] = "PAID"
            bill["razorpay_payment_id"] = payment_id
            bill["payment_method"] = method
            bill["paid_at"] = iso_now()
            bill["initiated_at"] = ""
            update_bill_record(bill)
            if patient:
                send_sms_notice(patient["phone"], f"Payment of {format_amount(bill['total'])} received for your {format_human_date(bill['date'])} visit. Bill available in your portal.")
    elif event == "payment.failed":
        bill["status"] = "PENDING"
        bill["razorpay_payment_id"] = payment_id
        bill["payment_method"] = method
        bill["paid_at"] = ""
        bill["initiated_at"] = ""
        update_bill_record(bill)
        if patient:
            send_sms_notice(patient["phone"], "Payment failed. Please retry in your portal or pay at the counter.")

    return jsonify({"ok": True})

@app.route("/payment/webhook/advance", methods=["POST"])
def payment_webhook_advance():
    from payment_service import verify_webhook_signature
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(raw_body, signature):
        return "", 400

    try:
        payload = json.loads(raw_body)
    except Exception:
        return "", 400

    event = payload.get("event", "")
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment_entity.get("order_id", "")
    payment_id = payment_entity.get("id", "")

    adv = find_advance_by_order_id(order_id)
    if not adv:
        return "", 200

    if event == "payment.captured":
        if adv["status"] == "PAID":
            return "", 200
        adv["status"] = "PAID"
        adv["razorpay_payment_id"] = payment_id
        adv["paid_at"] = iso_now()
        update_advance_record(adv)
        _confirm_booking_after_advance(adv)
    elif event == "payment.failed":
        adv["status"] = "EXPIRED"
        adv["settled_at"] = iso_now()
        update_advance_record(adv)
        patient = find_patient_by_id(adv["patient_id"])
        if patient:
            send_sms_notice(
                patient["phone"],
                "Your HealthDesk booking payment failed. No charge was made. Please try booking again."
            )

    return "", 200

@app.route("/patient/book")
@require_role("Patient")
def patient_book():
    patient = find_patient_by_id(session["patient_id"])
    if not patient:
        return redirect(url_for("patient_dashboard"))
    if has_blocking_unpaid_bill(session["patient_id"]):
        return redirect(url_for(
            "patient_dashboard",
            status_note="You have an outstanding bill older than 7 days. Please clear your dues before booking a new appointment."
        ))
    departments = sorted({doctor["department"] for doctor in get_doctors()})
    doctors = get_doctors()
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(7)]
    status_note = request.args.get("status_note", "")
    return render_template(
        "patient_book.html",
        patient=patient,
        departments=departments,
        doctors=doctors,
        week_dates=week_dates,
        status_note=status_note,
        is_new_patient=False
    )

@app.route("/patient/advance/pay")
@require_role("Patient")
def patient_advance_pay():
    advance_id = safe_int(request.args.get("advance_id", "0"))
    adv = find_advance_by_id(advance_id)
    if (not adv
            or adv["patient_id"] != int(session["patient_id"])
            or adv["status"] != "PENDING_PAYMENT"):
        return redirect(url_for(
            "patient_dashboard",
            status_note="Booking session expired. Please try booking again."
        ))
    doctor = get_doctor_by_id(adv["doctor_id"]) or {}
    followup_corrected = session.pop("followup_corrected", False)
    return render_template(
        "patient_advance_pay.html",
        advance=adv,
        doctor=doctor,
        razorpay_key=get_razorpay_key_id(),
        payments_configured=payments_configured(),
        followup_corrected=followup_corrected,
    )


@app.route("/patient/advance/create-order", methods=["POST"])
@require_role("Patient")
def patient_advance_create_order():
    from payment_service import create_advance_order
    advance_id = safe_int(request.form.get("advance_id", "0"))
    adv = find_advance_by_id(advance_id)
    if (not adv
            or adv["patient_id"] != int(session["patient_id"])
            or adv["status"] != "PENDING_PAYMENT"):
        return jsonify({"ok": False, "error": "Invalid or expired booking session."}), 400

    patient = find_patient_by_id(session["patient_id"])
    ok, error, order = create_advance_order(
        amount_rupees=adv["amount"],
        advance_id=adv["advance_id"],
        patient_name=patient.get("name", "") if patient else "",
    )
    if not ok:
        return jsonify({"ok": False, "error": error}), 503

    adv["razorpay_order_id"] = order.get("id", "")
    update_advance_record(adv)

    return jsonify({
        "ok": True,
        "key": get_razorpay_key_id(),
        "order_id": order.get("id"),
        "amount": order.get("amount"),
        "advance_id": adv["advance_id"],
        "currency": "INR",
    })

@app.route("/patient/book/slots")
@require_role("Patient")
def patient_book_slots():
    return patient_slots_response()

@app.route("/patient/new/slots")
def new_patient_slots():
    return patient_slots_response()

def patient_slots_response():
    department = clean_record_field(request.args.get("department", ""))
    doctor_id = request.args.get("doctor_id", "any")
    requested_date = clean_record_field(request.args.get("date", ""))
    parsed_date = parse_iso_date(requested_date)
    if not department or not parsed_date or parsed_date < date.today():
        return jsonify({"ok": False, "error": "Choose today or a future date."}), 400
    slots = build_patient_slot_payload(department, doctor_id, requested_date)
    return jsonify({"ok": True, "slots": slots})

@app.route("/patient/new")
def new_patient_request():
    departments = sorted({doctor["department"] for doctor in get_doctors()})
    doctors = get_doctors()
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(7)]
    return render_template(
        "patient_book.html",
        patient=None,
        departments=departments,
        doctors=doctors,
        week_dates=week_dates,
        status_note=request.args.get("status_note", ""),
        is_new_patient=True
    )

@app.route("/patient/new/submit", methods=["POST"])
def new_patient_submit():
    required = ["name", "age", "gender", "phone", "address", "department", "doctor_id", "requested_date", "requested_slot", "reason"]
    if any(not str(request.form.get(field, "")).strip() for field in required):
        return redirect(url_for("new_patient_request", status_note="Please complete all required details."))
    phone = normalize_phone(request.form.get("phone", ""))
    if not is_valid_patient_phone(phone):
        return redirect(url_for("new_patient_request", status_note="Enter a valid 10-digit phone number."))
    if not is_valid_age(request.form.get("age", "")):
        return redirect(url_for("new_patient_request", status_note="Enter an age between 1 and 120."))
    if find_registered_patient_by_phone(phone):
        return redirect(url_for("patient_login", status_note="This phone number is already registered. Please login with OTP."))
    requested_date = clean_record_field(request.form.get("requested_date", ""))
    requested_slot = clean_record_field(request.form.get("requested_slot", ""))
    parsed_date = parse_iso_date(requested_date)
    if not parsed_date or parsed_date < date.today():
        return redirect(url_for("new_patient_request", status_note="Choose today or a future appointment date."))
    doctor = get_doctor_by_id(safe_int(request.form.get("doctor_id", "0")))
    if not doctor or doctor["department"] != request.form.get("department", ""):
        return redirect(url_for("new_patient_request", status_note="Choose a valid doctor and department."))
    if pending_slot_exists(doctor["id"], requested_date, requested_slot) or not slot_is_available(doctor["id"], requested_date, requested_slot):
        return redirect(url_for("new_patient_request", status_note="That slot is no longer available. Please choose another."))
    row = create_new_patient_request(request.form)
    send_sms_notice(phone, f"Your first-time appointment request for {format_human_date(requested_date)}, {requested_slot} has been sent. Reception will verify and confirm within 2 hours.")
    notify_receptionists(f"New first-time request from {row['name']} ({row['phone']}) for {doctor['name']}, {format_human_date(requested_date)}, {requested_slot}. Review dashboard.")
    return render_template("new_patient_request_submitted.html", request_row=decorate_new_patient_request(row), clinic_phone=os.environ.get("CLINIC_PHONE", DEFAULT_CLINIC_PHONE))

@app.route("/patient/book/submit", methods=["POST"])
@require_role("Patient")
def patient_book_submit():
    patient = find_patient_by_id(session["patient_id"])
    if not patient:
        return redirect(url_for("patient_dashboard"))
    if has_blocking_unpaid_bill(session["patient_id"]):
        return redirect(url_for(
            "patient_dashboard",
            status_note="You have an outstanding bill older than 7 days. Please clear your dues before booking."
        ))
    department = clean_record_field(request.form.get("department", ""))
    doctor_id_raw = request.form.get("doctor_id", "")
    requested_date = clean_record_field(request.form.get("requested_date", ""))
    requested_slot = clean_record_field(request.form.get("requested_slot", ""))
    reason = clean_record_field(request.form.get("reason", ""), 220)
    visit_type = clean_record_field(request.form.get("visit_type", "New"))
    if visit_type not in {"New", "Follow-up"}:
        visit_type = "New"
    followup_corrected = False
    parsed_date = parse_iso_date(requested_date)
    if not department or not parsed_date or parsed_date < date.today() or not requested_slot:
        return redirect(url_for("patient_book", status_note="Choose a department, today or a future date, and an available slot."))
    if find_booked_appointment_for_patient_on_date(session["patient_id"], requested_date):
        return redirect(url_for("patient_book", status_note="You already have a booked appointment for that date."))

    if doctor_id_raw == "any":
        doctor = choose_any_available_doctor(department, requested_date, requested_slot)
        if not doctor:
            return redirect(url_for("patient_book", status_note="No doctor is available for that slot. Please choose another time."))
        doctor_id = doctor["id"]
    else:
        doctor_id = safe_int(doctor_id_raw)
        doctor = get_doctor_by_id(doctor_id)
        if not doctor or doctor["department"] != department:
            return redirect(url_for("patient_book", status_note="Choose a valid doctor for this department."))
        if not slot_is_available(doctor_id, requested_date, requested_slot):
            return redirect(url_for("patient_book", status_note="That slot is no longer available. Please choose another."))

        if visit_type == "Follow-up":
            if not patient_has_completed_visit_with_doctor(session["patient_id"], doctor_id):
                visit_type = "New"
                followup_corrected = True

    # --- FIX 4: bypass advance flow entirely when payments are not configured ---
    if not payments_configured():
        triage, reasons = triage_booking_request(doctor_id, requested_date, visit_type)
        if triage == "auto":
            ok, message, _row = auto_approve_booking(
                patient, doctor_id, requested_date, requested_slot, reason, visit_type
            )
            if ok:
                return redirect(url_for("patient_dashboard", status_note="Your appointment has been confirmed."))
            return redirect(url_for("patient_book", status_note=message))
        else:
            ok, message, _row = exception_queue_booking(
                patient, doctor_id, requested_date, requested_slot, reason, visit_type, triage_reasons=reasons
            )
            if ok:
                return redirect(url_for("patient_dashboard", status_note="Your booking request has been submitted and is under review."))
            return redirect(url_for("patient_book", status_note=message))
    # --- end FIX 4 ---

    triage, reasons = triage_booking_request(doctor_id, requested_date, visit_type)

    advance_amount = get_advance_amount_for_department(department)

    # --- FIX 5: follow-up visits skip advance (exception-queue still applies) ---
    if visit_type == "Follow-up":
        advance_amount = 0.0
    # --- end FIX 5 ---

    # --- FIX 2: bypass advance if amount is zero (department fee not configured or zero) ---
    if advance_amount <= 0:
        if triage == "auto":
            ok, message, _row = auto_approve_booking(
                patient, doctor_id, requested_date, requested_slot, reason, visit_type
            )
            if ok:
                return redirect(url_for("patient_dashboard", status_note="Your appointment has been confirmed."))
            return redirect(url_for("patient_book", status_note=message))
        else:
            ok, message, _row = exception_queue_booking(
                patient, doctor_id, requested_date, requested_slot, reason, visit_type, triage_reasons=reasons
            )
            if ok:
                return redirect(url_for("patient_dashboard", status_note="Your booking request has been submitted and is under review."))
            return redirect(url_for("patient_book", status_note=message))
    # --- end FIX 2 ---

    adv = create_advance_record(
        patient_id=session["patient_id"],
        doctor_id=doctor_id,
        appointment_date=requested_date,
        amount=advance_amount,
        pending_request_id=0,
    )
    save_booking_intent(
        adv["advance_id"], doctor_id, requested_date,
        requested_slot, reason, visit_type, triage
    )
    if followup_corrected:
        session["followup_corrected"] = True
    return redirect(url_for("patient_advance_pay", advance_id=adv["advance_id"]))

@app.route("/patient/cancel", methods=["POST"])
@require_role("Patient")
def patient_cancel_appointment():
    appointment_id = safe_int(request.form.get("appointment_id", "0"))
    appointment = find_appointment_by_id(appointment_id)
    if not appointment or appointment["patient_id"] != int(session["patient_id"]):
        return redirect(url_for("patient_dashboard", status_note="Appointment not found."))
    appointment_dt = parse_appointment_datetime(appointment)
    if appointment["status"] != "Booked":
        return redirect(url_for("patient_dashboard", status_note="Only confirmed upcoming appointments can be cancelled."))
    if appointment_dt - datetime.now() <= timedelta(hours=24):
        return redirect(url_for("patient_dashboard", status_note="To cancel within 24 hours, please call the clinic."))
    adv = find_advance_by_appointment_id(appointment_id)
    if adv and adv["status"] == "PAID":
        from payment_service import initiate_refund
        ok_refund, err_refund = initiate_refund(adv["razorpay_payment_id"], adv["amount"])
        if not ok_refund:
            return redirect(url_for(
                "patient_dashboard",
                status_note=f"Refund could not be initiated: {err_refund}. Please call the clinic to cancel."
            ))
        adv["status"] = "REFUNDED"
        adv["settled_at"] = iso_now()
        update_advance_record(adv)
    result = run_appointment_command("cancel", appointment_id)
    if result.returncode == 0:
        update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
        patient = find_patient_by_id(appointment["patient_id"])
        doctor = get_doctor_by_id(appointment["doctor_id"]) or {}
        if patient:
            refund_note = (f" Advance of Rs.{adv['amount']:.0f} refunded in 5-7 business days."
                          if adv and adv["status"] == "REFUNDED" else "")
            send_sms_notice(
                patient["phone"],
                f"Your appointment with {doctor.get('name', 'the doctor')} on "
                f"{format_human_date(appointment['date'])} has been cancelled.{refund_note}"
            )
        return redirect(url_for(
            "patient_dashboard",
            status_note="Your appointment was cancelled." + (" Advance refund initiated." if adv else "")
        ))
    return redirect(url_for("patient_dashboard", status_note="Could not cancel the appointment. Please call the clinic."))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    lockout_seconds = 0
    username_prefill = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        username_prefill = username

        # Check lockout
        with _login_lockout_lock:
            record = _login_lockout_store.get(username, {})
            locked_until = record.get("locked_until")
            if locked_until and datetime.now() < locked_until:
                remaining = int((locked_until - datetime.now()).total_seconds())
                return render_template(
                    "login.html",
                    error=f"Account locked after {LOGIN_MAX_ATTEMPTS} failed attempts. Try again in {remaining} second(s).",
                    lockout_seconds=remaining,
                    username=username_prefill
                )
            # If lockout expired, reset
            if locked_until and datetime.now() >= locked_until:
                _login_lockout_store.pop(username, None)

        user = authenticate_user(username, password)

        if user:
            if user["role"] not in {"Receptionist", "Doctor"}:
                error = "Unauthorized role."
                return render_template("login.html", error=error, username=username_prefill)
            if user["role"] == "Doctor" and int(user["doctor_id"] or 0) <= 0:
                error = "Invalid doctor account mapping."
                return render_template("login.html", error=error, username=username_prefill)
            if user["role"] == "Doctor" and not any(d["id"] == int(user["doctor_id"]) for d in get_doctors()):
                error = "Doctor account is not linked to an active doctor profile."
                return render_template("login.html", error=error, username=username_prefill)

            # Successful login — clear lockout record
            with _login_lockout_lock:
                _login_lockout_store.pop(username, None)

            session["logged_in"] = True
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["doctor_id"] = user["doctor_id"]
            if user["role"] == "Receptionist":
                return redirect("/receptionist_dashboard")
            if user["role"] == "Doctor":
                return redirect("/doctor")
            return redirect("/")

        # Failed login — increment attempt counter
        with _login_lockout_lock:
            record = _login_lockout_store.setdefault(username, {"attempts": 0, "locked_until": None})
            record["attempts"] += 1
            if record["attempts"] >= LOGIN_MAX_ATTEMPTS:
                record["locked_until"] = datetime.now() + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
                lockout_seconds = LOGIN_LOCKOUT_SECONDS
                error = (f"Too many failed attempts. Account locked for {LOGIN_LOCKOUT_SECONDS // 60} minute(s).")
            else:
                attempts_left = LOGIN_MAX_ATTEMPTS - record["attempts"]
                error = f"Invalid username or password. {attempts_left} attempt(s) remaining before lockout."

    return render_template(
        "login.html",
        error=error,
        lockout_seconds=lockout_seconds,
        username=username_prefill
    )

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")

@app.route("/receptionist")
@require_role("Receptionist")
def receptionist_redirect():
    return redirect("/receptionist_dashboard")

@app.route("/reception", methods=["GET", "POST"])
@require_role("Receptionist")
def reception():
    patient = None
    message = request.args.get("status_note", "") or None
    show_registration = False
    phone = request.values.get("phone", "").strip()
    patient_id = request.values.get("patient_id", "").strip()
    doctors = get_doctors()
    selected_department = request.values.get("department", "")
    selected_doctor = request.values.get("doctor_id", "")
    selected_date = request.values.get("date", date.today().isoformat())
    slots = []
    suggested_doctors = []
    selected_doctor_info = None
    booking_status = request.args.get("booking_status", "")
    queue_token = request.args.get("queue_token", "")
    queue_doctor_id = request.args.get("queue_doctor_id", "")

    if patient_id:
        patient = find_patient_by_id(patient_id)

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "search":
            phone = request.form.get("phone", "").strip()
            if not is_valid_phone(phone):
                message = "Enter a valid 10-digit phone number."
                return render_template(
                    "reception.html",
                    patient=patient,
                    message=message,
                    phone=phone,
                    show_registration=show_registration,
                    doctors=doctors,
                    slots=slots,
                    selected_doctor=selected_doctor,
                    selected_doctor_info=selected_doctor_info,
                    selected_department=selected_department,
                    selected_date=selected_date,
                    suggested_doctors=suggested_doctors,
                    booking_status=booking_status,
                    queue_token=queue_token,
                    queue_doctor_id=queue_doctor_id
                )
            patient = find_patient_by_phone(phone)
            if not patient:
                show_registration = True
                message = "Patient not found. Register the patient to continue."

        elif action == "register":
            name = clean_record_field(request.form["name"])
            age = request.form["age"].strip()
            gender = clean_record_field(request.form["gender"])
            phone = clean_record_field(request.form["phone"])
            address = clean_record_field(request.form["address"])
            symptoms = clean_record_field(request.form["symptoms"])
            visit_type = clean_record_field(request.form["visit_type"])
            priority = clean_record_field(request.form["priority"])
            department = clean_record_field(request.form["department"])
            if not all([name, age, gender, phone, address, symptoms, visit_type, priority, department]):
                show_registration = True
                message = "All patient registration fields are required."
            elif not is_valid_phone(phone):
                show_registration = True
                message = "Phone must be 10 digits."
            elif not is_valid_age(age):
                show_registration = True
                message = "Age must be between 1 and 120."
            elif find_patient_by_phone(phone):
                patient = find_patient_by_phone(phone)
                selected_department = patient["department"]
                message = "Patient already exists. Continue with appointment booking."
                show_registration = False
            else:
                exe_path = os.path.join(BACKEND_DIR, "c_modules", "patient.exe")
                data_string = f"{name}|{age}|{gender}|{phone}|{address}|{symptoms}|{visit_type}|{priority}|{department}"
                patient_output = subprocess.run(
                    [exe_path, data_string],
                    capture_output=True,
                    text=True,
                    cwd=BASE_DIR
                )

                data = patient_output.stdout.strip().split("|")
                if len(data) >= 3:
                    patient = find_patient_by_id(data[0])
                    selected_department = department
                    message = "Patient registered. Choose an appointment slot."
                else:
                    show_registration = True
                    message = "Could not register patient. Please check the details."

    if patient:
        if not selected_department:
            selected_department = patient["department"]

        if selected_doctor:
            slots = load_appointment_slots(selected_doctor, selected_date)
            suggested_doctors = get_suggested_doctors(selected_department, selected_doctor, selected_date)
            selected_doctor_info = next(
                (doctor for doctor in doctors if str(doctor["id"]) == str(selected_doctor)),
                None
            )

    return render_template(
        "reception.html",
        patient=patient,
        message=message,
        phone=phone,
        show_registration=show_registration,
        doctors=doctors,
        slots=slots,
        selected_doctor=selected_doctor,
        selected_doctor_info=selected_doctor_info,
        selected_department=selected_department,
        selected_date=selected_date,
        suggested_doctors=suggested_doctors,
        booking_status=booking_status,
        queue_token=queue_token,
        queue_doctor_id=queue_doctor_id
    )

@app.route("/receptionist_dashboard")
@require_role("Receptionist")
def receptionist_dashboard_page():
    expire_stale_consultations()
    run_expiry_check()
    queue = reconcile_waiting_queue_entries()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)
    appointments = read_appointments()
    booked_count = len([a for a in appointments if a["status"] == "Booked"])
    cancelled_count = len([a for a in appointments if a["status"] == "Cancelled"])
    available_doctors = count_available_doctors()
    today_str = date.today().strftime("%A, %d %B %Y")

    return render_template(
        "receptionist_dashboard.html",
        waiting_count=waiting_count,
        completed_count=completed_count,
        booked_count=booked_count,
        cancelled_count=cancelled_count,
        available_doctors=available_doctors,
        next_patient=next_patient,
        today=today_str,
        pending_patient_requests=read_pending_requests_for_reception(),
        pending_new_patient_requests=read_new_patient_requests_for_reception(),
        advances_attention=get_advances_needing_attention(),
        status_note=request.args.get("status_note", "")
    )

@app.route("/reception/pending")
@require_role("Receptionist")
def reception_pending():
    return redirect(url_for("receptionist_dashboard_page"))

@app.route("/reception/approve", methods=["POST"])
@require_role("Receptionist")
def reception_approve_request():
    request_type = request.form.get("request_type", "existing")
    request_id = safe_int(request.form.get("request_id", "0"))
    if request_type == "new":
        row = next((item for item in read_all_new_patient_requests() if item["request_id"] == request_id), None)
        if not row or row["status"] != "Pending":
            return redirect(url_for("receptionist_dashboard_page", status_note="Request is no longer pending."))
        if not slot_is_available(row["doctor_id"], row["requested_date"], row["requested_slot"]):
            return redirect(url_for("receptionist_dashboard_page", status_note="This slot was booked while the request was pending. Reject it and ask the patient to choose another slot."))
        patient = register_patient_from_request(row)
        if not patient:
            return redirect(url_for("receptionist_dashboard_page", status_note="Could not create the patient record. Please review the request details."))
        if find_booked_appointment_for_patient_on_date(patient["id"], row["requested_date"]):
            return redirect(url_for("receptionist_dashboard_page", status_note="This patient already has a booked appointment for that date."))
        result = run_appointment_command("book", patient["id"], row["doctor_id"], row["requested_date"], row["requested_slot"])
        appointment_id = parse_booked_appointment_id(result)
        if not appointment_id:
            return redirect(url_for("receptionist_dashboard_page", status_note="Could not book the slot. It may have just been taken."))
        update_new_patient_request_status(request_id, "Approved", "Registered and approved by reception", patient_id=patient["id"], appointment_id=appointment_id)
        doctor = get_doctor_by_id(row["doctor_id"]) or {}
        send_sms_notice(row["phone"], f"Confirmed! {doctor.get('name', 'Doctor')}, {format_human_date(row['requested_date'])}, {row['requested_slot']}. Please arrive 10 min early.")
        return redirect(url_for("receptionist_dashboard_page", status_note="First-time patient request approved and appointment booked."))

    row = next((item for item in read_all_pending_requests() if item["request_id"] == request_id), None)
    if not row or row["status"] != "Pending":
        return redirect(url_for("receptionist_dashboard_page", status_note="Request is no longer pending."))
    if not slot_is_available(row["doctor_id"], row["requested_date"], row["requested_slot"]):
        return redirect(url_for("receptionist_dashboard_page", status_note="This slot was booked while the request was pending. Reject it and ask the patient to choose another slot."))
    if find_booked_appointment_for_patient_on_date(row["patient_id"], row["requested_date"]):
        return redirect(url_for("receptionist_dashboard_page", status_note="This patient already has a booked appointment for that date."))
    result = run_appointment_command("book", row["patient_id"], row["doctor_id"], row["requested_date"], row["requested_slot"])
    appointment_id = parse_booked_appointment_id(result)
    if not appointment_id:
        return redirect(url_for("receptionist_dashboard_page", status_note="Could not book the slot. It may have just been taken."))
    update_pending_status(request_id, "Approved", "Approved by reception", appointment_id=appointment_id)
    patient = find_patient_by_id(row["patient_id"])
    doctor = get_doctor_by_id(row["doctor_id"]) or {}
    if patient:
        send_sms_notice(patient["phone"], f"Confirmed! {doctor.get('name', 'Doctor')}, {format_human_date(row['requested_date'])}, {row['requested_slot']}. Please arrive 10 min early.")
    return redirect(url_for("receptionist_dashboard_page", status_note="Patient request approved and appointment booked."))

@app.route("/reception/reject", methods=["POST"])
@require_role("Receptionist")
def reception_reject_request():
    request_type = request.form.get("request_type", "existing")
    request_id = safe_int(request.form.get("request_id", "0"))
    reason = clean_record_field(request.form.get("receptionist_note", ""), 220)
    if not reason:
        return redirect(url_for("receptionist_dashboard_page", status_note="A rejection reason is required."))
    if request_type == "new":
        row = update_new_patient_request_status(request_id, "Rejected", reason)
        if row:
            send_sms_notice(row["phone"], f"Request not confirmed. Reason: {reason}. Please submit again or call the clinic.")
        return redirect(url_for("receptionist_dashboard_page", status_note="First-time patient request rejected."))
    row = update_pending_status(request_id, "Rejected", reason)
    if row:
        patient = find_patient_by_id(row["patient_id"])
        adv = next((a for a in read_advances()
                    if a["pending_request_id"] == request_id
                    and a["status"] == "PAID"), None)
        if adv:
            from payment_service import initiate_refund
            ok_refund, err_refund = initiate_refund(adv["razorpay_payment_id"], adv["amount"])
            if ok_refund:
                adv["status"] = "REFUNDED"
                adv["settled_at"] = iso_now()
                update_advance_record(adv)
            else:
                print(f"[HealthDesk] Advance refund failed on rejection, advance {adv['advance_id']}: {err_refund}")
        if patient:
            refund_note = (f" Advance of Rs.{adv['amount']:.0f} refunded in 5-7 business days."
                          if adv and adv.get("status") == "REFUNDED" else "")
            send_sms_notice(patient["phone"], f"Request not confirmed. Reason: {reason}. Log in to rebook.{refund_note}")
    return redirect(url_for("receptionist_dashboard_page", status_note="Patient request rejected."))

@app.route("/doctor")
@require_role("Doctor")
def doctor_dashboard():
    doctor_id = int(session.get("doctor_id", "0") or 0)
    billing_patient_id = request.args.get("billing_patient_id", "")
    billing_doctor_id = request.args.get("doctor_id", str(doctor_id))
    billing_bill_id = request.args.get("bill_id", "")
    status_note = request.args.get("status_note", "")
    dashboard_context = build_doctor_dashboard_context(doctor_id)
    return render_template(
        "doctor_dashboard.html",
        billing_patient_id=billing_patient_id,
        billing_doctor_id=billing_doctor_id,
        billing_bill_id=billing_bill_id,
        status_note=status_note,
        today_iso=date.today().isoformat(),
        **dashboard_context
    )


def build_doctor_dashboard_context(doctor_id):
    expire_stale_consultations()
    auto_queue_todays_appointments()
    reconcile_waiting_queue_entries()
    appointments = [
        a for a in read_appointments()
        if a["doctor_id"] == doctor_id and a["status"] == "Booked" and is_future_appointment(a)
    ]
    appointments.sort(key=lambda x: (x["date"], x["time_slot"]))
    
    # NEW: Fetch ALL vitals for this doctor in one go
    vitals_map = get_doctor_vitals_dict(doctor_id)

    queue_patients = read_assigned_queue_patients(doctor_id)
    # Attach vitals to each queue patient — remap field names to short aliases
    # that the doctor_dashboard_panels.html template uses
    for qp in queue_patients:
        raw = vitals_map.get(qp["patient_id"])
        if raw:
            qp["vitals"] = {
                "temp":       raw.get("temperature", ""),
                "bp_sys":     raw.get("bp_systolic", ""),
                "bp_dia":     raw.get("bp_diastolic", ""),
                "pulse":      raw.get("pulse_rate", ""),
                "weight":     raw.get("weight", ""),
                "spo2":       raw.get("oxygen_level", ""),
                "sugar":      raw.get("sugar_level", ""),
                "allergies":  raw.get("allergy_conditions", ""),
                "conditions": raw.get("health_conditions", ""),
                "notes":      raw.get("notes", ""),
                "smoking":    raw.get("smoking_habit", ""),
                "drinking":   raw.get("drinking_habit", ""),
                "recorded_at":raw.get("recorded_at", ""),
            }
        else:
            qp["vitals"] = None
    live_queue_patients = queue_patients

    doctor_info = next((d for d in get_doctors() if d["id"] == doctor_id), None)
    return {
        "appointments": appointments,
        "queue_patients": queue_patients,
        "live_queue_patients": live_queue_patients,
        "doctor_info": doctor_info,
    }


@app.route("/doctor/dashboard-panels")
@require_role("Doctor")
def doctor_dashboard_panels():
    doctor_id = int(session.get("doctor_id", "0") or 0)
    return render_template(
        "doctor_dashboard_panels.html",
        **build_doctor_dashboard_context(doctor_id)
    )

@app.route("/queue")
@require_role("Receptionist")
def queue_page():
    queue_context = build_queue_page_context()
    return render_template(
        "queue.html",
        status_note=request.args.get("status_note", ""),
        **queue_context
    )


def build_reception_queue_groups(queue_items, patients_list):
    """
    Groups queue items by doctor and hydrates with patient info.
    Includes an "Add Vitals" URL and status for each patient.
    """
    doctors = {doctor["id"]: doctor for doctor in get_doctors()}
    patients = {p["id"]: p for p in patients_list}

    groups = {}
    for item in queue_items:
        if item.get("status") != "Waiting":
            continue

        did = item["doctor_id"]
        pid = item["patient_id"]
        
        doctor = doctors.get(did)
        if did not in groups:
            groups[did] = {
                "doctor_id": did,
                "doctor_name": doctor["name"] if doctor else f"Unknown (ID: {did})",
                "department": doctor["department"] if doctor else "",
                "patients": []
            }
        
        patient = patients.get(pid, {})
        entry = {
            "token": item["token"],
            "patient_id": pid,
            "priority": item["priority"],
            "name": patient.get("name", f"Patient {pid}"),
            "symptoms": patient.get("symptoms", ""),
            "outstanding_amount": float(item.get("outstanding_amount", 0) or 0),
            "vitals_recorded": item.get("vitals_recorded", False),
            "vitals_url": item.get("vitals_url", "")
        }

        groups[did]["patients"].append(entry)

    grouped = list(groups.values())
    for group in grouped:
        group["patients"].sort(key=lambda row: (row["priority"] != "Urgent", row["token"]))

    grouped.sort(key=lambda group: (group["doctor_id"] == -1, group["doctor_name"]))
    return grouped

def build_queue_page_context():
    expire_stale_consultations()
    auto_queue_todays_appointments()
    queue = reconcile_waiting_queue_entries()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)
    
    # NEW: Fetch all vitals once instead of N times
    all_vitals = get_all_vitals_dict()
    
    # NEW: Fetch patients once for the queue groups
    patients_list = read_patients()
    
    for entry in queue:
        if entry.get("status") != "Waiting":
            entry["outstanding_amount"] = 0.0
            entry["vitals_url"] = ""
            entry["vitals_recorded"] = False
            continue

        pid = entry.get("patient_id")
        if pid:
            pending = [bill for bill in read_bills_for_patient(pid)
                       if str(bill.get("status", "")).upper() == "PENDING"]
            entry["outstanding_amount"] = sum(float(bill.get("total", 0)) for bill in pending)
        else:
            entry["outstanding_amount"] = 0.0
        
        # Add vitals URL and recording status.
        # Vitals are patient-level history: check by patient_id only.
        # If a patient has had vitals recorded in any prior visit (any doctor),
        # the receptionist should see "Update Vitals" not "Add Vitals".
        did = entry.get("doctor_id")
        if pid and did:
            existing = all_vitals.get(pid)
            entry["vitals_url"] = url_for(
                "vitals_add_page",
                patient_id=pid,
                token=entry.get("token", 0),
                doctor_id=did
            )
            entry["vitals_recorded"] = existing is not None
        else:
            entry["vitals_url"] = ""
            entry["vitals_recorded"] = False
    
    queue_groups = build_reception_queue_groups(queue, patients_list)
    return {
        "queue": queue,
        "queue_groups": queue_groups,
        "next_patient": next_patient,
        "waiting_count": waiting_count,
        "completed_count": completed_count,
    }


@app.route("/queue/panels")
@require_role("Receptionist")
def queue_panels():
    return render_template(
        "queue_panels.html",
        **build_queue_page_context()
    )

@app.route("/appointments")
@require_role("Receptionist")
def appointments_page():
    expire_stale_consultations()
    doctors = get_doctors()
    appointments = read_appointments()
    selected_doctor = request.args.get("doctor_id", "")
    selected_department = request.args.get("department", "")
    selected_date = request.args.get("date", date.today().isoformat())
    status_note = request.args.get("status_note", "")
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(7)]
    slots = []
    suggested_doctors = []

    department_doctors = [d for d in doctors if d["department"] == selected_department] if selected_department else []

    if not selected_doctor and department_doctors:
        selected_doctor = str(department_doctors[0]["id"])

    slots = load_appointment_slots(selected_doctor, selected_date)
    date_slot_overview = []
    if selected_doctor:
        for slot_date in week_dates:
            day_slots = load_appointment_slots(selected_doctor, slot_date)
            available_count = len([slot for slot in day_slots if slot["state"] == "Available"])
            date_slot_overview.append({
                "date": slot_date,
                "available_count": available_count
            })

    suggested_doctors = get_suggested_doctors(selected_department, selected_doctor, selected_date)
    selected_history_date = request.args.get("history_date", "").strip()
    historical_source = [
        a for a in appointments
        if appointment_date_value(a) and appointment_date_value(a) < date.today() - timedelta(days=1)
    ]
    if selected_department:
        doctor_ids_for_department = {
            doctor["id"] for doctor in doctors
            if doctor.get("department") == selected_department
        }
        historical_source = [
            a for a in historical_source
            if a.get("doctor_id") in doctor_ids_for_department
        ]
    if selected_doctor:
        historical_source = [
            a for a in historical_source
            if str(a.get("doctor_id")) == str(selected_doctor)
        ]

    previous_dates = sorted({
        a["date"]
        for a in historical_source
    }, reverse=True)
    if not selected_history_date and previous_dates:
        selected_history_date = previous_dates[0]
    elif selected_history_date and selected_history_date not in previous_dates and previous_dates:
        selected_history_date = previous_dates[0]

    current_appointments = [
        enrich_appointment_workflow_status(a)
        for a in appointments
        if should_show_in_appointments_list(a)
    ]
    action_appointments = [
        a for a in current_appointments
        if str(a.get("status", "")).strip() != "Cancelled"
    ]
    cancelled_appointments = [
        a for a in current_appointments
        if str(a.get("status", "")).strip() == "Cancelled"
    ]
    previous_appointments = [
        enrich_appointment_workflow_status(a)
        for a in historical_source
        if selected_history_date and a.get("date") == selected_history_date
    ]
    doctor_map = {doctor["id"]: doctor for doctor in doctors}
    patient_map = {patient["id"]: patient for patient in read_patients()}
    for appointment in action_appointments:
        doctor = doctor_map.get(appointment["doctor_id"], {})
        patient = patient_map.get(appointment["patient_id"], {})
        appointment["doctor_name"] = doctor.get("name", f"Doctor #{appointment['doctor_id']}")
        appointment["department"] = doctor.get("department") or patient.get("department", "")
        appointment["patient_name"] = patient.get("name", "")
        appointment["patient_phone"] = patient.get("phone", "")
        appointment["patient_age"] = patient.get("age", "")
        appointment["patient_gender"] = patient.get("gender", "")
        appointment["patient_symptoms"] = patient.get("symptoms", "")
        reassign_department = doctor.get("department") or patient.get("department", "")
        unavailable_reason = doctor.get("daily_status") in {"Unavailable", "Off"} or doctor.get("current_status") == "Emergency"
        appointment["reassign_department"] = reassign_department
        appointment["requires_reassign_confirmation"] = unavailable_reason
        appointment["reassign_context_label"] = (
            "Doctor unavailable for this appointment"
            if unavailable_reason
            else "Manual reassignment"
        )
    for appointment in cancelled_appointments:
        doctor = doctor_map.get(appointment["doctor_id"], {})
        patient = patient_map.get(appointment["patient_id"], {})
        appointment["doctor_name"] = doctor.get("name", f"Doctor #{appointment['doctor_id']}")
        appointment["department"] = doctor.get("department") or patient.get("department", "")
        appointment["patient_name"] = patient.get("name", "")
        appointment["patient_phone"] = patient.get("phone", "")
        appointment["patient_age"] = patient.get("age", "")
        appointment["patient_gender"] = patient.get("gender", "")
        appointment["patient_symptoms"] = patient.get("symptoms", "")
    for appointment in previous_appointments:
        doctor = doctor_map.get(appointment["doctor_id"], {})
        patient = patient_map.get(appointment["patient_id"], {})
        appointment["doctor_name"] = doctor.get("name", f"Doctor #{appointment['doctor_id']}")
        appointment["department"] = doctor.get("department") or patient.get("department", "")
        appointment["patient_name"] = patient.get("name", "")
        appointment["patient_phone"] = patient.get("phone", "")
        appointment["patient_age"] = patient.get("age", "")
        appointment["patient_gender"] = patient.get("gender", "")
        appointment["patient_symptoms"] = patient.get("symptoms", "")
    appointment_groups = build_appointment_action_groups(action_appointments, doctors)

    if request.args.get("history_only") == "1":
        return render_template(
            "appointments_history_section.html",
            previous_appointments=previous_appointments,
            previous_dates=previous_dates,
            selected_history_date=selected_history_date,
            selected_department=selected_department,
            selected_doctor=selected_doctor,
            selected_date=selected_date
        )

    return render_template(
        "appointments.html",
        doctors=doctors,
        slots=slots,
        selected_doctor=selected_doctor,
        selected_department=selected_department,
        selected_date=selected_date,
        appointments=current_appointments,
        appointment_groups=appointment_groups,
        cancelled_appointments=cancelled_appointments,
        previous_appointments=previous_appointments,
        previous_dates=previous_dates,
        selected_history_date=selected_history_date,
        suggested_doctors=suggested_doctors,
        week_dates=week_dates,
        date_slot_overview=date_slot_overview,
        status_note=status_note
    )


@app.route("/appointment_reassign_options")
@require_role("Receptionist")
def appointment_reassign_options():
    department = request.args.get("department", "").strip()
    selected_date = request.args.get("date", "").strip()
    excluded_doctor_id = safe_int(request.args.get("exclude_doctor_id", "0")) or None
    appointment_id = safe_int(request.args.get("appointment_id", "0"))

    if appointment_id:
        appointment = find_appointment_by_id(appointment_id)
        if appointment and not department:
            doctor = get_doctor_by_id(appointment["doctor_id"]) or {}
            department = doctor.get("department", "")
        if appointment and not selected_date:
            selected_date = appointment["date"]

    parsed_date = parse_iso_date(selected_date)
    if not department or not parsed_date or parsed_date < date.today():
        return jsonify({"candidates": []})

    return jsonify({
        "candidates": get_reassignment_candidates(
            department,
            selected_date,
            excluded_doctor_id=excluded_doctor_id
        )
    })

@app.route("/book_appointment", methods=["POST"])
@require_role("Receptionist")
def book_appointment():
    patient_id = request.form["patient_id"]
    doctor_id = request.form["doctor_id"]
    appointment_date = request.form["appointment_date"]
    time_slot = request.form["time_slot"]
    return_to = request.form.get("return_to", "")
    patient = find_patient_by_id(patient_id)
    doctor_exists = any(str(d["id"]) == str(doctor_id) for d in get_doctors())
    if not patient or not doctor_exists:
        if return_to == "reception":
            return redirect(
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&booking_status=failed"
            )
        return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}")

    parsed_appt_date = parse_iso_date(appointment_date)
    if not parsed_appt_date or parsed_appt_date < date.today():
        if return_to == "reception":
            return redirect(
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&status_note=Cannot book an appointment for a past date"
            )
        return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}&status_note=Cannot book an appointment for a past date")
    if find_booked_appointment_for_patient_on_date(patient_id, appointment_date):
        if return_to == "reception":
            return redirect(
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&status_note=This patient already has a booked appointment for that date"
            )
        return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}&status_note=This patient already has a booked appointment for that date")

    slot_available = any(
        slot["time"] == time_slot and slot["state"] == "Available"
        for slot in load_appointment_slots(doctor_id, appointment_date)
    )
    if not slot_available:
        if return_to == "reception":
            return redirect(
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&booking_status=failed"
            )
        return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}")

    result = run_appointment_command("book", patient_id, doctor_id, appointment_date, time_slot)
    output = result.stdout.strip().split("|")
    booking_success = result.returncode == 0 and len(output) >= 6 and output[0] == "BOOKED"
    queue_info = (
        add_patient_to_queue(patient_id, doctor_id=doctor_id)
        if booking_success and parse_iso_date(appointment_date) == date.today()
        else None
    )

    if return_to == "reception":
        if booking_success:
            queue_query = f"&queue_token={queue_info['token']}" if queue_info else ""
            queue_doctor_query = f"&queue_doctor_id={queue_info['doctor_id']}" if queue_info else ""
            return redirect(
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&booking_status=booked{queue_query}{queue_doctor_query}"
            )
        return redirect(
            f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&booking_status=failed"
        )

    return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}")

@app.route("/cancel_appointment", methods=["POST"])
@require_role("Receptionist")
def cancel_appointment():
    appointment_id = request.form["appointment_id"]
    appointment = find_appointment_by_id(appointment_id)
    result = run_appointment_command("cancel", appointment_id)
    if result.returncode == 0 and appointment:
        update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
    return redirect("/appointments")

@app.route("/reschedule", methods=["POST"])
@require_role("Receptionist")
def reschedule():
    appointment_id = request.form["appointment_id"]
    new_date = request.form["new_date"]
    new_time = request.form["new_time"]
    appointment = find_appointment_by_id(appointment_id)
    parsed_new_date = parse_iso_date(new_date)
    if not parsed_new_date or parsed_new_date < date.today():
        return redirect("/appointments?status_note=Cannot reschedule to a past date")
    result = run_appointment_command("reschedule", appointment_id, new_date, new_time)
    if result.returncode == 0 and appointment:
        update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Rescheduled")
        if parse_iso_date(new_date) == date.today():
            add_patient_to_queue(appointment["patient_id"], doctor_id=appointment["doctor_id"])
    return redirect("/appointments")

@app.route("/update_appointment", methods=["POST"])
@require_role("Receptionist", "Doctor")
def update_appointment():
    appointment_id = request.form["appointment_id"]
    action = request.form["action"]
    appointment = find_appointment_by_id(appointment_id)

    if not appointment:
        target = "/doctor" if session.get("role") == "Doctor" else "/appointments"
        return redirect(f"{target}?status_note=Appointment not found")

    if session.get("role") == "Doctor":
        doctor_id = int(session.get("doctor_id", "0") or 0)
        if not doctor_owns_appointment(appointment, doctor_id):
            return redirect("/doctor?status_note=You can only update your own appointments")
        if action != "complete":
            return redirect("/doctor?status_note=Doctors can only complete their own consultations")
        if appointment["status"] not in {"Booked", "No-show"}:
            return redirect("/doctor?status_note=Only active appointments can be completed")
    elif session.get("role") == "Receptionist" and action == "complete":
        return redirect("/appointments?status_note=Reception cannot complete consultations manually. Completion happens when the doctor saves diagnosis.")

    actionable_statuses = {"Booked", "No-show"}
    if action in {"cancel", "noshow", "reschedule", "reassign"} and appointment["status"] not in actionable_statuses:
        if appointment["status"] == "Rescheduled":
            return redirect("/appointments?status_note=This row is the old rescheduled appointment. Use the newer booked appointment row for further actions.")
        return redirect(f"/appointments?status_note=This appointment is already {appointment['status']} and cannot be updated further.")

    if action == "reschedule":
        new_date = request.form["new_date"]
        new_time = request.form["new_time"]
        if not new_date or not new_time:
            return redirect("/appointments?status_note=Provide new date and time for reschedule")
        parsed_new_date = parse_iso_date(new_date)
        if not parsed_new_date or parsed_new_date < date.today():
            return redirect("/appointments?status_note=Cannot reschedule to a past date")
        result = run_appointment_command("reschedule", appointment_id, new_date, new_time)
        if result.returncode == 0:
            reschedule_meta = parse_reschedule_result(result)
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Rescheduled")
            if parse_iso_date(new_date) == date.today():
                add_patient_to_queue(appointment["patient_id"], doctor_id=appointment["doctor_id"])
            if reschedule_meta and reschedule_meta["new_appointment_id"]:
                return redirect(
                    f"/appointments?status_note=Appointment rescheduled successfully. Continue with new appointment #{reschedule_meta['new_appointment_id']} for further actions."
                )
            return redirect("/appointments?status_note=Appointment rescheduled successfully.")
        return redirect("/appointments?status_note=Could not reschedule the appointment. Please choose another date or slot.")
    elif action == "cancel":
        result = run_appointment_command("cancel", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
            return redirect("/appointments?status_note=Appointment cancelled successfully.")
        return redirect("/appointments?status_note=Could not cancel the appointment.")
    elif action == "complete":
        result = run_appointment_command("complete", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Completed")
            return redirect("/doctor?status_note=Consultation completed successfully.")
        return redirect("/doctor?status_note=Could not complete the consultation.")
    elif action == "noshow":
        result = run_appointment_command("noshow", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "No-show")
            adv = find_advance_by_appointment_id(appointment_id)
            if adv and adv["status"] == "PAID":
                adv["status"] = "FORFEITED"
                adv["settled_at"] = iso_now()
                update_advance_record(adv)
                patient_ns = find_patient_by_id(appointment["patient_id"])
                if patient_ns:
                    send_sms_notice(
                        patient_ns["phone"],
                        f"You missed your appointment on {format_human_date(appointment['date'])}. "
                        f"Your advance of Rs.{adv['amount']:.0f} has been forfeited. Call us to reschedule."
                    )
            return redirect("/appointments?status_note=Appointment marked as no-show.")
        return redirect("/appointments?status_note=Could not mark the appointment as no-show.")
    elif action == "reassign":
        if session.get("role") != "Receptionist":
            return redirect("/appointments?status_note=Only reception can reassign appointments")
        new_doctor_id = safe_int(request.form.get("new_doctor_id", "0"))
        new_date = request.form.get("new_date", "").strip()
        new_time = request.form.get("new_time", "").strip()
        patient_id = appointment["patient_id"]
        patient_confirmed = request.form.get("patient_confirmed", "").strip().lower() in {"on", "true", "yes", "1"}
        confirmation_note = clean_record_field(request.form.get("confirmation_note", ""), 220)
        if not new_doctor_id or not new_date or not new_time:
            return redirect("/appointments?status_note=Doctor, date and slot are required for reassignment")
        if not patient_confirmed:
            return redirect("/appointments?status_note=Record patient confirmation before reassigning the appointment")
        if not confirmation_note:
            return redirect("/appointments?status_note=Add a short confirmation note before reassigning the appointment")
        parsed_new_date = parse_iso_date(new_date)
        if not parsed_new_date or parsed_new_date < date.today():
            return redirect("/appointments?status_note=Cannot reassign to a past date")
        if (
            appointment["doctor_id"] == new_doctor_id
            and appointment["date"] == new_date
            and appointment["time_slot"] == new_time
        ):
            return redirect("/appointments?status_note=Choose a different doctor, date, or slot for reassignment")
        if not get_doctor_by_id(new_doctor_id):
            return redirect("/appointments?status_note=The selected replacement doctor was not found")
        if pending_slot_exists(new_doctor_id, new_date, new_time) or not slot_is_available(new_doctor_id, new_date, new_time):
            return redirect("/appointments?status_note=The selected replacement slot is no longer available")

        patient = find_patient_by_id(patient_id)
        old_doctor = get_doctor_by_id(appointment["doctor_id"]) or {}
        new_doctor = get_doctor_by_id(new_doctor_id) or {}
        old_doctor_name = old_doctor.get("name", f"Doctor #{appointment['doctor_id']}")
        new_doctor_name = new_doctor.get("name", f"Doctor #{new_doctor_id}")
        old_doctor_unavailable = old_doctor.get("daily_status") in {"Unavailable", "Off"} or old_doctor.get("current_status") == "Emergency"

        book_result = run_appointment_command("book", patient_id, new_doctor_id, new_date, new_time)
        new_appointment_id = parse_booked_appointment_id(book_result)
        if not new_appointment_id:
            return redirect("/appointments?status_note=Could not book the replacement slot. Please choose another one.")

        cancel_result = run_appointment_command("cancel", appointment_id)
        if cancel_result.returncode != 0:
            run_appointment_command("cancel", new_appointment_id)
            return redirect("/appointments?status_note=Could not complete reassignment because the original appointment could not be cancelled.")

        if cancel_result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
        if parse_iso_date(new_date) == date.today():
            add_patient_to_queue(patient_id, doctor_id=new_doctor_id)

        sms_sent = False
        if patient:
            if old_doctor_unavailable:
                message = (
                    f"Your appointment with {old_doctor_name} was changed because the doctor is unavailable. "
                    f"New appointment: {new_doctor_name} on {format_human_date(new_date)} at {new_time}. "
                    f"Please contact reception if needed."
                )
            else:
                message = (
                    f"Your appointment was updated to {new_doctor_name} on {format_human_date(new_date)} at {new_time}. "
                    f"Please contact reception if needed."
                )
            sms_sent = send_sms_notice(patient.get("phone", ""), message)

        sms_note = " Patient notified by SMS." if sms_sent else " Reassignment saved, but patient SMS could not be delivered."
        return redirect(
            f"/appointments?status_note=Appointment reassigned after patient confirmation ({confirmation_note}).{sms_note}"
        )

    if session.get("role") == "Doctor":
        return redirect("/doctor")
    return redirect("/appointments")


@app.route("/doctors")
@require_role("Receptionist")
def doctors_page():
    doctors = get_doctors()
    user_accounts = read_user_accounts()
    accounts = {
        account["doctor_id"]: account["username"]
        for account in user_accounts
        if account["role"] == "Doctor"
    }
    doctor_map = {doctor["id"]: doctor for doctor in doctors}
    for doctor in doctors:
        doctor["username"] = accounts.get(doctor["id"], "")

    staff_accounts = []
    for account in user_accounts:
        if account["role"] not in {"Doctor", "Receptionist"}:
            continue
        doctor = doctor_map.get(account["doctor_id"], {})
        staff_accounts.append({
            "id": account["id"],
            "username": account["username"],
            "role": account["role"],
            "doctor_id": account["doctor_id"],
            "staff_name": doctor.get("name", "Reception Desk" if account["role"] == "Receptionist" else ""),
            "department": doctor.get("department", ""),
        })

    created_account = session.pop("new_doctor_credentials", None)
    reset_account = session.pop("reset_staff_credentials", None)
    status_note = request.args.get("status_note", "")
    return render_template(
        "doctors.html",
        doctors=doctors,
        staff_accounts=staff_accounts,
        created_account=created_account,
        reset_account=reset_account,
        status_note=status_note,
        today_iso=date.today().isoformat()
    )


@app.route("/add_doctor", methods=["POST"])
@require_role("Receptionist")
def add_doctor():
    name = request.form["name"].replace("|", " ").strip()
    department = request.form["department"].replace("|", " ").strip()
    experience = request.form["experience"].strip()
    requested_username = request.form.get("username", "").replace("|", "").strip()
    requested_password = request.form.get("password", "").replace("|", "").strip()

    existing_usernames = {account["username"] for account in read_user_accounts()}
    if requested_username and requested_username in existing_usernames:
        return redirect(url_for("doctors_page", status_note="Username already exists. Choose a different one."))

    data_string = f"{name}|{department}|{experience}"
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    result = subprocess.run([exe_path, data_string], capture_output=True, text=True, cwd=BASE_DIR)
    doctor_id = result.stdout.strip()
    if not doctor_id.isdigit():
        return redirect(url_for("doctors_page", status_note="Doctor could not be added. Please check the details."))

    username = requested_username or build_doctor_username(name, existing_usernames)
    password = requested_password or build_doctor_password(int(doctor_id))
    save_user_account(username, password, "Doctor", int(doctor_id))
    session["new_doctor_credentials"] = {
        "doctor_id": int(doctor_id),
        "doctor_name": name,
        "username": username,
        "password": password
    }
    return redirect("/doctors")


@app.route("/doctor/edit", methods=["POST"])
@require_role("Receptionist")
def edit_doctor():
    doctor_id = safe_int(request.form.get("doctor_id", "0"))
    name = clean_record_field(request.form.get("name", "").strip())
    department = clean_record_field(request.form.get("department", "").strip())
    experience = safe_int(request.form.get("experience", "0"))

    if not doctor_id or not name or not department or experience < 0:
        return redirect(url_for("doctors_page", status_note="Invalid doctor details."))

    exe_path = os.path.join(BACKEND_DIR, "c_modules", f"doctor{_EXE_SUFFIX}")
    result = subprocess.run(
        [exe_path, "edit", str(doctor_id), clean_record_field(name), clean_record_field(department), str(experience)],
        capture_output=True, text=True, cwd=BASE_DIR
    )
    if result.returncode != 0:
        return redirect(url_for("doctors_page", status_note="Could not update doctor. Please try again."))

    return redirect(url_for("doctors_page", status_note=f"Doctor #{doctor_id} updated successfully."))


@app.route("/staff/reset-password", methods=["POST"])
@require_role("Receptionist")
def reset_staff_password_route():
    account_id = request.form.get("account_id", "0")
    reset_data = reset_staff_password(account_id)
    if not reset_data:
        return redirect(url_for("doctors_page", status_note="Password could not be regenerated for that account."))
    doctor = get_doctor_by_id(reset_data["doctor_id"]) if reset_data["doctor_id"] else None
    reset_data["staff_name"] = doctor["name"] if doctor else "Reception Desk"
    session["reset_staff_credentials"] = reset_data
    return redirect(url_for("doctors_page"))


@app.route("/toggle_doctor", methods=["POST"])
@require_role("Receptionist")
def toggle_doctor():

    doctor_id = request.form["doctor_id"]
    status = request.form["status"]

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")

    subprocess.run([exe_path, "daily", doctor_id, status], cwd=BASE_DIR)

    return redirect("/doctors")

@app.route("/doctor_status", methods=["POST"])
@require_role("Receptionist")
def doctor_status():
    doctor_id = request.form["doctor_id"]
    daily_status, current_status = normalize_doctor_statuses(
        request.form["daily_status"],
        request.form["current_status"]
    )
    status_until = request.form.get("status_until", "").strip()
    if daily_status in {"Unavailable", "Off"}:
        parsed_until = parse_iso_date(status_until) or date.today()
        if parsed_until < date.today():
            return redirect(url_for("doctors_page", status_note="Choose a valid end date for the unavailable period."))
        status_until = parsed_until.isoformat()
    else:
        status_until = date.today().isoformat()

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    subprocess.run([exe_path, "status", doctor_id, daily_status, current_status], cwd=BASE_DIR)
    update_doctor_status_meta(doctor_id, daily_status, current_status, status_until)
    if daily_status in {"Unavailable", "Off"} or current_status == "Emergency":
        if daily_status in {"Unavailable", "Off"} and status_until > date.today().isoformat():
            status_note = f"Status saved through {format_human_date(status_until)}. Existing patients were not reassigned automatically; please contact them and get confirmation before any change."
        else:
            status_note = "Status saved for today only. Existing patients were not reassigned automatically; please contact them and get confirmation before any change."
        return redirect(url_for("doctors_page", status_note=status_note))
    return redirect("/doctors")

@app.route("/doctor_my_status", methods=["POST"])
@require_role("Doctor")
def doctor_my_status():
    doctor_id = session.get("doctor_id", "0")
    daily_status, current_status = normalize_doctor_statuses(
        request.form["daily_status"],
        request.form["current_status"]
    )
    status_until = request.form.get("status_until", "").strip()
    if daily_status in {"Unavailable", "Off"}:
        parsed_until = parse_iso_date(status_until) or date.today()
        if parsed_until < date.today():
            return redirect(url_for("doctor_dashboard", status_note="Choose a valid end date for your unavailable period."))
        status_until = parsed_until.isoformat()
    else:
        status_until = date.today().isoformat()
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    subprocess.run([exe_path, "status", doctor_id, daily_status, current_status], cwd=BASE_DIR)
    update_doctor_status_meta(doctor_id, daily_status, current_status, status_until)
    if daily_status in {"Unavailable", "Off"} or current_status == "Emergency":
        if daily_status in {"Unavailable", "Off"} and status_until > date.today().isoformat():
            status_note = f"Status saved through {format_human_date(status_until)}. Your booked patients were not reassigned automatically; reception should confirm with them before making any change."
        else:
            status_note = "Status saved for today only. Your booked patients were not reassigned automatically; reception should confirm with them before making any change."
        return redirect(url_for("doctor_dashboard", status_note=status_note))
    return redirect("/doctor")

@app.route("/doctor_complete_consultation", methods=["POST"])
@require_role("Doctor")
def doctor_complete_consultation():
    appointment_id = request.form["appointment_id"]
    patient_id = request.form["patient_id"]
    doctor_id = int(session.get("doctor_id", "0") or 0)
    appointment = find_appointment_by_id(appointment_id)
    if (
        not appointment
        or not doctor_owns_appointment(appointment, doctor_id)
        or appointment["patient_id"] != safe_int(patient_id)
        or appointment["status"] not in {"Booked", "No-show"}
    ):
        return redirect("/doctor?status_note=You can only complete your own assigned appointments")
    if not is_consultation_day_reached(appointment):
        return redirect("/doctor?status_note=Consultation can be started only on or after the appointment date")
    return redirect(f"/diagnosis?patient_id={patient_id}&appointment_id={appointment_id}")
@app.route("/diagnosis")
@require_role("Doctor")
def diagnosis_page():
    patient_id = request.args.get("patient_id", "").strip()
    appointment_id = request.args.get("appointment_id", "").strip()
    doctor_id = session.get("doctor_id", "0")
    doctor_patients = get_doctor_patient_options(doctor_id)
    if patient_id:
        if not doctor_can_access_patient(patient_id, doctor_id):
            return redirect("/doctor?status_note=Patient is not assigned to your consultation list")
        consultation_appointment = resolve_consultation_appointment(patient_id, doctor_id, appointment_id)
        patient, diagnosis, error_message = get_diagnosis_context(patient_id)
        # NEW: load vitals for doctor
        vitals = find_vitals_for_patient_doctor(patient_id, doctor_id) if patient_id else None
        # NEW: load latest prescription for display
        rx_header, rx_medicines = find_prescription_by_appointment(
            consultation_appointment["appointment_id"]
        ) if consultation_appointment else (None, [])
        return render_template(
            "diagnosis.html",
            patient=patient,
            diagnosis=diagnosis,
            error_message=error_message,
            appointment_id=consultation_appointment["appointment_id"] if consultation_appointment else 0,
            doctor_patients=doctor_patients,
            current_doctor_id=session.get("doctor_id", ""),
            today=date.today().isoformat(),
            vitals=vitals,
            rx_header=rx_header,
            rx_medicines=rx_medicines,
        )
    return render_template(
        "diagnosis.html",
        appointment_id=0,
        doctor_patients=doctor_patients,
        current_doctor_id=session.get("doctor_id", ""),
        today=date.today().isoformat(),
        vitals=None,
        rx_header=None,
        rx_medicines=[],
    )


@app.route("/diagnosis_history", methods=["POST"])
@require_role("Doctor")
def diagnosis_history():

    patient_id = request.form["patient_id"]
    doctor_id = session.get("doctor_id", "0")
    doctor_patients = get_doctor_patient_options(doctor_id)
    if not doctor_can_access_patient(patient_id, doctor_id):
        return redirect("/doctor?status_note=Patient is not assigned to your consultation list")
    consultation_appointment = resolve_consultation_appointment(patient_id, doctor_id)
    patient, diagnosis, error_message = get_diagnosis_context(patient_id)
    # NEW: load vitals and prescription for history view
    vitals = find_vitals_for_patient_doctor(patient_id, doctor_id) if patient_id else None
    rx_header, rx_medicines = find_prescription_by_appointment(
        consultation_appointment["appointment_id"]
    ) if consultation_appointment else (None, [])

    return render_template(
        "diagnosis.html",
        patient=patient,
        diagnosis=diagnosis,
        error_message=error_message,
        appointment_id=consultation_appointment["appointment_id"] if consultation_appointment else 0,
        doctor_patients=doctor_patients,
        current_doctor_id=session.get("doctor_id", ""),
        today=date.today().isoformat(),
        vitals=vitals,
        rx_header=rx_header,
        rx_medicines=rx_medicines,
    )


@app.route("/add_diagnosis", methods=["POST"])
@require_role("Doctor")
def add_diagnosis():

    patient_id = request.form["patient_id"]
    doctor_id = session.get("doctor_id", request.form.get("doctor_id", "0"))
    appointment_id = safe_int(request.form.get("appointment_id", "0"))
    if not doctor_can_access_patient(patient_id, doctor_id):
        return redirect("/doctor?status_note=Patient is not assigned to your consultation list")

    consult_date = clean_record_field(request.form["date"])
    diagnosis_text = clean_record_field(request.form["diagnosis"])
    prescription = clean_record_field(request.form["prescription"])
    appointment = resolve_consultation_appointment(patient_id, doctor_id, appointment_id)

    if not consult_date:
        return redirect(f"/diagnosis?patient_id={patient_id}&appointment_id={appointment_id}&status_note=Consultation date is required")
    if not diagnosis_text:
        return redirect(f"/diagnosis?patient_id={patient_id}&appointment_id={appointment_id}&status_note=Diagnosis details are required")
    if not prescription:
        return redirect(f"/diagnosis?patient_id={patient_id}&appointment_id={appointment_id}&status_note=Prescription is required before completing consultation")
    if not appointment:
        return redirect(f"/doctor?status_note=No active consultation was found for this patient")
    if appointment["status"] == "Completed" and find_bill_by_appointment_id(appointment["appointment_id"]):
        return redirect(f"/doctor?status_note=This consultation has already been diagnosed and billed")

    if appointment["status"] in {"Booked", "No-show"}:
        result = run_appointment_command("complete", appointment["appointment_id"])
        if result.returncode != 0:
            return redirect(f"/diagnosis?patient_id={patient_id}&appointment_id={appointment['appointment_id']}&status_note=Appointment could not be completed")
    elif appointment["status"] != "Completed":
        return redirect(f"/doctor?status_note=Consultation cannot be saved for an inactive appointment")

    data_string = f"{patient_id}|{doctor_id}|{consult_date}|{diagnosis_text}|{prescription}"

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "diagnosis.exe")

    with _diagnosis_lock:
        subprocess.run(
            [exe_path, data_string],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )

    # NEW CODE — save structured prescription if submitted (backward compatible)
    medicines_json = request.form.get("medicines_json", "").strip()
    advice_notes   = clean_record_field(request.form.get("advice_notes", ""), 400)
    diagnosis_summary_for_rx = clean_record_field(diagnosis_text, 400)

    if medicines_json:
        try:
            medicines_list = json.loads(medicines_json)
            if isinstance(medicines_list, list) and len(medicines_list) > 0:
                save_prescription(
                    appointment_id=appointment["appointment_id"],
                    patient_id=int(patient_id),
                    doctor_id=int(doctor_id),
                    date=consult_date,
                    diagnosis_summary=diagnosis_summary_for_rx,
                    advice_notes=advice_notes,
                    medicines=medicines_list
                )
        except (ValueError, KeyError, TypeError):
            pass  # Prescription save failure must NOT block diagnosis save
    # END NEW CODE

    update_waiting_queue_status(patient_id, doctor_id, "Completed")

    latest_completed = find_appointment_by_id(appointment["appointment_id"]) or get_latest_completed_patient_appointment(patient_id, doctor_id=doctor_id)
    bill = auto_generate_bill(
        patient_id,
        doctor_id,
        consult_date,
        appointment_id=latest_completed["appointment_id"] if latest_completed else None
    )
    if bill:
        return redirect(
            f"/doctor?billing_patient_id={patient_id}&doctor_id={doctor_id}&bill_id={bill['bill_id']}"
        )

    return redirect(f"/doctor?billing_patient_id={patient_id}&doctor_id={doctor_id}")

# ── VITALS ROUTES ──

@app.route("/reception/vitals/add")
@require_role("Receptionist")
def vitals_add_page():
    """Show the Add Vitals form for a specific queue entry."""
    patient_id = safe_int(request.args.get("patient_id", "0"))
    token      = safe_int(request.args.get("token", "0"))
    doctor_id  = safe_int(request.args.get("doctor_id", "0"))

    patient = find_patient_by_id(patient_id)
    doctor  = get_doctor_by_id(doctor_id)

    if not patient or not doctor:
        return redirect(url_for("queue_page", status_note="Patient or doctor not found."))

    existing_vitals = find_vitals_for_patient_doctor(patient_id, doctor_id)

    return render_template(
        "vitals_form.html",
        patient=patient,
        doctor=doctor,
        token=token,
        existing_vitals=existing_vitals,
        status_note=request.args.get("status_note", "")
    )


@app.route("/reception/vitals/save", methods=["POST"])
@require_role("Receptionist")
def vitals_save():
    """Save vitals submitted by receptionist."""
    patient_id = safe_int(request.form.get("patient_id", "0"))
    doctor_id  = safe_int(request.form.get("doctor_id", "0"))
    token      = safe_int(request.form.get("token", "0"))

    patient = find_patient_by_id(patient_id)
    if not patient:
        return redirect(url_for("queue_page", status_note="Patient not found."))

    vitals = {
        "vitals_id":          next_vitals_id(),
        "patient_id":         patient_id,
        "doctor_id":          doctor_id,
        "token":              token,
        "recorded_at":        iso_now(),
        "temperature":        clean_record_field(request.form.get("temperature", ""), 20),
        "bp_systolic":        clean_record_field(request.form.get("bp_systolic", ""), 20),
        "bp_diastolic":       clean_record_field(request.form.get("bp_diastolic", ""), 20),
        "pulse_rate":         clean_record_field(request.form.get("pulse_rate", ""), 20),
        "weight":             clean_record_field(request.form.get("weight", ""), 20),
        "oxygen_level":       clean_record_field(request.form.get("oxygen_level", ""), 20),
        "sugar_level":        clean_record_field(request.form.get("sugar_level", ""), 20),
        "allergy_conditions": clean_record_field(request.form.get("allergy_conditions", ""), 200),
        "health_conditions":  clean_record_field(request.form.get("health_conditions", ""), 200),
        "notes":              clean_record_field(request.form.get("notes", ""), 200),
    }

    if not save_vitals_record(vitals):
        return redirect(url_for(
            "vitals_add_page",
            patient_id=patient_id, token=token, doctor_id=doctor_id,
            status_note="Could not save vitals. Please try again."
        ))

    return redirect(url_for("queue_page", status_note=f"Vitals saved for {patient['name']}."))


@app.route("/doctor/patient/vitals")
@require_role("Doctor")
def doctor_view_vitals():
    """Doctor views vitals for a specific patient. AJAX-friendly — returns partial HTML."""
    patient_id = safe_int(request.args.get("patient_id", "0"))
    doctor_id  = int(session.get("doctor_id", "0") or 0)

    if not doctor_can_access_patient(patient_id, doctor_id):
        return "Not authorised", 403

    vitals = find_vitals_for_patient_doctor(patient_id, doctor_id)
    patient = find_patient_by_id(patient_id)

    return render_template(
        "vitals_display.html",
        vitals=vitals,
        patient=patient
    )

@app.route("/billing")
@require_role("Receptionist")
def billing_page():
    bills = read_bills()
    patients = read_patients()
    appointments = read_appointments()
    doctors = get_doctors()
    patient_map = {int(patient["id"]): patient for patient in patients}
    patient_id = request.args.get("patient_id", "")
    preview_bill_id = request.args.get("preview_bill_id", "")
    status_note = request.args.get("status_note", "")
    bill_preview = ""
    preview_bill = find_bill_by_id(preview_bill_id) if preview_bill_id else None
    decorated_bills = []
    for bill in bills:
        patient = patient_map.get(int(bill.get("patient_id", 0) or 0), {})
        decorated_bills.append({
            **bill,
            "age": patient.get("age", ""),
            "gender": patient.get("gender", ""),
            "phone": patient.get("phone", ""),
            "symptoms": patient.get("symptoms", ""),
            "payment_method_label": payment_method_label(bill.get("payment_method")),
            "paid_at_label": payment_timestamp_label(bill.get("paid_at"))
        })
    bills = decorated_bills
    billing_lookup = build_billing_lookup(patients, appointments, doctors, bills)
    billing_context = (
        billing_lookup.get(str(patient_id))
        if patient_id
        else None
    )
    billing_ready_patients = []
    for patient in patients:
        context = billing_lookup.get(str(patient["id"]))
        if not context:
            continue
        if context.get("appointment_status") != "Completed":
            continue
        billing_ready_patients.append({
            "patient_id": patient["id"],
            "name": patient["name"],
            "age": patient.get("age", ""),
            "gender": patient.get("gender", ""),
            "phone": patient.get("phone", ""),
            "symptoms": patient.get("symptoms", ""),
            "doctor_name": context.get("doctor_name", ""),
            "department": context.get("department", ""),
            "appointment_id": context.get("appointment_id", 0),
            "appointment_date": context.get("appointment_date", ""),
            "appointment_status": context.get("appointment_status", ""),
            "warning": context.get("warning", ""),
            "bill_id": context.get("existing_bill_id", 0)
        })
    billing_ready_patients.sort(
        key=lambda item: parse_iso_date(item["appointment_date"]) or date.min,
        reverse=True
    )
    if preview_bill:
        bill_preview = build_bill_preview_text(preview_bill)

    return render_template(
        "billing.html",
        bills=bills,
        bill_preview=bill_preview,
        patients=patients,
        pricing_catalog=load_pricing_catalog(),
        billing_lookup=billing_lookup,
        payment_method_label=payment_method_label,
        payment_timestamp_label=payment_timestamp_label,
        selected_patient_id=str(patient_id),
        selected_date=request.args.get(
            "date",
            billing_context["appointment_date"] if billing_context and billing_context["appointment_date"] else date.today().isoformat()
        ),
        billing_ready_patients=billing_ready_patients,
        preview_bill=preview_bill,
        status_note=status_note,
        billing_context=billing_context
    )

@app.route("/generate_bill", methods=["POST"])
@require_role("Receptionist")
def generate_bill():
    patient_id = request.form["patient_id"].strip()
    bill_date = request.form["date"].strip()
    payment_status = request.form["payment_status"].strip().upper()
    if payment_status not in ALLOWED_PAYMENT_STATUSES:
        payment_status = "PENDING"
    patient = find_patient_by_id(patient_id) if patient_id else None
    billing_context = get_patient_billing_context(patient_id) if patient_id else None

    if not patient:
        return redirect(url_for("billing_page", status_note="Choose a valid patient before generating the bill."))

    if not billing_context or not billing_context["can_bill"]:
        warning = billing_context["warning"] if billing_context else "Billing information could not be retrieved."
        return redirect(url_for("billing_page", patient_id=patient_id, status_note=warning))

    if billing_context["existing_bill_id"]:
        return redirect(
            url_for(
                "billing_page",
                patient_id=patient_id,
                preview_bill_id=billing_context["existing_bill_id"],
                status_note=f"Bill #{billing_context['existing_bill_id']} already exists for this completed appointment."
            )
        )

    doctor = get_doctor_by_id(billing_context["doctor_id"])
    if not doctor:
        return redirect(url_for("billing_page", patient_id=patient_id, status_note="Doctor details could not be retrieved from the completed appointment."))

    bill = create_bill_record(
        patient=patient,
        doctor=doctor,
        bill_date=bill_date,
        treatment_codes=request.form.getlist("treatments"),
        lab_test_codes=request.form.getlist("lab_tests"),
        medicine_amount=request.form.get("medicine_amount", "0"),
        medicine_notes=request.form.get("medicine_notes", ""),
        payment_status=payment_status,
        appointment_id=billing_context["appointment_id"]
    )
    save_bill_record(bill)

    adv = find_advance_by_appointment_id(billing_context["appointment_id"])
    if adv and adv["status"] == "PAID":
        adv["status"] = "CREDITED"
        adv["settled_at"] = iso_now()
        update_advance_record(adv)
        bill["advance_id"] = adv["advance_id"]
        bill["advance_amount"] = adv["amount"]
        bill["advance_credited_at"] = iso_now()
        update_bill_record(bill)
        balance = max(0.0, float(bill.get("total", 0)) - adv["amount"])
        patient_obj = find_patient_by_id(int(patient_id))
        if patient_obj:
            send_sms_notice(
                patient_obj["phone"],
                f"Bill generated for your visit on {bill_date}. "
                f"Total: Rs.{bill['total']:.0f}. "
                f"Advance paid: Rs.{adv['amount']:.0f}. "
                f"Balance due: Rs.{balance:.0f}. Pay via portal or at counter."
            )
    return redirect(
        url_for(
            "billing_page",
            patient_id=patient_id,
            date=bill_date,
            preview_bill_id=bill["bill_id"]
        )
    )


@app.route("/billing/update-status", methods=["POST"])
@require_role("Receptionist")
def billing_update_status():
    bill_id = safe_int(request.form.get("bill_id", "0"))
    target_status = request.form.get("target_status", "").strip().upper()
    patient_id = request.form.get("return_patient_id", "").strip()
    preview_bill_id = request.form.get("return_preview_bill_id", "").strip()

    bill = find_bill_by_id(bill_id)
    if not bill:
        return redirect(url_for("billing_page", status_note="Bill not found."))

    ok, message = apply_reception_bill_status_update(bill, target_status)
    if ok and not update_bill_record(bill):
        ok = False
        message = "Could not update the bill status. Please try again."

    redirect_args = {"status_note": message}
    if patient_id:
        redirect_args["patient_id"] = patient_id
    if preview_bill_id:
        redirect_args["preview_bill_id"] = preview_bill_id
    return redirect(url_for("billing_page", **redirect_args))


@app.route("/billing/download/<int:bill_id>")
@require_role("Receptionist")
def download_bill(bill_id):
    bill = find_bill_by_id(bill_id)
    if not bill:
        return "Bill not found", 404

    response = make_response(build_bill_pdf(bill))
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=bill-{bill_id}.pdf"
    return response

# ── PRESCRIPTION PDF ROUTES ──

@app.route("/doctor/prescription/pdf/<int:prescription_id>")
@require_role("Doctor")
def download_prescription_pdf(prescription_id):
    """Doctor downloads prescription PDF."""
    doctor_id = int(session.get("doctor_id", "0") or 0)
    rx_header, rx_medicines = _find_prescription_by_id(prescription_id)

    if not rx_header:
        return "Prescription not found", 404
    if rx_header.get("doctor_id") != doctor_id:
        return "Not authorised", 403

    patient = find_patient_by_id(rx_header["patient_id"])
    doctor  = get_doctor_by_id(doctor_id)
    vitals  = find_vitals_for_patient_doctor(rx_header["patient_id"], doctor_id)

    if not patient or not doctor:
        return "Patient or doctor record not found", 404

    pdf_bytes = build_prescription_pdf(rx_header, rx_medicines, patient, doctor, vitals)
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=prescription-{prescription_id}.pdf"
    return response


@app.route("/patient/prescription/pdf/<int:prescription_id>")
@require_role("Patient")
def patient_download_prescription_pdf(prescription_id):
    """Patient downloads their own prescription PDF."""
    patient_id = int(session.get("patient_id", "0") or 0)
    rx_header, rx_medicines = _find_prescription_by_id(prescription_id)

    if not rx_header or rx_header.get("patient_id") != patient_id:
        return "Prescription not found", 404

    patient = find_patient_by_id(patient_id)
    doctor  = get_doctor_by_id(rx_header["doctor_id"])
    vitals  = find_vitals_for_patient_doctor(patient_id, rx_header["doctor_id"])

    pdf_bytes = build_prescription_pdf(rx_header, rx_medicines, patient, doctor, vitals)
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=prescription-{prescription_id}.pdf"
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5000)
