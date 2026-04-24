#include "common.h"

struct DiagnosisNode {
    struct Diagnosis data;
    struct DiagnosisNode* next;
};

int parseDiagnosisLine(char *line, struct Diagnosis *d);

void push(struct DiagnosisNode** top, struct Diagnosis data) {
    struct DiagnosisNode* newNode = malloc(sizeof(struct DiagnosisNode));
    if (newNode == NULL) return;

    newNode->data = data;
    newNode->next = *top;
    *top = newNode;
}

struct Diagnosis* peek(struct DiagnosisNode* top) {
    if (top == NULL) return NULL;
    return &top->data;
}

int pop(struct DiagnosisNode** top, struct Diagnosis* out) {
    struct DiagnosisNode* temp;

    if (*top == NULL) return 0;

    temp = *top;
    *out = temp->data;
    *top = temp->next;
    free(temp);

    return 1;
}

void freeStack(struct DiagnosisNode** top) {
    struct Diagnosis temp;

    while (pop(top, &temp)) {
    }
}

int generateDiagnosisId() {
    FILE *fp = fopen(DIAGNOSIS_FILE, "r");
    int max_id = 0;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            struct Diagnosis d;
            if (parseDiagnosisLine(line, &d) && d.record_id > max_id) {
                max_id = d.record_id;
            }
        }
        fclose(fp);
    }

    return max_id + 1;
}

int parseDiagnosisLine(char *line, struct Diagnosis *d) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);

    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    d->record_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    d->patient_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    d->doctor_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(d->date, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(d->diagnosis, token);

    token = strtok(NULL, "\n");
    if (token == NULL) return 0;
    strcpy(d->prescription, token);

    return 1;
}

int getPatientById(int patient_id, struct Patient *p) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) {
        return 0;
    }

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;

        strcpy(buffer, line);

        token = strtok(buffer, "|");
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

int loadDiagnosisStack(int patient_id, struct DiagnosisNode** top) {
    FILE *fp = fopen(DIAGNOSIS_FILE, "r");
    char line[MAX_LINE];
    int found = 0;

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Diagnosis d;

        if (!parseDiagnosisLine(line, &d)) continue;

        if (d.patient_id == patient_id) {
            push(top, d);
            found = 1;
        }
    }

    fclose(fp);
    return found;
}

void printDiagnosis(struct Diagnosis d) {
    printf("DIAGNOSIS|%d|%d|%d|%s|%s|%s\n",
        d.record_id,
        d.patient_id,
        d.doctor_id,
        d.date,
        d.diagnosis,
        d.prescription
    );
}

void printPatientHistory(int patient_id) {
    struct Patient p;
    struct DiagnosisNode* top = NULL;
    struct Diagnosis d;
    int found;

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

    found = loadDiagnosisStack(patient_id, &top);
    if (!found) {
        printf("NO_DIAGNOSIS\n");
        return;
    }

    while (pop(&top, &d)) {
        printDiagnosis(d);
    }
}

void printLatestDiagnosis(int patient_id) {
    struct DiagnosisNode* top = NULL;
    struct Diagnosis* latest;

    if (!loadDiagnosisStack(patient_id, &top)) {
        printf("NO_DIAGNOSIS");
        return;
    }

    latest = peek(top);
    if (latest != NULL) {
        printDiagnosis(*latest);
    }

    freeStack(&top);
}

void addDiagnosis(char *input) {
    FILE *fp = fopen(DIAGNOSIS_FILE, "a");
    struct Diagnosis d;
    char buffer[MAX_LINE];
    char *token;

    if (fp == NULL) {
        printf("Error");
        return;
    }

    d.record_id = generateDiagnosisId();
    strcpy(buffer, input);

    token = strtok(buffer, "|");
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
        printPatientHistory(atoi(argv[2]));
    }
    else if (strcmp(argv[1], "latest") == 0 && argc == 3) {
        printLatestDiagnosis(atoi(argv[2]));
    }
    else {
        addDiagnosis(argv[1]);
    }

    return 0;
}
