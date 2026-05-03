# HealthDesk Project Walkthrough

Last updated: May 2026

This document is the detailed technical walkthrough of the current HealthDesk project. It explains how the major files contribute to the system, what each module is responsible for, how data moves through Flask and the C executables, and how the receptionist, doctor, patient portal, queue, diagnosis, billing, SMS, and payment flows fit together.

It is intentionally more detailed than `README.md`, but still smaller and more current than the older oversized walkthrough.

## 1. Big Picture

HealthDesk is a clinic workflow system built around three active user journeys:

- receptionist operations,
- doctor operations,
- patient portal operations.

The project still uses flat files instead of a database. The running system is a hybrid architecture:

```text
Browser / Frontend templates
        |
        v
Flask app.py routes and validation
        |
        +--> direct text/JSON reads and writes where Python owns the logic
        |
        +--> subprocess calls to Backend/c_modules/*.exe for record operations
        |
        +--> SMS adapter (sms_service.py)
        |
        +--> payment adapter (payment_service.py)
        |
        v
Backend/data/*.txt and *.json
        |
        v
Flask builds page context
        |
        v
Frontend renders updated workflow
```

The architecture split is now:

### Python owns

- routing,
- authentication,
- role checks,
- sessions,
- CSRF,
- patient OTP login,
- slot triage,
- workflow rules,
- cross-file consistency,
- queue reconciliation,
- stale cleanup,
- billing calculations,
- PDF generation,
- SMS coordination,
- Razorpay integration.

### C owns

- low-level record operations for patient, doctor, appointment, queue, diagnosis, billing, and pending requests,
- file parsing and rewriting for those modules,
- some module-specific data structures such as linked lists, arrays, stacks, and trees.

## 2. Top-Level Files

### `app.py`

This is the main Flask application and the center of the runtime.

It is responsible for:

- starting Flask with `Frontend/templates` and `Frontend/static`,
- defining all routes,
- enforcing authentication and roles,
- validating CSRF tokens,
- authenticating staff users from `Backend/data/users.txt`,
- storing patient OTP state in memory,
- calling the C executables,
- parsing the text files into Python records,
- coordinating reception, queue, doctor, diagnosis, billing, and portal workflows,
- generating bill previews and PDFs,
- keeping queue, appointment, and doctor states in sync,
- verifying Razorpay webhooks,
- sending SMS notifications.

Important runtime constants in `app.py` include:

```text
BASE_DIR
TMPL_DIR
STATIC_DIR
BACKEND_DIR
DATA_DIR
USER_FILE
BILLING_FILE
PRICING_FILE
APPOINTMENT_FILE
QUEUE_FILE
DIAGNOSIS_FILE
PENDING_APPOINTMENTS_FILE
NEW_PATIENT_REQUESTS_FILE
DOCTOR_STATUS_META_FILE
BILLING_EXE
ALLOWED_PAYMENT_STATUSES
OTP_EXPIRY_SECONDS
OTP_MAX_ATTEMPTS
PENDING_REQUEST_EXPIRY_HOURS
```

Important in-memory structures include:

- `dict` for patient, doctor, appointment, billing, and page-context records,
- `list` for collections of records,
- `set` for allowed statuses and role checks,
- `tuple` keys such as `(patient_id, doctor_id)`,
- `threading.Lock` for text-file write protection inside one Flask process,
- Flask `session` for current login state,
- `_otp_store` for patient OTP hashes, expiry, and attempt count,
- `BytesIO` for generated PDF bytes.

### `sms_service.py`

This module is the SMS boundary for the app.

It is used for:

- patient OTP delivery,
- appointment confirmation messages,
- rejection messages,
- request expiry messages,
- payment success and failure messages,
- receptionist notifications.

Behavior:

- loads environment variables through `python-dotenv` when available,
- sends through Fast2SMS when `FAST2SMS_API_KEY` is configured,
- falls back to console logging in development when the API key is missing,
- normalizes phone numbers before sending,
- captures provider errors and exposes them through `get_last_sms_error()`.

### `payment_service.py`

This module is the Razorpay integration boundary.

It is responsible for:

- checking whether payment credentials are configured,
- exposing the publishable Razorpay key ID to the Flask layer,
- creating INR payment orders from server-side bill totals,
- verifying webhook signatures using `RAZORPAY_WEBHOOK_SECRET`.

Important rule:

- the bill amount comes from the server-side bill record, not from the browser.

### `README.md`

This is the short project overview and setup guide. It is useful for first contact with the repository, but it does not cover the full runtime details.

### `SYSTEM_FLOW.md`

This is the user-facing and demo-facing system explanation. It focuses on page flow, user actions, and the operational sequence between reception, doctor, queue, and billing.

### `changes.md`

This is a historical architecture and change-tracking document for the portal expansion. It is not part of the runtime.

### `.env`

This file provides optional runtime configuration such as:

- Flask secret configuration,
- Fast2SMS credentials,
- Razorpay credentials,
- clinic phone numbers.

### `__pycache__/app.cpython-313.pyc`

This is generated Python bytecode. It is not source code and should not be edited manually.

## 3. Backend Data Files

The project uses flat files in `Backend/data/` as the system of record.

### `Backend/data/users.txt`

Purpose:

- stores staff accounts,
- supports receptionist and doctor login.

Owned by:

- Python login helpers in `app.py`.

Important note:

- current staff authentication is handled in Python, not `auth.exe`.

### `Backend/data/doctors.txt`

Purpose:

- stores doctor profile data and status fields.

Typical fields:

```text
id|name|department|experience|daily_status|current_status
```

Used by:

- doctor dashboard,
- doctors page,
- appointment slot blocking,
- alternative doctor suggestions,
- reassignment logic.

### `Backend/data/patients.txt`

Purpose:

- stores patient master records.

Typical fields:

```text
id|name|age|gender|phone|address|symptoms|visit_type|priority|department
```

Used by:

- receptionist search and registration,
- patient OTP login lookup,
- diagnosis context,
- billing context,
- patient dashboard.

### `Backend/data/appointment.txt`

Purpose:

- stores appointment records and appointment statuses.

Typical fields:

```text
appointment_id|patient_id|doctor_id|date|time_slot|status
```

Statuses used in the running app:

- `Booked`
- `Completed`
- `Cancelled`
- `Rescheduled`
- `No-show`

### `Backend/data/queue.txt`

Purpose:

- stores same-day waiting and completed queue rows.

Typical fields:

```text
token|patient_id|doctor_id|priority|status
```

Used by:

- receptionist queue page,
- doctor live queue list,
- queue reconciliation helpers.

### `Backend/data/diagnosis.txt`

Purpose:

- stores diagnosis history and prescriptions.

Used by:

- diagnosis page,
- doctor history lookup,
- patient dashboard medical-record section.

### `Backend/data/billing.txt`

Purpose:

- stores bill records,
- connects bills to appointments and patients,
- stores payment status and payment metadata.

Billing records are richer than the simpler text files and include fields such as:

- appointment linkage,
- doctor and patient labels,
- treatments,
- lab tests,
- medicine amount,
- bill total,
- payment status,
- Razorpay order ID,
- Razorpay payment ID,
- payment method,
- paid timestamp,
- initiated timestamp.

### `Backend/data/pending_appointments.txt`

Purpose:

- stores existing-patient portal booking requests,
- acts as the pending-review queue and audit trail for those requests.

Typical fields:

```text
request_id|patient_id|doctor_id|requested_date|requested_slot|reason|visit_type|status|submitted_at|expires_at|receptionist_note|appointment_id
```

### `Backend/data/new_patient_requests.txt`

Purpose:

- stores first-time online appointment requests before a patient record exists.

Typical fields:

```text
request_id|name|age|gender|phone|address|department|doctor_id|requested_date|requested_slot|reason|visit_type|priority|status|submitted_at|expires_at|receptionist_note|patient_id|appointment_id
```

### `Backend/data/pricing_catalog.json`

Purpose:

- stores doctor fees,
- treatment prices,
- treatment categories,
- department restrictions,
- lab-test pricing.

This file is owned by Python and loaded by the billing flow.

### `Backend/data/doctor_status_meta.json`

Purpose:

- stores the effective end date for doctor status overrides,
- lets Python block dates beyond today for `Unavailable`, `Off`, or `Emergency` status cases.

This file is created by Python when needed. It is part of the current runtime even though it is generated dynamically.

## 4. Shared C Header

### `Backend/c_modules/common.h`

This file defines the shared C constants, file paths, and structs used by the C modules.

It includes:

- buffer-size constants such as `MAX_NAME`, `MAX_TEXT`, `MAX_LINE`, and `MAX_TIMESTAMP`,
- file path constants for all major data files,
- shared record structs for patient, doctor, queue, diagnosis, appointment, billing, pending existing-patient requests, and first-time requests.

Important struct coverage:

- `struct Patient`
- `struct Doctor`
- `struct QueueNode`
- `struct Diagnosis`
- `struct Appointment`
- `struct BillingItem`
- `PendingAppointmentRequest`
- `NewPatientRequest`

This file keeps the C side consistent and ensures every helper points to the same record layout and file paths.

## 5. C Helper Modules

### `Backend/c_modules/patient.c`

Runtime role:

- patient search,
- patient registration.

Active executable:

```text
Backend/c_modules/patient.exe
```

Used by:

- `find_patient_by_phone()`,
- receptionist registration flow,
- first-time request approval flow.

Typical commands:

```text
patient.exe search <phone>
patient.exe "<name>|<age>|<gender>|<phone>|<address>|<symptoms>|<visit_type>|<priority>|<department>"
```

Main structure pattern:

- linked list of patient records.

Why it matters:

- reception can search quickly by phone,
- new patients can be appended without a fixed small array,
- first-time request approval can turn a request into a proper patient record.

### `Backend/c_modules/doctor.c`

Runtime role:

- doctor profile creation,
- doctor status updates,
- doctor suggestion by department.

Active executable:

```text
Backend/c_modules/doctor.exe
```

Used by:

- `/add_doctor`,
- `/doctor_status`,
- `/doctor_my_status`,
- suggestion helpers in appointment and reception flows.

Typical commands:

```text
doctor.exe status <doctor_id> <daily_status> <current_status>
doctor.exe suggest <department>
doctor.exe "<name>|<department>|<experience>"
```

Main structure pattern:

- binary tree for doctor organization and lookup in the C module.

Why it matters:

- reception can add doctors,
- doctor availability can be changed from both receptionist and doctor flows,
- same-department alternatives can be suggested when a doctor is blocked.

### `Backend/c_modules/appointment.c`

Runtime role:

- appointment slot listing,
- slot availability checks,
- booking,
- cancellation,
- reschedule,
- completion,
- no-show updates.

Active executable:

```text
Backend/c_modules/appointment.exe
```

Used by:

- `load_appointment_slots()`,
- `run_appointment_command()`,
- reception booking,
- portal booking,
- appointment actions,
- diagnosis completion flow.

Typical commands:

```text
appointment.exe slots <doctor_id> <date>
appointment.exe book <patient_id> <doctor_id> <date> <time_slot>
appointment.exe cancel <appointment_id>
appointment.exe complete <appointment_id>
appointment.exe noshow <appointment_id>
appointment.exe reschedule <appointment_id> <new_date> <new_time>
```

Main structure pattern:

- dynamically loaded appointment array with fixed slot definitions.

Why it matters:

- this module is the core source for appointment state,
- queue, diagnosis, and billing all depend on appointment status transitions.

### `Backend/c_modules/queue.c`

Runtime role:

- creates same-day queue tokens.

Active executable:

```text
Backend/c_modules/queue.exe
```

Used by:

- `add_patient_to_queue()`.

Main structure pattern:

- linked-list queue representation inside the C module.

Why it matters:

- same-day staff bookings move into the live doctor workflow by way of this queue record.

### `Backend/c_modules/diagnosis.c`

Runtime role:

- reads diagnosis history,
- appends diagnosis and prescription records.

Active executable:

```text
Backend/c_modules/diagnosis.exe
```

Used by:

- diagnosis page history loading,
- diagnosis save flow,
- patient dashboard record history.

Main structure pattern:

- stack-style usage for history ordering on the C side.

Why it matters:

- diagnosis save is the event that turns an active consultation into a completed billable visit.

### `Backend/c_modules/billing.c`

Runtime role:

- bill ID generation,
- bill lookup,
- bill listing,
- bill save commands.

Active executable:

```text
Backend/c_modules/billing.exe
```

Used by:

- `read_bills()`,
- `find_bill_by_id()`,
- `find_bill_by_appointment_id()`,
- `save_bill_record()`,
- other bill lookup helpers.

Why it matters:

- billing persistence still lives in the C helper layer even though pricing and bill logic are mainly in Python.

### `Backend/c_modules/pending_request.c`

Runtime role:

- owns both existing-patient pending requests and first-time pending requests,
- checks whether a pending soft-lock already exists on a slot,
- expires old requests.

Active executable:

```text
Backend/c_modules/pending_request.exe
```

Used by:

- patient portal booking,
- first-time request submission,
- receptionist approval,
- receptionist rejection,
- request expiry processing.

Typical command families:

```text
list-existing
add-existing
update-existing
soft-lock-exists
list-new
add-new
update-new
expire
```

Main structure pattern:

- linked lists for both pending existing-patient requests and first-time requests.

Why it matters:

- it prevents portal requests from going directly into `appointment.txt` when receptionist review is required.

### `Backend/c_modules/auth.c`

This file still exists in the repository, but it is not part of the active login path. Staff login is handled in Python now.

## 6. `app.py` By Responsibility Area

This section is the most important part of the walkthrough because most real system behavior now lives in Python.

### 6.1 Core utilities

Important helpers:

- `append_data_line()`
- `clean_record_field()`
- `safe_int()`
- `parse_iso_date()`
- `parse_iso_datetime()`
- `format_human_date()`
- `format_amount()`

These helpers make the rest of the code safer and keep file formatting consistent.

### 6.2 Authentication and authorization

Important helpers:

- `is_authenticated()`
- `require_role()`
- `get_csrf_token()`
- `verify_csrf_token()`
- `password_matches()`
- `authenticate_user()`

Important rules:

- staff passwords are checked in Python,
- every state-changing form must include `_csrf_token`,
- the Razorpay webhook is the only CSRF-exempt POST route,
- doctor pages are restricted by doctor role,
- patient portal pages are restricted by patient role.

### 6.3 Patient OTP login

Important helpers:

- `normalize_phone()`
- `is_valid_patient_phone()`
- `mask_phone()`
- `hash_otp()`
- `find_registered_patient_by_phone()`
- `generate_otp()`
- `verify_otp()`

Important rules:

- OTPs are six digits,
- OTPs are stored as hashes in memory,
- OTP expires after five minutes,
- too many wrong attempts invalidate it,
- OTP is only for already registered patients.

### 6.4 SMS notification helpers

Important helpers:

- `send_patient_otp()`
- `send_sms_notice()`
- `notify_receptionists()`

These functions keep all messaging in one place and allow the rest of the code to treat SMS as an optional service boundary instead of inline provider logic.

### 6.5 Billing helpers

Important helpers:

- `run_billing_command()`
- `parse_bill_line()`
- `read_bills()`
- `find_bill_by_id()`
- `find_bill_by_appointment_id()`
- `serialize_bill_record()`
- `save_bill_record()`
- `update_bill_record()`
- `build_bill_preview_text()`
- `build_bill_pdf()`
- `create_bill_record()`

Important billing rules:

- billing is tied to appointment completion,
- duplicate billing is blocked by appointment linkage,
- totals are recalculated from structured bill components,
- paid bills show payment metadata in preview and PDF.

### 6.6 Appointment helpers

Important helpers:

- `parse_appointment_line()`
- `read_appointment_file()`
- `write_appointment_file()`
- `load_appointment_slots()`
- `slot_is_available()`
- `run_appointment_command()`
- `parse_booked_appointment_id()`
- `read_appointments()`
- `parse_appointment_datetime()`
- `is_consultation_day_reached()`
- `is_future_appointment()`
- `find_appointment_by_id()`

These helpers are used by:

- reception,
- appointments page,
- doctor consultation flow,
- patient cancellation flow,
- queue reconciliation,
- billing context construction.

### 6.7 Queue helpers

Important helpers:

- `add_patient_to_queue()`
- `update_waiting_queue_status()`
- `read_queue()`
- `write_queue_file()`
- `reconcile_waiting_queue_entries()`
- `process_queue()`
- `build_reception_queue_groups()`
- `read_assigned_queue_patients()`

Important queue rule:

- queue is not an independent service sequence anymore,
- it is derived from same-day appointment activity and kept synchronized with appointment state.

### 6.8 Doctor helpers

Important helpers:

- `get_doctors()`
- `write_doctor_file()`
- `load_doctor_status_meta()`
- `save_doctor_status_meta()`
- `normalize_doctor_statuses()`
- `doctor_current_status_view()`
- `doctor_status_end_date()`
- `doctor_is_blocked_for_date()`
- `update_doctor_status_meta()`
- `expire_doctor_status_overrides()`
- `doctor_has_live_workload()`
- `sync_doctor_busy_statuses()`
- `suggest_doctors_by_department()`
- `get_suggested_doctors()`
- `get_reassignment_candidates()`

Important current rule:

- doctor unavailability blocks future slot selection,
- but existing appointments are not silently auto-moved,
- reassignment requires manual action and patient confirmation.

### 6.9 Diagnosis helpers

Important helpers:

- `read_diagnosis_for_patient()`
- `get_diagnosis_context()`
- `resolve_consultation_appointment()`
- `doctor_can_access_patient()`
- `auto_generate_bill()`

Important rule:

- diagnosis save is the real consultation completion event,
- not just opening the diagnosis page and not just clicking a generic complete button.

### 6.10 Pending request helpers

Important helpers:

- `parse_pending_request_line()`
- `run_pending_request_command()`
- `read_all_pending_requests()`
- `create_pending_request()`
- `update_pending_status()`
- `read_pending_requests_for_patient()`
- `read_pending_requests_for_reception()`
- `pending_slot_exists()`
- `parse_new_patient_request_line()`
- `read_all_new_patient_requests()`
- `create_new_patient_request()`
- `update_new_patient_request_status()`
- `read_new_patient_requests_for_reception()`
- `run_expiry_check()`

These helpers are what make the patient portal safe to operate without allowing pending online requests to directly corrupt appointment state.

### 6.11 Patient portal triage helpers

Important helpers:

- `triage_booking_request()`
- `auto_approve_booking()`
- `exception_queue_booking()`
- `doctor_options_for_department()`
- `choose_any_available_doctor()`
- `build_patient_slot_payload()`
- `register_patient_from_request()`

Important triage rule:

Portal auto-approval only happens when:

- the request is submitted during clinic review hours,
- doctor availability does not require receptionist review,
- visit type is `New`.

Otherwise the request goes to the pending-review queue.

### 6.12 Payment helpers

Important helpers:

- `revert_stale_initiated_payments()`
- `find_bill_by_razorpay_order_id()`
- payment routes using `create_payment_order()` and `verify_webhook_signature()`

Important payment rules:

- browser checkout does not mark a bill paid,
- only the verified webhook updates final payment state,
- stale initiated payments are cleaned up,
- patient ownership is checked before allowing payment or PDF access.

## 7. Route Map

### Public routes

```text
/                         -> landing page
/login                    -> staff login
/patient/login            -> patient OTP login
/patient/request-otp      -> request OTP
/patient/verify-otp       -> verify OTP
/patient/new              -> first-time request form
/patient/new/slots        -> public future-slot lookup
/patient/new/submit       -> first-time request submit
/payment/webhook          -> Razorpay webhook
```

### Patient portal routes

```text
/patient/dashboard
/patient/book
/patient/book/slots
/patient/book/submit
/patient/cancel
/patient/bills/<bill_id>/pdf
/patient/payment/create-order
/patient/logout
```

### Receptionist routes

```text
/receptionist_dashboard
/reception
/reception/approve
/reception/reject
/appointments
/appointment_reassign_options
/book_appointment
/cancel_appointment
/reschedule
/update_appointment
/queue
/queue/panels
/doctors
/add_doctor
/toggle_doctor
/doctor_status
/billing
/generate_bill
/billing/update-status
/billing/download/<bill_id>
```

### Doctor routes

```text
/doctor
/doctor/dashboard-panels
/doctor_my_status
/doctor_complete_consultation
/diagnosis
/diagnosis_history
/add_diagnosis
```

## 8. Frontend Templates

All major pages are rendered server-side through Jinja templates.

### `Frontend/templates/index.html`

Role:

- base shell for authenticated staff pages.

Contributes:

- document shell,
- sidebar,
- topbar,
- logout form,
- role-aware navigation,
- shared content block.

### `Frontend/templates/landing.html`

Role:

- public landing page.

Contributes:

- staff login entry,
- patient OTP entry,
- first-time request entry,
- visual explanation of the product.

### `Frontend/templates/login.html`

Role:

- staff login screen.

Contributes:

- username/password form,
- CSRF token,
- error display.

### `Frontend/templates/patient_login.html`

Role:

- patient OTP login flow UI.

Contributes:

- phone-number step,
- OTP step,
- masked-phone display,
- error and message feedback.

### `Frontend/templates/patient_dashboard.html`

Role:

- patient self-service home.

Contributes:

- upcoming appointments,
- pending requests,
- appointment history,
- diagnosis history,
- bills and payment actions,
- profile summary,
- cancellation actions where allowed.

### `Frontend/templates/patient_book.html`

Role:

- existing-patient booking form,
- also reused for first-time request form.

Contributes:

- department and doctor selection,
- future-date selection,
- slot loading,
- reason entry,
- visit-type selection,
- first-time or existing-patient specific sections.

### `Frontend/templates/new_patient_request_submitted.html`

Role:

- confirmation page after first-time request submission.

### `Frontend/templates/receptionist_dashboard.html`

Role:

- receptionist command center.

Contributes:

- summary counts,
- pending request review cards,
- approve and reject controls,
- quick access links.

### `Frontend/templates/reception.html`

Role:

- receptionist intake page.

Contributes:

- phone search,
- registration form,
- patient profile view,
- department and doctor selection,
- slot board,
- booking confirmation and queue token display.

### `Frontend/templates/appointments.html`

Role:

- appointment control page.

Contributes:

- department and doctor filters,
- date filter,
- seven-day availability overview,
- slot board,
- appointment action groups,
- reschedule and reassignment controls.

Important current rule:

- reception does not manually finish consultations from here.

### `Frontend/templates/queue.html` and `_queue_panels.html`

Role:

- receptionist queue monitoring.

Contributes:

- grouped waiting queue by doctor,
- completed counts,
- queue token display,
- patient priority and symptoms.

### `Frontend/templates/doctors.html`

Role:

- doctor roster and status management.

Contributes:

- add-doctor form,
- optional username and password input,
- newly created account preview,
- doctor status controls.

### `Frontend/templates/doctor_dashboard.html` and `_doctor_dashboard_panels.html`

Role:

- doctor dashboard.

Contributes:

- doctor identity and availability controls,
- live queue patients,
- future booked appointments,
- consultation start actions,
- billing-result context after diagnosis save.

### `Frontend/templates/diagnosis.html`

Role:

- consultation and diagnosis page.

Contributes:

- patient history,
- appointment-linked consultation form,
- diagnosis and prescription entry.

### `Frontend/templates/billing.html`

Role:

- receptionist billing page.

Contributes:

- billable patient selection,
- pricing-driven treatment and lab-test capture,
- medicine amount and notes,
- bill preview,
- status update actions,
- bill PDF links.

## 9. Static Files

### `Frontend/static/css/style.css`

Role:

- shared application design system and responsive styling.

It contains:

- CSS variables,
- shared layout styles,
- button, badge, table, and card systems,
- page-specific styles for reception, appointments, queue, doctors, diagnosis, billing, and patient pages.

### `Frontend/static/script/main.js`

Role:

- shared frontend behavior.

It handles:

- sidebar toggling,
- mobile overlay behavior,
- auto-refresh when configured,
- appointment action form field toggling.

## 10. Runtime Data Flow By Workflow

### Staff login

```text
login.html
    -> POST /login
    -> app.py authenticate_user()
    -> read users.txt
    -> password check in Python
    -> session created
    -> redirect to receptionist or doctor dashboard
```

### Patient OTP login

```text
patient_login.html
    -> POST /patient/request-otp
    -> app.py generate_otp()
    -> send SMS
    -> POST /patient/verify-otp
    -> app.py verify_otp()
    -> patient session created
    -> redirect /patient/dashboard
```

### Receptionist search and registration

```text
reception.html
    -> POST /reception action=search
    -> patient.exe search phone
    -> existing patient returned or not found

if not found:
    -> POST /reception action=register
    -> patient.exe "name|age|..."
    -> patients.txt updated
```

### Staff appointment booking

```text
reception.html or appointments.html
    -> POST /book_appointment
    -> Flask validates patient, doctor, date, and slot
    -> appointment.exe book ...
    -> appointment.txt updated
    -> if same day: queue.exe
    -> queue.txt updated
    -> confirmation shown in UI
```

### Existing patient portal booking

```text
patient_book.html
    -> POST /patient/book/submit
    -> Flask validates doctor/date/slot
    -> triage_booking_request()

if auto-approved:
    -> appointment.exe book ...
    -> pending_request.exe add-existing with status Approved
    -> SMS confirmation

if needs review:
    -> pending_request.exe add-existing with status Pending
    -> slot soft-lock recorded
    -> receptionist notified
```

### First-time patient request

```text
patient_book.html (new mode)
    -> POST /patient/new/submit
    -> Flask validates fields and future date
    -> pending_request.exe add-new
    -> new_patient_requests.txt updated
    -> SMS confirmation of request receipt
    -> receptionist dashboard receives pending item
```

### Receptionist approval flow

```text
receptionist_dashboard.html
    -> POST /reception/approve
    -> Flask re-checks slot

existing patient:
    -> appointment.exe book ...
    -> pending_request.exe update-existing

first-time patient:
    -> patient.exe create patient
    -> appointment.exe book ...
    -> pending_request.exe update-new
```

### Queue monitoring

```text
queue.html
    -> Flask expire_stale_consultations()
    -> Flask reconcile_waiting_queue_entries()
    -> read queue.txt and appointment state
    -> build per-doctor queue groups
    -> render monitoring page
```

### Doctor consultation

```text
doctor_dashboard.html
    -> POST /doctor_complete_consultation
    -> access and date checks
    -> redirect /diagnosis?patient_id=...&appointment_id=...
```

### Diagnosis save

```text
diagnosis.html
    -> POST /add_diagnosis
    -> Flask validates assignment, date, diagnosis, prescription
    -> appointment.exe complete appointment_id
    -> diagnosis.exe save record
    -> queue row marked Completed
    -> auto_generate_bill()
    -> doctor redirected with billing context
```

### Billing generation

```text
billing.html
    -> GET /billing
    -> read patients, appointments, doctors
    -> billing.exe list
    -> build billing lookup

POST /generate_bill
    -> validate completed appointment context
    -> calculate totals from pricing catalog
    -> billing.exe save
    -> preview returned
```

### Online payment

```text
patient dashboard
    -> POST /patient/payment/create-order
    -> payment_service.py create Razorpay order
    -> bill marked INITIATED
    -> webhook POST /payment/webhook
    -> signature verified
    -> bill marked PAID or reset to PENDING
```

### Doctor unavailable and reassignment

```text
doctors.html or doctor dashboard
    -> POST doctor status route
    -> doctor.exe status ...
    -> doctor_status_meta.json updated
    -> future slots blocked

if reception reassigns manually:
    -> patient confirmation required
    -> replacement slot re-checked
    -> appointment.exe book replacement
    -> appointment.exe cancel original
    -> queue updated if same-day
```

## 11. Current Runtime Rules

These are the most important rules the code currently enforces.

- Staff authentication is handled in Python, not by passing passwords to `auth.exe`.
- Every normal POST form requires CSRF.
- Patient OTPs are in memory only.
- Portal patients can request only future appointments.
- Reception can book same-day or future appointments.
- Same-day staff bookings create queue tokens.
- Diagnosis save completes the consultation.
- Reception cannot manually complete consultations from the appointments page.
- Billing is allowed only for completed appointments.
- Duplicate billing is blocked for the same completed appointment.
- Online payment is finalized only by verified webhook.
- Existing-patient requests go through pending review unless triage allows auto-approval.
- First-time requests do not create patient records until reception approves them.
- Reassignment is manual and requires patient confirmation and a confirmation note.
- Patient self-cancel is blocked within 24 hours of the appointment time.

## 12. Data Structures Summary

### Python

Used heavily throughout `app.py`:

- `dict` for records and lookup maps,
- `list` for ordered collections,
- `set` for status and role checks,
- `tuple` for grouping keys,
- `threading.Lock` for write coordination,
- Flask `session` for active identity,
- in-memory OTP dictionary for hashed OTP state.

### C

Defined in `common.h` and used across modules:

- `struct Patient`
- `struct Doctor`
- `struct QueueNode`
- `struct Diagnosis`
- `struct Appointment`
- `struct BillingItem`
- `PendingAppointmentRequest`
- `NewPatientRequest`

Patterns used by the C side include:

- linked lists,
- dynamic arrays,
- stack-style history handling,
- tree-based doctor organization.

### Frontend

The frontend mainly uses:

- Jinja template context objects,
- DOM references,
- small JavaScript arrays and objects,
- CSS custom properties and responsive layout classes.

## 13. Security And Validation

Current safeguards include:

- hashed staff passwords,
- role-gated routes,
- CSRF on state-changing forms,
- phone-number validation,
- age validation,
- appointment date validation,
- server-side slot re-checks before approval or booking,
- patient ownership checks for bill PDF and payment actions,
- payment status whitelisting,
- webhook signature verification,
- data sanitization through `clean_record_field()`.

Known architectural limitation:

- flat files are simple and workable for a small local system, but they do not provide the transaction safety and concurrency control of a real database.

## 14. Generated And Binary Files

### Active executables

```text
appointment.exe
billing.exe
doctor.exe
diagnosis.exe
patient.exe
pending_request.exe
queue.exe
```

### Legacy executable

```text
auth.exe
```

### Runtime-generated files

```text
Backend/data/doctor_status_meta.json
__pycache__/*
```

If a C source file changes, its matching executable should be rebuilt.

Examples:

```powershell
gcc Backend\c_modules\appointment.c -o Backend\c_modules\appointment.exe
gcc Backend\c_modules\doctor.c -o Backend\c_modules\doctor.exe
gcc Backend\c_modules\queue.c -o Backend\c_modules\queue.exe
gcc Backend\c_modules\billing.c -o Backend\c_modules\billing.exe
gcc Backend\c_modules\pending_request.c -o Backend\c_modules\pending_request.exe
gcc Backend\c_modules\patient.c -o Backend\c_modules\patient.exe
gcc Backend\c_modules\diagnosis.c -o Backend\c_modules\diagnosis.exe
```

## 15. File-By-File Quick Reference

```text
app.py
```

Main Flask app. Owns routes, session logic, CSRF, triage, workflow coordination, bill generation, queue reconciliation, and payment webhook handling.

```text
sms_service.py
```

Fast2SMS integration and development fallback logging.

```text
payment_service.py
```

Razorpay order creation and webhook signature verification.

```text
Backend/c_modules/common.h
```

Shared C structs, constants, and file paths.

```text
Backend/c_modules/patient.c / patient.exe
```

Patient search and registration.

```text
Backend/c_modules/doctor.c / doctor.exe
```

Doctor profile creation, doctor status writes, and doctor suggestions.

```text
Backend/c_modules/appointment.c / appointment.exe
```

Appointment slot handling and appointment status transitions.

```text
Backend/c_modules/queue.c / queue.exe
```

Queue token generation for same-day appointments.

```text
Backend/c_modules/diagnosis.c / diagnosis.exe
```

Diagnosis history and diagnosis save.

```text
Backend/c_modules/billing.c / billing.exe
```

Bill persistence and lookup helper.

```text
Backend/c_modules/pending_request.c / pending_request.exe
```

Existing-patient and first-time request persistence, soft locks, and expiry handling.

```text
Frontend/templates/*
```

All user-facing and staff-facing server-rendered pages.

```text
Frontend/static/css/style.css
```

Global styling and responsive layout system.

```text
Frontend/static/script/main.js
```

Shared UI behavior and appointment action toggling.

## 16. Most Important End-To-End Rule

The system is now strongly doctor-driven at the completion stage:

```text
Appointment booked
        -> if same day, queue token created
        -> doctor sees patient in live queue
        -> doctor opens diagnosis
        -> doctor saves diagnosis and prescription
        -> appointment becomes Completed
        -> queue row becomes Completed
        -> bill context becomes available
        -> receptionist can review, preview, update status, and download the bill
```

That is the main workflow thread connecting reception, doctor, queue, diagnosis, and billing in the current project.
