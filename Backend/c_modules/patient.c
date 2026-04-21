#include "common.h"

int generate_id(const char *filename) {
    FILE *fp;
    int count = 0;
    char line[MAX_LINE];

    fp = fopen(filename, "r");

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            count++;
        }
        fclose(fp);
    }

    return count + 1;
}

int parsePatientLine(char *line, struct Patient *p) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);

    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    p->id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->name, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    p->age = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->gender, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->phone, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->address, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->symptoms, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->visit_type, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(p->priority, token);

    token = strtok(NULL, "\n");
    if (token == NULL) return 0;
    strcpy(p->department, token);

    return 1;
}

void printPatient(struct Patient p) {
    printf("PATIENT|%d|%s|%d|%s|%s|%s|%s|%s|%s|%s",
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
}

int searchByPhone(const char *phone, struct Patient *result) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Patient p;

        if (!parsePatientLine(line, &p)) continue;

        if (strcmp(p.phone, phone) == 0) {
            *result = p;
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

void parse_patient_data(const char *data, struct Patient *p) {
    char buffer[MAX_LINE];
    char *token;

    strncpy(buffer, data, sizeof(buffer) - 1);
    buffer[sizeof(buffer) - 1] = '\0';

    token = strtok(buffer, "|");
    if (token != NULL) strcpy(p->name, token);

    token = strtok(NULL, "|");
    if (token != NULL) p->age = atoi(token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->gender, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->phone, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->address, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->symptoms, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->visit_type, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->priority, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(p->department, token);
}

void addPatient(const char *input) {
    struct Patient p;
    struct Patient existing;
    FILE *fp;

    parse_patient_data(input, &p);
    if (strlen(p.name) == 0 || strlen(p.phone) == 0 || p.age <= 0 || strlen(p.department) == 0) {
        printf("Error|InvalidPatientData");
        return;
    }

    if (strlen(p.phone) != 10) {
        printf("Error|InvalidPhone");
        return;
    }

    for (int i = 0; p.phone[i] != '\0'; i++) {
        if (p.phone[i] < '0' || p.phone[i] > '9') {
            printf("Error|InvalidPhone");
            return;
        }
    }

    if (searchByPhone(p.phone, &existing)) {
        printf("%d|%s|%s", existing.id, existing.visit_type, existing.priority);
        return;
    }

    p.id = generate_id(PATIENT_FILE);

    fp = fopen(PATIENT_FILE, "a");

    if (fp == NULL) {
        printf("Error opening file\n");
        return;
    }

    fprintf(fp, "%d|%s|%d|%s|%s|%s|%s|%s|%s|%s\n",
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

    fclose(fp);

    printf("%d|%s|%s", p.id, p.visit_type, p.priority);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Invalid Input\n");
        return 1;
    }

    if (strcmp(argv[1], "search") == 0 && argc == 3) {
        struct Patient p;

        if (searchByPhone(argv[2], &p)) {
            printPatient(p);
            return 0;
        }

        printf("PatientNotFound");
        return 1;
    }

    addPatient(argv[1]);
    return 0;
}
