#ifndef COMMON_H
#define COMMON_H

// STANDARD LIBRARIES

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// CONSTANTS

// Buffer sizes
#define MAX_NAME 50
#define MAX_PHONE 20
#define MAX_ADDRESS 200
#define MAX_TEXT 200
#define MAX_SMALL 20
#define MAX_LINE 500
#define MAX_REASON 221
#define MAX_TIMESTAMP 40

// File paths
#define DOCTOR_FILE "Backend/data/doctors.txt"
#define PATIENT_FILE "Backend/data/patients.txt"
#define QUEUE_FILE "Backend/data/queue.txt"
#define DIAGNOSIS_FILE "Backend/data/diagnosis.txt"
#define BILLING_FILE "Backend/data/billing.txt"
#define APPOINTMENT_FILE "Backend/data/appointment.txt"
#define PENDING_APPOINTMENTS_FILE "Backend/data/pending_appointments.txt"
#define NEW_PATIENT_REQUESTS_FILE "Backend/data/new_patient_requests.txt"
#define USER_FILE "Backend/data/users.txt"
#define ADVANCE_FILE "Backend/data/advances.txt"
#define BOOKING_INTENT_FILE "Backend/data/pending_booking_intents.txt"
// STRUCT DECLARATIONS

struct Patient;
struct Doctor;
struct Queue;
struct Diagnosis;
struct Appointment;
struct BillingItem;
struct PendingAppointmentRequest;
struct NewPatientRequest;
typedef struct Advance Advance;
typedef struct BookingIntent BookingIntent;
typedef struct UserAccount UserAccount;

// STRUCT DEFINITIONS

// Patient
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

// Doctor
struct Doctor {
    int id;
    char name[MAX_NAME];
    char specialization[MAX_NAME];
    int experience;
    char daily_status[MAX_SMALL];   // Available / Off
    char current_status[MAX_SMALL]; // Free / Busy
};

// Queue
struct QueueNode {
    int token;
    int patient_id;
    int doctor_id;
    char priority[MAX_SMALL];
    char status[MAX_SMALL];   // Waiting / Completed
    struct QueueNode* next;
};

// Diagnosis
struct Diagnosis {
    int record_id;
    int patient_id;
    int doctor_id;
    char date[20];
    char diagnosis[MAX_TEXT];
    char prescription[MAX_TEXT];
};

// Appointment
struct Appointment {
    int appointment_id;
    int patient_id;
    int doctor_id;
    char date[20];
    char time_slot[20];
    char status[MAX_SMALL];   // Booked / Completed / Cancelled / Rescheduled / No-show
};

// Billing item
struct BillingItem {
    char description[MAX_NAME];
    float amount;
};

// Existing patient portal appointment request
typedef struct PendingAppointmentRequest {
    int request_id;
    int patient_id;
    int doctor_id;
    char requested_date[20];
    char requested_slot[32];
    char reason[MAX_REASON];
    char visit_type[32];
    char status[32];
    char submitted_at[MAX_TIMESTAMP];
    char expires_at[MAX_TIMESTAMP];
    char receptionist_note[MAX_REASON];
    int appointment_id;
    struct PendingAppointmentRequest *next;
} PendingAppointmentRequest;

// First-time patient portal appointment request
typedef struct NewPatientRequest {
    int request_id;
    char name[100];
    char age[8];
    char gender[24];
    char phone[20];
    char address[MAX_REASON];
    char department[80];
    int doctor_id;
    char requested_date[20];
    char requested_slot[32];
    char reason[MAX_REASON];
    char visit_type[32];
    char priority[32];
    char status[32];
    char submitted_at[MAX_TIMESTAMP];
    char expires_at[MAX_TIMESTAMP];
    char receptionist_note[MAX_REASON];
    int patient_id;
    int appointment_id;
    struct NewPatientRequest *next;
} NewPatientRequest;

// Advance payment record
typedef struct Advance {
    int    advance_id;
    int    patient_id;
    int    appointment_id;
    int    doctor_id;
    char   appointment_date[20];
    float  amount;
    char   status[32];              // PENDING_PAYMENT | PAID | EXPIRED | SETTLED | REFUNDED
    char   razorpay_order_id[84];
    char   razorpay_payment_id[84];
    char   created_at[MAX_TIMESTAMP];
    char   paid_at[MAX_TIMESTAMP];
    char   settled_at[MAX_TIMESTAMP];
    int    pending_request_id;
    struct Advance *next;
} Advance;

// Booking intent (links an advance to a pending slot request)
typedef struct BookingIntent {
    int  advance_id;
    int  doctor_id;
    char requested_date[20];
    char requested_slot[32];
    char reason[MAX_REASON];
    char visit_type[32];
    char triage[32];
    struct BookingIntent *next;
} BookingIntent;

// Staff / doctor user account
typedef struct UserAccount {
    int  id;
    char username[MAX_NAME];
    char password[280];    // werkzeug scrypt hash is ~200 chars; 280 is safe
    char role[MAX_SMALL];
    int  doctor_id;
    struct UserAccount *next;
} UserAccount;

#endif
