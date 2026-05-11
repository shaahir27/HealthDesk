import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import app


class HealthDeskSmokeFlows(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        app.send_sms = lambda phone, message: True
        app._otp_store.clear()
        self.client = app.app.test_client()

    def seed_csrf(self, token="test-token"):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
        return token

    def login_reception(self):
        token = self.seed_csrf()
        return self.client.post(
            "/login",
            data={
                "username": "reception",
                "password": "admin123",
                "_csrf_token": token,
            },
        )

    def test_patient_resend_otp_is_public_ajax_flow(self):
        token = self.seed_csrf()
        response = self.client.post(
            "/patient/resend-otp",
            data={"phone": "9000000006", "_csrf_token": token},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertTrue(response.get_json()["ok"])

    def test_reception_pages_load_after_login(self):
        login = self.login_reception()
        self.assertEqual(login.status_code, 302)

        for path in (
            "/receptionist_dashboard",
            "/reception",
            "/appointments",
            "/queue",
            "/doctors",
            "/billing",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_reception_department_change_drops_stale_doctor(self):
        self.assertEqual(self.login_reception().status_code, 302)

        response = self.client.get(
            "/reception?patient_id=7&phone=9000000007&department=General&doctor_id=6"
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="rcxDepartmentSelect"', html)
        self.assertIn('id="rcxDoctorSelect"', html)
        self.assertIn('data-selected-doctor=""', html)
        self.assertNotIn('value="6" selected', html)

    def test_appointments_department_change_drops_stale_doctor(self):
        self.assertEqual(self.login_reception().status_code, 302)

        response = self.client.get("/appointments?department=General&doctor_id=6")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="apxDepartmentSelect"', html)
        self.assertIn('data-selected-doctor="1"', html)
        self.assertNotIn('value="6" selected', html)

    def test_existing_vitals_form_uses_update_copy(self):
        self.assertEqual(self.login_reception().status_code, 302)

        response = self.client.get("/reception/vitals/add?patient_id=6&doctor_id=8&token=13")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Update Vitals", html)
        self.assertIn("save an updated backend record", html)

    def test_queue_existing_vitals_button_uses_update_label(self):
        with app.app.test_request_context("/queue"):
            html = app.render_template(
                "queue_panels.html",
                queue_groups=[
                    {
                        "doctor_id": 1,
                        "doctor_name": "Dr Test",
                        "department": "General",
                        "patients": [
                            {
                                "token": 1,
                                "patient_id": 6,
                                "priority": "Normal",
                                "name": "Patient Test",
                                "symptoms": "Fever",
                                "outstanding_amount": 0,
                                "vitals_url": "/reception/vitals/add",
                                "vitals_recorded": True,
                            }
                        ],
                    }
                ],
                waiting_count=1,
                completed_count=0,
            )

        self.assertIn("Update Vitals", html)

    def test_future_unavailable_period_blocks_slots_until_expiry(self):
        tomorrow = (app.date.today() + timedelta(days=1)).isoformat()
        meta = {
            "4": {
                "expires_on": tomorrow,
                "daily_status": "Unavailable",
                "current_status": "Unavailable",
            }
        }

        with patch("app.load_doctor_status_meta", return_value=meta):
            self.assertTrue(app.doctor_is_blocked_for_date(4, tomorrow))

    def test_unavailable_period_does_not_block_after_expiry(self):
        after_expiry = (app.date.today() + timedelta(days=2)).isoformat()
        meta = {
            "4": {
                "expires_on": app.date.today().isoformat(),
                "daily_status": "Unavailable",
                "current_status": "Unavailable",
            }
        }

        with patch("app.load_doctor_status_meta", return_value=meta), \
             patch("app.run_doctor_command", return_value=SimpleNamespace(returncode=0, stdout="0")):
            self.assertFalse(app.doctor_is_blocked_for_date(4, after_expiry))

    def test_vitals_serialization_keeps_lifestyle_fields(self):
        vitals = {
            "vitals_id": 1,
            "patient_id": 6,
            "doctor_id": 1,
            "token": 10,
            "recorded_at": "2026-05-07T10:00:00",
            "temperature": "98.6",
            "bp_systolic": "120",
            "bp_diastolic": "80",
            "pulse_rate": "72",
            "weight": "68",
            "oxygen_level": "98",
            "sugar_level": "110",
            "allergy_conditions": "",
            "health_conditions": "",
            "notes": "",
            "smoking_habit": "Non-smoker",
            "drinking_habit": "Non-drinker",
        }

        parsed = app.parse_vitals_line(app.serialize_vitals_record(vitals))

        self.assertEqual(parsed["smoking_habit"], "Non-smoker")
        self.assertEqual(parsed["drinking_habit"], "Non-drinker")

    def test_vitals_c_validation_rejects_unrealistic_temperature(self):
        vitals = {
            "vitals_id": 1,
            "patient_id": 6,
            "doctor_id": 1,
            "token": 10,
            "recorded_at": "2026-05-07T10:00:00",
            "temperature": "180",
            "bp_systolic": "120",
            "bp_diastolic": "80",
            "pulse_rate": "72",
            "weight": "68",
            "oxygen_level": "98",
            "sugar_level": "110",
            "allergy_conditions": "",
            "health_conditions": "",
            "notes": "",
            "smoking_habit": "Non-smoker",
            "drinking_habit": "Non-drinker",
        }

        ok, message = app.validate_vitals_record(vitals)

        self.assertFalse(ok)
        self.assertIn("Temperature", message)


if __name__ == "__main__":
    unittest.main()
