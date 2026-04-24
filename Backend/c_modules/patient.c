#include "common.h"

struct PatientNode {
    struct Patient data;
    struct PatientNode *next;
};

static struct PatientNode *patients_head = NULL;
static struct PatientNode *patients_tail = NULL;
static int patients_loaded = 0;
static int patients_dirty = 0;

void safeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

int parsePatientLine(char *line, struct Patient *p) {
    char buffer[MAX_LINE];
    char *token;

    safeCopy(buffer, line, sizeof(buffer));

    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    p->id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->name, token, sizeof(p->name));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    p->age = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->gender, token, sizeof(p->gender));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->phone, token, sizeof(p->phone));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->address, token, sizeof(p->address));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->symptoms, token, sizeof(p->symptoms));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->visit_type, token, sizeof(p->visit_type));

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    safeCopy(p->priority, token, sizeof(p->priority));

    token = strtok(NULL, "\n");
    if (token == NULL) return 0;
    safeCopy(p->department, token, sizeof(p->department));

    return 1;
}

int appendPatientNode(struct Patient p) {
    struct PatientNode *node = malloc(sizeof(struct PatientNode));
    if (node == NULL) return 0;

    node->data = p;
    node->next = NULL;

    if (patients_tail == NULL) {
        patients_head = node;
        patients_tail = node;
    } else {
        patients_tail->next = node;
        patients_tail = node;
    }

    return 1;
}

void loadPatients() {
    FILE *fp;
    char line[MAX_LINE];

    if (patients_loaded) return;
    patients_loaded = 1;

    fp = fopen(PATIENT_FILE, "r");
    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        struct Patient p;
        if (parsePatientLine(line, &p)) {
            appendPatientNode(p);
        }
    }

    fclose(fp);
}

void savePatientsIfDirty() {
    FILE *fp;
    struct PatientNode *current;

    if (!patients_dirty) return;

    fp = fopen(PATIENT_FILE, "w");
    if (fp == NULL) return;

    current = patients_head;
    while (current != NULL) {
        struct Patient p = current->data;
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
        current = current->next;
    }

    fclose(fp);
    patients_dirty = 0;
}

void freePatients() {
    struct PatientNode *current = patients_head;

    while (current != NULL) {
        struct PatientNode *next = current->next;
        free(current);
        current = next;
    }

    patients_head = NULL;
    patients_tail = NULL;
}

void shutdownPatients() {
    savePatientsIfDirty();
    freePatients();
}

int nextPatientId() {
    int max_id = 0;
    struct PatientNode *current;

    loadPatients();
    current = patients_head;
    while (current != NULL) {
        if (current->data.id > max_id) {
            max_id = current->data.id;
        }
        current = current->next;
    }

    return max_id + 1;
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
    struct PatientNode *current;

    loadPatients();
    current = patients_head;

    while (current != NULL) {
        if (strcmp(current->data.phone, phone) == 0) {
            *result = current->data;
            return 1;
        }
        current = current->next;
    }

    return 0;
}

void parse_patient_data(const char *data, struct Patient *p) {
    char buffer[MAX_LINE];
    char *token;

    memset(p, 0, sizeof(*p));
    safeCopy(buffer, data, sizeof(buffer));

    token = strtok(buffer, "|");
    if (token != NULL) safeCopy(p->name, token, sizeof(p->name));

    token = strtok(NULL, "|");
    if (token != NULL) p->age = atoi(token);

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->gender, token, sizeof(p->gender));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->phone, token, sizeof(p->phone));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->address, token, sizeof(p->address));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->symptoms, token, sizeof(p->symptoms));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->visit_type, token, sizeof(p->visit_type));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->priority, token, sizeof(p->priority));

    token = strtok(NULL, "|");
    if (token != NULL) safeCopy(p->department, token, sizeof(p->department));
}

void addPatient(const char *input) {
    struct Patient p;
    struct Patient existing;

    loadPatients();
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

    p.id = nextPatientId();
    if (!appendPatientNode(p)) {
        printf("Error|MemoryAllocationFailed");
        return;
    }

    patients_dirty = 1;
    printf("%d|%s|%s", p.id, p.visit_type, p.priority);
}

int main(int argc, char *argv[]) {
    atexit(shutdownPatients);

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
