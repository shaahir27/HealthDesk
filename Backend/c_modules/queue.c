#include "common.h"

struct QueueStore {
    struct QueueNode *front;
    struct QueueNode *rear;
};

static struct QueueStore queue_store = { NULL, NULL };
static int queue_loaded = 0;
static int queue_dirty = 0;

#define APPOINTMENT_STATUS_BUCKETS 1021

struct QueuePriorityHeap {
    struct QueueNode **items;
    int size;
    int capacity;
};

struct AppointmentStatusNode {
    int patient_id;
    int doctor_id;
    int has_booked;
    char last_terminal[MAX_SMALL];
    struct AppointmentStatusNode *next;
};

void safeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

int appendQueueNode(struct QueueNode q) {
    struct QueueNode *node = malloc(sizeof(struct QueueNode));
    if (node == NULL) return 0;

    *node = q;
    node->next = NULL;

    if (queue_store.rear == NULL) {
        queue_store.front = node;
        queue_store.rear = node;
    } else {
        queue_store.rear->next = node;
        queue_store.rear = node;
    }

    return 1;
}

void loadQueue() {
    FILE *fp;
    char line[MAX_LINE];

    if (queue_loaded) return;
    queue_loaded = 1;

    fp = fopen(QUEUE_FILE, "r");
    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        struct QueueNode q;
        char buffer[MAX_LINE];
        char *token;

        safeCopy(buffer, line, sizeof(buffer));

        token = strtok(buffer, "|");
        if (token == NULL) continue;
        q.token = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        q.patient_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        q.doctor_id = atoi(token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        safeCopy(q.priority, token, sizeof(q.priority));

        token = strtok(NULL, "\n");
        if (token == NULL) continue;
        safeCopy(q.status, token, sizeof(q.status));

        q.next = NULL;
        appendQueueNode(q);
    }

    fclose(fp);
}

void saveQueueIfDirty() {
    FILE *fp;
    struct QueueNode *current;

    if (!queue_dirty) return;

    fp = fopen(QUEUE_FILE, "w");
    if (fp == NULL) return;

    current = queue_store.front;
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
    queue_dirty = 0;
}

void freeQueueStore() {
    struct QueueNode *current = queue_store.front;

    while (current != NULL) {
        struct QueueNode *next = current->next;
        free(current);
        current = next;
    }

    queue_store.front = NULL;
    queue_store.rear = NULL;
}

void shutdownQueueStore() {
    saveQueueIfDirty();
    freeQueueStore();
}

int nextToken() {
    int max_token = 0;
    struct QueueNode *current;

    loadQueue();
    current = queue_store.front;
    while (current != NULL) {
        if (current->token > max_token) {
            max_token = current->token;
        }
        current = current->next;
    }

    return max_token + 1;
}

struct QueueNode* findWaitingByPatient(int patient_id) {
    struct QueueNode *current;

    loadQueue();
    current = queue_store.front;
    while (current != NULL) {
        if (current->patient_id == patient_id && strcmp(current->status, "Waiting") == 0) {
            return current;
        }
        current = current->next;
    }

    return NULL;
}

int getPatientPriority(int patient_id, char *priority) {
    FILE *fp = fopen(PATIENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;
        int id;

        safeCopy(buffer, line, sizeof(buffer));

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

            safeCopy(priority, token, MAX_SMALL);
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
        char buffer[MAX_LINE];
        char *token;
        int id;

        safeCopy(buffer, line, sizeof(buffer));

        token = strtok(buffer, "|");
        if (token == NULL) continue;
        id = atoi(token);

        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");

        token = strtok(NULL, "\n");
        if (token == NULL) continue;

        if (id == patient_id) {
            safeCopy(department, token, MAX_NAME);
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

    safeCopy(buffer, line, sizeof(buffer));
    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    d->id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(d->name, token, sizeof(d->name));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(d->specialization, token, sizeof(d->specialization));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    d->experience = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(d->daily_status, token, sizeof(d->daily_status));

    token = strtok(NULL, "\n");
    if (token == NULL) return 0;
    safeCopy(d->current_status, token, sizeof(d->current_status));

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
            strcmp(d.current_status, "Emergency") != 0) {
            fclose(fp);
            return d.id;
        }
    }

    fclose(fp);
    return -1;
}

int doctorExists(int doctor_id) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (doctor_id <= 0 || fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;
        if (!parseDoctorLine(line, &d)) continue;
        if (d.id == doctor_id) {
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int enqueuePatient(struct QueueNode q) {
    if (!appendQueueNode(q)) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    queue_dirty = 1;
    return 1;
}

int queuePriorityRank(struct QueueNode *node) {
    if (node != NULL && strcmp(node->priority, "Urgent") == 0) {
        return 0;
    }
    return 1;
}

int queueNodeHigherPriority(struct QueueNode *a, struct QueueNode *b) {
    int rank_a;
    int rank_b;
    if (a == NULL) return 0;
    if (b == NULL) return 1;

    rank_a = queuePriorityRank(a);
    rank_b = queuePriorityRank(b);
    if (rank_a != rank_b) {
        return rank_a < rank_b;
    }
    return a->token < b->token;
}

void priorityHeapSwap(struct QueueNode **a, struct QueueNode **b) {
    struct QueueNode *tmp = *a;
    *a = *b;
    *b = tmp;
}

int priorityHeapPush(struct QueuePriorityHeap *heap, struct QueueNode *node) {
    int idx;
    if (heap == NULL || node == NULL) return 0;
    if (heap->size >= heap->capacity) return 0;

    idx = heap->size;
    heap->items[idx] = node;
    heap->size++;

    while (idx > 0) {
        int parent = (idx - 1) / 2;
        if (!queueNodeHigherPriority(heap->items[idx], heap->items[parent])) {
            break;
        }
        priorityHeapSwap(&heap->items[idx], &heap->items[parent]);
        idx = parent;
    }

    return 1;
}

struct QueueNode* priorityHeapPop(struct QueuePriorityHeap *heap) {
    struct QueueNode *top;
    int idx = 0;
    if (heap == NULL || heap->size <= 0) return NULL;

    top = heap->items[0];
    heap->size--;
    heap->items[0] = heap->items[heap->size];

    while (1) {
        int left = idx * 2 + 1;
        int right = idx * 2 + 2;
        int best = idx;

        if (left < heap->size && queueNodeHigherPriority(heap->items[left], heap->items[best])) {
            best = left;
        }
        if (right < heap->size && queueNodeHigherPriority(heap->items[right], heap->items[best])) {
            best = right;
        }
        if (best == idx) break;

        priorityHeapSwap(&heap->items[idx], &heap->items[best]);
        idx = best;
    }

    return top;
}

void listQueueByPriority(void) {
    struct QueueNode *current;
    struct QueuePriorityHeap heap;
    int count = 0;

    loadQueue();
    current = queue_store.front;
    while (current != NULL) {
        if (strcmp(current->status, "Waiting") == 0) {
            count++;
        }
        current = current->next;
    }

    if (count == 0) return;

    heap.items = malloc(sizeof(struct QueueNode*) * count);
    if (heap.items == NULL) return;
    heap.size = 0;
    heap.capacity = count;

    current = queue_store.front;
    while (current != NULL) {
        if (strcmp(current->status, "Waiting") == 0) {
            priorityHeapPush(&heap, current);
        }
        current = current->next;
    }

    while (heap.size > 0) {
        struct QueueNode *node = priorityHeapPop(&heap);
        printf("%d|%d|%d|%s|%s\n",
            node->token,
            node->patient_id,
            node->doctor_id,
            node->priority,
            node->status
        );
    }

    free(heap.items);
}

void listQueue(void) {
    struct QueueNode *current;

    loadQueue();
    current = queue_store.front;
    while (current != NULL) {
        printf("%d|%d|%d|%s|%s\n",
            current->token,
            current->patient_id,
            current->doctor_id,
            current->priority,
            current->status
        );
        current = current->next;
    }
}

int updateWaitingStatus(int patient_id, int doctor_id, const char *status) {
    struct QueueNode *current;
    int updated = 0;

    loadQueue();
    current = queue_store.front;
    while (current != NULL) {
        if (current->patient_id == patient_id &&
            strcmp(current->status, "Waiting") == 0 &&
            (doctor_id <= 0 || current->doctor_id == doctor_id)) {
            safeCopy(current->status, status, sizeof(current->status));
            updated = 1;
        }
        current = current->next;
    }

    if (!updated) return 0;
    queue_dirty = 1;
    saveQueueIfDirty();
    return 1;
}

int writeAllQueueFromStdin(void) {
    FILE *tmp = fopen("Backend/data/queue.tmp", "w");
    char line[MAX_LINE];
    if (!tmp) return 0;
    while (fgets(line, sizeof(line), stdin)) {
        fputs(line, tmp);
    }
    fclose(tmp);
    remove(QUEUE_FILE);
    if (rename("Backend/data/queue.tmp", QUEUE_FILE) != 0) {
        remove("Backend/data/queue.tmp");
        return 0;
    }
    return 1;
}

unsigned int appointmentStatusHash(int patient_id, int doctor_id) {
    unsigned int hash = 2166136261u;
    hash = (hash ^ (unsigned int)patient_id) * 16777619u;
    hash = (hash ^ (unsigned int)doctor_id) * 16777619u;
    return hash % APPOINTMENT_STATUS_BUCKETS;
}

int isTerminalAppointmentStatus(const char *status) {
    return strcmp(status, "Completed") == 0 ||
           strcmp(status, "Cancelled") == 0 ||
           strcmp(status, "Rescheduled") == 0 ||
           strcmp(status, "No-show") == 0;
}

struct AppointmentStatusNode* findAppointmentStatusNode(
    struct AppointmentStatusNode **table,
    int patient_id,
    int doctor_id
) {
    unsigned int bucket = appointmentStatusHash(patient_id, doctor_id);
    struct AppointmentStatusNode *current = table[bucket];

    while (current != NULL) {
        if (current->patient_id == patient_id && current->doctor_id == doctor_id) {
            return current;
        }
        current = current->next;
    }

    return NULL;
}

struct AppointmentStatusNode* getOrCreateAppointmentStatusNode(
    struct AppointmentStatusNode **table,
    int patient_id,
    int doctor_id
) {
    unsigned int bucket;
    struct AppointmentStatusNode *node;

    node = findAppointmentStatusNode(table, patient_id, doctor_id);
    if (node != NULL) return node;

    node = malloc(sizeof(struct AppointmentStatusNode));
    if (node == NULL) return NULL;

    node->patient_id = patient_id;
    node->doctor_id = doctor_id;
    node->has_booked = 0;
    node->last_terminal[0] = '\0';

    bucket = appointmentStatusHash(patient_id, doctor_id);
    node->next = table[bucket];
    table[bucket] = node;

    return node;
}

void loadAppointmentStatusTable(struct AppointmentStatusNode **table) {
    FILE *fp = fopen(APPOINTMENT_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;
        int patient_id = 0;
        int doctor_id = 0;
        char status[MAX_SMALL] = "";
        struct AppointmentStatusNode *node;

        safeCopy(buffer, line, sizeof(buffer));

        token = strtok(buffer, "|");
        if (!token) continue;

        token = strtok(NULL, "|");
        if (!token) continue;
        patient_id = atoi(token);

        token = strtok(NULL, "|");
        if (!token) continue;
        doctor_id = atoi(token);

        token = strtok(NULL, "|");
        if (!token) continue;

        token = strtok(NULL, "|");
        if (!token) continue;

        token = strtok(NULL, "\n");
        if (!token) continue;
        safeCopy(status, token, sizeof(status));

        node = getOrCreateAppointmentStatusNode(table, patient_id, doctor_id);
        if (node == NULL) continue;

        if (strcmp(status, "Booked") == 0) {
            node->has_booked = 1;
        }
        if (isTerminalAppointmentStatus(status)) {
            safeCopy(node->last_terminal, status, sizeof(node->last_terminal));
        }
    }

    fclose(fp);
}

void freeAppointmentStatusTable(struct AppointmentStatusNode **table) {
    int i;

    for (i = 0; i < APPOINTMENT_STATUS_BUCKETS; i++) {
        struct AppointmentStatusNode *current = table[i];
        while (current != NULL) {
            struct AppointmentStatusNode *next = current->next;
            free(current);
            current = next;
        }
        table[i] = NULL;
    }
}

int queueReconcile(void) {
    struct QueueNode *current;
    struct AppointmentStatusNode *appointment_status[APPOINTMENT_STATUS_BUCKETS] = { NULL };
    int updated = 0;

    loadQueue();
    loadAppointmentStatusTable(appointment_status);

    current = queue_store.front;
    while (current != NULL) {
        if (strcmp(current->status, "Waiting") == 0) {
            struct AppointmentStatusNode *status_node;

            status_node = findAppointmentStatusNode(
                appointment_status,
                current->patient_id,
                current->doctor_id
            );

            if (status_node != NULL &&
                !status_node->has_booked &&
                status_node->last_terminal[0] != '\0') {
                safeCopy(current->status, status_node->last_terminal, sizeof(current->status));
                updated = 1;
            }
        }
        current = current->next;
    }

    freeAppointmentStatusTable(appointment_status);

    if (updated) {
        queue_dirty = 1;
        saveQueueIfDirty();
    }
    return 1;
}

int main(int argc, char *argv[]) {
    int patient_id;
    int doctor_id = -1;
    char priority[MAX_SMALL] = "";
    char department[MAX_NAME] = "";
    struct QueueNode q;
    struct QueueNode *existing;

    atexit(shutdownQueueStore);

    if (argc < 2) {
        printf("Invalid Input");
        return 1;
    }

    if (strcmp(argv[1], "list") == 0) {
        listQueue();
        return 0;
    }

    if (strcmp(argv[1], "list-priority") == 0) {
        listQueueByPriority();
        return 0;
    }

    if (strcmp(argv[1], "update-waiting") == 0 && argc >= 5) {
        if (updateWaitingStatus(atoi(argv[2]), atoi(argv[3]), argv[4])) {
            printf("UPDATED");
            return 0;
        }
        printf("NOT_FOUND");
        return 1;
    }

    if (strcmp(argv[1], "write-all") == 0) {
        if (writeAllQueueFromStdin()) {
            printf("OK");
            return 0;
        }
        printf("Error|WriteAllFailed");
        return 1;
    }

    if (strcmp(argv[1], "reconcile") == 0) {
        queueReconcile();
        listQueue();
        return 0;
    }

    patient_id = atoi(argv[1]);
    if (patient_id <= 0) {
        printf("Error|InvalidPatient");
        return 1;
    }

    existing = findWaitingByPatient(patient_id);
    if (existing != NULL) {
        printf("%d|%d|%s", existing->token, existing->doctor_id, existing->priority);
        return 0;
    }

    if (argc >= 3) {
        doctor_id = atoi(argv[2]);
        if (!doctorExists(doctor_id)) {
            doctor_id = -1;
        }
    }

    if (argc >= 4) {
        safeCopy(priority, argv[3], sizeof(priority));
    } else if (!getPatientPriority(patient_id, priority)) {
        printf("Error|PatientNotFound");
        return 1;
    }

    if (doctor_id <= 0 && getPatientDepartment(patient_id, department)) {
        doctor_id = findAvailableDoctor(department);
    }

    q.token = nextToken();
    q.patient_id = patient_id;
    q.doctor_id = doctor_id;
    safeCopy(q.priority, priority, sizeof(q.priority));
    safeCopy(q.status, "Waiting", sizeof(q.status));
    q.next = NULL;

    if (!enqueuePatient(q)) {
        return 1;
    }

    printf("%d|%d|%s", q.token, q.doctor_id, q.priority);
    return 0;
}
