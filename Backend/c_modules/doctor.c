#include "common.h"

struct DoctorNode {
    struct Doctor data;
    struct DoctorNode* left;
    struct DoctorNode* right;
};

void freeDoctorTree(struct DoctorNode* root);

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

void printDoctor(struct Doctor d) {
    printf("%d|%s|%s|%d|%s|%s\n",
        d.id,
        d.name,
        d.specialization,
        d.experience,
        d.daily_status,
        d.current_status
    );
}

int generate_id() {
    FILE *fp;
    int max_id = 0;
    char line[MAX_LINE];

    fp = fopen(DOCTOR_FILE, "r");

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            struct Doctor d;
            if (parseDoctorLine(line, &d) && d.id > max_id) {
                max_id = d.id;
            }
        }
        fclose(fp);
    }

    return max_id + 1;
}

void addDoctor(char *input) {
    FILE *fp = fopen(DOCTOR_FILE, "a");
    int id = generate_id();
    char name[MAX_NAME];
    char department[MAX_NAME];
    int experience;
    char *token;

    if (fp == NULL) {
        printf("Error");
        return;
    }

    token = strtok(input, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    strcpy(name, token);

    token = strtok(NULL, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    strcpy(department, token);

    token = strtok(NULL, "|");
    if (token == NULL) {
        fclose(fp);
        printf("Invalid Input");
        return;
    }
    experience = atoi(token);

    fprintf(fp, "%d|%s|%s|%d|%s|%s\n",
        id,
        name,
        department,
        experience,
        "Available",
        "Free"
    );

    fclose(fp);
    printf("%d", id);
}

void viewDoctors() {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return;

    while (fgets(line, sizeof(line), fp)) {
        printf("%s", line);
    }

    fclose(fp);
}

void updateDoctorStatuses(int doctor_id, char *daily_status, char *current_status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    FILE *temp = fopen("Backend/data/temp.txt", "w");
    char line[MAX_LINE];

    if (fp == NULL || temp == NULL) {
        if (fp != NULL) fclose(fp);
        if (temp != NULL) fclose(temp);
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;

        if (!parseDoctorLine(line, &d)) continue;

        if (d.id == doctor_id) {
            strcpy(d.daily_status, daily_status);
            strcpy(d.current_status, current_status);
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

void updateDailyStatus(int doctor_id, char *status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    FILE *temp = fopen("Backend/data/temp.txt", "w");
    char line[MAX_LINE];

    if (fp == NULL || temp == NULL) {
        if (fp != NULL) fclose(fp);
        if (temp != NULL) fclose(temp);
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;

        if (!parseDoctorLine(line, &d)) continue;

        if (d.id == doctor_id) {
            strcpy(d.daily_status, status);
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

void updateCurrentStatus(int doctor_id, char *status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    FILE *temp = fopen("Backend/data/temp.txt", "w");
    char line[MAX_LINE];

    if (fp == NULL || temp == NULL) {
        if (fp != NULL) fclose(fp);
        if (temp != NULL) fclose(temp);
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;

        if (!parseDoctorLine(line, &d)) continue;

        if (d.id == doctor_id) {
            strcpy(d.current_status, status);
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

struct DoctorNode* createDoctorNode(struct Doctor data) {
    struct DoctorNode* node = malloc(sizeof(struct DoctorNode));
    if (node == NULL) return NULL;

    node->data = data;
    node->left = NULL;
    node->right = NULL;

    return node;
}

struct DoctorNode* insertDoctor(struct DoctorNode* root, struct Doctor data) {
    int cmp;

    if (root == NULL) {
        return createDoctorNode(data);
    }

    cmp = strcmp(data.specialization, root->data.specialization);
    if (cmp < 0 || (cmp == 0 && data.id < root->data.id)) {
        root->left = insertDoctor(root->left, data);
    } else {
        root->right = insertDoctor(root->right, data);
    }

    return root;
}

struct DoctorNode* loadDoctorTree() {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];
    struct DoctorNode* root = NULL;

    if (fp == NULL) return NULL;

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;

        if (parseDoctorLine(line, &d)) {
            root = insertDoctor(root, d);
        }
    }

    fclose(fp);
    return root;
}

void searchByDepartment(struct DoctorNode* root, char *department, int available_only, int *found) {
    if (root == NULL) return;

    searchByDepartment(root->left, department, available_only, found);

    if (strcmp(root->data.specialization, department) == 0) {
        if (!available_only ||
            (strcmp(root->data.daily_status, "Available") == 0 &&
             strcmp(root->data.current_status, "Emergency") != 0)) {
            printDoctor(root->data);
            *found = 1;
        }
    }

    searchByDepartment(root->right, department, available_only, found);
}

int findAvailableDoctorInTree(struct DoctorNode* root, char *department) {
    int result;

    if (root == NULL) return 0;

    result = findAvailableDoctorInTree(root->left, department);
    if (result != 0) return result;

    if (strcmp(root->data.specialization, department) == 0 &&
        strcmp(root->data.daily_status, "Available") == 0 &&
        strcmp(root->data.current_status, "Free") == 0) {
        return root->data.id;
    }

    return findAvailableDoctorInTree(root->right, department);
}

int findAvailableDoctor(char *department) {
    struct DoctorNode* root = loadDoctorTree();
    int doctor_id = findAvailableDoctorInTree(root, department);
    freeDoctorTree(root);
    return doctor_id;
}

void freeDoctorTree(struct DoctorNode* root) {
    if (root == NULL) return;

    freeDoctorTree(root->left);
    freeDoctorTree(root->right);
    free(root);
}

void printDepartmentSearch(char *department, int available_only) {
    struct DoctorNode* root = loadDoctorTree();
    int found = 0;

    searchByDepartment(root, department, available_only, &found);

    if (!found) {
        printf("NoDoctorFound");
    }

    freeDoctorTree(root);
}

int main(int argc, char *argv[]) {
    if (argc < 2) return 1;

    if (strcmp(argv[1], "view") == 0) {
        viewDoctors();
    }
    else if (strcmp(argv[1], "daily") == 0 && argc == 4) {
        updateDailyStatus(atoi(argv[2]), argv[3]);
    }
    else if (strcmp(argv[1], "current") == 0 && argc == 4) {
        updateCurrentStatus(atoi(argv[2]), argv[3]);
    }
    else if (strcmp(argv[1], "status") == 0 && argc == 5) {
        updateDoctorStatuses(atoi(argv[2]), argv[3], argv[4]);
    }
    else if (strcmp(argv[1], "search") == 0 && argc == 3) {
        printDepartmentSearch(argv[2], 0);
    }
    else if (strcmp(argv[1], "suggest") == 0 && argc == 3) {
        printDepartmentSearch(argv[2], 1);
    }
    else if (strcmp(argv[1], "find") == 0 && argc == 3) {
        printf("%d", findAvailableDoctor(argv[2]));
    }
    else {
        addDoctor(argv[1]);
    }

    return 0;
}
