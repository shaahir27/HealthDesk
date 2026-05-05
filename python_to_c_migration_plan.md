# Zero-Regressions Python-to-C Migration Plan for `app.py`

## Summary
Reduce Python lines aggressively by moving nearly all deterministic, file-backed business logic from `app.py` into the existing C executables, while preserving the current system behavior exactly. The system must continue to work with no user-facing changes, no flow changes, no schema changes, and no logical compromises.

The migration strategy is: make each C module the sole owner of its domain, keep Python as a thin orchestration/web layer, and remove Python implementations only after command-level parity is proven. Every migration step must preserve the current route behavior, payment behavior, SMS behavior, template behavior, and file formats.

## Non-Negotiable Invariants
- No change to route URLs, request shapes, redirect flow, session behavior, flash/status messages, or template variables unless strictly required for parity.
- No change to text-file schemas:
  `patients.txt`, `doctors.txt`, `appointment.txt`, `queue.txt`, `billing.txt`, `advances.txt`, `pending_appointments.txt`, `new_patient_requests.txt`, `pending_booking_intents.txt`, `users.txt`, `diagnosis.txt`.
- No movement of Flask-only logic to C:
  `request`, `session`, `g`, decorators, CSRF, `url_for`, `render_template`, `jsonify`.
- No movement of external side effects to C:
  Razorpay SDK calls, webhook verification, SMS sending, PDF generation.
- Python remains the transaction/orchestration layer whenever a workflow combines:
  C file mutations + payment API + SMS + session + redirects.
- Every C command added must be machine-readable and stable.
- Old Python implementation is deleted only after:
  command parity verified, adapter verified, and route-level scenarios verified.

## Target Architecture
### Python keeps
- Flask routes and route-local request parsing.
- Session/auth/role decorators and CSRF enforcement.
- Payment creation/webhook/refund orchestration.
- SMS notifications.
- PDF generation and template rendering.
- Final user messaging and redirect choices.
- Thin adapter functions that invoke C executables and return Python dict/list objects.

### C owns
- Record parsing and serialization for file-backed domains.
- File reads, writes, updates, replacements, counts, and searches.
- Deterministic domain validations and rule checks.
- Pure status transitions and expiry calculations.
- Deterministic reconciliation logic for queue/appointments/advances/requests.
- Deterministic lookup helpers and grouped record selection.

## Interop Contract
### Command contract
All new commands must follow a consistent contract:
- Success with record payload: plain serialized record or one-record-per-line list.
- Success with scalar payload: plain scalar value.
- Not found: empty stdout with nonzero exit, or one stable sentinel consistently within that executable.
- Error: stable `Error|...` format already used by the codebase.

### Python adapter contract
For each domain, Python must expose:
- `run_<domain>_command(*args)`
- `parse_<domain>_line(...)` or equivalent record parser
- `parse_<domain>_command_output(...)` if command output shape differs from file line shape
- thin helpers like `find_*`, `read_*`, `count_*` that only:
  call C, parse output, and optionally fallback during transition

### Transition rule
Each helper migration follows this sequence:
1. Add C command.
2. Add/update Python adapter.
3. Switch Python helper to prefer C.
4. Verify parity.
5. Remove fallback.
6. Remove obsolete Python implementation details.

## Migration Phases

## Phase 0: Freeze and classify `app.py`
Goal: produce a decision-complete map of what stays in Python and what must move first.

### Work
- Make a function inventory in `app.py` grouped into:
  patient, doctor, appointment, queue, pending request, advance, billing, diagnosis, auth/session/web, payment/SMS/PDF, formatting/utilities.
- Mark each function as one of:
  `stay-python`, `move-to-c`, `wrapper-after-move`, `shared-utility`.
- Identify all direct file writes in Python and map each to its intended C owner.
- Identify all direct file reads in Python and map each to its intended C owner.
- Identify all cross-domain workflows that must remain Python-orchestrated.

### Deliverable
- A migration checklist document or internal mapping table that names every targeted function and its destination executable.

### Acceptance
- No implementation change yet.
- Every Python function has an explicit migration disposition.

## Phase 1: Complete persistence ownership
Goal: Python stops directly owning core file CRUD for target domains.

### 1A. Patient ownership
C owner: `patient.exe`

Move fully to C:
- list patients
- count patients
- find patient by id
- find patient by phone
- patient creation
- patient existence checks that rely only on patient file

Python after move:
- `read_patients`, `find_patient_by_id`, `find_patient_by_phone` remain as thin adapters only
- remove direct patient file parsing from `app.py`

Acceptance:
- all patient reads/mutations happen through `patient.exe`
- no direct Python read/write of `patients.txt` remains except temporary compatibility code during transition

### 1B. Doctor ownership
C owner: `doctor.exe`

Move fully to C:
- list doctors
- count available doctors
- find doctor by id
- doctor existence
- doctor suggestion/search by department
- doctor status updates on `doctors.txt`

Keep in Python for now:
- JSON-based `doctor_status_meta.json` helpers if not yet migrated

Acceptance:
- all `doctors.txt` read/write logic is owned by `doctor.exe`
- Python only enriches doctor rows with meta-derived display data

### 1C. Appointment ownership
C owner: `appointment.exe`

Move fully to C:
- list all appointments
- list appointments by patient
- list appointments by doctor/date
- find appointment by id
- find booked appointment by patient/date
- appointment create/update/status transitions
- slot availability reads against appointment data

Keep in Python for now:
- time-based presentation helpers that format or interpret appointment rows for UI

Acceptance:
- all `appointment.txt` CRUD and search logic owned by `appointment.exe`
- `read_appointment_file` becomes adapter-only or is deleted

### 1D. Queue ownership
C owner: `queue.exe`

Move fully to C:
- queue list
- queue add
- queue update status
- queue persistence/rewrite
- queue reconciliation primitives if they only touch queue data

Acceptance:
- all `queue.txt` reads/writes owned by `queue.exe`
- Python no longer rewrites `queue.txt`

### 1E. Advance ownership
C owner: `advance.exe`

Move fully to C:
- list advances
- next advance id
- find by id
- find by appointment id
- find by order id
- create/save/update advance record
- save booking intent
- pop booking intent
- rewrite advances file
- stranded advance lookup helpers
- stale advance file mutation paths

Acceptance:
- Python no longer writes `advances.txt` or `pending_booking_intents.txt` directly

### 1F. Pending request ownership
C owner: `pending_request.exe`

Move fully to C:
- list existing requests
- list new requests
- create existing/new request
- update request states
- expire requests
- soft-lock slot checks based on pending files

Acceptance:
- Python no longer writes `pending_appointments.txt` or `new_patient_requests.txt` directly

### 1G. Billing ownership
C owner: `billing.exe`

Move fully to C:
- next bill id
- list bills
- find by id
- find by appointment id
- find by Razorpay order id
- append/save bill
- update bill record
- bill rewrite operations

Keep in Python:
- pricing catalog usage
- bill construction from request/diagnosis context
- PDF rendering
- payment/SMS orchestration

Acceptance:
- Python no longer writes `billing.txt` directly

## Phase 2: Move read/query helpers completely
Goal: delete Python implementations that just search/filter file-backed data.

### Candidate helpers to eliminate from Python
- patient/doctor/appointment/bill/advance lookup helpers
- count helpers
- “latest” record selectors
- record existence checks
- patient-on-date/doctor-on-date filters
- list-for-patient/list-for-doctor selectors
- order-id and appointment-id bill/advance lookups

### Required C additions
- `patient.exe`: `list`, `count`, `get-by-id`, `search`
- `doctor.exe`: `view`, `get-by-id`, `exists`, `count-available`, `suggest`, `search`
- `appointment.exe`: `list-all`, `list-for-patient`, `list-for-doctor-date`, `find-id`, `find-booked-patient-date`
- `billing.exe`: `find-order`, `update`, `list-for-patient` if beneficial
- `advance.exe`: `list`, `get-by-id`, `find-appointment`, `find-order`, `list-needing-attention`
- `pending_request.exe`: `list-existing`, `list-new`, `soft-lock-exists`

### Acceptance
- Python helper bodies become adapters only.
- Old file-parsing loops are removed from `app.py`.
- Returned dict/list structures remain identical to today’s callers.

## Phase 3: Move deterministic domain rules
Goal: reduce Python lines by migrating pure rules that do not need Flask or external APIs.

### 3A. Appointment rules to C
C owner: `appointment.exe`

Move:
- booked/active/completed/future/no-show filtering
- latest appointment selection
- latest completed appointment selection
- latest active appointment selection
- patient already booked on date checks
- stale consultation expiry logic over appointment file

Keep in Python:
- human-readable message selection
- redirect decisions
- any rule depending on current route intent

### 3B. Queue rules to C
C owner: `queue.exe`

Move:
- queue reconciliation against appointments if implemented as C cross-read logic
- waiting/completed counting
- queue status normalization
- queue selection/grouping inputs

Keep in Python:
- final dashboard/template shaping if it is purely presentation

### 3C. Advance rules to C
C owner: `advance.exe`

Move:
- advance expiry eligibility
- booking intent parsing/serialization
- stale advance scans
- stranded advance detection
- pure advance settlement-state calculations

Keep in Python:
- refund API call
- webhook coordination
- SMS text choice

### 3D. Pending request rules to C
C owner: `pending_request.exe`

Move:
- pending slot collision checks
- expiry status transitions
- request state mutation rules that do not require payment/session logic

### 3E. Doctor availability rules
C owner: `doctor.exe` plus `appointment.exe` where needed

Move:
- normalized doctor status rules if based only on doctor record values
- availability state calculations that do not require template concerns
- suggestion and “available doctor” selection logic

### Acceptance
- Python retains only orchestration and presentation.
- Rule outputs remain behaviorally identical.
- No user-facing change in when bookings are auto-approved, queued, blocked, expired, or marked stale.

## Phase 4: Move multi-record internal workflows
Goal: remove large chunks of Python orchestration where the workflow is still fully internal and deterministic.

### Safe multi-record workflows to migrate
- queue reconciliation against appointments
- stale consultation expiry that updates both appointments and queue
- advance expiry that updates advances and booking intents
- internal request expiry and cleanup
- doctor availability resync based on workload if it only touches internal files

### Important boundary
Do not move workflows that directly include:
- Razorpay calls
- SMS sending
- Flask session reads/writes
- redirects/template response logic

### Pattern
- C command computes and persists all internal state mutations.
- Python calls one C command, then performs any side effects and user-facing response.

### Acceptance
- fewer Python loops over multiple domain files
- route outcomes remain identical
- internal file mutation order remains preserved

## Phase 5: Shrink route-adjacent service code
Goal: reduce `app.py` further by turning large helper bodies into adapter/orchestration shells.

### Work
For each route-heavy domain flow:
- booking flow
- reception approve/reject flow
- doctor completion flow
- billing update flow
- advance payment follow-up flow

Refactor helper layers so Python does only:
- validate request/session
- call 1..N C commands
- call payment/SMS/PDF if needed
- return redirect/JSON/template

Do not move the route itself to C.

### Acceptance
- large Python helper bodies are replaced by short orchestrators
- core business mechanics are handled in C
- route behavior and messages stay identical

## Domain-by-Domain Function Disposition

## Keep in Python permanently
- all `@app.route` functions
- `require_role`, `require_login`, `verify_csrf_token`, auth/session hooks
- OTP/session helpers
- payment order creation and webhook handlers
- refund initiation
- SMS send/notify helpers
- PDF/text rendering helpers for bills
- template composition and view-model decoration where purely presentation-focused
- route redirect/message selection

## Move to C completely
- record parsing/serialization for patient/doctor/appointment/queue/advance/pending request/billing files
- file-backed CRUD and counts
- list/find/get-by-id helpers
- appointment and queue internal reconciliation
- advance and request expiry mechanics
- patient/doctor/appointment deterministic selectors and state checks
- internal grouped record selectors that do not depend on templates

## Keep as thin Python wrappers after move
- `read_patients`
- `find_patient_by_id`
- `find_patient_by_phone`
- `get_doctors`
- `get_doctor_by_id`
- `read_appointments`
- `find_appointment_by_id`
- `find_booked_appointment_for_patient_on_date`
- `read_bills`
- `find_bill_by_id`
- `find_bill_by_appointment_id`
- `find_bill_by_razorpay_order_id`
- `read_advances`
- `find_advance_by_*`
- `read_pending_requests_*`
- `read_new_patient_requests_*`

These wrappers should become only adapter code, or be inlined away later if no longer needed.

## Testing and Verification Strategy

## 1. Baseline before each domain migration
Capture current behavior for:
- patient create/search
- doctor add/view/status update/suggest
- appointment slots/book/cancel/complete/noshow/reschedule
- queue add/update/reconcile
- pending request create/update/expire/soft-lock
- advance create/update/find/pop intent/expire
- billing save/update/find/list
- key route flows:
  patient booking, follow-up booking, reception approval/rejection, appointment update, doctor completion, bill generation, advance payment flow

## 2. Command-level parity tests
For every new C command:
- valid input path
- malformed input path
- file missing path
- not-found path
- list output parsing
- single-record output parsing

## 3. Python adapter parity tests
For every migrated helper:
- compare old Python result vs new C-backed result on the same dataset
- compare dict keys, types, and values
- compare empty/not-found behavior

## 4. Route-level regression tests
Must pass unchanged after each phase:
- patient portal booking
- same-day slot load
- follow-up correction path
- pending request approval/rejection
- queue visibility
- doctor consultation completion
- billing page and bill creation
- payment webhook and advance flow
- stale expiry jobs

## 5. Removal gate
A Python implementation may be deleted only if:
- C command exists
- adapter exists
- parity tests pass
- route-level regression for affected flows passes

## Recommended Execution Order
1. Finish `patient` completely.
2. Finish `doctor` completely.
3. Finish `appointment` completely.
4. Finish `billing` and `advance` persistence ownership.
5. Finish `queue`.
6. Finish `pending_request`.
7. Move deterministic rule helpers.
8. Move multi-record internal workflows.
9. Compress Python orchestration helpers.

This order gives the largest Python line reduction early while minimizing break risk.

## What “done” looks like
- `app.py` is mostly Flask/web/payment/SMS/template orchestration.
- Existing C executables own nearly all file-backed business logic.
- No duplicate ownership remains for migrated domains.
- Python fallbacks are removed after verification.
- User-facing behavior, internal file schemas, and logical decisions remain unchanged.

## Assumptions
- Existing C modules are the correct ownership boundaries.
- Text files remain the persistence layer.
- The current behavior is the source of truth and must be preserved exactly.
- Reducing Python lines is a goal, but only through parity-preserving migration, never by changing logic or taking shortcuts.
