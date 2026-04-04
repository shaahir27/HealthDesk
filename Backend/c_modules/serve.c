#include "common.h"

int countQueue() {
    FILE *fp = fopen(QUEUE_FILE, "r");
    int count = 0;
    char line[MAX_LINE];

    if (fp) {
        while (fgets(line, sizeof(line), fp)) count++;
        fclose(fp);
    }

    return count;
}

struct QueueNode* loadQueue(int n) {
    FILE *fp = fopen(QUEUE_FILE, "r");
    if (!fp) return NULL;

    struct QueueNode *arr = malloc(n * sizeof(struct QueueNode));
    char line[MAX_LINE];
    int i = 0;

    while (fgets(line, sizeof(line), fp) && i < n) {

        char *token = strtok(line, "|");
        arr[i].token = atoi(token);

        token = strtok(NULL, "|");
        arr[i].patient_id = atoi(token);

        token = strtok(NULL, "|");
        arr[i].doctor_id = atoi(token);

        token = strtok(NULL, "|");
        strcpy(arr[i].priority, token);

        token = strtok(NULL, "\n");
        strcpy(arr[i].status, token);

        i++;
    }

    fclose(fp);
    return arr;
}

void sortQueue(struct QueueNode *arr, int n) {
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (strcmp(arr[j].priority, "Normal") == 0 &&
                strcmp(arr[j+1].priority, "Urgent") == 0) {

                struct QueueNode temp = arr[j];
                arr[j] = arr[j+1];
                arr[j+1] = temp;
            }
        }
    }
}

void updateQueueFile(struct QueueNode *arr, int n) {

    FILE *fp = fopen(QUEUE_FILE, "w");

    for (int i = 0; i < n; i++) {
        fprintf(fp, "%d|%d|%d|%s|%s\n",
            arr[i].token,
            arr[i].patient_id,
            arr[i].doctor_id,
            arr[i].priority,
            arr[i].status
        );
    }

    fclose(fp);
}

void freeDoctor(int doctor_id) {

    FILE *fp = fopen(DOCTOR_FILE, "r");
    FILE *temp = fopen("Backend/data/temp.txt", "w");

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
            strcpy(d.current_status, "Free");
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
    rename("Backend/data/temp.txt", DOCTOR_FILE);
}

int serveNextPatient() {

    int n = countQueue();
    if (n == 0) return 0;

    struct QueueNode *arr = loadQueue(n);
    if (!arr) return 0;

    sortQueue(arr, n);

    int index = -1;

    for (int i = 0; i < n; i++) {
        if (strcmp(arr[i].status, "Waiting") == 0) {
            index = i;
            break;
        }
    }

    if (index == -1) {
        free(arr);
        return 0;
    }

    int doctor_id = arr[index].doctor_id;

    strcpy(arr[index].status, "Completed");

    updateQueueFile(arr, n);

    if (doctor_id != -1) { 
        freeDoctor(doctor_id);
    }

    free(arr);

    return doctor_id;
}

int main() {

    int doctor_id = serveNextPatient();

    if (doctor_id == 0) {
        printf("No Patient");
    } else {
        printf("Served|DoctorFreed");
    }

    return 0;
}