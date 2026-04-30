# HealthDesk

HealthDesk is a clinic and hospital front-desk management system built with Flask, HTML templates, text-file storage, and a set of C helper executables for core record operations. It is designed for small clinics that need a lightweight workflow for reception, doctor consultations, appointments, queue handling, diagnosis, and billing.

The current version includes role-based login for receptionists and doctors, automatic doctor account creation during doctor registration, structured billing with fixed pricing, and bill download as PDF.

## What The App Does

- Reception staff can search or register patients, book appointments, monitor the queue, manage doctors, and generate bills.
- Doctors can log in using their own credentials, manage their availability, open assigned consultations, and complete visits by saving diagnosis and prescription.
- Bills are generated only for completed appointments.
- Doctor details are fetched automatically from the patient appointment history during billing.
- Treatment, lab test, and doctor fee pricing are pulled from a pricing catalog instead of being typed manually each time.
- Generated bills can be previewed and downloaded as PDF.

## Main Features

- Role-based authentication for `Receptionist` and `Doctor`
- Unique login credentials for every doctor
- Auto-generated doctor username and password during doctor registration if not entered manually
- Reception dashboard with queue, appointments, billing, and doctor access
- Doctor dashboard with appointment list, queue, status update, and diagnosis workflow
- Appointment booking, cancellation, reschedule, no-show, and reassignment
- Doctor-driven queue completion after diagnosis save
- Separate receptionist queue monitoring by doctor
- Patient registration and lookup
- Diagnosis history and consultation recording
- Billing workflow with:
  - completed-appointment validation
  - auto-created bill record after doctor diagnosis save
  - receptionist billing follow-up from completed patients
  - automatic doctor retrieval
  - department-based treatment dropdowns
  - fixed doctor fee by department
  - fixed treatment and lab test prices
  - live total summary
  - PDF export and bill preview

## Tech Stack

- Python
- Flask
- ReportLab for PDF bill generation
- HTML, CSS, Bootstrap, Bootstrap Icons
- Plain-text files for application data
- C executables in `Backend/c_modules` for selected data operations

## Project Structure

```text
HealthDesk/
|-- app.py
|-- README.md
|-- Backend/
|   |-- data/
|   |   |-- appointment.txt
|   |   |-- billing.txt
|   |   |-- diagnosis.txt
|   |   |-- doctors.txt
|   |   |-- patients.txt
|   |   |-- pricing_catalog.json
|   |   |-- queue.txt
|   |   |-- users.txt
|   `-- c_modules/
|       |-- appointment.c / appointment.exe
|       |-- auth.c / auth.exe
|       |-- billing.c / billing.exe
|       |-- diagnosis.c / diagnosis.exe
|       |-- doctor.c / doctor.exe
|       |-- patient.c / patient.exe
|       `-- queue.c / queue.exe
`-- Frontend/
    |-- static/
    |   |-- css/style.css
    |   `-- script/main.js
    `-- templates/
        |-- appointments.html
        |-- billing.html
        |-- diagnosis.html
        |-- doctor_dashboard.html
        |-- doctors.html
        |-- index.html
        |-- login.html
        |-- queue.html
        |-- reception.html
        `-- receptionist_dashboard.html
```

## Requirements

- Python 3.10 or newer recommended
- Windows environment recommended for the included `.exe` files in `Backend/c_modules`
- `pip` available in your Python installation

## Installation

1. Clone or download this project.
2. Open a terminal in the project root.
3. Install the required Python packages:

```bash
pip install flask reportlab
```

4. Start the application:

```bash
python app.py
```

5. Open the app in your browser:

```text
http://127.0.0.1:5000
```

## Demo Login Credentials

The application currently ships with one receptionist account and multiple doctor accounts in `Backend/data/users.txt`.

Passwords are shown below for demo login, but `users.txt` stores hashed password values.

| Role | Username | Password |
|---|---|---|
| Receptionist | `reception` | `admin123` |
| Doctor | `dr.arun.kumar` | `HDDoc1@2026` |
| Doctor | `dr.meena.ravi` | `HDDoc2@2026` |
| Doctor | `dr.suresh.babu` | `HDDoc3@2026` |

Additional doctor accounts are listed in `Backend/data/users.txt`.

## Doctor Account Creation

When a new doctor is added from the Doctors page:

- a doctor profile is created
- the system checks whether a username was provided
- if no username is entered, a username is generated in the form `dr.<name>`
- if no password is entered, a password is generated in the form `HDDoc<doctor_id>@<year>`
- the password is hashed before the account is stored in `Backend/data/users.txt`
- the newly created credentials are shown immediately in the UI so they can be shared with the doctor

This ensures only valid doctor accounts can log in to the doctor dashboard.

## Billing Workflow

The billing module is designed to reduce manual entry while keeping the bill detailed.

- When the doctor saves diagnosis and prescription for an active consultation, the appointment is completed, the queue entry is closed, and a bill record is created automatically.
- Select a patient from the billing page.
- The system loads the latest appointment context for that patient.
- Billing is allowed only if the latest relevant appointment status is `Completed`.
- If the appointment is not completed, the UI shows a warning and prevents bill generation.
- Doctor information is automatically pulled from the appointment record.
- Doctor fee is automatically loaded from the department fee map.
- Bill IDs, bill lookup, and bill writes are handled through `Backend/c_modules/billing.exe`, while pricing rules, validation, UI, and PDF generation remain in Python.
- Treatments are chosen from categorized dropdowns based on department.
- Lab tests are selected from the pricing catalog.
- Medicines can be added as an amount plus optional notes.
- A live summary updates the total before the bill is generated.
- Reception can review completed patients directly from the billing page before previewing or downloading bills.
- Bills can be previewed again later and downloaded as PDF from the billing page.

## Pricing Configuration

All pricing is stored in:

```text
Backend/data/pricing_catalog.json
```

This file currently defines:

- doctor consultation fees by department
- treatment catalog
- treatment categories
- department restrictions for treatments
- lab test pricing

Update this file when you want to change treatment fees, doctor fees, or lab test charges.

## Data Storage

This project uses flat files instead of a database. Important files include:

- `Backend/data/users.txt` for login accounts
- `Backend/data/doctors.txt` for doctor profiles and status
- `Backend/data/patients.txt` for patient records
- `Backend/data/appointment.txt` for appointment records
- `Backend/data/queue.txt` for queue flow
- `Backend/data/diagnosis.txt` for diagnosis history
- `Backend/data/billing.txt` for bill records
- `Backend/data/pricing_catalog.json` for pricing rules

## UI Pages

Important pages in the current application:

- `/login`
- `/receptionist_dashboard`
- `/reception`
- `/appointments`
- `/queue`
- `/doctors`
- `/billing`
- `/doctor`
- `/diagnosis`

## Notes

- The project currently runs with local text files and does not use a relational database.
- The included C executables are Windows binaries. If you want to run the project on another platform, you may need to rebuild those modules from the `.c` sources.
- Login is handled in Python so passwords are not passed to `auth.exe` through command-line arguments. `auth.c` / `auth.exe` remain in the source tree for reference but are not part of the active login path.
- `app.py` runs Flask in debug mode by default on port `5000`.
- If `HEALTHDESK_SECRET` is not set, the app generates a temporary development secret at startup. Set `HEALTHDESK_SECRET` for stable sessions.
- State-changing forms include a CSRF token checked by Flask before processing POST requests.

## Future Improvements

- Replace text-file storage with SQLite or PostgreSQL
- Add audit logs for billing and appointment changes
- Add search, filters, and reports across all modules
- Add unit and integration tests
- Add Docker support and a `requirements.txt`

## License

This project currently does not include a license file. Add one if you plan to distribute or publish it publicly.
