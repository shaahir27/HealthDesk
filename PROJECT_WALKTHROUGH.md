# HealthDesk Project Walkthrough

This document explains how every important file in the HealthDesk project contributes to the system, what data structures it uses, and how the workflow moves through the frontend, Flask, C helper executables, and text files.

## 1. Big Picture

HealthDesk is a clinic front-desk and doctor workflow system.

The active architecture is:

```text
Browser / Frontend templates
        |
        v
Flask app.py routes and validation
        |
        v
subprocess call to C executable when low-level file operation is needed
        |
        v
C helper reads/writes Backend/data/*.txt
        |
        v
Flask parses output, builds page context
        |
        v
Frontend renders updated workflow
```

The project intentionally uses flat text files instead of a database.

Python owns:

- web routes
- authentication
- sessions
- CSRF checks
- workflow decisions
- business validation
- billing rules
- PDF generation
- UI context building
- data reconciliation between files

C owns:

- low-level record operations for patient, doctor, appointment, queue, diagnosis, and billing files
- fixed-format parsing and printing for subprocess communication
- some module-specific data structures like linked lists, stacks, binary trees, and dynamic arrays

## 2. Root Files

### `app.py`

This is the main Flask application and the center of the system.

It connects all pages, templates, C executables, and data files.

Main responsibilities:

- Starts Flask using `Frontend/templates` and `Frontend/static`.
- Defines all URL routes.
- Enforces login and role checks.
- Verifies CSRF tokens for every POST request.
- Authenticates users from `Backend/data/users.txt`.
- Calls C executables through `subprocess.run`.
- Parses text files into Python dictionaries and lists.
- Controls appointment, queue, doctor, diagnosis, and billing workflows.
- Generates bill preview text and PDF files.
- Auto-cleans stale appointments and queues.
- Auto-resets doctor `Busy` status when no live workload exists.
- Auto-reassigns future appointments when a doctor becomes unavailable, off, or emergency.

Important constants:

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
BILLING_EXE
ALLOWED_PAYMENT_STATUSES
```

Important Python data structures used:

- `dict`: patient records, doctor records, appointment records, billing records, page context, lookup maps.
- `list`: collections of patients, doctors, queue rows, appointments, bills, treatments, lab tests.
- `set`: allowed roles, allowed statuses, payment statuses, status comparisons.
- `tuple`: grouping keys such as `(patient_id, doctor_id)`.
- `threading.Lock`: `_appointment_lock` protects Python calls to `appointment.exe` so two requests do not book the same slot at the same time inside one Flask process.
- Flask `session`: stores `logged_in`, `username`, `role`, `doctor_id`, and `_csrf_token`.
- `BytesIO`: holds generated PDF bytes in memory before returning the response.

Important helper areas:

- `append_data_line()`: safely appends a new line to a text file.
- `clean_record_field()`: removes pipe delimiters and newlines from user-controlled text before writing to pipe-separated files.
- `safe_int()`: safely converts values to integers.
- Appointment helpers: parse, read, write, complete, cancel, reschedule, stale cleanup.
- Queue helpers: read, write, group by doctor, complete/cancel/reschedule rows.
- Doctor helpers: read doctors, write doctor file, status synchronization, suggestion, reassignment.
- Billing helpers: read bills through `billing.exe`, parse multiple bill formats, recalculate totals, create bill records, save bills, build PDF.
- Diagnosis helpers: get patient history through `diagnosis.exe`, save diagnosis, complete appointment, close queue, auto-generate bill.

Main routes:

```text
/                         -> role-based redirect
/login                    -> login page and authentication
/logout                   -> clears session
/receptionist             -> redirects to receptionist dashboard
/reception                -> patient search, registration, appointment selection
/receptionist_dashboard   -> receptionist summary cards
/doctor                   -> doctor dashboard
/queue                    -> receptionist queue page grouped by doctor
/appointments             -> appointment slot board and grouped appointment actions
/book_appointment         -> create appointment, optionally queue same-day patient
/cancel_appointment       -> cancel appointment and queue row
/reschedule               -> reschedule appointment and queue row
/update_appointment       -> cancel, reschedule, reassign, no-show; doctor completion guard
/doctors                  -> doctor management page
/add_doctor               -> create doctor profile and login account
/toggle_doctor            -> legacy daily-status update route
/doctor_status            -> receptionist updates doctor status
/doctor_my_status         -> doctor updates own status
/doctor_complete_consultation -> opens diagnosis for assigned active appointment
/diagnosis                -> diagnosis page
/diagnosis_history        -> loads diagnosis history by patient ID
/add_diagnosis            -> saves diagnosis, completes appointment, closes queue, creates bill
/billing                  -> billing page, completed patient follow-up, bill preview
/generate_bill            -> manual receptionist bill generation after completed appointment
/billing/download/<id>    -> PDF download
```

Important workflow rules in `app.py`:

- Login is handled in Python, not by `auth.exe`, so passwords are not exposed in OS process arguments.
- Passwords in `users.txt` are stored as hashes and checked with Werkzeug.
- Every POST form must include `_csrf_token`.
- Reception cannot manually complete consultations.
- Doctor completion is not final until diagnosis and prescription are saved.
- Diagnosis requires patient, doctor, appointment, date, diagnosis text, and prescription.
- Saving diagnosis completes the appointment and marks the queue row completed.
- Billing is allowed only for completed appointments.
- Duplicate billing is blocked by appointment ID.
- Bill totals are recalculated from stored components when parsed.
- Past-date appointment booking and rescheduling are rejected.

### `README.md`

High-level project README.

It explains:

- project purpose
- technology stack
- folder structure
- setup/run command
- demo credentials
- doctor account creation
- billing workflow
- data storage files
- UI pages
- notes and future improvements

This is for quick onboarding.

### `SYSTEM_FLOW.md`

User-facing workflow explanation.

It explains:

- login flow
- receptionist dashboard
- reception page
- appointment flow
- queue flow
- doctors page
- doctor dashboard
- diagnosis flow
- billing flow
- end-to-end patient journey
- doctor unavailable/reassignment flow
- cancellation/reschedule/no-show flows
- data file update flow

This is useful for demos and viva-style explanation.

### `changes.html`

A project review report file.

It is not used by the running application.

It lists review issues, priorities, test cases, and suggested fixes. We used it as the checklist for recent fixes.

### `Claude review check.zip`

A zip artifact in the root folder.

It is not part of the active runtime unless manually opened. Treat it as supporting review material.

### `__pycache__/app.cpython-313.pyc`

Generated Python bytecode cache.

It is not source code and should not be edited manually. Python can recreate it when `app.py` is imported or compiled.

## 3. Backend C Module Header

### `Backend/c_modules/common.h`

Shared C header used by all C modules.

It defines:

- standard includes: `stdio.h`, `stdlib.h`, `string.h`
- buffer limits
- file paths
- shared structs

Buffer constants:

```c
#define MAX_NAME 50
#define MAX_PHONE 20
#define MAX_ADDRESS 200
#define MAX_TEXT 200
#define MAX_SMALL 20
#define MAX_LINE 500
```

File path constants:

```c
DOCTOR_FILE
PATIENT_FILE
QUEUE_FILE
DIAGNOSIS_FILE
BILLING_FILE
APPOINTMENT_FILE
USER_FILE
```

C structs:

```c
struct Patient {
    int id;
    char name[MAX_NAME];
    int age;
    char gender[MAX_SMALL];
    char phone[MAX_PHONE];
    char address[MAX_ADDRESS];
    char symptoms[MAX_TEXT];
    char visit_type[MAX_SMALL];
    char priority[MAX_SMALL];
    char department[MAX_NAME];
};
```

```c
struct Doctor {
    int id;
    char name[MAX_NAME];
    char specialization[MAX_NAME];
    int experience;
    char daily_status[MAX_SMALL];
    char current_status[MAX_SMALL];
};
```

```c
struct QueueNode {
    int token;
    int patient_id;
    int doctor_id;
    char priority[MAX_SMALL];
    char status[MAX_SMALL];
    struct QueueNode* next;
};
```

```c
struct Diagnosis {
    int record_id;
    int patient_id;
    int doctor_id;
    char date[20];
    char diagnosis[MAX_TEXT];
    char prescription[MAX_TEXT];
};
```

```c
struct Appointment {
    int appointment_id;
    int patient_id;
    int doctor_id;
    char date[20];
    char time_slot[20];
    char status[MAX_SMALL];
};
```

```c
struct BillingItem {
    char description[MAX_NAME];
    float amount;
};
```

Contribution:

- Keeps C modules consistent.
- Prevents each C file from redefining record layouts.
- Ensures all C helpers point to the same data file paths.

## 4. C Helper Modules

### `Backend/c_modules/patient.c`

Handles patient search and patient registration at the file-operation level.

Active executable:

```text
Backend/c_modules/patient.exe
```

Called from Python:

- `find_patient_by_phone()`
- registration branch inside `/reception`

Commands:

```text
patient.exe search <phone>
patient.exe "<name>|<age>|<gender>|<phone>|<address>|<symptoms>|<visit_type>|<priority>|<department>"
```

Outputs:

```text
PATIENT|id|name|age|gender|phone|address|symptoms|visit_type|priority|department
PatientNotFound
id|visit_type|priority
Error|InvalidPatientData
Error|InvalidPhone
Error|MemoryAllocationFailed
```

Data structures:

- `struct Patient`: actual patient data.
- `struct PatientNode`: linked-list node containing `struct Patient data` and `next`.
- `patients_head`, `patients_tail`: linked-list pointers.
- `patients_loaded`: prevents repeated file loading in one process.
- `patients_dirty`: tells `atexit()` whether file save is needed.

Why linked list is used:

- Patients are loaded from file into a dynamic list.
- New patients can be appended without fixed array size.
- The module can search by phone and append records before saving.

Important functions:

- `safeCopy()`: bounded string copy.
- `parsePatientLine()`: converts one text-file row into `struct Patient`.
- `appendPatientNode()`: adds patient to linked list.
- `loadPatients()`: loads `patients.txt` into linked list.
- `savePatientsIfDirty()`: rewrites file only if changed.
- `freePatients()`: releases linked-list memory.
- `shutdownPatients()`: saves and frees at program exit.
- `nextPatientId()`: finds max patient ID and returns next ID.
- `searchByPhone()`: finds existing patient by phone.
- `parse_patient_data()`: parses new patient input from Python.
- `addPatient()`: validates and appends new patient.

Workflow contribution:

- Receptionist searches by phone.
- If patient does not exist, receptionist registers patient.
- Python validates first, then C validates again and writes to `patients.txt`.

### `Backend/c_modules/doctor.c`

Handles doctor file operations, status updates, doctor lookup, doctor suggestions, and doctor creation.

Active executable:

```text
Backend/c_modules/doctor.exe
```

Called from Python:

- `suggest_doctors_by_department()`
- `add_doctor()`
- `doctor_status()`
- `doctor_my_status()`
- `toggle_doctor()`

Commands:

```text
doctor.exe view
doctor.exe daily <doctor_id> <daily_status>
doctor.exe current <doctor_id> <current_status>
doctor.exe status <doctor_id> <daily_status> <current_status>
doctor.exe search <department>
doctor.exe suggest <department>
doctor.exe find <department>
doctor.exe "<name>|<department>|<experience>"
```

Outputs:

```text
id|name|department|experience|daily_status|current_status
NoDoctorFound
<new_doctor_id>
```

Data structures:

- `struct Doctor`: doctor record.
- `struct DoctorNode`: binary search tree node with `data`, `left`, and `right`.
- Process-specific temp file path for safe doctor file rewrite.

Why binary tree is used:

- Doctors are inserted ordered by specialization and ID.
- Department search traverses the tree.
- `findAvailableDoctor()` returns the first matching available doctor from the tree.

Important functions:

- `parseDoctorLine()`: parses `doctors.txt`.
- `printDoctor()`: prints a doctor row to stdout.
- `generate_id()`: finds next doctor ID.
- `addDoctor()`: appends new doctor with `Available|Free`.
- `viewDoctors()`: prints all doctors.
- `updateDoctorStatuses()`: updates both daily and current status.
- `updateDailyStatus()`: updates daily status only.
- `updateCurrentStatus()`: updates current status only.
- `buildDoctorTempPath()`: creates process-specific temp path such as `doctors.<pid>.tmp`.
- `createDoctorNode()`: allocates a BST node.
- `insertDoctor()`: inserts into BST.
- `loadDoctorTree()`: loads `doctors.txt` into BST.
- `searchByDepartment()`: prints matching department doctors.
- `findAvailableDoctorInTree()`: finds department doctor where `daily_status == Available` and `current_status != Emergency`.
- `freeDoctorTree()`: releases tree memory.

Workflow contribution:

- Receptionist manages doctors.
- Doctor can update own availability.
- Appointment page uses doctor suggestion.
- If doctor becomes unavailable/off/emergency, Python tries to reassign future booked appointments.

Important status rules:

- `daily_status`: `Available`, `Unavailable`, `Off`.
- `current_status`: `Free`, `Busy`, `Emergency`.
- Appointment slots are blocked if doctor is `Unavailable`, `Off`, or `Emergency`.
- Suggestions include doctors who are `Available` and not `Emergency`.

### `Backend/c_modules/appointment.c`

Handles appointment slots, booking, status updates, rescheduling, availability, and doctor-date appointment listing.

Active executable:

```text
Backend/c_modules/appointment.exe
```

Called from Python:

- `load_appointment_slots()`
- `run_appointment_command()`
- booking, cancel, reschedule, complete, no-show, reassignment flows

Commands:

```text
appointment.exe slots <doctor_id> <date>
appointment.exe book <patient_id> <doctor_id> <date> <time_slot>
appointment.exe cancel <appointment_id>
appointment.exe complete <appointment_id>
appointment.exe noshow <appointment_id>
appointment.exe reschedule <appointment_id> <new_date> <new_time>
appointment.exe availability <doctor_id> <date> <time_slot>
appointment.exe list <doctor_id> <date>
```

Outputs:

```text
SLOT|08:30 AM|Available
SLOT|09:30 AM|Booked
BOOKED|appointment_id|patient_id|doctor_id|date|time_slot|Booked
UPDATED|appointment_id|Status
RESCHEDULED|old_id|new_id|new_date|new_time
AVAILABILITY|Available
APPOINTMENT|appointment_id|patient_id|doctor_id|date|time_slot|status
Error|InvalidInput
Error|SlotNotAvailable
Error|AppointmentNotFound
Error|AppointmentNotActive
Error|AppointmentLimitReached
Error|NewSlotNotAvailable
Error|UpdateFailed
```

Data structures:

- `struct Appointment`: one appointment record.
- Dynamic heap array: `malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS)`.
- `DEFAULT_SLOTS`: fixed array of 8 appointment time strings.

Why dynamic heap array is used:

- Appointment records are loaded into an array for slot calculations.
- `MAX_APPOINTMENTS` is `50000`.
- Heap allocation avoids stack overflow from a large static array.

Slot constants:

```text
08:30 AM
09:30 AM
10:30 AM
11:40 AM
02:00 PM
04:00 PM
06:00 PM
08:05 PM
```

Important functions:

- `validSlot()`: only accepts one of the fixed slots.
- `validDate()`: validates `YYYY-MM-DD`, real month/day, leap year, and rejects past dates.
- `generateAppointmentId()`: max existing ID + 1.
- `loadAppointments()`: loads `appointment.txt`.
- `saveAppointments()`: rewrites `appointment.txt`.
- `doctorIsBlocked()`: checks `doctors.txt`; blocks if unavailable/off/emergency.
- `getSlotState()`: calculates slot state from doctor status and appointment status.
- `printSlots()`: prints all 8 slots for a doctor/date.
- `bookSlot()`: validates and appends a `Booked` appointment.
- `updateAppointmentStatus()`: updates status to cancelled/completed/no-show.
- `rescheduleAppointment()`: marks old appointment `Rescheduled`, creates new `Booked` row.
- `checkDoctorAvailability()`: prints one slot state.
- `listAppointmentsForDoctorDate()`: prints appointments for one doctor/date.

Workflow contribution:

- Receptionist slot board depends on this module.
- Booking uses this module.
- Doctor save diagnosis completes appointment through this module.
- Reschedule/reassign/cancel/no-show all update appointment state through this module.

### `Backend/c_modules/queue.c`

Handles same-day queue token creation and queue persistence.

Active executable:

```text
Backend/c_modules/queue.exe
```

Called from Python:

- `add_patient_to_queue()`

Commands:

```text
queue.exe <patient_id>
queue.exe <patient_id> <doctor_id>
queue.exe <patient_id> <doctor_id> <priority>
```

Outputs:

```text
token|doctor_id|priority
Error|InvalidPatient
Error|PatientNotFound
Error|MemoryAllocationFailed
```

Data structures:

- `struct QueueNode`: queue item.
- `struct QueueStore`: has `front` and `rear`.
- Linked list queue: `front -> ... -> rear`.
- Static flags: `queue_loaded`, `queue_dirty`.

Why queue linked list is used:

- Queue rows are naturally ordered.
- New rows are appended at rear.
- Existing waiting patient can be found without creating duplicate waiting rows.

Important functions:

- `safeCopy()`: bounded string copy.
- `appendQueueNode()`: appends queue node.
- `loadQueue()`: loads `queue.txt` into linked list.
- `saveQueueIfDirty()`: rewrites queue file when changed.
- `freeQueueStore()`: releases linked list.
- `shutdownQueueStore()`: saves and frees at exit.
- `nextToken()`: max token + 1.
- `findWaitingByPatient()`: prevents duplicate waiting queue row for same patient.
- `getPatientPriority()`: reads priority from `patients.txt`.
- `getPatientDepartment()`: reads department from `patients.txt`.
- `findAvailableDoctor()`: finds department doctor available and not emergency if no doctor was passed.
- `doctorExists()`: validates passed doctor ID.
- `enqueuePatient()`: adds row and marks dirty.

Workflow contribution:

- Same-day appointment creates queue token.
- Receptionist queue page displays waiting patients grouped by doctor.
- Doctor dashboard displays assigned waiting patients.
- Queue status is changed by Python when appointment status changes or diagnosis is saved.

### `Backend/c_modules/diagnosis.c`

Handles diagnosis history and diagnosis record creation.

Active executable:

```text
Backend/c_modules/diagnosis.exe
```

Called from Python:

- `get_diagnosis_context()`
- `add_diagnosis()`

Commands:

```text
diagnosis.exe history <patient_id>
diagnosis.exe latest <patient_id>
diagnosis.exe "<patient_id>|<doctor_id>|<date>|<diagnosis>|<prescription>"
```

Outputs:

```text
PATIENT|id|name|age|gender|phone|address|symptoms|visit_type|priority|department
DIAGNOSIS|record_id|patient_id|doctor_id|date|diagnosis|prescription
NO_DIAGNOSIS
PatientNotFound
record_id|patient_id|doctor_id
```

Data structures:

- `struct Diagnosis`: diagnosis record.
- `struct DiagnosisNode`: stack node.
- Stack implemented through linked list.

Why stack is used:

- Diagnosis records for a patient are pushed as found.
- Popping prints latest first because newest matching rows become top of stack.
- `peek()` supports latest diagnosis.

Important functions:

- `push()`: stack push.
- `peek()`: returns top diagnosis.
- `pop()`: stack pop.
- `freeStack()`: clears stack.
- `generateDiagnosisId()`: max diagnosis ID + 1.
- `parseDiagnosisLine()`: parses `diagnosis.txt`.
- `getPatientById()`: reads patient details from `patients.txt`.
- `loadDiagnosisStack()`: loads matching patient diagnoses into stack.
- `printDiagnosis()`: prints `DIAGNOSIS|...`.
- `printPatientHistory()`: prints patient plus diagnosis history.
- `printLatestDiagnosis()`: prints latest diagnosis only.
- `addDiagnosis()`: appends new diagnosis row.

Workflow contribution:

- Doctor opens diagnosis page and sees patient profile plus history.
- Doctor saves diagnosis and prescription.
- Python then completes appointment, closes queue, and creates bill.

### `Backend/c_modules/billing.c`

Handles bill file operations only.

Active executable:

```text
Backend/c_modules/billing.exe
```

Called from Python:

- `run_billing_command()`
- `generate_bill_id()`
- `read_bills()`
- `find_bill_by_id()`
- `find_bill_by_appointment_id()`
- `save_bill_record()`

Commands:

```text
billing.exe next-id
billing.exe list
billing.exe find-id <bill_id>
billing.exe find-appointment <appointment_id>
billing.exe save <serialized_bill_line>
```

Outputs:

```text
<next_bill_id>
<billing.txt lines>
<matching bill line>
SAVED
Error|InvalidInput
Error|InvalidCommand
Error|SaveFailed
```

Data structures:

- File line buffer: `char line[MAX_LINE]`.
- No complex business struct is used here.
- Field extraction function preserves empty fields.

Important functions:

- `safeCopy()`: bounded copy.
- `nextBillId()`: max bill ID + 1, starting from 1000 because default max is 999.
- `extractFieldPreserveEmpty()`: extracts a pipe-separated field without losing empty fields.
- `parseAppointmentId()`: reads field index 18 for appointment ID.
- `listBills()`: prints all bills.
- `findBillById()`: prints matching bill.
- `findBillByAppointmentId()`: prints bill linked to appointment.
- `saveBillLine()`: appends serialized Python-created bill line.

Workflow contribution:

- Keeps bill file operations in C.
- Python keeps billing business logic, pricing, validation, UI context, and PDF generation.
- This matches the current architecture split.

### `Backend/c_modules/auth.c`

Legacy authentication helper.

Active runtime status:

- Not used by current Flask login.
- Kept as source/reference only.
- `auth.exe` still exists in the folder, but `app.py` does not call it.

Why it is inactive:

- It expects plaintext passwords.
- Current `users.txt` stores hashed passwords.
- Passing passwords as command-line arguments is unsafe because OS process lists can expose them.

Data structures:

- Simple file line buffers and local char arrays.
- No dynamic structure.

Contribution now:

- Historical/reference module only.
- Do not use for current login unless rewritten for hashed password verification or stdin-based secret handling.

### Removed module: `serve.c` / `serve.exe`

This was removed because the active system no longer lets the receptionist manually serve the next queue patient.

Current queue movement:

```text
Doctor saves diagnosis
        -> Flask completes appointment
        -> Flask marks queue row Completed
        -> Flask auto-generates bill
```

## 5. Backend Data Files

All data files use pipe-separated text records unless stated otherwise.

### `Backend/data/users.txt`

Stores login accounts.

Format:

```text
user_id|username|password_hash|role|doctor_id
```

Example:

```text
3|dr.arun.kumar|scrypt:...|Doctor|1
```

Fields:

- `user_id`: numeric account ID.
- `username`: login username.
- `password_hash`: Werkzeug hash, currently `scrypt`.
- `role`: `Receptionist` or `Doctor`.
- `doctor_id`: `0` for receptionists, real doctor ID for doctors.

Used by:

- Python `read_user_accounts()`
- Python `authenticate_user()`
- Python `save_user_account()`

Data structures after parsing:

```python
{
    "id": int,
    "username": str,
    "password": str,
    "role": str,
    "doctor_id": int
}
```

### `Backend/data/doctors.txt`

Stores doctor profiles and availability.

Format:

```text
doctor_id|name|department|experience|daily_status|current_status
```

Example:

```text
1|Dr. Arun Kumar|General|10|Available|Busy
```

Fields:

- `doctor_id`: numeric doctor profile ID.
- `name`: doctor display name.
- `department`: specialization/department.
- `experience`: years.
- `daily_status`: `Available`, `Unavailable`, or `Off`.
- `current_status`: `Free`, `Busy`, or `Emergency`.

Used by:

- Python doctor dashboards, appointment page, reassignment, billing doctor lookup.
- `doctor.exe` for status and suggestions.
- `appointment.exe` for slot blocking.
- `queue.exe` for automatic doctor assignment.

### `Backend/data/patients.txt`

Stores patient records.

Format:

```text
patient_id|name|age|gender|phone|address|symptoms|visit_type|priority|department
```

Example:

```text
1|Aakash|34|Male|9000000001|Chennai|Chest tightness|New|Urgent|General
```

Fields:

- `patient_id`
- `name`
- `age`
- `gender`
- `phone`
- `address`
- `symptoms`
- `visit_type`: `New`, `Follow-up`, `Emergency`
- `priority`: `Normal`, `Urgent`
- `department`

Used by:

- Reception search and registration.
- Queue priority and department lookup.
- Diagnosis patient context.
- Billing patient details.

Python parsing now accepts records with at least 10 fields, so a minor extra field does not make a patient invisible.

### `Backend/data/appointment.txt`

Stores appointment records.

Format:

```text
appointment_id|patient_id|doctor_id|date|time_slot|status
```

Example:

```text
1|1|1|2026-04-30|08:30 AM|Booked
```

Statuses:

- `Booked`
- `Completed`
- `Cancelled`
- `Rescheduled`
- `No-show`

Used by:

- Appointment slot board.
- Doctor upcoming appointments.
- Doctor live consultation resolution.
- Queue reconciliation.
- Billing eligibility.
- Auto-reassignment.

Important rule:

- Completion should happen through doctor diagnosis save, not receptionist manual action.

### `Backend/data/queue.txt`

Stores same-day consultation queue rows.

Format:

```text
token|patient_id|doctor_id|priority|status
```

Example:

```text
1|1|1|Urgent|Waiting
```

Statuses:

- `Waiting`
- `Completed`
- `Cancelled`
- `Rescheduled`
- `No-show`

Used by:

- Receptionist queue page.
- Doctor live queue.
- Queue counts on dashboard.
- Stale queue cleanup.
- Diagnosis completion.

Important rule:

- Queue is grouped by doctor.
- Receptionist monitors queue; doctor workflow clears it.

### `Backend/data/diagnosis.txt`

Stores diagnosis and prescription history.

Format:

```text
record_id|patient_id|doctor_id|date|diagnosis|prescription
```

Example:

```text
4|15|6|2026-04-30|Dust allergy|Cetirizine once daily
```

Used by:

- Doctor diagnosis history.
- Diagnosis save workflow.

Important rule:

- Diagnosis requires prescription before consultation can be completed.

### `Backend/data/billing.txt`

Stores bills.

Current 19-field format:

```text
bill_id|date|patient_id|name|age|gender|doctor|department|doctor_fee|treatment_total|lab_total|medicine_total|total|status|doctor_id|treatments|lab_tests|medicine_notes|appointment_id
```

Example:

```text
1003|2026-04-30|15|Omkar|33|Male|Dr. Priya Sharma|Dermatology|700|0|0|200|900|PENDING|6|||Cetirizine and moisturizer|15
```

Fields:

- `bill_id`: starts from 1000.
- `date`: bill date.
- patient fields: ID, name, age, gender.
- doctor fields: name, department, doctor ID.
- billing totals: doctor fee, treatment total, lab total, medicine total, total.
- `status`: `PENDING`, `PAID`, or `WAIVED`.
- `treatments`: serialized with `^` between items and `~` between name and price.
- `lab_tests`: same item serialization.
- `medicine_notes`: free text sanitized by Python.
- `appointment_id`: links bill to completed appointment.

Used by:

- `billing.exe` for file operations.
- Python billing parser and PDF generator.

Important rule:

- Python recalculates total from component values after parsing.
- Duplicate billing is prevented by appointment ID.

### `Backend/data/pricing_catalog.json`

Stores pricing rules.

JSON structure:

```json
{
  "doctor_fees": {},
  "treatments": [],
  "lab_tests": []
}
```

Contributes:

- Department doctor consultation fees.
- Treatment catalog.
- Treatment category.
- Treatment department restrictions.
- Lab test prices.

Used by:

- `load_pricing_catalog()`
- `get_pricing_maps()`
- billing page JavaScript
- bill total calculation
- PDF bill line items

Important design choice:

- Pricing is JSON, not hardcoded in C, so fees can be changed without recompiling executables.

## 6. Frontend Templates

All main page templates except `login.html` extend `index.html`.

They are rendered server-side by Flask/Jinja.

### `Frontend/templates/index.html`

Base layout for authenticated pages.

Contributes:

- HTML document shell.
- Bootstrap and Bootstrap Icons includes.
- Shared sidebar navigation.
- Topbar/mobile hamburger.
- Logout form.
- Main content area with `{% block content %}`.
- Injected auth state: current user and current role.
- Loads `Frontend/static/css/style.css`.
- Loads `Frontend/static/script/main.js`.

Data structures:

- Jinja conditionals check `is_logged_in`, `current_role`, `current_user`.
- Sidebar links are role-aware.

### `Frontend/templates/login.html`

Login page.

Contributes:

- Standalone clinical staff login UI.
- POST form to `/login`.
- CSRF hidden field.
- Displays login error message.

Inputs:

```text
username
password
_csrf_token
```

### `Frontend/templates/receptionist_dashboard.html`

Receptionist landing dashboard.

Contributes:

- Summary stats.
- Quick access cards.
- Current date.
- No live queue snapshot, because queue has its own page.

Context variables:

```text
waiting_count
completed_count
booked_count
cancelled_count
available_doctors
today
```

### `Frontend/templates/reception.html`

Patient intake and appointment booking page.

Contributes:

- Patient phone search.
- Patient registration form.
- Patient profile display.
- Doctor/date selector.
- Doctor status display.
- Alternative doctor suggestions.
- Slot booking buttons.
- Booking confirmation and queue token display.

Forms:

- POST `/reception` with `action=search`.
- POST `/reception` with `action=register`.
- GET `/reception` to reload selected doctor/date.
- POST `/book_appointment` for selected slot.

Important UI logic:

- If patient exists, show appointment booking controls.
- If patient does not exist, show registration.
- Same-day successful booking may show queue token.

### `Frontend/templates/appointments.html`

Receptionist appointment management page.

Contributes:

- Department/doctor/date filters.
- Seven-day slot availability overview.
- Daily slot board.
- Patient-ID based booking.
- Appointment action groups by doctor.
- Cancel, no-show, reschedule, and reassign actions.

Forms:

- GET `/appointments` for filtering.
- POST `/book_appointment`.
- POST `/update_appointment`.

Important rule:

- No receptionist `Complete` option is shown.
- Completion happens only when doctor saves diagnosis.

JavaScript contribution:

- Uses `.appointment-action-select` and extra fields.
- `main.js` shows/hides date/time/doctor fields depending on chosen action.

### `Frontend/templates/queue.html`

Receptionist queue monitoring page.

Contributes:

- Queue grouped by doctor.
- Waiting/completed queue counts.
- Per-doctor waiting patient rows.
- Patient token, ID, name, priority, symptoms.
- Status note display.

Important rule:

- No serve button.
- Queue exits automatically after doctor diagnosis save.

### `Frontend/templates/doctors.html`

Doctor management page for receptionist.

Contributes:

- Add doctor form.
- Optional username/password fields.
- Shows newly created doctor login credentials.
- Doctor directory table.
- Doctor status update forms.

Forms:

- POST `/add_doctor`.
- POST `/doctor_status`.

Important rule:

- If username/password are blank, Python generates them.
- Password is hashed before storing in `users.txt`.
- If doctor becomes unavailable/off/emergency, Python tries appointment reassignment.

### `Frontend/templates/doctor_dashboard.html`

Doctor home page.

Contributes:

- Doctor identity/status hero.
- Status update form.
- Live queue section above upcoming appointments.
- Upcoming appointments section below live queue.
- Consultation start buttons.
- Billing result context after diagnosis.

Forms:

- POST `/doctor_my_status`.
- POST `/doctor_complete_consultation`.

Important rule:

- Live queue is the actionable consultation list.
- Upcoming appointments are future informational items.
- Start consultation opens `/diagnosis` with appointment context.

### `Frontend/templates/diagnosis.html`

Doctor diagnosis page.

Contributes:

- Patient history search when no patient context is active.
- Patient overview.
- Diagnosis history table.
- Diagnosis and prescription form.
- Completion button.

Forms:

- POST `/diagnosis_history`.
- POST `/add_diagnosis`.

Important rule:

- Save button is disabled if there is no active appointment.
- Prescription is required.
- Save diagnosis completes consultation.

### `Frontend/templates/billing.html`

Billing management page.

Contributes:

- Patient selector.
- Appointment context panel.
- Payment status selector.
- Dynamic treatment row builder.
- Lab test checkboxes.
- Medicine amount and notes.
- Live bill total summary.
- Completed patients sidebar.
- Existing bills sidebar.
- Bill preview text.
- PDF download links.

Forms:

- POST `/generate_bill`.

Inline JavaScript data structures:

- `patients`: JSON list from Flask.
- `billingLookup`: JSON object mapping patient ID to billing context.
- `pricingCatalog`: JSON pricing catalog.
- `patientMap`: JavaScript object created with `Object.fromEntries`.
- DOM rows for treatment selection.

Important JavaScript functions:

- `formatCurrency()`
- `getCurrentContext()`
- `treatmentCategories()`
- `buildOption()`
- `populateTreatmentSelect()`
- `createTreatmentRow()`
- `ensureTreatmentRow()`
- `updateRowPrice()`
- `updateTreatmentRowsDisplay()`
- `updateContextPanel()`
- `updateTotals()`

Important rule:

- Generate Bill button is enabled only when the selected patient has a completed appointment and no existing bill for that appointment.

## 7. Static Files

### `Frontend/static/css/style.css`

Global styling for the app.

Contributes:

- CSS custom properties in `:root`.
- Sidebar and topbar layout.
- Responsive mobile sidebar.
- Shared card styles.
- Dashboard stat cards.
- Action cards.
- Tables.
- Badges.
- Buttons.
- Slot grid.
- Alerts.
- Billing layouts.
- Doctor dashboard layouts.
- Reception/appointment/queue/doctor/diagnosis/billing page-specific classes.
- Media queries for tablet and mobile.

Important CSS class families:

```text
hd-*      shared HealthDesk design system
rx-*      reception/dashboard related older classes
rcx-*     reception page
apx-*     appointments page
qx-*      queue page
docx-*    doctor dashboard
drx-*     doctors page
dgx-*     diagnosis page
billx-*   billing page
```

Data structure concept:

- CSS uses variables as a design token map, for example color, shadows, radius, sidebar width.

### `Frontend/static/script/main.js`

Shared frontend behavior.

Contributes:

- Mobile sidebar open/close.
- Overlay click closes sidebar.
- Escape key closes sidebar.
- Sidebar link click closes sidebar on mobile.
- Auto-refresh if a page includes `data-auto-refresh`.
- Appointment action field toggling.

JavaScript data structures:

- DOM node references.
- Arrays of extra fields.
- Event listeners.

Important behavior:

- For appointment action forms, date/time fields appear for `reschedule` and `reassign`.
- Doctor ID field appears only for `reassign`.
- Hidden fields are not required; visible fields become required.

## 8. Runtime Data Flow By Workflow

### Login

```text
login.html
    -> POST /login
    -> app.py authenticate_user()
    -> read users.txt
    -> check_password_hash()
    -> session created
    -> redirect to receptionist dashboard or doctor dashboard
```

No C executable is used for current login.

### Patient Search

```text
reception.html
    -> POST /reception action=search
    -> app.py find_patient_by_phone()
    -> patient.exe search phone
    -> patient.c loads patients.txt into linked list
    -> prints PATIENT|...
    -> Flask parses into dict
    -> reception.html displays patient
```

### Patient Registration

```text
reception.html
    -> POST /reception action=register
    -> Flask validates required fields, phone, age
    -> patient.exe "name|age|..."
    -> patient.c validates and appends linked-list node
    -> patients.txt updated at exit
    -> Flask reloads patient
    -> receptionist chooses appointment slot
```

### Appointment Booking

```text
appointments.html or reception.html
    -> POST /book_appointment
    -> Flask validates patient, doctor, date, slot
    -> Flask acquires _appointment_lock
    -> appointment.exe book ...
    -> appointment.c validates date/slot/doctor slot state
    -> appointment.txt appended
    -> if date is today, Flask calls queue.exe
    -> queue.txt appended
    -> frontend shows confirmation
```

### Queue Monitoring

```text
queue.html
    -> GET /queue
    -> Flask expire_stale_consultations()
    -> Flask reconcile_waiting_queue_entries()
    -> read queue.txt, patients.txt, doctors.txt
    -> build_reception_queue_groups()
    -> render queue grouped by doctor
```

### Doctor Consultation

```text
doctor_dashboard.html
    -> POST /doctor_complete_consultation
    -> Flask verifies appointment belongs to doctor
    -> Flask verifies consultation date reached
    -> redirect /diagnosis?patient_id=...&appointment_id=...
```

### Diagnosis Save

```text
diagnosis.html
    -> POST /add_diagnosis
    -> Flask validates assignment, date, diagnosis, prescription
    -> appointment.exe complete appointment_id
    -> diagnosis.exe "patient|doctor|date|diagnosis|prescription"
    -> diagnosis.txt appended
    -> Flask marks queue row Completed
    -> Flask auto_generate_bill()
    -> billing.exe save serialized bill
    -> redirect doctor dashboard with billing context
```

### Billing Page

```text
billing.html
    -> GET /billing
    -> billing.exe list
    -> Flask parses bills and recalculates totals
    -> Flask reads patients, appointments, doctors
    -> build_billing_lookup()
    -> render patient context and completed patients
```

### Manual Bill Generation

```text
billing.html
    -> POST /generate_bill
    -> Flask validates completed appointment and no existing bill
    -> Flask loads pricing_catalog.json
    -> Flask calculates doctor/treatment/lab/medicine totals
    -> billing.exe next-id
    -> billing.exe save line
    -> redirect billing preview
```

### PDF Download

```text
/billing/download/<bill_id>
    -> billing.exe find-id bill_id
    -> Flask parse_bill_line()
    -> Flask build_bill_pdf()
    -> ReportLab writes PDF into BytesIO
    -> browser downloads PDF
```

### Doctor Availability and Reassignment

```text
doctors.html or doctor_dashboard.html
    -> POST doctor status route
    -> doctor.exe status doctor_id daily current
    -> doctor.c rewrites doctors.txt via process-specific temp file
    -> if unavailable/off/emergency:
        -> Flask reads future booked appointments
        -> suggests same-department doctors
        -> checks available slot through appointment.exe slots
        -> cancels old appointment
        -> books new appointment
        -> updates same-day queue if needed
```

## 9. Data Structures Summary

### Python

```text
dict
```

Used for:

- patient records
- doctor records
- appointment records
- queue rows
- diagnosis records
- bill records
- billing lookup
- doctor maps
- appointment maps
- page context

```text
list
```

Used for:

- all patients
- all doctors
- all appointments
- all queue rows
- all bills
- grouped appointment lists
- grouped queue lists
- selected treatments
- selected lab tests
- billing-ready patients

```text
set
```

Used for:

- allowed roles
- allowed payment statuses
- status membership checks
- duplicate username checks

```text
tuple
```

Used for:

- grouping keys like `(patient_id, doctor_id)`

```text
threading.Lock
```

Used for:

- appointment command serialization inside Flask process

```text
Flask session
```

Used for:

- login state
- role
- current username
- doctor ID
- CSRF token
- newly-created doctor credentials flash context

### C

```text
struct Patient
struct Doctor
struct QueueNode
struct Diagnosis
struct Appointment
struct BillingItem
```

Defined in `common.h`.

```text
Linked list
```

Used in:

- `patient.c`: patient store
- `queue.c`: queue store

```text
Stack
```

Used in:

- `diagnosis.c`: diagnosis history for newest-first behavior

```text
Binary search tree
```

Used in:

- `doctor.c`: doctor search/suggestion by department

```text
Dynamic heap array
```

Used in:

- `appointment.c`: appointment records loaded for slot-state calculation

```text
File line buffers and token parsing
```

Used in:

- all C modules

### JavaScript

```text
DOM references
arrays
plain objects
event listeners
JSON-injected server data
```

Used in:

- sidebar interaction
- appointment action dynamic fields
- billing treatment builder
- billing total calculation

### CSS

```text
CSS custom properties
responsive grids
class families
media queries
```

Used for:

- visual system
- layout
- responsive behavior
- page-specific UI composition

## 10. Security and Validation

Current safeguards:

- Password hashes in `users.txt`.
- Login handled in Python, not command-line password passing.
- `SESSION_COOKIE_HTTPONLY=True`.
- `SESSION_COOKIE_SAMESITE="Lax"`.
- Random development secret if `HEALTHDESK_SECRET` is missing.
- CSRF token on every POST form.
- Pipe and newline sanitization through `clean_record_field()`.
- Phone validation.
- Age validation.
- Required patient registration fields.
- Appointment past-date rejection in Python and C.
- Payment status whitelist.
- Billing total recalculation after parsing.
- Doctor route ownership checks.
- Doctor cannot access patients not assigned to them.
- Receptionist cannot manually complete consultations.

Important limitation:

- Flat-file storage is simple but not as safe as a real database for multi-user concurrency.
- The Python appointment lock protects one Flask process, but not multiple separate server processes.
- C file rewrites are basic file operations, not transactional database writes.

## 11. Generated and Binary Files

### `.exe` files in `Backend/c_modules`

These are compiled Windows executables from the corresponding `.c` files.

Active executables:

```text
appointment.exe
billing.exe
doctor.exe
diagnosis.exe
patient.exe
queue.exe
```

Legacy executable:

```text
auth.exe
```

Removed executable:

```text
serve.exe
```

If C source changes, rebuild the matching exe.

Example:

```powershell
gcc Backend\c_modules\appointment.c -o Backend\c_modules\appointment.exe
gcc Backend\c_modules\doctor.c -o Backend\c_modules\doctor.exe
gcc Backend\c_modules\queue.c -o Backend\c_modules\queue.exe
gcc Backend\c_modules\billing.c -o Backend\c_modules\billing.exe
gcc Backend\c_modules\patient.c -o Backend\c_modules\patient.exe
gcc Backend\c_modules\diagnosis.c -o Backend\c_modules\diagnosis.exe
```

### `__pycache__`

Generated by Python.

Not part of application logic.

## 12. File-by-File Quick Reference

```text
app.py
```

Main Flask app. Owns routing, validation, sessions, CSRF, workflow, billing rules, PDF generation, and subprocess calls.

```text
README.md
```

Project overview and setup guide.

```text
SYSTEM_FLOW.md
```

Workflow explanation for demo and understanding.

```text
PROJECT_WALKTHROUGH.md
```

This full technical walkthrough.

```text
changes.html
```

Review report/checklist, not runtime code.

```text
Claude review check.zip
```

Review artifact, not runtime code.

```text
Backend/c_modules/common.h
```

Shared C structs, constants, and file paths.

```text
Backend/c_modules/patient.c / patient.exe
```

Patient search and registration using linked list.

```text
Backend/c_modules/doctor.c / doctor.exe
```

Doctor profile/status/search/suggestion using binary search tree.

```text
Backend/c_modules/appointment.c / appointment.exe
```

Appointment slot state, booking, completion, cancellation, no-show, reschedule using dynamic array.

```text
Backend/c_modules/queue.c / queue.exe
```

Same-day queue token creation using linked-list queue.

```text
Backend/c_modules/diagnosis.c / diagnosis.exe
```

Diagnosis history and save using stack.

```text
Backend/c_modules/billing.c / billing.exe
```

Bill file helper for IDs, listing, finding, and saving.

```text
Backend/c_modules/auth.c / auth.exe
```

Legacy auth helper, not used by active Flask login.

```text
Backend/data/users.txt
```

Hashed login accounts.

```text
Backend/data/doctors.txt
```

Doctor profiles and statuses.

```text
Backend/data/patients.txt
```

Patient records.

```text
Backend/data/appointment.txt
```

Appointment records.

```text
Backend/data/queue.txt
```

Same-day queue records.

```text
Backend/data/diagnosis.txt
```

Diagnosis and prescription history.

```text
Backend/data/billing.txt
```

Bill records linked to completed appointments.

```text
Backend/data/pricing_catalog.json
```

Doctor fees, treatment prices, treatment categories, department restrictions, and lab test prices.

```text
Frontend/templates/index.html
```

Base authenticated layout and sidebar.

```text
Frontend/templates/login.html
```

Login screen.

```text
Frontend/templates/receptionist_dashboard.html
```

Receptionist summary dashboard.

```text
Frontend/templates/reception.html
```

Patient intake and slot booking.

```text
Frontend/templates/appointments.html
```

Slot board and grouped appointment actions.

```text
Frontend/templates/queue.html
```

Doctor-grouped queue monitoring.

```text
Frontend/templates/doctors.html
```

Doctor creation and availability management.

```text
Frontend/templates/doctor_dashboard.html
```

Doctor status, live queue, upcoming appointments, consultation entry.

```text
Frontend/templates/diagnosis.html
```

Patient history, diagnosis, prescription, consultation completion.

```text
Frontend/templates/billing.html
```

Billing workflow, dynamic charges, bill preview, PDF download.

```text
Frontend/static/css/style.css
```

Global styling and responsive design.

```text
Frontend/static/script/main.js
```

Shared sidebar behavior, auto-refresh, appointment action field toggling.

## 13. Most Important End-to-End Rule

The system is now doctor-driven for completion:

```text
Appointment booked
        -> if same day, queue token created
        -> doctor sees patient in live queue
        -> doctor starts consultation
        -> doctor saves diagnosis and prescription
        -> appointment becomes Completed
        -> queue row becomes Completed
        -> bill record is created
        -> receptionist can preview/download bill
```

This is the core workflow that ties the whole project together.
