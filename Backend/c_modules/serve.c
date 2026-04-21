#include "common.h"

struct Queue {
    struct QueueNode* front;
    struct QueueNode* rear;
};

void initQueue(struct Queue* q) {
    q->front = NULL;
    q->rear = NULL;
}

void enqueue(struct Queue* q, struct QueueNode data) {
    struct QueueNode* newNode = malloc(sizeof(struct QueueNode));
    if (newNode == NULL) return;

    *newNode = data;
    newNode->next = NULL;

    if (q->rear == NULL) {
        q->front = newNode;
        q->rear = newNode;
        return;
    }

    q->rear->next = newNode;
    q->rear = newNode;
}

void loadQueue(struct Queue* q) {
    FILE *fp = fopen(QUEUE_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        struct QueueNode temp;
        char buffer[MAX_LINE];
        char *token;

        strcpy(buffer, line);

        token = strtok(buffer, "|");
        if (token == NULL) continue;
        temp.token = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        temp.patient_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        temp.doctor_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(temp.priority, token);

        token = strtok(NULL, "\n");
        if (token == NULL) continue;
        strcpy(temp.status, token);

        temp.next = NULL;
        enqueue(q, temp);
    }

    fclose(fp);
}

struct QueueNode* dequeueNextPatient(struct Queue* q) {
    struct QueueNode* current = q->front;

    while (current != NULL) {
        if (strcmp(current->status, "Waiting") == 0 &&
            strcmp(current->priority, "Urgent") == 0) {
            return current;
        }
        current = current->next;
    }

    current = q->front;
    while (current != NULL) {
        if (strcmp(current->status, "Waiting") == 0) {
            return current;
        }
        current = current->next;
    }

    return NULL;
}

void updateQueueFile(struct Queue* q) {
    FILE *fp = fopen(QUEUE_FILE, "w");
    struct QueueNode* current = q->front;

    if (fp == NULL) return;

    while (current != NULL) {
        fprintf(fp, "%d|%d|%d|%s|%s\n",
            current->token,
            current->patient_id,
            current->doctor_id,
            current->priority,
            current->status
        );
        current = current->next;
    }

    fclose(fp);
}

void freeQueue(struct Queue* q) {
    struct QueueNode* current = q->front;

    while (current != NULL) {
        struct QueueNode* next = current->next;
        free(current);
        current = next;
    }

    q->front = NULL;
    q->rear = NULL;
}

int serveNextPatient() {
    struct Queue q;
    struct QueueNode* nextPatient;

    initQueue(&q);
    loadQueue(&q);

    nextPatient = dequeueNextPatient(&q);
    if (nextPatient == NULL) {
        freeQueue(&q);
        return 0;
    }

    strcpy(nextPatient->status, "Completed");
    updateQueueFile(&q);

    freeQueue(&q);
    return 1;
}

int main() {
    int served = serveNextPatient();

    if (served == 0) {
        printf("No Patient");
    } else {
        printf("Served|QueueUpdated");
    }

    return 0;
}
