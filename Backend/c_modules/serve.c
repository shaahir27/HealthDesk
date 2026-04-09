#include "common.h"

struct Queue {
    struct QueueNode* front;
    struct QueueNode* rear;
};

void initQueue(struct Queue* q) {
    q->front = q->rear = NULL;
}

void enqueue(struct Queue* q, struct QueueNode data) {
    struct QueueNode* newNode = malloc(sizeof(struct QueueNode));
    *newNode = data;
    newNode->next = NULL;

    if (q->rear == NULL) {
        q->front = q->rear = newNode;
        return;
    }

    q->rear->next = newNode;
    q->rear = newNode;
}

struct QueueNode* dequeue(struct Queue* q) {
    if (q->front == NULL) return NULL;

    struct QueueNode* temp = q->front;
    q->front = q->front->next;

    if (q->front == NULL) q->rear = NULL;

    temp->next = NULL;
    return temp;
}

void loadQueue(struct Queue* urgentQ, struct Queue* normalQ) {
    FILE *fp = fopen(QUEUE_FILE, "r");
    if (!fp) return;

    char line[MAX_LINE];

    while (fgets(line, sizeof(line), fp)) {

        struct QueueNode temp;

        char *token = strtok(line, "|");
        temp.token = atoi(token);

        token = strtok(NULL, "|");
        temp.patient_id = atoi(token);

        token = strtok(NULL, "|");
        temp.doctor_id = atoi(token);

        token = strtok(NULL, "|");
        strcpy(temp.priority, token);

        token = strtok(NULL, "\n");
        strcpy(temp.status, token);

        temp.next = NULL;

        if (strcmp(temp.priority, "Urgent") == 0) {
            enqueue(urgentQ, temp);
        } else {
            enqueue(normalQ, temp);
        }
    }

    fclose(fp);
}

void updateQueueFile(struct Queue* urgentQ, struct Queue* normalQ) {
    FILE *fp = fopen(QUEUE_FILE, "w");

    struct QueueNode* temp = urgentQ->front;
    while (temp != NULL) {
        fprintf(fp, "%d|%d|%d|%s|%s\n",
            temp->token,
            temp->patient_id,
            temp->doctor_id,
            temp->priority,
            temp->status
        );
        temp = temp->next;
    }

    temp = normalQ->front;
    while (temp != NULL) {
        fprintf(fp, "%d|%d|%d|%s|%s\n",
            temp->token,
            temp->patient_id,
            temp->doctor_id,
            temp->priority,
            temp->status
        );
        temp = temp->next;
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

    struct Queue urgentQ, normalQ;
    initQueue(&urgentQ);
    initQueue(&normalQ);

    loadQueue(&urgentQ, &normalQ);

    struct QueueNode* temp = NULL;

    if (urgentQ.front != NULL) {
        temp = dequeue(&urgentQ);
    } else if (normalQ.front != NULL) {
        temp = dequeue(&normalQ);
    } else {
        return 0;
    }

    while (temp != NULL) {

        if (strcmp(temp->status, "Waiting") == 0) {

            int doctor_id = temp->doctor_id;

            strcpy(temp->status, "Completed");

            updateQueueFile(&urgentQ, &normalQ);

            if (doctor_id != -1) {
                freeDoctor(doctor_id);
            }

            free(temp);
            return doctor_id;
        }

        free(temp);

        if (urgentQ.front != NULL) {
            temp = dequeue(&urgentQ);
        } else if (normalQ.front != NULL) {
            temp = dequeue(&normalQ);
        } else {
            return 0;
        }
    }

    return 0;
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