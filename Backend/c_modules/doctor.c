#include "common.h"

int generate_id() {

    // Reading and Writing data in file
    FILE *fp;
    int count = 0;
    char line[1024];

    fp = fopen(DOCTOR_FILE, "r");

    if(fp != NULL){
        while(fgets(line, sizeof(line), fp)){
                count++;
            }
        fclose(fp);
    }

    return count + 1;
}

void addDoctor(char *input) {
    FILE *fp = fopen(DOCTOR_FILE, "a");

    int id = generate_id();

    char name[MAX_NAME];
    char department[MAX_NAME];
    int experience;

    char *token = strtok(input, "|");
    strcpy(name, token);

    token = strtok(NULL, "|");
    strcpy(department, token);

    token = strtok(NULL, "|");
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

void updateDailyStatus(int doctor_id, char *status) {
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
    rename("../data/temp.txt", DOCTOR_FILE);
}

void updateCurrentStatus(int doctor_id, char *status) {
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
    rename("../data/temp.txt", DOCTOR_FILE);
}

int findAvailableDoctor(char *department) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {

        struct Doctor d;

        char *token = strtok(line, "|");
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

int main(int argc, char *argv[]) {

    if (argc < 2) return 1;

    if (strcmp(argv[1], "view") == 0) {
        viewDoctors();
    }
    else if (strcmp(argv[1], "daily") == 0 && argc == 4) {
        int id = atoi(argv[2]);
        updateDailyStatus(id, argv[3]);
    }
    else if (strcmp(argv[1], "current") == 0 && argc == 4) {
        int id = atoi(argv[2]);
        updateCurrentStatus(id, argv[3]);
    }
    else {
        addDoctor(argv[1]);
    }

    return 0;
}