# HealthDesk — Patient Portal Architecture
### Complete System Design · All Discussed Changes · May 2026

> **How to use this file**
> Paste into your project root as `ARCHITECTURE.md`.
> Read top to bottom before writing a single line of code.
> Every decision in here has a reason. If something looks unnecessary, the reason is written below it.

---

## Table of Contents

1. [What We Are Building and Why](#1-what-we-are-building-and-why)
2. [What Does NOT Change](#2-what-does-not-change)
3. [The Three Roles](#3-the-three-roles)
4. [Phase 1 — Patient Auth (OTP Login)](#4-phase-1--patient-auth-otp-login)
5. [Phase 2 — Patient Dashboard (Read-Only)](#5-phase-2--patient-dashboard-read-only)
6. [Phase 3 — Appointment Booking + Hybrid Triage](#6-phase-3--appointment-booking--hybrid-triage)
7. [Phase 4 — SMS Notifications (Fast2SMS)](#7-phase-4--sms-notifications-fast2sms)
8. [Phase 5 — Razorpay Payments](#8-phase-5--razorpay-payments)
9. [Receptionist Side Changes](#9-receptionist-side-changes)
10. [New Data Files and Schema Changes](#10-new-data-files-and-schema-changes)
11. [All New Routes](#11-all-new-routes)
12. [Environment Variables](#12-environment-variables)
13. [Files to Create and Modify](#13-files-to-create-and-modify)
14. [UX Rules — Designing for Real Patients](#14-ux-rules--designing-for-real-patients)
15. [Security Checklist](#15-security-checklist)

---

## 1. What We Are Building and Why

### The core problem we are solving

Right now, the only way a patient can book an appointment is to call the clinic or physically walk in. The receptionist manually enters everything. This creates four real problems:

**Problem 1 — Phone tag.** Patients call, nobody picks up, they try again, leave a message, wait. They have no confirmation, no visibility. Anxiety builds. They end up calling again to confirm.

**Problem 2 — Zero record access.** After every visit, the patient walks out with a paper prescription they can lose. They cannot see what diagnosis was recorded, what was prescribed, or what they were charged. They carry physical files to every visit.

**Problem 3 — Rescheduling pain.** Changing a slot means calling again, re-explaining, and waiting. It takes 10 minutes to do something that should take 10 seconds.

**Problem 4 — Billing confusion.** Patients receive a total with line items they do not understand. They cannot access old bills. Any dispute has to be handled in person.

### What this feature fixes

The patient portal turns the clinic system into a **platform between patient and hospital** — not a one-way system where only the receptionist can do anything. Patients can:

- Log in from their phone with no password to remember
- Book appointments with the doctor they want, at the slot they want
- Track whether their request was confirmed, and why if it was not
- See every past diagnosis and prescription from every visit
- View and pay every bill online

### What it does NOT do (intentional limits)

- **Patients cannot register themselves.** They must visit the clinic once to be registered by the receptionist. This ensures the hospital has verified their identity before they can use the portal. A patient who does not exist in `patients.txt` cannot log in at all.
- **Patients cannot edit their own profile.** Name, age, address, department — all read-only. To change anything, they contact the hospital. This protects the integrity of medical records.
- **Patients cannot cancel within 24 hours.** Beyond 24 hours, they can cancel themselves. Within 24 hours, they must call. This protects doctors from last-minute empty slots.

---

## 2. What Does NOT Change

This is the most important section to read before writing any code.

The existing system — receptionist workflow, doctor workflow, all C modules, all existing data files — **is completely untouched**. The patient portal is an additive layer that sits on top of the existing system.

### Why this matters

If you build the portal wrong, you risk corrupting the data files that the rest of the system depends on. The safe approach is: the portal only reads from the existing files (`patients.txt`, `appointment.txt`, `diagnosis.txt`, `billing.txt`), and only writes to them through the existing pathways — the same C executables the receptionist already uses.

### The rule: patient requests never go directly to appointment.txt

A patient submitting a booking request does not immediately create an appointment. The request goes to `pending_appointments.txt` first. Only after a receptionist approves it (or the triage system auto-approves it) does the system call `appointment.exe` and create the real appointment. This means:

- Unverified patient requests cannot corrupt the appointment file
- Slot management remains controlled by the existing C module
- The doctor's queue is never polluted by unverified bookings

### Files that are never modified by the portal

```
Backend/c_modules/appointment.c      — no changes, ever
Backend/c_modules/queue.c            — no changes, ever
Backend/c_modules/diagnosis.c        — no changes, ever
Backend/c_modules/doctor.c           — no changes, ever
Backend/c_modules/patient.c          — no changes, ever
Backend/data/patients.txt            — portal reads only, never writes
Backend/data/diagnosis.txt           — portal reads only, never writes
Backend/data/doctors.txt             — portal reads only, never writes
Backend/data/queue.txt               — portal does not touch
Backend/data/users.txt               — portal does not touch
```

---

## 3. The Three Roles

The system currently has two roles: Receptionist and Doctor. We are adding a third: Patient.

| Role | How they log in | What is new for them |
|---|---|---|
| Receptionist | Username + password (unchanged) | Gets a "Pending Patient Requests" section on their dashboard |
| Doctor | Username + password (unchanged) | Nothing changes at all |
| **Patient** | **Phone number + 6-digit OTP (new)** | **Entire portal is new** |

### Why the roles are kept strictly separate

Each role is a completely separate surface of the application. A patient logging in should never be able to see the receptionist dashboard or access any internal data. This is enforced by checking `session["role"]` at the start of every route.

The session structure for a patient after login:

```
session["role"]          = "Patient"
session["patient_id"]    = 6              ← integer from patients.txt
session["patient_name"]  = "Aakash"
session["patient_phone"] = "9000000006"
```

Every patient route checks that `session["role"] == "Patient"` before doing anything else. If someone manually navigates to `/patient/dashboard` without being logged in, they are redirected to `/patient/login`. If a receptionist tries to access a patient route, they are redirected to `/`. This is not optional — it is the first line of every route function.

---

## 4. Phase 1 — Patient Auth (OTP Login)

### What we are building in this phase

- The login page at `/patient/login`
- The OTP generation and delivery system
- The OTP verification logic
- The patient session

### Why OTP and not username/password

This decision was made deliberately. Here is the reasoning:

**Reason 1 — Zero registration friction.** The patient is already in the system. They were registered by the receptionist on their first visit. There is no separate sign-up step. They enter their phone number — if they exist, they get an OTP. If they do not exist, they are told to visit the clinic. No "create an account" form.

**Reason 2 — No password management.** Hospital patients include elderly people who struggle with passwords — who forget them, write them on paper, or use the same password everywhere. OTP on their phone is something they already understand from banking apps and food delivery. It requires zero explanation.

**Reason 3 — Phone number is already the patient identity.** The existing system already uses phone number as the unique patient identifier. Authentication and identity resolution happen in the same step: find the patient by phone, generate OTP, done.

**Reason 4 — OTP is naturally time-limited.** A password, once compromised, works forever. An OTP expires in 5 minutes and is useless after that.

### How the login flow works, step by step

**Step 1 — Patient enters phone number**

The login page shows a single text field asking for phone number. Nothing else. No username, no password. The field is `type="tel"` for mobile keyboards, with `maxlength="10"`.

**Step 2 — System looks up the phone number**

Python reads `patients.txt` and searches for a record where the phone number matches. Two outcomes:

- **Not found:** The page shows "This phone number is not registered with us. Please visit the clinic to register." No OTP is generated. No SMS is sent. The patient is not told to try a different number — this is intentional, as it prevents phone number enumeration by attackers.
- **Found:** Proceed to Step 3.

**Step 3 — OTP is generated and sent**

Python generates a 6-digit number using `secrets.randbelow(900000) + 100000`. The `secrets` module is used instead of `random` because `random` is not cryptographically secure — it can be predicted if the seed is known. The OTP is immediately hashed with SHA-256 and stored in memory. The plaintext OTP is sent via SMS and then discarded — only the hash is kept.

The in-memory OTP store structure:

```python
_otp_store = {
    "9000000006": {
        "hash": "a3f4b2...",       # SHA-256 hash of the 6-digit OTP
        "expires_at": 1714900200,  # Unix timestamp: now + 5 minutes
        "attempts": 0              # increments on each wrong guess
    }
}
```

**Why hash the OTP even in memory?**

If someone could read the server's memory — via a crash dump, a logging mistake, or a debug endpoint accidentally left open — they would see hashed values, not plaintext OTPs. It is a small extra step that meaningfully reduces risk.

**Step 4 — Patient enters OTP**

The OTP entry screen shows the phone number in masked form (e.g., `90XXXXX006`) so the patient knows which number received the message. The OTP input is `type="number"`, `maxlength="6"`, and auto-submits when 6 digits are entered — no button press required. This small detail matters on mobile, where pressing a separate submit button after typing 6 digits feels like extra friction.

**Step 5 — OTP is verified**

Three checks happen in order:

1. **Does a record exist for this phone?** If not: "No OTP was requested. Please start again."
2. **Has the OTP expired?** Compare current time against `expires_at`. If expired, delete the record and show "OTP expired. Please request a new one."
3. **Is the entered OTP correct?** Hash the entered value and compare to the stored hash. If wrong, increment `attempts`. After 3 wrong attempts, delete the record entirely and force restart.

**Why delete the record after 3 wrong attempts?**

This prevents brute-forcing a 6-digit OTP (1,000,000 possibilities) by trying all combinations. With 3 attempts and a 5-minute expiry, an attacker would need to guess the correct OTP within their first three tries — a 1-in-333,333 chance per request cycle. Combined with the 5-minute window, this makes automated attacks impractical.

**Step 6 — Session created**

On successful verification, delete the OTP record from memory and create the Flask session. Redirect to `/patient/dashboard`.

### What can go wrong and how to handle it

| Problem | What the patient sees | What the system does |
|---|---|---|
| Wrong phone number | "Not registered. Visit clinic." | No OTP generated, no error exposed |
| SMS not delivered (API failure) | "OTP sent to your number" | Dev mode: prints to console. Never crash the app. |
| Patient enters wrong OTP | "Incorrect OTP. X attempt(s) left." | Increment attempt counter |
| Patient takes too long | "OTP expired. Request a new one." | Delete record, patient restarts cleanly |
| 3 wrong attempts | "Too many attempts. Request a new OTP." | Delete record, patient restarts |

### What to build in this phase

- `Frontend/templates/patient_login.html` — two-step form (phone entry then OTP entry) on one page, toggled by JavaScript without a page reload between steps.
- Route `POST /patient/request-otp` — validate phone format (10 digits), look up patient, generate OTP, send SMS, show OTP step.
- Route `POST /patient/verify-otp` — run three verification checks, create session on success.
- Route `POST /patient/logout` — clear session, redirect to `/patient/login`.
- Helper functions: `generate_otp(phone)`, `verify_otp(phone, entered)`.

---

## 5. Phase 2 — Patient Dashboard (Read-Only)

### What we are building in this phase

The patient's home page. It shows everything that belongs to them — appointments, medical records, bills, and their profile. Nothing is editable yet. This phase has no write operations.

### Why build this before booking

Building the dashboard first forces you to solve the data access layer cleanly. Every piece of data on this page — appointments, diagnosis, billing — needs a function that fetches records filtered by patient ID. You will need exactly those same functions in Phase 3 when booking is added. Building the dashboard first means those functions are already written and tested before you need them for booking logic.

### The four sections and what goes in each

**Section 1 — Upcoming Appointments (shown first)**

This is the first thing on the page because it answers the patient's most frequent question: "Do I have an appointment coming up?"

Show:
- Doctor name (not `doctor_id` — look it up from `doctors.txt`)
- Date in human format: "Tuesday, 10 May 2026" — never "2026-05-10"
- Time: "8:30 AM" — never "08:30"
- Department
- Status badge: Confirmed / Pending Confirmation / Cancelled

If there is a pending request in `pending_appointments.txt` for this patient, it appears here too with a "Pending Confirmation" badge and the time remaining before it expires (e.g., "Expires in 1h 23m").

Cancel button appears only if the appointment is more than 24 hours away. If it is within 24 hours, show: "To cancel within 24 hours, please call the clinic" with the clinic phone number. Do not just hide the button — tell the patient why it is not there.

**Section 2 — Medical Records**

This answers: "What did the doctor say last time?"

Show one card per visit, newest first:
- Visit date (human format)
- Doctor name and department
- First 80 characters of the diagnosis as a preview
- An "Expand" button to see the full diagnosis and prescription

What NOT to show:
- `record_id`, `doctor_id`, `patient_id` — these are internal identifiers
- Any empty fields — if prescription is empty, do not show the prescription row at all
- Raw field labels like "visit_type: New" — the patient does not need to know this

**Section 3 — Bills**

This answers: "What do I owe, and what have I paid?"

Show bills newest first. Bills with status `PENDING` appear at the very top — above paid ones — because they require action. A patient with an unpaid bill should see it the moment they open the portal.

Each bill shows:
- Visit date (human format)
- Total amount: "Rs 1,200" (not "1200.0")
- Payment status badge: Paid (green) / Pending (orange) / Waived (gray)
- "Pay Now" button for pending bills — this is wired in Phase 5
- "Download PDF" button for all bills

On expand, show line items in plain English:
- "Doctor consultation fee: Rs 500"
- "Lab tests: Rs 300"
- "Medicines: Rs 200"
- "Total: Rs 1,200"

Never show: "doctor_fee: 500.0", "lab_total: 300.0" — format everything.

**Section 4 — My Profile (bottom)**

Read-only. Shows name, age, phone (masked), department, address.

Include the note: "To update your details, please contact the clinic." This sets the expectation clearly — there is no edit button, and that is intentional.

### The data security rule that must never be broken

Every data fetch on this page must be filtered server-side by `session["patient_id"]`. The patient ID comes from the session — not from the URL, not from a form field.

**Why this matters:** Without this check, Patient A could modify the URL or send a crafted request to see Patient B's diagnosis records and bills. Medical records are private. This is a legal and ethical issue, not just a technical one.

The correct pattern:

```python
# CORRECT — always use session
pid = session["patient_id"]
my_bills = [b for b in all_bills if str(b["patient_id"]) == str(pid)]

# WRONG — never trust URL parameters for identity
pid = request.args.get("patient_id")  # an attacker can set this to any value
```

### What to build in this phase

- `Frontend/templates/patient_dashboard.html` — four sections as described above
- Route `GET /patient/dashboard` — fetch and filter all data for the logged-in patient, run expiry check (described in Phase 3)
- Helper functions: `read_diagnosis_for_patient(patient_id)`, `read_pending_requests_for_patient(patient_id)`

---

## 6. Phase 3 — Appointment Booking + Hybrid Triage

### What we are building in this phase

The booking flow, the triage decision engine, the auto-approve path, the exception queue, the receptionist approval and rejection flow, and the patient cancellation rule.

### The hybrid triage model — why full manual verification is not enough

The original plan was: every booking request goes to the receptionist for approval. This is safe, but it has a critical flaw — **what happens when the receptionist is busy, at lunch, or it is 8 PM?**

The patient submits a request, waits an hour, nothing happens, they do not know if the system is broken or the receptionist is reviewing. They call the clinic. The portal has now made things worse, not better.

The hybrid model solves this by dividing requests into two types:

- **Standard case** (low risk, high volume): auto-approve instantly. No receptionist involvement. Patient gets confirmation in seconds.
- **Exception case** (needs human judgment): route to receptionist with a clear 2-hour SLA and SMS on both ends.

### The three triage checks — what they are and why each one exists

The system evaluates three conditions at the moment a patient submits a booking request. All three must pass for auto-approval.

**Check 1 — Is it within clinic hours right now?**

If a patient submits a request at 11 PM, no receptionist can review it until morning. Auto-approving an appointment at 11 PM also means the clinic has no notice to prepare. Any request submitted outside `CLINIC_HOURS_START` (default 9 AM) to `CLINIC_HOURS_END` (default 6 PM) goes to the exception queue automatically with a note explaining the hours.

**Check 2 — Is the doctor currently available?**

The doctor's `current_status` in `doctors.txt` is checked. `Free` or `Busy` means the doctor is working today and taking appointments — auto-approve is safe. `Unavailable`, `Emergency`, or `Off` means the receptionist needs to reassign the patient to another doctor. This cannot be done automatically because it requires choosing which available doctor is appropriate.

**Check 3 — Is it a New visit type?**

`New` visits are straightforward — patient has a new problem, sees the doctor, standard flow.

`Follow-up` visits are different. They often require the receptionist to check whether the previous appointment was completed, whether the doctor has notes to review, whether any special preparation or tests were ordered. A human should review follow-up requests to ensure continuity of care.

**If all three pass → auto-approve.** The system calls `appointment.exe book` immediately. Patient gets SMS within seconds. No receptionist involvement.

**If any check fails → exception queue.** Written to `pending_appointments.txt`. Receptionist gets SMS. Patient gets acknowledgement SMS with the 2-hour window clearly stated.

### The booking flow — five steps from the patient's perspective

**Step 1 — Choose department, not doctor**

The first screen shows department cards with plain-language descriptions. A patient does not know which department to choose for "chest tightness" — but they understand "Heart and Chest — chest pain, palpitations, breathlessness." Once they pick a department, the system shows only the available doctors in that department. This is a critical UX decision: patients think in symptoms, not department codes.

**Step 2 — Choose doctor (optional)**

The patient can choose a specific doctor, or choose "Any available doctor." If the patient has a previous diagnosis record with a doctor in this department, that doctor is highlighted as "Your previous doctor." This is a small UX detail that makes the portal feel personal — and clinically it makes sense, because continuity of care matters.

**Step 3 — Choose date and slot**

Show a 7-day calendar starting from tomorrow. No same-day bookings through the portal — patients who need same-day appointments should call or walk in (a same-day request via portal would likely expire before it could be reviewed). Past dates are disabled. Fully booked days show as greyed out.

When a date is selected, a JavaScript call fetches the available slots from `GET /patient/book/slots`. Slots are displayed as visual buttons:
- Green = Available
- Gray = Taken (already booked in `appointment.txt`)
- Yellow = Pending (soft-locked by another patient's unresolved request)

This visual slot display is important — it gives the patient confidence that their selected slot is genuinely available, not just a text dropdown where they cannot tell what is free.

**Step 4 — Describe reason**

A short text area: "Briefly describe your reason for this visit." Limited to 200 characters. A radio button: New visit / Follow-up. Both are optional but encouraged. The reason appears on the receptionist's pending review screen — a patient who writes "recurring chest pain for 3 days" gives the receptionist enough context to make a faster, better-informed decision than one who leaves it blank.

**Step 5 — Review and confirm**

A summary card showing: doctor name, date (human format), time, visit type, reason. Two buttons: "Confirm Request" and "Go Back." No payment at this stage. Once confirmed, the triage runs and the patient is told whether it was instantly confirmed or sent for review.

### The soft-lock concept — why it exists and how it works

When a patient submits a booking request for Doctor X at Slot Y on Date Z, that slot should not appear freely available to other patients while the request is pending. Otherwise, two patients could request the same slot simultaneously — both would be approved and one would be disappointed.

The soft-lock works by checking `pending_appointments.txt` during slot generation. When building the slot buttons for Step 3, the system reads all unexpired Pending requests. If a Pending request exists for the same doctor, date, and slot being displayed, that slot shows yellow ("Being processed") rather than green ("Available"). The slot is not truly locked in `appointment.txt` — it is just visually marked as occupied.

When the pending request is approved, the slot becomes truly locked (written to `appointment.txt`). When it is rejected or expires, the slot turns green again on the next page load.

### What happens on approval — the exact sequence

When the receptionist clicks Approve on a pending request, the following steps happen in strict order:

**Step 1 — Re-check the slot is still free.** Between the patient's request and this approval, another receptionist may have manually booked the same slot for a walk-in patient. The system checks `appointment.txt` before proceeding. If the slot is now taken, the receptionist sees: "This slot was booked while the request was pending. Please reject and ask the patient to choose a different slot." This is expected behavior — it is handled gracefully, not treated as an error.

**Step 2 — Call `appointment.exe book`.** This is the exact same call the receptionist makes when manually booking. Same parameters, same format, same result. The appointment appears in `appointment.txt` identically to a manually entered appointment.

**Step 3 — Update `pending_appointments.txt`.** Set `status` to `Approved`, fill in the `appointment_id` returned by `appointment.exe`. This record stays in the file permanently for the audit trail.

**Step 4 — Send SMS to patient.** "Confirmed! Your appointment with Dr. Arun Kumar is on Tuesday 10 May at 8:30 AM. Please arrive 10 minutes early."

### What happens on rejection — why the reason is mandatory

The receptionist must enter a reason before rejecting. This is enforced both in the HTML (`required` attribute) and server-side (route returns an error if `receptionist_note` is empty). The reason is stored in `pending_appointments.txt` and sent directly to the patient as an SMS.

**Why mandatory?** A rejection without a reason leaves the patient with no idea what to do. Should they try a different slot? Call the clinic? Come in person? Has the doctor been removed? The reason removes all ambiguity.

Good rejection reasons:
- "Doctor is on leave on this date. Please choose a different date."
- "This slot is reserved for emergency patients. Please select the 10:30 AM or later slots."
- "For follow-up visits, please call us at [number] so we can pull your previous records."

The rejection SMS includes a link back to the booking form. The booking form pre-fills the same doctor and department so the patient does not start from scratch.

### The 2-hour expiry — what it is, why it exists, and how it works

Every pending request has an `expires_at` timestamp set to exactly 2 hours after submission. If the receptionist does not act within 2 hours, the request automatically expires and the slot is released.

**Why 2 hours?** Long enough that a receptionist who stepped out briefly or had a busy period can still review it. Short enough that the patient is not left waiting half the day wondering what happened.

**Why not use a background thread for expiry?** This is a Flask flat-file project without a task queue (no Celery, no APScheduler). Adding one would be significant complexity for a feature that does not require real-time precision — a clinic context where both the patient and the receptionist will load a page within a few minutes is well-served by lazy expiry. The expiry check runs whenever the patient loads their dashboard or the receptionist loads the pending screen.

**What lazy expiry means in practice:** When a page loads and calls `run_expiry_check()`, the function scans the pending records. Any record with `expires_at` in the past and `status = Pending` is immediately marked `Expired` and the SMS is sent then. The patient and receptionist may not see the expiry the exact second it happens, but they will see it within minutes of the next page load by either party.

**The expiry SMS is not optional.** Without it, the patient's request simply disappears with no explanation — which is worse than the original problem of not having a portal at all. The expiry SMS must say what happened and what the patient should do next.

### Patient cancellation — the 24-hour rule and why it is server-enforced

Patients can cancel their own confirmed appointments if the appointment is more than 24 hours away. This is checked server-side in the cancellation route — not just hidden in the UI.

**Why server-side?** Because a determined user could bypass the UI by sending a direct POST request to the cancel route. The 24-hour check must be in the Python route logic, not just the template.

**Why 24 hours?** Within 24 hours, the doctor has likely reviewed their schedule for the next day. Empty slots left by last-minute cancellations usually cannot be filled on short notice. Patients who genuinely need to cancel within 24 hours should call — this ensures a human conversation where the clinic can sometimes fill the slot or make other arrangements.

**The ownership check:** Before cancelling, the route verifies that `appointment["patient_id"] == session["patient_id"]`. This prevents Patient A from cancelling Patient B's appointment by crafting a POST with Patient B's appointment ID. This check must happen even when the UI never shows a cancel button for other patients' appointments — a UI control is not a security control.

### What to build in this phase

- `Frontend/templates/patient_book.html` — five-step booking form with JavaScript step navigation (no page reloads between steps)
- Route `GET /patient/book` — load departments and available doctors with their current status
- Route `GET /patient/book/slots` — AJAX: return slot availability plus soft-lock status for a given doctor and date
- Route `POST /patient/book/submit` — run triage, call the appropriate path
- Route `POST /patient/cancel` — 24h check, ownership check, call `appointment.exe cancel`
- `triage_booking_request(doctor_id, requested_date, visit_type)` — returns `"auto"` or `"exception"`
- `auto_approve_booking(...)` — slot recheck, `appointment.exe` call, SMS
- `exception_queue_booking(...)` — write to `pending_appointments.txt`, SMS to both patient and receptionist
- `run_expiry_check(pending_records)` — scan for expired records, mark them, send SMS
- Helper functions: `read_pending_requests_for_patient(pid)`, `read_all_pending_requests()`, `update_pending_status(request_id, status, ...)`
- Route `GET /reception/pending` — receptionist view, runs expiry check on load
- Route `POST /reception/approve` — slot recheck, `appointment.exe`, update pending record, SMS
- Route `POST /reception/reject` — validate reason is not empty, update pending record, SMS

---

## 7. Phase 4 — SMS Notifications (Fast2SMS)

### What we are building in this phase

A single SMS module (`sms_service.py`) that every part of the system calls. It handles dev mode (print to console), production mode (Fast2SMS API), and failure gracefully — never crashing the application.

### Why Fast2SMS over other providers

**Twilio** is reliable but expensive for Indian numbers — it charges per SMS in USD and requires international business setup.

**MSG91** requires DLT pre-registration before sending any SMS. DLT takes 3–5 business days and needs business documents. It blocks all development until it is complete.

**Fast2SMS** has a free tier of 500 SMS/month — enough for a demo and early real-clinic use. It supports Indian numbers only, which is exactly what this system needs. It does not require DLT registration on the free tier during development.

### The most important design rule for SMS integration

SMS delivery must **never crash the application**. If Fast2SMS is down, if the API key is wrong, if the network times out — none of these should produce a 500 error. The SMS function must catch all exceptions internally, log the failure, and return `False`. The calling code checks the return value and logs it, but the user-facing operation (booking, confirmation, payment) completes regardless.

**Why this matters with a concrete example:** A patient submits a booking request. The booking is written to `pending_appointments.txt` successfully. Then the SMS call times out. Should the patient see an error page? No — the booking succeeded. The SMS failure is a secondary concern. The patient will still see the confirmation on their dashboard.

### The abstraction layer — why you must not skip it

The SMS function is called from many places: OTP generation, booking confirmation, approval, rejection, expiry, payment capture. If you write the Fast2SMS API call directly in each of those places, and you later need to switch to MSG91 (when you register DLT templates for production), you have to find and update every single call across the codebase.

Instead, every part of the system calls one function: `send_sms(phone, message)`. To switch providers, you change one file (`sms_service.py`). Nothing else in the codebase changes. This is the abstraction.

### Dev mode

When `FAST2SMS_API_KEY` is not in the environment, `send_sms()` prints the phone number and message to the Flask console and returns `True`. This means:

- The entire application works correctly during development with zero API keys
- You can see exactly what SMS would have been sent and to which number
- No accidental SMS sent to real patients during testing

### Complete SMS catalog — every message, who receives it, and why

| Trigger | Recipient | Message | Why |
|---|---|---|---|
| Patient requests OTP | Patient | "Your HealthDesk OTP is 482917. Valid 5 min. Do not share." | Authentication. Time-limited and secret. |
| Booking submitted | Patient | "Request for Dr. Arun on May 10, 8:30 AM received. Confirming within 2 hours (9 AM–6 PM)." | Sets expectation. Without this, the patient assumes the system failed. |
| Booking submitted | Receptionist | "New request from Aakash (9000000006) for Dr. Arun, May 10, 8:30 AM. Review dashboard." | Without this, a receptionist not actively watching the dashboard misses the request entirely. |
| Auto-approved | Patient | "Confirmed! Dr. Arun Kumar, May 10, 8:30 AM. Please arrive 10 min early." | Instant confirmation without needing to log in again. |
| Receptionist approved | Patient | "Confirmed! Dr. Arun Kumar, May 10, 8:30 AM. Please arrive 10 min early." | Same outcome as auto-approve, same SMS. |
| Receptionist rejected | Patient | "Request not confirmed. Reason: Doctor on leave. Log in to rebook: [url]" | Explains what happened and gives clear next action. A rejection without a reason is a dead end. |
| Request expired (2h) | Patient | "Your request for May 10, 8:30 AM expired before it was confirmed. Log in to rebook." | Without this, the request just disappears. Patient has no idea what happened. |
| Request expired (2h) | Receptionist | "Booking request from Aakash expired unreviewed." | Creates accountability. Receptionists know when they missed a request. |
| Patient cancels | Patient | "Your appointment with Dr. Arun Kumar on May 10 has been cancelled." | Confirms the action. Patient has a record. |
| Payment captured | Patient | "Payment of Rs 1200 received for your May 10 visit. Bill available in your portal." | Confirms the money was received without needing to log in. |
| Payment failed | Patient | "Payment failed. Please retry in your portal or pay at the counter." | Explains what happened and gives two options. No dead end. |

### DLT registration for production

TRAI requires all commercial SMS senders in India to register their message templates and sender ID on the DLT platform before going live. For development and demos, this is not needed.

For a real clinic going live:
1. Register a Sender ID (e.g., `HLTHDK`) on the Fast2SMS DLT portal
2. Submit each message template from the catalog above for approval
3. Each template gets a template ID which replaces the free-text message in API calls
4. Process takes 3–5 business days and is free

Build the system using free-text messages now. Switch to registered templates when ready for production by updating `sms_service.py` only.

### What to build in this phase

- Create `sms_service.py` as described above
- Go back through Phases 1, 2, and 3 and add the actual `send_sms()` calls at the points identified in the SMS catalog above

---

## 8. Phase 5 — Razorpay Payments

### What we are building in this phase

Online bill payment. The patient clicks "Pay Now" on their bill, completes payment via UPI/card/netbanking on the Razorpay checkout, the payment is verified server-side via a webhook, and the bill status is updated. Counter payments by the receptionist are unchanged.

### Why Razorpay

Razorpay is the correct choice for an Indian clinic:
- Handles UPI, cards, netbanking, and wallets in one integration
- Patients already trust it — they see it on dozens of everyday apps
- Free sandbox for development, no charges until live
- Clean Python SDK (`pip install razorpay`)
- Handles all PCI compliance — your server never sees card numbers

### The most critical security rule in the payment system

**Never trust the browser for the payment amount.**

When a patient initiates payment, their browser sends a request to your server. It is technically possible to intercept and modify that request. If your server creates a Razorpay order for whatever amount the browser sent, an attacker could pay Rs 1 for a Rs 1,200 bill.

**The correct flow:**
1. Browser sends: `bill_id = "BILL-1000"` — only the ID, no amount
2. Server reads `billing.txt`, finds the bill by ID, reads the amount from the file
3. Server creates the Razorpay order using that amount
4. The amount is never provided by the browser

This is enforced in the route `POST /patient/payment/create-order`. There is no workaround.

### The webhook vs redirect — the most misunderstood part of Razorpay integration

When a patient completes payment, two things happen nearly simultaneously:

1. **The browser is redirected** to your success handler (the `handler` function in the checkout JavaScript)
2. **Razorpay calls your webhook** at `POST /payment/webhook` from their servers — server-to-server, not through the browser

The redirect happens first and is visible to the patient. The webhook arrives a moment later, server-to-server.

**The redirect is for UI only.** It tells the browser to show "Thank you" to the patient. You should not update the bill status here. The browser redirect can be faked — anyone can manually send a POST to your success URL and make it look like they paid. The redirect provides no security guarantee.

**The webhook is the only payment confirmation you trust.** It arrives from Razorpay's servers, not the patient's browser. It includes a cryptographic signature. You verify the signature before touching any data. Only after verification do you update `billing.txt` to `PAID`.

**What the patient sees:** They pay, the checkout closes, the page shows "Payment received. Your bill will update shortly." They check back in a few seconds and see the bill is now marked Paid. The short delay is because the webhook arrives slightly after the browser redirect.

### Webhook signature verification — why it exists and how it works

The webhook signature ensures the POST to `/payment/webhook` genuinely came from Razorpay and was not fabricated by an attacker trying to mark bills as paid without paying.

Razorpay signs each webhook payload using HMAC-SHA256 with your `RAZORPAY_WEBHOOK_SECRET`. Your server recomputes the same HMAC using the raw request body and the same secret, then compares the result to the signature in the `X-Razorpay-Signature` header. If they match, the request is genuine. If they do not match, return HTTP 400 and ignore the request entirely.

This signature check must be the **first thing** that happens in the webhook handler. No data should be read from the payload, no database should be touched, before the signature passes.

**Critical setup note:** The `/payment/webhook` route must be **exempt from CSRF protection**. Flask-WTF CSRF rejects any POST that does not include a CSRF token. Razorpay's server cannot provide a CSRF token. Add this route to the CSRF exempt list. The HMAC signature verification replaces CSRF protection for this route.

### The payment state machine — every state and its transitions

```
PENDING
  Bill generated. No payment initiated.
  Patient sees "Pay Now" button.

  ↓ Patient clicks Pay Now, server creates Razorpay order

INITIATED
  Razorpay order created. Checkout may be open in browser.
  Money has not moved yet.
  If no webhook arrives in 30 minutes → revert to PENDING
  (checked lazily when patient next loads dashboard)

  ↓ Razorpay webhook arrives: event = payment.captured
    Signature verified ✓

PAID
  Money received and confirmed.
  billing.txt updated: payment_id, method, paid_at timestamp.
  SMS sent to patient.
  Bill PDF now shows payment details.

  ↓ OR: Razorpay webhook arrives: event = payment.failed

PENDING (reverted)
  Payment failed (declined card, UPI timeout, insufficient funds).
  billing.txt status reverted to PENDING.
  SMS sent: "Payment failed. Please retry or pay at counter."

PAID → REFUNDED
  Receptionist processes refund via Razorpay dashboard.
  billing.txt updated manually.
  Patient notified via SMS.

PENDING → WAIVED
  Receptionist marks bill as waived (existing functionality, unchanged).
  No Razorpay involved.

PENDING → PAID (counter)
  Receptionist marks paid at counter (existing functionality, unchanged).
  payment_method field set to "counter".
  No Razorpay involved.
```

### How the bill PDF changes

After Phase 5, paid bills add three lines to the PDF:

- "Payment method: Paid via UPI" (or Card, Netbanking, Counter)
- "Payment reference: pay_XXXXXXXXXXXXXXXX" (for online payments)
- "Paid on: Tuesday 10 May 2026 at 2:14 PM"

Counter-paid bills show "Paid at counter" with the date the receptionist marked it. Waived bills show "Waived" with no payment details.

### What to build in this phase

- Create `payment_service.py` — Razorpay order creation and HMAC signature verification as two separate functions
- Route `POST /patient/payment/create-order` — verifies ownership, reads amount from server, creates order
- Route `POST /payment/webhook` — CSRF-exempt, signature verified first, handles `payment.captured` and `payment.failed`
- Update `patient_dashboard.html` — wire up the "Pay Now" button with Razorpay `checkout.js`
- Update bill PDF generation — add payment method, payment ID, and timestamp on paid bills
- Update `billing.txt` parser — handle the 4 new payment fields (old records without them remain valid)
- Add helper: `find_bill_by_razorpay_order_id(order_id)` — needed to match webhook to the right bill

---

## 9. Receptionist Side Changes

### What changes and what does not

The receptionist's core workflow — registering patients, booking appointments, managing doctors, generating bills, marking bills paid — does not change at all. Their existing screens are unchanged.

### The pending requests section

A "Pending Patient Requests" section is added to the top of the receptionist dashboard. This section appears only when there are unreviewed requests. When there are none, the dashboard looks exactly as it does today.

Each pending request card shows:
- Patient name, age, gender
- Requested doctor, date, slot
- The patient's reason for the visit
- Visit type (New or Follow-up)
- Time since submitted
- Time remaining before expiry (e.g., "1h 23m to expiry")
- Approve button
- Reject button — clicking expands a text field for the mandatory reason

**The "slot conflict" case:** If the receptionist clicks Approve and the slot is no longer available (someone else booked it in the meantime), the system shows a message explaining the conflict and prompts the receptionist to reject with a note asking the patient to choose a different slot. This is not an error — it is a handled edge case.

**Billing view after Phase 5:** Bills paid online show a "Paid Online" badge instead of the plain "PAID" badge. The receptionist can see the payment method and payment ID but cannot initiate refunds from within HealthDesk — refunds go through the Razorpay dashboard.

---

## 10. New Data Files and Schema Changes

### New file: `Backend/data/pending_appointments.txt`

Create this file as an empty file. Populate it as patients submit requests.

**Format:** pipe-delimited, one record per line, 12 fields.

```
request_id|patient_id|doctor_id|requested_date|requested_slot|reason|visit_type|status|submitted_at|expires_at|receptionist_note|appointment_id
```

| Field | Type | Notes |
|---|---|---|
| `request_id` | int | Auto-increment: read max from file + 1 |
| `patient_id` | int | FK → patients.txt |
| `doctor_id` | int | FK → doctors.txt |
| `requested_date` | str | YYYY-MM-DD |
| `requested_slot` | str | Exactly matches slot format in appointment.txt — e.g., `08:30 AM` |
| `reason` | str | Patient note. Always passed through `clean_record_field()` |
| `visit_type` | str | `New` or `Follow-up` — these exact strings are checked in triage |
| `status` | str | `Pending` / `Approved` / `Rejected` / `Expired` |
| `submitted_at` | str | ISO datetime |
| `expires_at` | str | ISO datetime = submitted_at + 2 hours |
| `receptionist_note` | str | Filled on Rejection. Empty string otherwise. Always pipe-sanitized. |
| `appointment_id` | int | Filled on Approval. `0` until then. |

**Why records are never deleted:** Keeping approved, rejected, and expired records permanently creates an audit trail. If a patient disputes that their request was rejected, the receptionist can see the record and the reason. If there is a billing dispute, the `appointment_id` in an approved record links back to the original appointment.

---

### Modified file: `Backend/data/billing.txt`

Add 5 new fields at the end of each new record. Old 19-field records remain valid — the existing parser handles variable field counts.

Note: the table below uses 1-indexed field positions for readability. In Python code these same fields are read with 0-indexed list indexes `data[19]` through `data[23]`.

| Position | Field | Notes |
|---|---|---|
| 20 | `razorpay_order_id` | Empty until payment initiated |
| 21 | `razorpay_payment_id` | Filled on successful payment capture |
| 22 | `payment_method` | `upi` / `card` / `netbanking` / `counter` |
| 23 | `paid_at` | ISO datetime of payment capture |
| 24 | `initiated_at` | ISO datetime of Razorpay order creation; used only for stale `INITIATED` cleanup |

Counter-paid bills: positions 20 and 21 are empty string, `payment_method` = `counter`, `paid_at` = timestamp when receptionist marked it paid.

---

## 11. All New Routes

### Patient routes

| Method | Route | Who can access | What it does |
|---|---|---|---|
| GET | `/patient/login` | Anyone | Phone entry page |
| POST | `/patient/request-otp` | Anyone | Validate phone, look up patient, generate + send OTP |
| POST | `/patient/verify-otp` | Anyone | Verify OTP, create session, redirect to dashboard |
| POST | `/patient/logout` | Patient | Clear session |
| GET | `/patient/dashboard` | Patient | Load all patient data, run expiry check |
| GET | `/patient/book` | Patient | Department and doctor selection |
| GET | `/patient/book/slots` | Patient | AJAX: return slot availability + soft-lock status |
| POST | `/patient/book/submit` | Patient | Run triage, auto-approve or exception queue |
| POST | `/patient/cancel` | Patient | 24h check, ownership check, cancel via appointment.exe |
| GET | `/patient/bills/<bill_id>/pdf` | Patient | Verify ownership, serve bill PDF |
| POST | `/patient/payment/create-order` | Patient | Verify ownership, read amount from server, create Razorpay order |

### New receptionist routes

| Method | Route | Who can access | What it does |
|---|---|---|---|
| GET | `/reception/pending` | Receptionist | Show all pending requests, run expiry check |
| POST | `/reception/approve` | Receptionist | Re-check slot, call appointment.exe, update pending record, SMS patient |
| POST | `/reception/reject` | Receptionist | Validate reason not empty, update pending record, SMS patient with reason |

### Payment webhook (server-to-server)

| Method | Route | Auth | What it does |
|---|---|---|---|
| POST | `/payment/webhook` | Razorpay HMAC (CSRF-exempt) | Verify signature, update bill status, send SMS |

---

## 12. Environment Variables

All secrets live in a `.env` file in the project root. Load with `python-dotenv`. The `.env` file must be in `.gitignore`.

```bash
# Existing
HEALTHDESK_SECRET=replace-with-long-random-string

# Phase 4 — SMS
FAST2SMS_API_KEY=your-fast2sms-api-key
# Absent = dev mode, SMS prints to console. App works normally.

RECEPTIONIST_PHONE=9XXXXXXXXX
# 10-digit. Receives new request and expiry alerts.
# Multiple receptionists: comma-separated 9XXXXXXXXX,9XXXXXXXXX

CLINIC_HOURS_START=9
# Requests before this hour go to exception queue.

CLINIC_HOURS_END=18
# Requests after this hour go to exception queue.

# Phase 5 — Razorpay
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXX
# Use rzp_test_... during development. Switch to rzp_live_... for production.

RAZORPAY_KEY_SECRET=your-key-secret
# Server-side only. Never send to browser.

RAZORPAY_WEBHOOK_SECRET=your-webhook-secret
# Separate from key secret. Set in Razorpay dashboard under Webhooks.
```

**What happens when a key is missing:**

| Missing key | Effect |
|---|---|
| `FAST2SMS_API_KEY` | SMS printed to console. App works normally. |
| `RECEPTIONIST_PHONE` | Patient SMS still sent. Receptionist alert silently skipped. |
| `RAZORPAY_KEY_ID` or `RAZORPAY_KEY_SECRET` | Payment routes return 503: "Payments not configured." |
| `RAZORPAY_WEBHOOK_SECRET` | All webhook signature checks fail. Bills never update from webhook. |

---

## 13. Files to Create and Modify

### New files

| File | Phase | Purpose |
|---|---|---|
| `sms_service.py` | 4 | SMS abstraction. Fast2SMS in prod, console in dev. Never crashes. |
| `payment_service.py` | 5 | Razorpay order creation + signature verification |
| `Backend/data/pending_appointments.txt` | 3 | Create empty. Stores booking requests before approval. |
| `Frontend/templates/patient_login.html` | 1 | Two-step login — phone entry then OTP |
| `Frontend/templates/patient_dashboard.html` | 2 | Four-section patient home view |
| `Frontend/templates/patient_book.html` | 3 | Five-step booking form |

### Modified files

| File | Phase | What changes |
|---|---|---|
| `app.py` | 1–5 | All new routes, helper functions, triage logic, expiry check, payment routes |
| `Frontend/templates/receptionist_dashboard.html` | 3 | Add pending requests section at top |
| `Backend/data/billing.txt` | 5 | New records get 5 extra payment fields |
| `.env` | 4–5 | New keys for SMS and Razorpay |
| `requirements.txt` | 4–5 | Add: `razorpay`, `requests`, `python-dotenv` |

### Files confirmed unchanged

```
All C source files and executables
appointment.txt, patients.txt, diagnosis.txt
doctors.txt, queue.txt, users.txt
All existing receptionist and doctor templates
All existing receptionist and doctor routes in app.py
```

---

## 14. UX Rules — Designing for Real Patients

Hospital patients include elderly people, people who are unwell, people anxious about a diagnosis, and first-time smartphone users. The portal must be forgiving, clear, and never leave anyone confused about what to do next.

### Plain-English status at all times

Never show raw status strings. Translate every internal status into a sentence.

| Internal status | Show to patient instead |
|---|---|
| `Pending` | "Your request has been sent. The clinic will confirm within 2 hours (9 AM–6 PM)." |
| `Booked` | "Confirmed — Dr. Arun Kumar, Tuesday 10 May at 8:30 AM." |
| `Rejected` | "This request was not confirmed. Reason: [note]. You can book a different slot below." |
| `Expired` | "This request expired before it was confirmed. Please book again." |
| `Completed` | "Visit completed on Tuesday 10 May 2026." |
| `No-show` | Never show "No-show". Show: "Appointment on [date] — not attended." |
| `Cancelled` | "This appointment was cancelled on [date]." |

### No dead ends — ever

Every error, rejection, and expired state must have a clear next action:

- Rejected request → "Book Again" button, pre-filled with the same doctor
- Expired request → "Rebook" link that opens the booking form
- Cannot cancel (within 24h) → "To cancel, please call us at [clinic phone]"
- OTP expired → "Send a new OTP" link prominently placed
- Slot taken during booking → "Choose a different slot" — takes back to Step 3 with the slot highlighted

### Human-readable dates everywhere

| Raw | Show |
|---|---|
| `2026-05-10` | `Tuesday, 10 May 2026` |
| `08:30` | `8:30 AM` |
| `2026-05-10T14:23:00` | `Tuesday, 10 May 2026 at 2:23 PM` |

### Never show internal IDs to patients

`patient_id`, `doctor_id`, `appointment_id`, `bill_id`, `record_id`, `request_id` — none of these should appear anywhere in a patient-facing template. They are meaningless to patients and create confusion.

### Mobile-first layout

Most patients will use this on their phone.
- Single-column layout throughout
- Minimum 44×44 pixels for all tap targets
- OTP input: `type="number"`, `inputmode="numeric"`, auto-submit at 6 characters
- No horizontal scrolling
- Labels above input fields — never placeholder text as the label (it disappears on focus)

### Confirmations for destructive actions

Cancel appointment screen must show:
> "Are you sure you want to cancel your appointment with Dr. Arun Kumar on Tuesday 10 May at 8:30 AM?"
>
> [Keep my appointment]   [Yes, cancel it]

The "Keep my appointment" button is the primary (larger, more prominent) button. This is intentional — the safe default should be visually preferred.

### Meaningful empty states

| Empty state | What to show |
|---|---|
| No upcoming appointments | "No upcoming appointments. [Book an appointment →]" |
| No past appointments | "Your appointment history will appear here after your first visit." |
| No medical records | "Your records will appear here after your first consultation." |
| No bills | "Your bills will appear here after your first visit." |

---

## 15. Security Checklist

Review every item before showing this to any real patient.

**Authentication and sessions**
- [ ] Every patient route checks `session.get("role") == "Patient"` before any logic
- [ ] Every patient data fetch uses `session["patient_id"]` — never a URL parameter or form field
- [ ] OTP maximum 3 wrong attempts before invalidation
- [ ] OTP expires in 5 minutes — checked server-side, not client-side
- [ ] OTP stored as SHA-256 hash, never plaintext, even in memory
- [ ] `HEALTHDESK_SECRET` is a long random string, not the dev default value

**Patient data isolation**
- [ ] Patient A cannot view Patient B's appointments, records, or bills
- [ ] Patient A cannot cancel Patient B's appointment
- [ ] Patient A cannot download Patient B's bill PDF
- [ ] All isolation is enforced by server-side checks, not just what the UI displays

**Payment security**
- [ ] Bill amount always read from `billing.txt` on server — never from browser POST body
- [ ] `/payment/webhook` is CSRF-exempt (cannot be CSRF-protected — server-to-server call)
- [ ] `/payment/webhook` verifies Razorpay HMAC signature as the absolute first action
- [ ] `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` are never sent to the browser
- [ ] Bill status only updated from the verified webhook — never from the browser redirect
- [ ] Using test keys (`rzp_test_...`) during development, not live keys

**Input validation**
- [ ] `clean_record_field()` called on all patient-supplied text before writing to any file
- [ ] `payment_status` validated against whitelist before writing
- [ ] Booking date validated as today or later — server-side, not just HTML `min` attribute
- [ ] Visit type validated as `New` or `Follow-up` only
- [ ] Phone number validated as exactly 10 digits before OTP generation

**Application security**
- [ ] All patient POST routes have CSRF tokens (except the webhook route)
- [ ] Patient cancellation 24-hour rule enforced in route logic, not just the UI
- [ ] `pending_appointments.txt` writes use a threading lock (same pattern as `appointment.txt`)
- [ ] Passwords in `users.txt` hashed with `werkzeug.security` (from earlier review)
- [ ] Auth credentials compared in Python dict — not passed as subprocess CLI arguments (from earlier review)
- [ ] `.env` is in `.gitignore` and never committed to the repository

---

*End of document.*
*HealthDesk Patient Portal Architecture · v2.0 · May 2026*
*Consolidates all changes discussed across all review sessions.*
