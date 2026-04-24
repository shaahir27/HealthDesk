#include "common.h"

struct QueueStore {
    struct QueueNode *front;
    struct QueueNode *rear;
};

static struct QueueStore queue_store = { NULL, NULL };
static int queue_loaded = 0;
static int queue_dirty = 0;

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
            strcmp(d.current_status, "Free") == 0) {
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
