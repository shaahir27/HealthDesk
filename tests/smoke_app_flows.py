import unittest

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
        token = self.seed_csrf()
        login = self.client.post(
            "/login",
            data={
                "username": "reception",
                "password": "admin123",
                "_csrf_token": token,
            },
        )
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
