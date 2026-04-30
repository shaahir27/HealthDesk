from flask import Flask, make_response, redirect, render_template, request, session, url_for
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
BILLING_EXE = os.path.join(BACKEND_DIR, "c_modules", "billing.exe")
_appointment_lock = threading.Lock()
ALLOWED_PAYMENT_STATUSES = {"PENDING", "PAID", "WAIVED"}

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
            "appointment_id": int(data[18] or 0)
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
            "appointment_id": 0
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
            "appointment_id": 0
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


def save_bill_record(bill):
    line = "|".join([
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
        str(int(bill.get("appointment_id", 0) or 0))
    ])
    result = run_billing_command("save", line)
    if not result or result.returncode != 0:
        save_bill_line_fallback(line)


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
        "appointment_id": int(appointment_id or 0)
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

    return slots

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
    public_endpoints = {"login", "static"}
    if request.endpoint in public_endpoints:
        return
    if not is_authenticated():
        return redirect(url_for("login"))

@app.before_request
def verify_csrf_token():
    if request.method != "POST":
        return
    token = session.get("_csrf_token", "")
    submitted = request.form.get("_csrf_token", "")
    if not token or not submitted or not hmac.compare_digest(token, submitted):
        return "Invalid or expired form token.", 400

@app.before_request
def sync_doctor_statuses_before_request():
    public_endpoints = {"login", "static"}
    if request.endpoint in public_endpoints or not is_authenticated():
        return
    sync_doctor_busy_statuses()

@app.context_processor
def inject_auth_state():
    return {
        "is_logged_in": is_authenticated(),
        "current_role": session.get("role", ""),
        "current_user": session.get("username", ""),
        "csrf_token": get_csrf_token
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


def get_doctors():
    doctors = []
    try:
        doctor_file = os.path.join(BACKEND_DIR, "data", "doctors.txt")
        with open(doctor_file, "r", encoding="utf-8") as f:
            for line in f:
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


def get_doctor_by_id(doctor_id):
    return next((doctor for doctor in get_doctors() if doctor["id"] == int(doctor_id)), None)


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
    role = session.get("role")
    if role == "Receptionist":
        return redirect("/receptionist_dashboard")
    if role == "Doctor":
        return redirect("/doctor")
    return redirect("/login")

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
        today=today_str
    )

@app.route("/doctor")
@require_role("Doctor")
def doctor_dashboard():
    doctor_id = int(session.get("doctor_id", "0") or 0)
    billing_patient_id = request.args.get("billing_patient_id", "")
    billing_doctor_id = request.args.get("doctor_id", str(doctor_id))
    billing_bill_id = request.args.get("bill_id", "")
    status_note = request.args.get("status_note", "")
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
    return render_template(
        "doctor_dashboard.html",
        appointments=appointments,
        queue_patients=queue_patients,
        live_queue_patients=live_queue_patients,
        doctor_info=doctor_info,
        billing_patient_id=billing_patient_id,
        billing_doctor_id=billing_doctor_id,
        billing_bill_id=billing_bill_id,
        status_note=status_note
    )

@app.route("/queue")
@require_role("Receptionist")
def queue_page():

    expire_stale_consultations()
    queue = reconcile_waiting_queue_entries()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)
    queue_groups = build_reception_queue_groups(queue)
    return render_template(
        "queue.html",
        queue=queue,
        queue_groups=queue_groups,
        next_patient=next_patient,
        waiting_count=waiting_count,
        completed_count=completed_count,
        status_note=request.args.get("status_note", "")
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
        new_doctor_id = request.form["new_doctor_id"]
        new_date = request.form["new_date"]
        new_time = request.form["new_time"]
        patient_id = request.form["patient_id"]
        if not new_doctor_id or not new_date or not new_time:
            return redirect("/appointments?status_note=Doctor, date and slot are required for reassignment")
        parsed_new_date = parse_iso_date(new_date)
        if not parsed_new_date or parsed_new_date < date.today():
            return redirect("/appointments?status_note=Cannot reassign to a past date")
        cancel_result = run_appointment_command("cancel", appointment_id)
        book_result = run_appointment_command("book", patient_id, new_doctor_id, new_date, new_time)
        if cancel_result.returncode == 0:
            update_waiting_queue_status(appointment["patient_id"], appointment["doctor_id"], "Cancelled")
        if book_result.returncode == 0 and parse_iso_date(new_date) == date.today():
            add_patient_to_queue(patient_id, doctor_id=new_doctor_id)

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
        status_note=status_note
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
    daily_status = request.form["daily_status"]
    current_status = request.form["current_status"]

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    subprocess.run([exe_path, "status", doctor_id, daily_status, current_status], cwd=BASE_DIR)
    should_reassign = daily_status in {"Unavailable", "Off"} or current_status == "Emergency"
    if should_reassign:
        reassigned = auto_reassign_unavailable_doctor_appointments(int(doctor_id))
        if reassigned:
            return redirect(url_for("appointments_page", status_note=f"Auto-reassigned {len(reassigned)} appointment(s)"))
        return redirect(url_for("appointments_page", status_note="No alternative doctor available for reassignment"))
    return redirect("/doctors")

@app.route("/doctor_my_status", methods=["POST"])
@require_role("Doctor")
def doctor_my_status():
    doctor_id = session.get("doctor_id", "0")
    daily_status = request.form["daily_status"]
    current_status = request.form["current_status"]
    exe_path = os.path.join(BACKEND_DIR, "c_modules", "doctor.exe")
    subprocess.run([exe_path, "status", doctor_id, daily_status, current_status], cwd=BASE_DIR)
    should_reassign = daily_status in {"Unavailable", "Off"} or current_status == "Emergency"
    if should_reassign:
        reassigned = auto_reassign_unavailable_doctor_appointments(int(doctor_id))
        if reassigned:
            return redirect(url_for("doctor_dashboard", status_note=f"Auto-reassigned {len(reassigned)} of your appointment(s)"))
        return redirect(url_for("doctor_dashboard", status_note="No alternative doctor was free for your booked appointments"))
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
            current_doctor_id=session.get("doctor_id", ""),
            today=date.today().isoformat()
        )
    return render_template(
        "diagnosis.html",
        appointment_id=0,
        current_doctor_id=session.get("doctor_id", ""),
        today=date.today().isoformat()
    )


@app.route("/diagnosis_history", methods=["POST"])
@require_role("Doctor")
def diagnosis_history():

    patient_id = request.form["patient_id"]
    doctor_id = session.get("doctor_id", "0")
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
