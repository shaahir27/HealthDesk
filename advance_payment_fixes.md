# Advance Payment System — Fix Specification

**For the AI agent implementing these changes in `app.py`.**  
Read this entirely before touching any code. Every fix is surgical — do not refactor anything outside the described scope.

---

## How the System Currently Works (Read This First)

The advance payment flow has these stages:

```
Patient submits booking form
        ↓
patient_book_submit()
  - Validates slot availability
  - Determines triage: "auto" (book immediately) or "exception" (receptionist review)
  - Calls create_advance_record() → writes to advances.txt with status=PENDING_PAYMENT
  - Calls save_booking_intent() → writes to pending_booking_intents.txt (doctor, slot, triage, reason)
  - Redirects to /patient/advance/pay
        ↓
Patient pays via Razorpay on patient_advance_pay.html
        ↓
Razorpay fires POST /payment/webhook/advance
  payment_webhook_advance()
  - Verifies signature
  - Finds advance by razorpay_order_id
  - On payment.captured: sets status=PAID, calls _confirm_booking_after_advance(adv)
  - On payment.failed: sets status=EXPIRED
        ↓
_confirm_booking_after_advance(adv)
  - Pops booking intent from pending_booking_intents.txt
  - If triage=="auto": calls auto_approve_booking() → books slot, sends confirmed SMS
  - If triage=="exception": calls exception_queue_booking() → queues for receptionist, sends "under review" SMS
        ↓
Later lifecycle events:
  - Patient cancels (>24h before): advance → REFUNDED via Razorpay
  - Patient cancels (<24h): blocked, must call clinic
  - Receptionist rejects exception-queue request: advance → REFUNDED via Razorpay
  - Doctor marks no-show: advance → FORFEITED
  - Bill generated at visit: advance → CREDITED, deducted from bill total
  - _expire_stale_advances(): PENDING_PAYMENT past 30min (auto) or 2h (exception) → EXPIRED
```

**Advance record fields (advances.txt, pipe-delimited, 13 fields):**
```
advance_id | patient_id | appointment_id | doctor_id | appointment_date |
amount | status | razorpay_order_id | razorpay_payment_id |
created_at | paid_at | settled_at | pending_request_id
```

**All valid statuses for an advance record:**
`PENDING_PAYMENT` → `PAID` → `CREDITED` / `REFUNDED` / `FORFEITED`  
`PENDING_PAYMENT` → `EXPIRED` (timeout or payment.failed)

---

## Problems to Fix

There are **3 required fixes** and **3 optional improvements**.  
The required fixes close real bugs. The optional ones improve resilience and UX.

---

### FIX 1 (Required) — Auto-refund when advance is PAID but booking confirmation fails

**Where:** `_confirm_booking_after_advance(adv)` in `app.py`

**The bug:** When a patient pays their advance successfully, the webhook marks it `PAID` and calls `_confirm_booking_after_advance`. If `auto_approve_booking` then fails (slot was taken during the payment window), the code sends an SMS saying "call the clinic" but leaves the advance in `PAID` status with no appointment linked and no refund. The money is stuck. There is a similar gap in the `exception_queue_booking` failure path.

**The fix — replace the entire `_confirm_booking_after_advance` function with this:**

```python
def _confirm_booking_after_advance(adv):
    """
    Called from payment_webhook_advance after payment.captured.
    Retrieves booking intent and runs the triage path.
    This function must not raise — a webhook crash causes Razorpay retries.
    On any booking failure after a successful payment, an automatic refund is initiated.
    """
    try:
        intent = pop_booking_intent(adv["advance_id"])
        if not intent:
            print(f"[HealthDesk] WARNING: No booking intent for advance {adv['advance_id']}")
            # Intent missing — cannot book, refund the patient
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
                # Slot gone or booking failed — refund automatically
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
                    "Your booking request is under review — response within 2 hours."
                )
            else:
                # Could not even queue the request — refund
                _refund_advance_after_failure(
                    adv,
                    f"Your advance was received but we could not queue your request ({_message}). "
                    "A full refund has been initiated and will arrive in 5-7 business days."
                )
    except Exception as exc:
        print(f"[HealthDesk] ERROR confirming advance {adv.get('advance_id')}: {exc}")
```

**Add this helper function right before `_confirm_booking_after_advance`:**

```python
def _refund_advance_after_failure(adv, sms_message):
    """
    Initiates a Razorpay refund for a PAID advance that could not result in a booking.
    Updates the advance status to REFUNDED on success, or logs a warning on failure.
    This must never raise — it is called from within the webhook handler.
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
                "Please call the clinic — a refund will be processed manually."
            )
        patient = find_patient_by_id(adv["patient_id"])
        if patient:
            send_sms_notice(patient["phone"], sms_message)
    except Exception as exc:
        print(f"[HealthDesk] ERROR in _refund_advance_after_failure for advance {adv.get('advance_id')}: {exc}")
```

---

### FIX 2 (Required) — Guard against zero-amount advance crashing the booking flow

**Where:** `patient_book_submit()` in `app.py`

**The bug:** `get_advance_amount_for_department(department)` returns `0.0` if the department is missing from the pricing catalog (or if the fee is 0). The code then calls `create_advance_record(amount=0)` and redirects to the payment page. On that page, clicking Pay calls `/patient/advance/create-order`, which calls `create_advance_order(amount_rupees=0)`. Inside `payment_service.py`, this fails because `amount_paise <= 0` and returns `(False, "Advance amount must be greater than zero.", None)`. The patient sees a confusing payment error after filling out the booking form.

**The fix — in `patient_book_submit()`, find this block:**

```python
    triage, reasons = triage_booking_request(doctor_id, requested_date, visit_type)

    advance_amount = get_advance_amount_for_department(department)
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
```

**Replace it with:**

```python
    triage, reasons = triage_booking_request(doctor_id, requested_date, visit_type)

    advance_amount = get_advance_amount_for_department(department)

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
```

**Important:** The `patient` variable is already resolved earlier in `patient_book_submit`. This block uses it directly. No new variable is needed.

---

### FIX 3 (Required) — Clean up orphaned booking intents when advances expire

**Where:** `_expire_stale_advances()` in `app.py`

**The bug:** When a PENDING_PAYMENT advance expires (patient never paid), the advance record is set to EXPIRED but the corresponding booking intent in `pending_booking_intents.txt` is never removed. These intents accumulate as dead entries. They don't cause crashes, but they waste space and could theoretically match a recycled advance_id in the very long run.

**The fix — in `_expire_stale_advances()`, find this block:**

```python
            adv["status"] = "EXPIRED"
            adv["settled_at"] = iso_now()
            changed = True
            if adv["pending_request_id"]:
                update_pending_status(adv["pending_request_id"], "Expired")
            patient = find_patient_by_id(adv["patient_id"])
            if patient:
                send_sms_notice(
                    patient["phone"],
                    "Your HealthDesk booking was not confirmed - the payment window expired. "
                    "Please try booking again."
                )
```

**Replace it with:**

```python
            adv["status"] = "EXPIRED"
            adv["settled_at"] = iso_now()
            changed = True
            # FIX 3: pop the booking intent so the intents file stays clean
            pop_booking_intent(adv["advance_id"])
            if adv["pending_request_id"]:
                update_pending_status(adv["pending_request_id"], "Expired")
            patient = find_patient_by_id(adv["patient_id"])
            if patient:
                send_sms_notice(
                    patient["phone"],
                    "Your HealthDesk booking was not confirmed - the payment window expired. "
                    "Please try booking again."
                )
```

The `pop_booking_intent` function already exists and is safe to call even if no intent exists for that advance_id (it returns `None` without error).

---

### FIX 4 (Optional but Recommended) — Allow booking when payments are not configured

**Where:** `patient_book_submit()` in `app.py`

**The problem:** If Razorpay keys are not set (`payments_configured()` returns False), the advance payment page renders a "book at the counter" message but the patient has no online path to actually complete the booking. Online booking is effectively broken for the entire clinic until Razorpay is configured. This is painful during development, testing, or payment outages.

**The fix — add this block at the very top of the triage section in `patient_book_submit()`, immediately after `visit_type` is finalized and before the `triage_booking_request` call:**

```python
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
```

Place this block **after** the `followup_corrected` assignment and **before** the `triage_booking_request` call that feeds the advance flow. This means in an unconfigured environment, bookings go through triage directly, no advance is collected or recorded, and the `patient_advance_pay.html` is never reached.

---

### FIX 5 (Optional) — Exempt follow-up visits from advance payment

**Where:** `patient_book_submit()` in `app.py`

**The rationale:** Verified follow-up patients (those with a completed prior visit with the same doctor) are low no-show risk. Charging them 20% advance creates friction for established patients. The `triage_booking_request` already flags follow-ups for exception-queue review anyway, so the clinic retains oversight without needing financial commitment.

**The fix — after the `advance_amount` calculation, add:**

```python
    advance_amount = get_advance_amount_for_department(department)

    # --- FIX 5: follow-up visits skip advance (exception-queue still applies) ---
    if visit_type == "Follow-up":
        advance_amount = 0.0
    # --- end FIX 5 ---
```

This integrates cleanly with FIX 2: since `advance_amount` is now 0, the zero-amount guard in FIX 2 fires and routes directly through the triage path. No additional logic is needed.

Note: `visit_type` is only `"Follow-up"` here if the earlier validation confirmed the patient genuinely has a completed visit with this doctor. The `followup_corrected` flag already handles the case where it was falsely claimed.

---

### FIX 6 (Optional) — Add receptionist visibility for stranded and forfeited advances

**Where:** Receptionist dashboard data-building function in `app.py`

**The problem:** When an advance is stuck in `PAID` with `appointment_id = 0` (paid but booking failed — the state FIX 1 resolves automatically going forward), or when a patient disputes a `FORFEITED` advance, there is no receptionist-facing view. Staff learn about these via phone calls with no tooling.

**The fix — add a helper function to read stranded and forfeited advances:**

```python
def get_advances_needing_attention():
    """
    Returns advances that need manual receptionist attention:
    - PAID with appointment_id == 0: payment received but no booking linked (booking failure)
    - FORFEITED: no-show advance, may be disputed by patient
    """
    advances = read_advances()
    stranded = [
        a for a in advances
        if a["status"] == "PAID" and a["appointment_id"] == 0
    ]
    forfeited = [
        a for a in advances
        if a["status"] == "FORFEITED"
    ]
    return {"stranded": stranded, "forfeited": forfeited}
```

**Pass this into the receptionist dashboard render call:**

Find the `render_template` call for `receptionist_dashboard.html` and add:

```python
        advances_attention=get_advances_needing_attention(),
```

**In `receptionist_dashboard.html`**, add a section (exact HTML is up to the implementer) that shows:
- A list of stranded advances (PAID, no appointment): show patient name, doctor, date, amount, and a note "Payment received — booking not confirmed. Manually confirm or refund."
- A list of forfeited advances: show patient name, date, amount, with a note "No-show advance. Patient may call to dispute."

No new route is needed. This is display-only data for staff awareness.

---

## Correctness Rules — Do Not Break These

These are invariants the rest of the system relies on. Do not violate them while implementing the fixes.

**1. `_confirm_booking_after_advance` must never raise.**  
It is called from inside the Razorpay webhook handler. Any uncaught exception causes Razorpay to retry the webhook, which can result in double-processing. Always wrap the entire function body in `try/except Exception`.

**2. Only update the advance record AFTER the Razorpay action succeeds.**  
In `_refund_advance_after_failure`, set `adv["status"] = "REFUNDED"` only after `initiate_refund` returns `ok=True`. The existing pattern throughout the codebase follows this — do not deviate.

**3. `pop_booking_intent` is safe to call on a missing intent.**  
It returns `None` without error. Calling it in `_expire_stale_advances` (FIX 3) is always safe.

**4. The advance lock (`_advance_lock`) is already held inside `_expire_stale_advances`.**  
`pop_booking_intent` acquires `_advance_lock` internally. This will deadlock if called while the lock is already held. 

**Solution:** Call `pop_booking_intent` via `_pop_booking_intent_fallback` directly inside `_expire_stale_advances` since the lock is already held. Replace:
```python
pop_booking_intent(adv["advance_id"])
```
with:
```python
_pop_booking_intent_fallback(adv["advance_id"])
```
`_pop_booking_intent_fallback` is the pure file-manipulation path that does not acquire `_advance_lock`. It already exists in the codebase.

**5. Do not skip the `payments_configured()` check in FIX 4 for the `/patient/advance/create-order` route.**  
That route already returns a 503 if payments are not configured. FIX 4 prevents the patient from ever reaching that page when payments are off, so the route's own guard becomes a belt-and-suspenders check.

**6. The `auto_approve_booking` and `exception_queue_booking` functions already send SMS confirmations internally.**  
Do not add duplicate SMS sends in the FIX 2 or FIX 4 bypass paths. The confirmation message is already sent inside those functions.

**7. FIX 5 zero-amount follow-up only applies to the online booking flow.**  
New-patient requests (`/patient/new/submit`) do not go through the advance flow at all and are unaffected. Billing, no-show, and cancellation paths check `adv["status"] == "PAID"` before touching the advance, so a zero-advance booking simply has no advance record to process.

---

## Summary Checklist for the Implementing Agent

- [ ] Add `_refund_advance_after_failure(adv, sms_message)` helper before `_confirm_booking_after_advance`
- [ ] Replace `_confirm_booking_after_advance` with the version that calls `_refund_advance_after_failure` on all failure paths
- [ ] Add zero-amount guard in `patient_book_submit` (FIX 2) before the `create_advance_record` call
- [ ] In `_expire_stale_advances`, call `_pop_booking_intent_fallback(adv["advance_id"])` (not `pop_booking_intent`) when expiring an advance (FIX 3)
- [ ] (Optional) Add `payments_configured()` bypass block in `patient_book_submit` (FIX 4)
- [ ] (Optional) Set `advance_amount = 0.0` for follow-up visits in `patient_book_submit` (FIX 5) — this composes with FIX 2 automatically
- [ ] (Optional) Add `get_advances_needing_attention()` helper and pass result to receptionist dashboard template (FIX 6)
- [ ] Verify: no new imports needed — `initiate_refund` is already imported inside functions using `from payment_service import initiate_refund`, `pop_booking_intent` / `_pop_booking_intent_fallback` already exist in scope
- [ ] Verify: `payments_configured` is already imported at the top of `app.py` from `payment_service`
- [ ] Do not touch: `payment_webhook_advance`, `patient_cancel_appointment`, `reception_reject_request`, `generate_bill`, the noshow handler — these are correct as-is