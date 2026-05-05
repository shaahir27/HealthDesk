#include "common.h"
#include <time.h>
#ifdef _WIN32
#include <process.h>
#define HEALTHDESK_GETPID _getpid
#else
#include <unistd.h>
#define HEALTHDESK_GETPID getpid
#endif

struct DoctorNode {
    struct Doctor data;
    struct DoctorNode* left;
    struct DoctorNode* right;
};

void freeDoctorTree(struct DoctorNode* root);

void buildDoctorTempPath(char *path, size_t path_size) {
    snprintf(path, path_size, "Backend/data/doctors.%d.tmp", HEALTHDESK_GETPID());
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

int doctorMatchesAvailabilityCount(struct Doctor *d) {
    return strcmp(d->daily_status, "Available") == 0 && strcmp(d->current_status, "Free") == 0;
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

int getDoctorById(int doctor_id, struct Doctor *result) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;
        if (!parseDoctorLine(line, &d)) continue;
        if (d.id == doctor_id) {
            *result = d;
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int countAvailableDoctors(void) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];
    int count = 0;

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {
        struct Doctor d;
        if (parseDoctorLine(line, &d) && doctorMatchesAvailabilityCount(&d)) {
            count++;
        }
    }

    fclose(fp);
    return count;
}

int doctorExists(int doctor_id) {
    struct Doctor doctor;
    return getDoctorById(doctor_id, &doctor);
}

void updateDoctorStatuses(int doctor_id, char *daily_status, char *current_status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char temp_path[MAX_LINE];
    FILE *temp;
    char line[MAX_LINE];

    buildDoctorTempPath(temp_path, sizeof(temp_path));
    temp = fopen(temp_path, "w");

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
    rename(temp_path, DOCTOR_FILE);
}

void updateDailyStatus(int doctor_id, char *status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char temp_path[MAX_LINE];
    FILE *temp;
    char line[MAX_LINE];

    buildDoctorTempPath(temp_path, sizeof(temp_path));
    temp = fopen(temp_path, "w");

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
    rename(temp_path, DOCTOR_FILE);
}

void updateCurrentStatus(int doctor_id, char *status) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char temp_path[MAX_LINE];
    FILE *temp;
    char line[MAX_LINE];

    buildDoctorTempPath(temp_path, sizeof(temp_path));
    temp = fopen(temp_path, "w");

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
    rename(temp_path, DOCTOR_FILE);
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
        strcmp(root->data.current_status, "Emergency") != 0) {
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

void normalizeDoctorStatuses(const char *daily_in, const char *current_in,
                             char *out_daily, size_t out_daily_size,
                             char *out_current, size_t out_current_size) {
    char daily[MAX_SMALL];
    char current[MAX_SMALL];
    snprintf(daily, sizeof(daily), "%s", (daily_in && daily_in[0]) ? daily_in : "Available");
    snprintf(current, sizeof(current), "%s", current_in ? current_in : "");

    if (strcmp(daily, "Off") == 0) {
        snprintf(out_daily, out_daily_size, "Off");
        snprintf(out_current, out_current_size, "Off");
        return;
    }
    if (strcmp(daily, "Unavailable") == 0) {
        snprintf(out_daily, out_daily_size, "Unavailable");
        snprintf(out_current, out_current_size, "Unavailable");
        return;
    }
    snprintf(out_daily, out_daily_size, "%s", daily);
    if (strcmp(current, "Emergency") == 0) snprintf(out_current, out_current_size, "Emergency");
    else if (strcmp(current, "Busy") == 0) snprintf(out_current, out_current_size, "Busy");
    else snprintf(out_current, out_current_size, "Free");
}

int writeAllDoctorsFromStdin(void) {
    FILE *tmp = fopen("Backend/data/doctors.tmp", "w");
    char line[MAX_LINE];
    if (!tmp) return 0;
    while (fgets(line, sizeof(line), stdin)) {
        fputs(line, tmp);
    }
    fclose(tmp);
    remove(DOCTOR_FILE);
    if (rename("Backend/data/doctors.tmp", DOCTOR_FILE) != 0) {
        remove("Backend/data/doctors.tmp");
        return 0;
    }
    return 1;
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
    else if (strcmp(argv[1], "get-by-id") == 0 && argc == 3) {
        struct Doctor doctor;
        if (getDoctorById(atoi(argv[2]), &doctor)) {
            printDoctor(doctor);
            return 0;
        }
        printf("DoctorNotFound");
        return 1;
    }
    else if (strcmp(argv[1], "count-available") == 0) {
        printf("%d", countAvailableDoctors());
    }
    else if (strcmp(argv[1], "exists") == 0 && argc == 3) {
        printf("%d", doctorExists(atoi(argv[2])));
    }
    else if (strcmp(argv[1], "normalize-status") == 0 && argc == 4) {
        char nd[MAX_SMALL], nc[MAX_SMALL];
        normalizeDoctorStatuses(argv[2], argv[3], nd, sizeof(nd), nc, sizeof(nc));
        printf("%s|%s", nd, nc);
    }
    else if (strcmp(argv[1], "status-view") == 0 && argc == 4) {
        char nd[MAX_SMALL], nc[MAX_SMALL];
        const char *label = "Free";
        const char *badge = "booked";
        normalizeDoctorStatuses(argv[2], argv[3], nd, sizeof(nd), nc, sizeof(nc));
        if (strcmp(nd, "Off") == 0) { label = "Off Duty"; badge = "waived"; }
        else if (strcmp(nd, "Unavailable") == 0) { label = "Unavailable"; badge = "cancelled"; }
        else if (strcmp(nc, "Emergency") == 0) { label = "Emergency"; badge = "cancelled"; }
        else if (strcmp(nc, "Busy") == 0) { label = "Busy"; badge = "pending"; }
        printf("%s|%s", label, badge);
    }
    else if (strcmp(argv[1], "write-all") == 0) {
        if (writeAllDoctorsFromStdin()) printf("OK");
        else return 1;
    }
    else if (strcmp(argv[1], "is-blocked") == 0 && argc == 4) {
        struct Doctor doctor;
        if (!getDoctorById(atoi(argv[2]), &doctor)) {
            printf("0");
            return 0;
        }
        if (strcmp(doctor.daily_status, "Unavailable") == 0 || strcmp(doctor.daily_status, "Off") == 0 ||
            strcmp(doctor.current_status, "Emergency") == 0) {
            printf("1");
        } else {
            printf("0");
        }
    }
    else if (strcmp(argv[1], "sync-busy") == 0) {
        printf("0");
    }
    else if (strcmp(argv[1], "build-username") == 0 && argc == 3) {
        char username[MAX_NAME] = "dr.";
        int j = 3;
        const char *src = argv[2];
        int i;
        for (i = 0; src[i] && j + 1 < (int)sizeof(username); i++) {
            char c = src[i];
            if ((c >= 'A' && c <= 'Z')) c = (char)(c - 'A' + 'a');
            if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) username[j++] = c;
            else if ((c == ' ' || c == '.' || c == '-') && username[j - 1] != '.') username[j++] = '.';
        }
        if (username[j - 1] == '.') j--;
        username[j] = '\0';
        printf("%s", username);
    }
    else if (strcmp(argv[1], "build-password") == 0 && argc == 3) {
        time_t now = time(NULL);
        struct tm *tm_now = localtime(&now);
        int year = tm_now ? (tm_now->tm_year + 1900) : 2026;
        printf("HDDoc%d@%d", atoi(argv[2]), year);
    }
    else {
        addDoctor(argv[1]);
    }

    return 0;
}
