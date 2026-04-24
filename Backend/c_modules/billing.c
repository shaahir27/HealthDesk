#include "common.h"

#define MAX_BILLS 2000
#define MAX_BILL_ITEMS 10

int generateBillId() {
    FILE *fp = fopen(BILLING_FILE, "r");
    int max_id = 999;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            char buffer[MAX_LINE];
            char *token;

            strcpy(buffer, line);
            token = strtok(buffer, "|");
            if (token != NULL && atoi(token) > max_id) {
                max_id = atoi(token);
            }
        }
        fclose(fp);
    }

    return max_id + 1;
}

void formatDateForPrint(const char *iso_date, char *out) {
    int y, m, d;
    if (sscanf(iso_date, "%d-%d-%d", &y, &m, &d) == 3) {
        sprintf(out, "%02d-%02d-%04d", d, m, y);
    } else {
        strcpy(out, iso_date);
    }
}

int addItem(struct BillingItem *items, int *count, const char *description, float amount) {
    if (*count >= MAX_BILL_ITEMS) return 0;

    strcpy(items[*count].description, description);
    items[*count].amount = amount;
    (*count)++;
    return 1;
}

float totalItems(struct BillingItem *items, int count) {
    float total = 0;
    int i;
    for (i = 0; i < count; i++) total += items[i].amount;
    return total;
}

int parsePatientLine(char *line, struct Patient *p) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);

    token = strtok(buffer, "|");
    if (!token) return 0;
    p->id = atoi(token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->name, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    p->age = atoi(token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->gender, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->phone, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->address, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->symptoms, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->visit_type, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(p->priority, token);

    token = strtok(NULL, "\n");
    if (!token) return 0;
    strcpy(p->department, token);

    return 1;
}

int parseDoctorLine(char *line, struct Doctor *d) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);

    token = strtok(buffer, "|");
    if (!token) return 0;
    d->id = atoi(token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(d->name, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(d->specialization, token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    d->experience = atoi(token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    strcpy(d->daily_status, token);

    token = strtok(NULL, "\n");
    if (!token) return 0;
    strcpy(d->current_status, token);

    return 1;
}

int getPatientById(int patient_id, struct Patient *p) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (!parsePatientLine(line, p)) continue;

        if (p->id == patient_id) {
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int getDoctorById(int doctor_id, struct Doctor *d) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (!parseDoctorLine(line, d)) continue;

        if (d->id == doctor_id) {
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

void printBill(
    int bill_id, const char *date, int patient_id, const char *name, int age, const char *gender,
    const char *doctor, const char *department, struct BillingItem *items, int item_count,
    float total, const char *payment_status
) {
    int i;
    char printable_date[20];
    formatDateForPrint(date, printable_date);

    printf("=========================================================\n");
    printf("                    HEALTHDESK CLINIC\n");
    printf("=========================================================\n");
    printf("Address: Chennai\n");
    printf("Phone: +91 XXXXX XXXXX\n\n");
    printf("---------------------------------------------------------\n");
    printf("Bill ID   : %d\n", bill_id);
    printf("Date      : %s\n", printable_date);
    printf("---------------------------------------------------------\n");
    printf("Patient ID: %d\n", patient_id);
    printf("Name      : %s\n", name);
    printf("Age       : %d\n", age);
    printf("Gender    : %s\n\n", gender);
    printf("Doctor    : %s\n", doctor);
    printf("Department: %s\n", department);
    printf("---------------------------------------------------------\n\n");
    printf("                   BILL DETAILS\n");
    printf("---------------------------------------------------------\n");
    printf("%-28s %s\n", "Description", "Amount (Rs)");
    printf("---------------------------------------------------------\n");
    for (i = 0; i < item_count; i++) {
        printf("%-28s %.0f\n", items[i].description, items[i].amount);
    }
    printf("\n---------------------------------------------------------\n");
    printf("TOTAL                        Rs %.0f\n", total);
    printf("---------------------------------------------------------\n\n");
    printf("Payment Status: %s\n\n", payment_status);
    printf("---------------------------------------------------------\n");
    printf("         Thank you for visiting HealthDesk\n");
    printf("---------------------------------------------------------\n");
}

void saveBill(
    int bill_id, const char *date, int patient_id, const char *name, int age, const char *gender,
    const char *doctor, const char *department, float consultation, float medicines,
    float lab_tests, float total, const char *payment_status
) {
    FILE *fp = fopen(BILLING_FILE, "a");
    if (!fp) return;

    fprintf(fp, "%d|%s|%d|%s|%d|%s|%s|%s|%.0f|%.0f|%.0f|%.0f|%s\n",
        bill_id, date, patient_id, name, age, gender, doctor, department,
        consultation, medicines, lab_tests, total, payment_status
    );

    fclose(fp);
}

void generateBill(char *input) {
    char buffer[MAX_LINE];
    char *token;
    int bill_id;
    int patient_id;
    char name[MAX_NAME];
    int age;
    char gender[MAX_SMALL];
    char doctor[MAX_NAME];
    char department[MAX_NAME];
    char date[20];
    float consultation;
    float medicines;
    float lab_tests;
    char payment_status[MAX_SMALL];
    struct BillingItem items[MAX_BILL_ITEMS];
    int item_count = 0;
    float total;

    strcpy(buffer, input);

    token = strtok(buffer, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    patient_id = atoi(token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(name, token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    age = atoi(token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(gender, token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(doctor, token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(department, token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(date, token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    consultation = (float)atof(token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    medicines = (float)atof(token);

    token = strtok(NULL, "|");
    if (!token) { printf("Error|InvalidInput"); return; }
    lab_tests = (float)atof(token);

    token = strtok(NULL, "\n");
    if (!token) { printf("Error|InvalidInput"); return; }
    strcpy(payment_status, token);

    addItem(items, &item_count, "Consultation Fee", consultation);
    addItem(items, &item_count, "Medicines", medicines);
    addItem(items, &item_count, "Lab Tests", lab_tests);

    total = totalItems(items, item_count);
    bill_id = generateBillId();

    printBill(
        bill_id, date, patient_id, name, age, gender, doctor, department,
        items, item_count, total, payment_status
    );

    saveBill(
        bill_id, date, patient_id, name, age, gender, doctor, department,
        consultation, medicines, lab_tests, total, payment_status
    );
}

void generateAutoBill(int patient_id, int doctor_id, const char *date) {
    struct Patient p;
    struct Doctor d;
    int bill_id;
    float consultation = 500;
    float medicines = 0;
    float lab_tests = 0;
    float total = consultation + medicines + lab_tests;

    if (!getPatientById(patient_id, &p)) {
        printf("Error|PatientNotFound");
        return;
    }

    if (!getDoctorById(doctor_id, &d)) {
        printf("Error|DoctorNotFound");
        return;
    }

    bill_id = generateBillId();

    saveBill(
        bill_id,
        date,
        p.id,
        p.name,
        p.age,
        p.gender,
        d.name,
        p.department,
        consultation,
        medicines,
        lab_tests,
        total,
        "PENDING"
    );

    printf("AUTO_BILL|%d|%d|%d|%.0f|PENDING", bill_id, patient_id, doctor_id, total);
}

void listBills() {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];
    if (!fp) return;

    while (fgets(line, sizeof(line), fp)) {
        printf("%s", line);
    }
    fclose(fp);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Error|InvalidInput");
        return 1;
    }

    if (strcmp(argv[1], "list") == 0) {
        listBills();
    } else if (strcmp(argv[1], "auto") == 0 && argc == 5) {
        generateAutoBill(atoi(argv[2]), atoi(argv[3]), argv[4]);
    } else {
        generateBill(argv[1]);
    }

    return 0;
}
