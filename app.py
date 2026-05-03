from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for
import hashlib
import hmac
from io import BytesIO
import json
import os
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
PENDING_APPOINTMENTS_FILE = os.path.join(DATA_DIR, "pending_appointments.txt")
NEW_PATIENT_REQUESTS_FILE = os.path.join(DATA_DIR, "new_patient_requests.txt")
DOCTOR_STATUS_META_FILE = os.path.join(DATA_DIR, "doctor_status_meta.json")
BILLING_EXE = os.path.join(BACKEND_DIR, "c_modules", "billing.exe")
PENDING_REQUEST_EXE = os.path.join(BACKEND_DIR, "c_modules", "pending_request.exe")
_appointment_lock = threading.Lock()
_pending_appointment_lock = threading.Lock()
_new_patient_request_lock = threading.Lock()
_billing_lock = threading.Lock()
_otp_lock = threading.Lock()
_otp_store = {}
ALLOWED_PAYMENT_STATUSES = {"PENDING", "INITIATED", "PAID", "WAIVED", "REFUNDED"}
OTP_EXPIRY_SECONDS = 5 * 60
OTP_MAX_ATTEMPTS = 3
PENDING_REQUEST_EXPIRY_HOURS = 2
DEFAULT_CLINIC_PHONE = "+91 XXXXX XXXXX"

app = Flask(__name__,
            template_folder = TMPL_DIR,
            static_folder=STATIC_DIR)
app.secret_key = os.environ.get("HEALTHDESK_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)
def append_data_line(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    needs_newline = False
    try:
        with open(path, "rb") as existing:
            existing.seek(0, os.SEEK_END)
            if existing.tell() > 0:
                existing.seek(-1, os.SEEK_END)
                needs_newline = existing.read(1) != b"\n"
    except FileNotFoundError:
        pass

    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(f"{line}\n")

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

def read_appointment_file():
    appointments = {}
    try:
        with open(APPOINTMENT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                appointment = parse_appointment_line(line)
                if appointment:
                    appointments[appointment["appointment_id"]] = appointment
    except FileNotFoundError:
        return []
    return sorted(appointments.values(), key=lambda item: item["appointment_id"])


def write_appointment_file(appointments):
    with open(APPOINTMENT_FILE, "w", encoding="utf-8") as f:
        for appointment in appointments:
            f.write(
                f"{int(appointment['appointment_id'])}|{int(appointment['patient_id'])}|"
                f"{int(appointment['doctor_id'])}|{clean_record_field(appointment['date'])}|"
                f"{clean_record_field(appointment['time_slot'])}|{clean_record_field(appointment['status'])}\n"
            )


def write_queue_file(rows):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                f"{int(row['token'])}|{int(row['patient_id'])}|{int(row['doctor_id'])}|"
                f"{clean_record_field(row['priority'])}|{clean_record_field(row['status'])}\n"
            )

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

def normalize_phone(phone):
    return re.sub(r"\D", "", str(phone or ""))


def is_valid_patient_phone(phone):
    return bool(re.fullmatch(r"\d{10}", str(phone or "")))


def mask_phone(phone):
    phone = normalize_phone(phone)
    if len(phone) != 10:
        return phone
    return f"{phone[:2]}XXXXX{phone[-3:]}"


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


def generate_otp(phone):
    normalized = normalize_phone(phone)
    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = datetime.now() + timedelta(seconds=OTP_EXPIRY_SECONDS)
    with _otp_lock:
        _otp_store[normalized] = {
            "hash": hash_otp(otp),
            "expires_at": expires_at,
            "attempts": 0
        }
    if not send_patient_otp(normalized, otp):
        with _otp_lock:
            _otp_store.pop(normalized, None)
        return False
    return True


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
    accounts = []
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            for line in f:
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
    except FileNotFoundError:
        pass
    return accounts


def next_user_id():
    return max((account["id"] for account in read_user_accounts()), default=0) + 1


def strip_doctor_title(name):
    return re.sub(r"^\s*dr\.?\s*", "", name.strip(), flags=re.IGNORECASE)


def build_doctor_username(name, existing_usernames):
    base_name = strip_doctor_title(name).lower()
    base = re.sub(r"[^a-z0-9]+", ".", base_name).strip(".") or "doctor"
    candidate = f"dr.{base}"
    suffix = 2
    while candidate in existing_usernames:
        candidate = f"dr.{base}{suffix}"
        suffix += 1
    return candidate


def build_doctor_password(doctor_id):
    return f"HDDoc{doctor_id}@{date.today().year}"


def save_user_account(username, password, role, doctor_id):
    user_id = next_user_id()
    stored_password = generate_password_hash(password)
    line = (
        f"{user_id}|{clean_record_field(username)}|{clean_record_field(stored_password, 260)}|"
        f"{clean_record_field(role)}|{int(doctor_id or 0)}"
    )
    append_data_line(USER_FILE, line)


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


def read_billing_lines_fallback():
    try:
        with open(BILLING_FILE, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f if line.strip()]
    except FileNotFoundError:
        return []


def next_bill_id_fallback():
    max_id = 999
    for line in read_billing_lines_fallback():
        head = line.split("|", 1)[0]
        try:
            max_id = max(max_id, int(head))
        except ValueError:
            continue
    return max_id + 1


def save_bill_line_fallback(line):
    append_data_line(BILLING_FILE, line)


def generate_bill_id():
    result = run_billing_command("next-id")
    if result and result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except ValueError:
            pass
    return next_bill_id_fallback()


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
            "initiated_at": data[23] if len(data) > 23 else (data[22] if len(data) > 22 and data[13] == "INITIATED" else "")
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
            "initiated_at": ""
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
            "initiated_at": ""
        }
        bill["total"] = recalculate_bill_total(bill)
        return bill
    return None


def recalculate_bill_total(bill):
    return (
        float(bill.get("doctor_fee", 0) or 0)
        + float(bill.get("treatment_total", 0) or 0)
        + float(bill.get("lab_total", 0) or 0)
        + float(bill.get("medicine_total", 0) or 0)
    )


def read_bills():
    bills = []
    result = run_billing_command("list")
    if result and result.returncode == 0:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
    else:
        lines = read_billing_lines_fallback()

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
        clean_record_field(bill.get("initiated_at", ""), 40)
    ])


def save_bill_record(bill):
    line = serialize_bill_record(bill)
    with _billing_lock:
        result = run_billing_command("save", line)
        if not result or result.returncode != 0:
            save_bill_line_fallback(line)


def _write_all_bill_records_unlocked(bills):
    os.makedirs(os.path.dirname(BILLING_FILE), exist_ok=True)
    with open(BILLING_FILE, "w", encoding="utf-8") as f:
        for bill in bills:
            f.write(f"{serialize_bill_record(bill)}\n")


def write_all_bill_records(bills):
    with _billing_lock:
        _write_all_bill_records_unlocked(bills)


def update_bill_record(updated_bill):
    with _billing_lock:
        bills = read_bills()
        changed = False
        for index, bill in enumerate(bills):
            if int(bill["bill_id"]) == int(updated_bill["bill_id"]):
                bills[index] = updated_bill
                changed = True
                break
        if changed:
            _write_all_bill_records_unlocked(bills)
        return changed


def find_bill_by_razorpay_order_id(order_id):
    order_id = str(order_id or "").strip()
    if not order_id:
        return None
    return next(
        (bill for bill in read_bills() if bill.get("razorpay_order_id") == order_id),
        None
    )


def build_bill_preview_text(bill):
    printable_date = bill["date"]
    parsed_date = parse_iso_date(bill["date"])
    if parsed_date:
        printable_date = parsed_date.strftime("%d-%m-%Y")

    line_items = [{"name": "Doctor Fee", "price": bill["doctor_fee"]}]
    line_items.extend(bill["treatments"])
    line_items.extend(bill["lab_tests"])
    if bill["medicine_total"]:
        line_items.append({"name": "Medicines", "price": bill["medicine_total"]})

    lines = [
        "=========================================================",
        "                    HEALTHDESK CLINIC",
        "=========================================================",
        "Address: Chennai",
        "Phone: +91 XXXXX XXXXX",
        "",
        "---------------------------------------------------------",
        f"Bill ID   : {bill['bill_id']}",
        f"Date      : {printable_date}",
        "---------------------------------------------------------",
        f"Patient ID: {bill['patient_id']}",
        f"Name      : {bill['name']}",
        f"Age       : {bill['age']}",
        f"Gender    : {bill['gender']}",
        "",
        f"Doctor    : {bill['doctor']}",
        f"Department: {bill['department']}",
        "---------------------------------------------------------",
        "",
        "                   BILL DETAILS",
        "---------------------------------------------------------",
        f"{'Description':<34}Amount (Rs)",
        "---------------------------------------------------------"
    ]
    for item in line_items:
        lines.append(f"{item['name']:<34}{item['price']:.0f}")
    lines.extend([
        "",
        "---------------------------------------------------------",
        f"{'TOTAL':<34}Rs {bill['total']:.0f}",
        "---------------------------------------------------------",
        f"Payment Status: {bill['status']}"
    ])
    payment_status = str(bill.get("status", "")).upper()
    if payment_status in {"PAID", "REFUNDED"} and bill.get("payment_method"):
        method_label = "Payment Method" if payment_status == "PAID" else "Original Payment Method"
        lines.append(f"{method_label}: {payment_method_label(bill.get('payment_method'))}")
        if bill.get("razorpay_payment_id"):
            lines.append(f"Payment Reference: {bill['razorpay_payment_id']}")
        if bill.get("paid_at"):
            lines.append(f"Paid On: {payment_timestamp_label(bill.get('paid_at'))}")
    if payment_status == "WAIVED":
        lines.append("This bill was waived by the clinic.")
    elif payment_status == "REFUNDED":
        lines.append("This bill was refunded by the clinic.")
    if bill["medicine_notes"]:
        lines.append(f"Medicine Notes : {bill['medicine_notes']}")
    lines.extend([
        "",
        "---------------------------------------------------------",
        "         Thank you for visiting HealthDesk",
        "---------------------------------------------------------"
    ])
    return "\n".join(lines)


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
    return phone.isdigit() and len(phone) == 10

def is_valid_age(age):
    if not age.isdigit():
        return False
    value = int(age)
    return 0 < value <= 120

def load_appointment_slots(doctor_id, selected_date):
    slots = []
    if not doctor_id or not selected_date:
        return slots

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "appointment.exe")
    result = subprocess.run(
        [exe_path, "slots", str(doctor_id), selected_date],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        data = line.strip().split("|")
        if len(data) == 3 and data[0] == "SLOT":
            slots.append({"time": data[1], "state": data[2]})

    if doctor_is_blocked_for_date(doctor_id, selected_date):
        return [
            {
                "time": slot["time"],
                "state": "Blocked" if slot["state"] == "Available" else slot["state"]
            }
            for slot in slots
        ]

    return slots


def slot_is_available(doctor_id, selected_date, time_slot):
    return any(
        slot["time"] == time_slot and slot["state"] == "Available"
        for slot in load_appointment_slots(doctor_id, selected_date)
    )

def run_appointment_command(*args):
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "appointment.exe")
    with _appointment_lock:
        return subprocess.run(
            [exe_path, *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )

def parse_iso_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def is_future_or_today(date_str):
    parsed = parse_iso_date(date_str)
    if not parsed:
        return False
    return parsed >= date.today()


def format_human_date(date_str):
    parsed = parse_iso_date(date_str)
    if not parsed:
        return date_str or ""
    return parsed.strftime("%A, %d %B %Y")


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
    if isinstance(expires_at, datetime):
        expiry = expires_at
    else:
        expiry = None
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                expiry = datetime.strptime(str(expires_at or ""), pattern)
                break
            except ValueError:
                continue
    if not expiry:
        return ""
    remaining = expiry - datetime.now()
    if remaining.total_seconds() <= 0:
        return "Expired"
    minutes = int(remaining.total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"Expires in {hours}h {mins}m"
    return f"Expires in {mins}m"


def parse_iso_datetime(value):
    if isinstance(value, datetime):
        return value
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(value or ""), pattern)
        except ValueError:
            continue
    return None


def iso_now():
    return datetime.now().replace(microsecond=0).isoformat()


def revert_stale_initiated_payments():
    with _billing_lock:
        rows = read_bills()
        now = datetime.now()
        changed = False
        for bill in rows:
            if str(bill.get("status", "")).upper() != "INITIATED":
                continue
            started_at = parse_iso_datetime(bill.get("initiated_at") or bill.get("paid_at"))
            if started_at and now - started_at <= timedelta(minutes=30):
                continue
            bill["status"] = "PENDING"
            bill["razorpay_order_id"] = ""
            bill["razorpay_payment_id"] = ""
            bill["payment_method"] = ""
            bill["paid_at"] = ""
            bill["initiated_at"] = ""
            changed = True
        if changed:
            _write_all_bill_records_unlocked(rows)
        return changed


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
        bill["status"] = "REFUNDED"
        bill["razorpay_order_id"] = ""
        bill["initiated_at"] = ""
        return True, f"Bill #{bill['bill_id']} was marked as refunded."

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
    reassigned = []
    pending = [
        appointment for appointment in read_appointments()
        if appointment["doctor_id"] == int(doctor_id)
        and appointment["status"] == "Booked"
        and is_future_or_today(appointment["date"])
    ]
    for appointment in pending:
        result = reassign_appointment_to_alternative(appointment)
        if result:
            reassigned.append(result)
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
    queue_exe_path = os.path.join(BACKEND_DIR, "c_modules", "queue.exe")
    command = [queue_exe_path, str(patient_id)]
    if doctor_id is not None:
        command.append(str(doctor_id))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    output = result.stdout.strip().split("|")
    if len(output) >= 3 and result.returncode == 0:
        return {
            "token": output[0],
            "doctor_id": output[1],
            "priority": output[2]
        }

    return None

def update_waiting_queue_status(patient_id, doctor_id=None, status="Completed"):
    rows = []
    changed = False
    patient_id = safe_int(patient_id)
    doctor_id = safe_int(doctor_id, None) if doctor_id is not None else None

    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                data = line.strip().split("|")
                if len(data) < 5:
                    continue
                try:
                    row = {
                        "token": int(data[0]),
                        "patient_id": int(data[1]),
                        "doctor_id": int(data[2]),
                        "priority": data[3],
                        "status": data[4]
                    }
                except ValueError:
                    continue
                if (
                    row["patient_id"] == patient_id
                    and row["status"] == "Waiting"
                    and (doctor_id is None or row["doctor_id"] == doctor_id)
                ):
                    row["status"] = status
                    changed = True
                rows.append(row)
    except FileNotFoundError:
        return False

    if not changed:
        return False

    write_queue_file(rows)
    return True


def reconcile_waiting_queue_entries():
    queue_rows = read_queue()
    appointments = read_appointments()
    latest_by_patient_doctor = {}
    updated = False

    for appointment in appointments:
        key = (appointment["patient_id"], appointment["doctor_id"])
        current = latest_by_patient_doctor.get(key)
        if current is None or parse_appointment_datetime(appointment) > parse_appointment_datetime(current):
            latest_by_patient_doctor[key] = appointment

    for row in queue_rows:
        if row["status"] != "Waiting":
            continue
        latest = latest_by_patient_doctor.get((row["patient_id"], row["doctor_id"]))
        if not latest:
            continue
        if latest["status"] in {"Completed", "Cancelled", "Rescheduled", "No-show"}:
            row["status"] = latest["status"]
            updated = True

    if not updated:
        return queue_rows

    write_queue_file(queue_rows)

    return queue_rows

@app.before_request
def require_login():
    public_endpoints = {"dashboard", "login", "patient_login", "patient_request_otp", "patient_verify_otp", "new_patient_request", "new_patient_slots", "new_patient_submit", "payment_webhook", "static"}
    if request.endpoint in public_endpoints:
        return
    if not is_authenticated():
        if request.endpoint and request.endpoint.startswith("patient_"):
            return redirect(url_for("patient_login"))
        return redirect(url_for("login"))

@app.before_request
def verify_csrf_token():
    if request.endpoint == "payment_webhook":
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

    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
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
    except:
        pass

    return queue


def write_doctor_file(doctors):
    doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
    with open(doctor_file, "w", encoding="utf-8") as f:
        for doctor in doctors:
            f.write(
                f"{int(doctor['id'])}|{clean_record_field(doctor['name'])}|"
                f"{clean_record_field(doctor['department'])}|{int(doctor['experience'])}|"
                f"{clean_record_field(doctor['daily_status'])}|{clean_record_field(doctor['current_status'])}\n"
            )


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
    daily = str(daily_status or "").strip() or "Available"
    current = str(current_status or "").strip()

    if daily == "Off":
        return "Off", "Off"
    if daily == "Unavailable":
        return "Unavailable", "Unavailable"
    if current == "Emergency":
        return daily, "Emergency"
    if current == "Busy":
        return daily, "Busy"
    return daily, "Free"


def doctor_current_status_view(daily_status, current_status):
    daily, current = normalize_doctor_statuses(daily_status, current_status)

    if daily == "Off":
        return {
            "current_status_label": "Off Duty",
            "current_status_badge": "waived"
        }
    if daily == "Unavailable":
        return {
            "current_status_label": "Unavailable",
            "current_status_badge": "cancelled"
        }
    if current == "Emergency":
        return {
            "current_status_label": "Emergency",
            "current_status_badge": "cancelled"
        }
    if current == "Busy":
        return {
            "current_status_label": "Busy",
            "current_status_badge": "pending"
        }
    return {
        "current_status_label": "Free",
        "current_status_badge": "booked"
    }


def doctor_status_end_date(doctor_id, meta=None):
    meta = meta or load_doctor_status_meta()
    key = str(safe_int(doctor_id))
    expires_on = str((meta.get(key) or {}).get("expires_on", "")).strip()
    return expires_on if parse_iso_date(expires_on) else ""


def doctor_is_blocked_for_date(doctor_id, selected_date, doctor=None, meta=None):
    selected = parse_iso_date(selected_date)
    if not selected:
        return False

    doctor = doctor or get_doctor_by_id(doctor_id) or {}
    daily_status, current_status = normalize_doctor_statuses(
        doctor.get("daily_status", "Available"),
        doctor.get("current_status", "Free")
    )
    if daily_status not in {"Unavailable", "Off"} and current_status != "Emergency":
        return False

    expires_on = doctor_status_end_date(doctor_id, meta=meta)
    if expires_on:
        expiry = parse_iso_date(expires_on)
        return bool(expiry and selected <= expiry)

    return selected == date.today()


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

    doctors = []
    doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
    try:
        with open(doctor_file, "r", encoding="utf-8") as f:
            for line in f:
                data = line.strip().split("|")
                if len(data) < 6:
                    continue
                try:
                    doctors.append({
                        "id": int(data[0]),
                        "name": data[1],
                        "department": data[2],
                        "experience": int(data[3]),
                        "daily_status": data[4],
                        "current_status": data[5]
                    })
                except ValueError:
                    continue
    except FileNotFoundError:
        return False

    changed = False
    for doctor in doctors:
        if doctor["id"] not in expired_ids:
            continue
        doctor["daily_status"] = "Available"
        doctor["current_status"] = "Free"
        changed = True

    if not changed:
        return False

    write_doctor_file(doctors)
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


def build_reception_queue_groups(queue):
    patients = {patient["id"]: patient for patient in read_patients()}
    doctors = {doctor["id"]: doctor for doctor in get_doctors()}
    groups = {}

    for item in queue:
        if item["status"] != "Waiting":
            continue

        doctor = doctors.get(item["doctor_id"])
        group_key = item["doctor_id"]
        if group_key not in groups:
            groups[group_key] = {
                "doctor_id": item["doctor_id"],
                "doctor_name": doctor["name"] if doctor else "Unassigned",
                "department": doctor["department"] if doctor else "",
                "patients": []
            }

        patient = patients.get(item["patient_id"], {})
        groups[group_key]["patients"].append({
            "token": item["token"],
            "patient_id": item["patient_id"],
            "priority": item["priority"],
            "name": patient.get("name", ""),
            "symptoms": patient.get("symptoms", "")
        })

    grouped = list(groups.values())
    for group in grouped:
        group["patients"].sort(key=lambda row: (row["priority"] != "Urgent", row["token"]))

    grouped.sort(key=lambda group: (group["doctor_id"] == -1, group["doctor_name"]))
    return grouped


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
    patient_file = os.path.join(BACKEND_DIR, "data", "patients.txt")
    try:
        with open(patient_file, "r") as f:
            return len(f.readlines())
    except Exception:
        return 0
    
def count_available_doctors():
    count = 0
    doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
    try:
        with open(doctor_file, "r") as f:
            for line in f:
                data = line.strip().split("|")
                if len(data) >= 6 and data[4] == "Available" and data[5] == "Free":
                    count += 1
    except Exception:
        pass
    return count

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
    try:
        doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
        with open(doctor_file, "r", encoding="utf-8") as f:
            for line in f:
                data = line.strip().split("|")
                if len(data) < 6:
                    continue
                daily_status, current_status = normalize_doctor_statuses(data[4], data[5])
                availability = doctor_availability_view(daily_status, current_status)
                current_view = doctor_current_status_view(daily_status, current_status)
                status_until = doctor_status_end_date(data[0], meta=meta)
                doctors.append({
                    "id": int(data[0]),
                    "name": data[1],
                    "department": data[2],
                    "experience": int(data[3]),
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
    doctors = get_doctors()
    changed = False

    for doctor in doctors:
        if doctor["daily_status"] != "Available":
            continue
        if doctor["current_status"] != "Busy":
            continue
        if doctor_has_live_workload(doctor["id"]):
            continue

        doctor["current_status"] = "Free"
        changed = True

    if changed:
        write_doctor_file(doctors)

    return changed

def suggest_doctors_by_department(department):
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    result = subprocess.run(
        [exe_path, "suggest", department],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    doctors = []
    for line in result.stdout.strip().split("\n"):
        if not line or line == "NoDoctorFound":
            continue

        data = line.strip().split("|")
        if len(data) < 6:
            continue

        doctors.append({
            "id": int(data[0]),
            "name": data[1],
            "department": data[2],
            "experience": int(data[3]),
            "daily_status": data[4],
            "current_status": data[5]
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
    appointments = read_appointments()
    queue_rows = read_queue()
    appointments_changed = False
    queue_changed = False
    latest_by_patient_doctor = {}

    for appointment in appointments:
        key = (appointment["patient_id"], appointment["doctor_id"])
        current = latest_by_patient_doctor.get(key)
        if current is None or parse_appointment_datetime(appointment) > parse_appointment_datetime(current):
            latest_by_patient_doctor[key] = appointment

        appointment_day = parse_iso_date(appointment.get("date"))
        if (
            appointment_day
            and appointment_day < date.today()
            and appointment["status"] == "Booked"
        ):
            appointment["status"] = "No-show"
            appointments_changed = True

            for row in queue_rows:
                if (
                    row["patient_id"] == appointment["patient_id"]
                    and row["doctor_id"] == appointment["doctor_id"]
                    and row["status"] == "Waiting"
                ):
                    row["status"] = "No-show"
                    queue_changed = True

    for row in queue_rows:
        if row["status"] != "Waiting":
            continue
        latest = latest_by_patient_doctor.get((row["patient_id"], row["doctor_id"]))
        if not latest:
            row["status"] = "Cancelled"
            queue_changed = True
        elif latest["status"] != "Booked":
            row["status"] = latest["status"]
            queue_changed = True
        elif not is_consultation_day_reached(latest):
            row["status"] = "Cancelled"
            queue_changed = True

    if appointments_changed:
        write_appointment_file(appointments)
    if queue_changed:
        write_queue_file(queue_rows)

    return {
        "appointments_changed": appointments_changed,
        "queue_changed": queue_changed
    }


def get_latest_patient_appointment(patient_id):
    appointments = [
        appointment for appointment in read_appointments()
        if appointment["patient_id"] == int(patient_id)
    ]
    if not appointments:
        return None
    appointments.sort(key=parse_appointment_datetime, reverse=True)
    return appointments[0]

def get_latest_completed_patient_appointment(patient_id, doctor_id=None):
    appointments = [
        appointment for appointment in read_appointments()
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
    appointments = [
        appointment for appointment in read_appointments()
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
    return next((doctor for doctor in get_doctors() if doctor["id"] == int(doctor_id)), None)


def read_diagnosis_for_patient(patient_id):
    patient_id = int(patient_id)
    doctor_map = {doctor["id"]: doctor for doctor in get_doctors()}
    records = []
    try:
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

    return {"pending_changed": pending_changed, "new_changed": new_changed}


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
    labels = {
        "Booked": "Confirmed",
        "Pending": "Pending Confirmation",
        "Cancelled": "Cancelled",
        "Completed": "Visit completed",
        "No-show": "Appointment not attended",
        "Rescheduled": "Rescheduled"
    }
    return labels.get(status, status or "Unknown")


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
    patient_file = os.path.join(BACKEND_DIR, "data", "patients.txt")
    try:
        with open(patient_file, "r", encoding="utf-8") as f:
            for line in f:
                data = line.strip().split("|")
                if len(data) < 10:
                    continue
                try:
                    patients.append({
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
                    })
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return patients

def find_patient_by_phone(phone):
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "patient.exe")
    result = subprocess.run(
        [exe_path, "search", phone],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

    data = result.stdout.strip().split("|")
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

def find_patient_by_id(patient_id):
    for patient in read_patients():
        if patient["id"] == int(patient_id):
            return patient
    return None

def read_assigned_queue_patients(doctor_id):
    assigned = []
    patients = {patient["id"]: patient for patient in read_patients()}

    for item in read_queue():
        if item["doctor_id"] != doctor_id or item["status"] != "Waiting":
            continue

        patient = patients.get(item["patient_id"], {})
        active_appointment = get_latest_active_patient_appointment(item["patient_id"], doctor_id=doctor_id)
        appointment_for_queue = active_appointment if active_appointment and active_appointment["doctor_id"] == doctor_id else None
        appointment_date = appointment_for_queue["date"] if appointment_for_queue else ""
        is_today_queue = bool(appointment_for_queue) and is_consultation_day_reached(appointment_for_queue)
        if not is_today_queue:
            continue

        assigned.append({
            "token": item["token"],
            "patient_id": item["patient_id"],
            "priority": item["priority"],
            "status": item["status"],
            "name": patient.get("name", ""),
            "department": patient.get("department", ""),
            "symptoms": patient.get("symptoms", ""),
            "appointment_id": appointment_for_queue["appointment_id"] if appointment_for_queue else 0,
            "appointment_date": appointment_date,
            "is_today_queue": is_today_queue,
            "can_consult": bool(appointment_for_queue) and is_today_queue
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

    def respond_error(error):
        if wants_json:
            return jsonify({"ok": False, "error": error}), 400
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

    if not generate_otp(phone):
        detail = get_last_sms_error()
        if detail:
            print(f"[HealthDesk OTP] SMS provider detail: {detail}")
        return respond_error("OTP could not be sent. Please check the Fast2SMS setup or try again.")
    masked = mask_phone(phone)
    message = "OTP sent to your registered phone number."
    if wants_json:
        return jsonify({"ok": True, "phone": phone, "masked_phone": masked, "message": message})
    return render_template(
        "patient_login.html",
        step="otp",
        phone=phone,
        masked_phone=masked,
        error=None,
        message=message
    )

@app.route("/patient/verify-otp", methods=["POST"])
def patient_verify_otp():
    phone = normalize_phone(request.form.get("phone", ""))
    entered_otp = request.form.get("otp", "")
    verified, message, _attempts_left = verify_otp(phone, entered_otp)
    if not verified:
        restart = "No OTP was requested" in message or "expired" in message.lower() or "Too many" in message
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
        masked_phone=mask_phone(session.get("patient_phone", patient.get("phone", "") if patient else ""))
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

@app.route("/patient/book")
@require_role("Patient")
def patient_book():
    patient = find_patient_by_id(session["patient_id"])
    departments = sorted({doctor["department"] for doctor in get_doctors()})
    doctors = get_doctors()
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(1, 8)]
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
    if not department or not parsed_date or parsed_date <= date.today():
        return jsonify({"ok": False, "error": "Choose a valid future date."}), 400
    slots = build_patient_slot_payload(department, doctor_id, requested_date)
    return jsonify({"ok": True, "slots": slots})

@app.route("/patient/new")
def new_patient_request():
    departments = sorted({doctor["department"] for doctor in get_doctors()})
    doctors = get_doctors()
    week_dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(1, 8)]
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
    if not parsed_date or parsed_date <= date.today():
        return redirect(url_for("new_patient_request", status_note="Choose a future appointment date."))
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
    department = clean_record_field(request.form.get("department", ""))
    doctor_id_raw = request.form.get("doctor_id", "")
    requested_date = clean_record_field(request.form.get("requested_date", ""))
    requested_slot = clean_record_field(request.form.get("requested_slot", ""))
    reason = clean_record_field(request.form.get("reason", ""), 220)
    visit_type = clean_record_field(request.form.get("visit_type", "New"))
    if visit_type not in {"New", "Follow-up"}:
        visit_type = "New"
    parsed_date = parse_iso_date(requested_date)
    if not department or not parsed_date or parsed_date <= date.today() or not requested_slot:
        return redirect(url_for("patient_book", status_note="Choose a department, future date, and available slot."))

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

    triage, reasons = triage_booking_request(doctor_id, requested_date, visit_type)
    if triage == "auto":
        ok, message, _row = auto_approve_booking(patient, doctor_id, requested_date, requested_slot, reason, visit_type)
    else:
        ok, message, _row = exception_queue_booking(patient, doctor_id, requested_date, requested_slot, reason, visit_type, reasons)
    return redirect(url_for("patient_dashboard", status_note=message if ok else message))

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
    result = run_appointment_command("cancel", appointment_id)
    if result.returncode == 0:
        update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
        patient = find_patient_by_id(appointment["patient_id"])
        doctor = get_doctor_by_id(appointment["doctor_id"]) or {}
        if patient:
            send_sms_notice(patient["phone"], f"Your appointment with {doctor.get('name', 'the doctor')} on {format_human_date(appointment['date'])} has been cancelled.")
        return redirect(url_for("patient_dashboard", status_note="Your appointment was cancelled."))
    return redirect(url_for("patient_dashboard", status_note="Could not cancel the appointment. Please call the clinic."))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = authenticate_user(username, password)

        if user:
            if user["role"] not in {"Receptionist", "Doctor"}:
                error = "Unauthorized role."
                return render_template("login.html", error=error)
            if user["role"] == "Doctor" and int(user["doctor_id"] or 0) <= 0:
                error = "Invalid doctor account mapping."
                return render_template("login.html", error=error)
            if user["role"] == "Doctor" and not any(d["id"] == int(user["doctor_id"]) for d in get_doctors()):
                error = "Doctor account is not linked to an active doctor profile."
                return render_template("login.html", error=error)

            session["logged_in"] = True
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["doctor_id"] = user["doctor_id"]
            if user["role"] == "Receptionist":
                return redirect("/receptionist_dashboard")
            if user["role"] == "Doctor":
                return redirect("/doctor")
            return redirect("/")

        error = "Invalid username or password."

    return render_template("login.html", error=error)

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
    message = None
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

        department_doctors = [
            doctor for doctor in doctors
            if not selected_department or doctor["department"] == selected_department
        ]

        if not selected_doctor and department_doctors:
            selected_doctor = str(department_doctors[0]["id"])

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
        if patient:
            send_sms_notice(patient["phone"], f"Request not confirmed. Reason: {reason}. Log in to rebook.")
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
    reconcile_waiting_queue_entries()
    appointments = [
        a for a in read_appointments()
        if a["doctor_id"] == doctor_id and a["status"] == "Booked" and is_future_appointment(a)
    ]
    appointments.sort(key=lambda x: (x["date"], x["time_slot"]))
    queue_patients = read_assigned_queue_patients(doctor_id)
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
        "_doctor_dashboard_panels.html",
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


def build_queue_page_context():
    expire_stale_consultations()
    queue = reconcile_waiting_queue_entries()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)
    queue_groups = build_reception_queue_groups(queue)
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
        "_queue_panels.html",
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
    enriched_appointments = [enrich_appointment_workflow_status(a) for a in appointments]
    doctor_map = {doctor["id"]: doctor for doctor in doctors}
    patient_map = {patient["id"]: patient for patient in read_patients()}
    for appointment in enriched_appointments:
        doctor = doctor_map.get(appointment["doctor_id"], {})
        patient = patient_map.get(appointment["patient_id"], {})
        reassign_department = doctor.get("department") or patient.get("department", "")
        unavailable_reason = doctor.get("daily_status") in {"Unavailable", "Off"} or doctor.get("current_status") == "Emergency"
        appointment["reassign_department"] = reassign_department
        appointment["requires_reassign_confirmation"] = unavailable_reason
        appointment["reassign_context_label"] = (
            "Doctor unavailable for this appointment"
            if unavailable_reason
            else "Manual reassignment"
        )
    appointment_groups = build_appointment_action_groups(enriched_appointments, doctors)

    return render_template(
        "appointments.html",
        doctors=doctors,
        slots=slots,
        selected_doctor=selected_doctor,
        selected_department=selected_department,
        selected_date=selected_date,
        appointments=enriched_appointments,
        appointment_groups=appointment_groups,
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
                f"/reception?patient_id={patient_id}&doctor_id={doctor_id}&date={appointment_date}&booking_status=failed"
            )
        return redirect(f"/appointments?doctor_id={doctor_id}&date={appointment_date}&status_note=Cannot book an appointment for a past date")

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
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Rescheduled")
            if parse_iso_date(new_date) == date.today():
                add_patient_to_queue(appointment["patient_id"], doctor_id=appointment["doctor_id"])
    elif action == "cancel":
        result = run_appointment_command("cancel", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
    elif action == "complete":
        result = run_appointment_command("complete", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Completed")
    elif action == "noshow":
        result = run_appointment_command("noshow", appointment_id)
        if result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "No-show")
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
    accounts = {
        account["doctor_id"]: account["username"]
        for account in read_user_accounts()
        if account["role"] == "Doctor"
    }
    for doctor in doctors:
        doctor["username"] = accounts.get(doctor["id"], "")

    created_account = session.pop("new_doctor_credentials", None)
    status_note = request.args.get("status_note", "")
    return render_template(
        "doctors.html",
        doctors=doctors,
        created_account=created_account,
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
        return render_template(
            "diagnosis.html",
            patient=patient,
            diagnosis=diagnosis,
            error_message=error_message,
            appointment_id=consultation_appointment["appointment_id"] if consultation_appointment else 0,
            doctor_patients=doctor_patients,
            current_doctor_id=session.get("doctor_id", ""),
            today=date.today().isoformat()
        )
    return render_template(
        "diagnosis.html",
        appointment_id=0,
        doctor_patients=doctor_patients,
        current_doctor_id=session.get("doctor_id", ""),
        today=date.today().isoformat()
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

    return render_template(
        "diagnosis.html",
        patient=patient,
        diagnosis=diagnosis,
        error_message=error_message,
        appointment_id=consultation_appointment["appointment_id"] if consultation_appointment else 0,
        doctor_patients=doctor_patients,
        current_doctor_id=session.get("doctor_id", ""),
        today=date.today().isoformat()
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

    subprocess.run(
        [exe_path, data_string],
        capture_output=True,
        text=True,
        cwd=BASE_DIR
    )

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

@app.route("/billing")
@require_role("Receptionist")
def billing_page():
    bills = read_bills()
    patients = read_patients()
    appointments = read_appointments()
    doctors = get_doctors()
    patient_id = request.args.get("patient_id", "")
    preview_bill_id = request.args.get("preview_bill_id", "")
    status_note = request.args.get("status_note", "")
    bill_preview = ""
    preview_bill = find_bill_by_id(preview_bill_id) if preview_bill_id else None
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
            "doctor_name": context.get("doctor_name", ""),
            "department": context.get("department", ""),
            "appointment_id": context.get("appointment_id", 0),
            "appointment_date": context.get("appointment_date", ""),
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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
