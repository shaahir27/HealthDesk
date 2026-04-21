#include "common.h"

int login(const char *username, const char *password, char *role, int *doctor_id) {
    FILE *fp = fopen(USER_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) {
        return 0;
    }

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char stored_username[MAX_NAME];
        char stored_password[MAX_NAME];
        char stored_role[MAX_SMALL];
        char *token;

        strcpy(buffer, line);

        token = strtok(buffer, "|");
        if (token == NULL) continue;

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(stored_username, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(stored_password, token);

        token = strtok(NULL, "|");
        if (token == NULL) continue;
        strcpy(stored_role, token);

        token = strtok(NULL, "\n");
        if (token == NULL) continue;

        if (strcmp(stored_username, username) == 0 &&
            strcmp(stored_password, password) == 0) {
            strcpy(role, stored_role);
            *doctor_id = atoi(token);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int main(int argc, char *argv[]) {
    char role[MAX_SMALL];
    int doctor_id = 0;

    if (argc != 3) {
        printf("ERROR|InvalidInput");
        return 1;
    }

    if (login(argv[1], argv[2], role, &doctor_id)) {
        printf("OK|%s|%d", role, doctor_id);
        return 0;
    }

    printf("ERROR|InvalidCredentials");
    return 1;
}
