#include "common.h"

int generateToken() {
    FILE *fp;
    int count = 0;
    char line[MAX_LINE];

    fp = fopen(QUEUE_FILE, "r");

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) count++;
        fclose(fp);
    }

    return count + 1;
}

int getPatientPriority(int patient_id, char *priority) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;
        int id;

        strcpy(buffer, line);

        token = strtok(buffer, "|");
        if (token == NULL) continue;
        id = atoi(token);

        if (id == patient_id) {
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");

            token = strtok(NULL, "|");
            if (token == NULL) {
                fclose(fp);
                return 0;
            }

            strcpy(priority, token);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int getPatientDepartment(int patient_id, char *department) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Patient p;
        char buffer[MAX_LINE];
        char *token;

        strcpy(buffer, line);
        token = strtok(buffer, "|");
        if (token == NULL) continue;
        p.id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.name, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        p.age = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.gender, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.phone, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.address, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.symptoms, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.visit_type, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(p.priority, token);

        token = strtok(NULL, "\n");
        if (token == NULL) continue;
        strcpy(p.department, token);

        if (p.id == patient_id) {
            strcpy(department, p.department);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int parseDoctorLine(char *line, struct Doctor *d) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);
    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    d->id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(d->name, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(d->specialization, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    d->experience = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(d->daily_status, token);

    token = strtok(NULL, "\n");
    if (token == NULL) return 0;
    strcpy(d->current_status, token);

    return 1;
}

int findAvailableDoctor(char *department) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return -1;

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;
        if (!parseDoctorLine(line, &d)) continue;

        if (strcmp(d.specialization, department) == 0 &&
            strcmp(d.daily_status, "Available") == 0 &&
            strcmp(d.current_status, "Free") == 0) {
            fclose(fp);
            return d.id;
        }
    }

    fclose(fp);
    return -1;
}

int enqueue(struct QueueNode q) {
    FILE *fp = fopen(QUEUE_FILE, "a");
    FILE *check;
    long size;
    int last_char;

    if (fp == NULL) {
        printf("Error|CannotOpenQueue");
        return 0;
    }

    check = fopen(QUEUE_FILE, "rb");
    if (check != NULL) {
        fseek(check, 0, SEEK_END);
        size = ftell(check);
        if (size > 0) {
            fseek(check, -1, SEEK_END);
            last_char = fgetc(check);
            if (last_char != '\n') {
                fprintf(fp, "\n");
            }
        }
        fclose(check);
    }

    fprintf(fp, "%d|%d|%d|%s|%s\n",
        q.token,
        q.patient_id,
        q.doctor_id,
        q.priority,
        q.status
    );

    fclose(fp);
    return 1;
}

int main(int argc, char *argv[]) {
    int patient_id;
    int token;
    int doctor_id = -1;
    char priority[MAX_SMALL];
    char department[MAX_NAME];
    struct QueueNode q;

    if (argc < 2) {
        printf("Invalid Input");
        return 1;
    }

    patient_id = atoi(argv[1]);

    if (argc >= 4) {
        strcpy(priority, argv[3]);
    } else if (!getPatientPriority(patient_id, priority)) {
        printf("Error|PatientNotFound");
        return 1;
    }

    token = generateToken();
    if (getPatientDepartment(patient_id, department)) {
        doctor_id = findAvailableDoctor(department);
    }

    q.token = token;
    q.patient_id = patient_id;
    q.doctor_id = doctor_id;
    strcpy(q.priority, priority);
    strcpy(q.status, "Waiting");
    q.next = NULL;

    if (!enqueue(q)) {
        return 1;
    }

    printf("%d|%d|%s", token, doctor_id, priority);
    return 0;
}
