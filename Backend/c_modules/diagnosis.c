#include "common.h"

int generateDiagnosisId() {
    FILE *fp = fopen(DIAGNOSIS_FILE, "r");
    int count = 0;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            count++;
        }
        fclose(fp);
    }

    return count + 1;
}

int getPatientById(int patient_id, struct Patient *p) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) {
        return 0;
    }

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        strcpy(buffer, line);

        char *token = strtok(buffer, "|");
        if (token == NULL) continue;
        p->id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->name, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        p->age = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->gender, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->phone, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->address, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->symptoms, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->visit_type, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p->priority, token);

        token = strtok(NULL, "\n");
        if (token == NULL) continue;
        strcpy(p->department, token);

        if (p->id == patient_id) {
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

void printPatientHistory(int patient_id) {
    struct Patient p;

    if (!getPatientById(patient_id, &p)) {
        printf("PatientNotFound");
        return;
    }

    printf("PATIENT|%d|%s|%d|%s|%s|%s|%s|%s|%s|%s\n",
        p.id,
        p.name,
        p.age,
        p.gender,
        p.phone,
        p.address,
        p.symptoms,
        p.visit_type,
        p.priority,
        p.department
    );

    FILE *fp = fopen(DIAGNOSIS_FILE, "r");
    char line[MAX_LINE];
    int found = 0;

    if (fp == NULL) {
        printf("NO_DIAGNOSIS\n");
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        struct Diagnosis d;
        char buffer[MAX_LINE];
        strcpy(buffer, line);

        char *token = strtok(buffer, "|");
        if (token == NULL) continue;
        d.record_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        d.patient_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        d.doctor_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(d.date, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(d.diagnosis, token);

        token = strtok(NULL, "\n");
        if (token == NULL) continue;
        strcpy(d.prescription, token);

        if (d.patient_id == patient_id) {
            printf("DIAGNOSIS|%d|%d|%d|%s|%s|%s\n",
                d.record_id,
                d.patient_id,
                d.doctor_id,
                d.date,
                d.diagnosis,
                d.prescription
            );
            found = 1;
        }
    }

    fclose(fp);

    if (!found) {
        printf("NO_DIAGNOSIS\n");
    }
}

void addDiagnosis(char *input) {
    FILE *fp = fopen(DIAGNOSIS_FILE, "a");
    if (fp == NULL) {
        printf("Error");
        return;
    }

    struct Diagnosis d;
    d.record_id = generateDiagnosisId();

    char buffer[MAX_LINE];
    strcpy(buffer, input);

    char *token = strtok(buffer, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    d.patient_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    d.doctor_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    strcpy(d.date, token);

    token = strtok(NULL, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    strcpy(d.diagnosis, token);

    token = strtok(NULL, "\n");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    strcpy(d.prescription, token);

    fprintf(fp, "%d|%d|%d|%s|%s|%s\n",
        d.record_id,
        d.patient_id,
        d.doctor_id,
        d.date,
        d.diagnosis,
        d.prescription
    );

    fclose(fp);

    printf("%d|%d|%d", d.record_id, d.patient_id, d.doctor_id);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Invalid Input");
        return 1;
    }

    if (strcmp(argv[1], "history") == 0 && argc == 3) {
        int patient_id = atoi(argv[2]);
        printPatientHistory(patient_id);
    }
    else {
        addDiagnosis(argv[1]);
    }

    return 0;
}