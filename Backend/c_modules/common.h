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

// File paths
#define DOCTOR_FILE "Backend/data/doctors.txt"
#define PATIENT_FILE "Backend/data/patients.txt"
#define QUEUE_FILE "Backend/data/queue.txt"
#define DIAGNOSIS_FILE "Backend/data/diagnosis.txt"
#define BILLING_FILE "Backend/data/billing.txt"
// STRUCT DECLARATIONS

struct Patient;
struct Doctor;
struct Queue;
struct Diagnosis;
struct Billing;

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

// Billing
struct Billing {
    int bill_id;
    int patient_id;
    float total;
    char status[MAX_SMALL];   // Paid / Pending
};

#endif