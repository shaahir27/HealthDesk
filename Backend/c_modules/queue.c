#include "common.h"

int generateToken() {
    FILE *fp = fopen(QUEUE_FILE, "r");
    int count = 0;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) count++;
        fclose(fp);
    }

    return count + 1;
}

int getPatientDetails(int patient_id, char *department, char *priority) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {
        char *token = strtok(line, "|");
        if (!token) continue;

        int id = atoi(token);

        if (id == patient_id) {
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");
            strtok(NULL, "|");

            token = strtok(NULL, "|");
            strcpy(priority, token);

            token = strtok(NULL, "\n");
            strcpy(department, token);

            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int findDoctor(char *department) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {

        struct Doctor d;
        char *token = strtok(line, "|");

        if (!token) continue;
        d.id = atoi(token);

        token = strtok(NULL, "|");
        strcpy(d.name, token);

        token = strtok(NULL, "|");
        strcpy(d.specialization, token);

        token = strtok(NULL, "|");
        d.experience = atoi(token);

        token = strtok(NULL, "|");
        strcpy(d.daily_status, token);

        token = strtok(NULL, "\n");
        strcpy(d.current_status, token);

        if (strcmp(d.specialization, department) == 0 &&
            strcmp(d.daily_status, "Available") == 0 &&
            strcmp(d.current_status, "Free") == 0) {
            fclose(fp);
            return d.id;
        }
    }

    fclose(fp);
    return 0;
}

void updateDoctorBusy(int doctor_id) {

    FILE *fp = fopen(DOCTOR_FILE, "r");
    FILE *temp = fopen("../data/temp.txt", "w");

    char line[MAX_LINE];

    while (fgets(line, sizeof(line), fp)) {

        struct Doctor d;
        char buffer[MAX_LINE];
        strcpy(buffer, line);

        char *token = strtok(buffer, "|");
        d.id = atoi(token);

        token = strtok(NULL, "|");
        strcpy(d.name, token);

        token = strtok(NULL, "|");
        strcpy(d.specialization, token);

        token = strtok(NULL, "|");
        d.experience = atoi(token);

        token = strtok(NULL, "|");
        strcpy(d.daily_status, token);

        token = strtok(NULL, "\n");
        strcpy(d.current_status, token);

        if (d.id == doctor_id) {
            strcpy(d.current_status, "Busy");
        }

        fprintf(temp, "%d|%s|%s|%d|%s|%s\n",
            d.id,
            d.name,
            d.specialization,
            d.experience,
            d.daily_status,
            d.current_status
        );
    }

    fclose(fp);
    fclose(temp);

    remove(DOCTOR_FILE);
    rename("../data/temp.txt", DOCTOR_FILE);
}

void addToQueue(struct QueueNode q) {
    FILE *fp = fopen(QUEUE_FILE, "a");

    fprintf(fp, "%d|%d|%d|%s|%s\n",
        q.token,
        q.patient_id,
        q.doctor_id,
        q.priority,
        q.status
    );

    fclose(fp);
}

int main(int argc, char *argv[]) {

    if (argc < 2) {
        printf("Invalid Input");
        return 1;
    }

    int patient_id = atoi(argv[1]);

    char department[MAX_NAME];
    char priority[MAX_SMALL];

    if (!getPatientDetails(patient_id, department, priority)) {
        printf("Error|PatientNotFound");
        return 1;
    }

    int doctor_id = findDoctor(department);

    if(doctor_id == 0) {
        doctor_id = -1;
    }

    if (doctor_id != 0) {
        updateDoctorBusy(doctor_id);
    }

    int token = generateToken();

    struct QueueNode q;
    q.token = token;
    q.patient_id = patient_id;
    q.doctor_id = doctor_id;
    strcpy(q.priority, priority);
    strcpy(q.status, "Waiting");

    addToQueue(q);

    printf("%d|%d|%s", token, doctor_id, priority);

    return 0;
}