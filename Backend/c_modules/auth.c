#include "common.h"

/* ── helpers ──────────────────────────────────────────────── */

static void authSafeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

/* Parse one pipe-delimited line of users.txt into a UserAccount.
   Returns 1 on success, 0 on failure. */
int parseUserLine(char *line, struct UserAccount *u) {
    char buffer[MAX_LINE];
    char *token;
    authSafeCopy(buffer, line, sizeof(buffer));

    token = strtok(buffer, "|");
    if (!token) return 0;
    u->id = atoi(token);

    token = strtok(NULL, "|");
    if (!token) return 0;
    authSafeCopy(u->username, token, sizeof(u->username));

    token = strtok(NULL, "|");
    if (!token) return 0;
    authSafeCopy(u->password, token, sizeof(u->password));

    token = strtok(NULL, "|");
    if (!token) return 0;
    authSafeCopy(u->role, token, sizeof(u->role));

    token = strtok(NULL, "\n");
    u->doctor_id = token ? atoi(token) : 0;

    return 1;
}

/* ── original login() kept exactly as-is ─────────────────── */

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

/* ── command: list ────────────────────────────────────────── */
/* Print every line verbatim — preserves exact password hashes */
void listUsers(void) {
    FILE *fp = fopen(USER_FILE, "r");
    char line[MAX_LINE];
    if (!fp) return;
    while (fgets(line, sizeof(line), fp))
        fputs(line, stdout);
    fclose(fp);
}

/* ── command: next-id ─────────────────────────────────────── */
void nextUserId(void) {
    FILE *fp = fopen(USER_FILE, "r");
    char line[MAX_LINE];
    int max_id = 0;
    struct UserAccount u;
    if (fp) {
        while (fgets(line, sizeof(line), fp)) {
            char copy[MAX_LINE];
            authSafeCopy(copy, line, sizeof(copy));
            if (parseUserLine(copy, &u) && u.id > max_id)
                max_id = u.id;
        }
        fclose(fp);
    }
    printf("%d", max_id + 1);
}

/* ── command: find-username <username> ────────────────────── */
int findByUsername(const char *username) {
    FILE *fp = fopen(USER_FILE, "r");
    char line[MAX_LINE];
    struct UserAccount u;
    if (!fp) return 0;
    while (fgets(line, sizeof(line), fp)) {
        char copy[MAX_LINE];
        authSafeCopy(copy, line, sizeof(copy));
        if (parseUserLine(copy, &u) && strcmp(u.username, username) == 0) {
            /* Print verbatim so the hash is not corrupted */
            fputs(line, stdout);
            fclose(fp);
            return 1;
        }
    }
    fclose(fp);
    return 0;  /* Not found — empty stdout; exit 1 via main */
}

/* ── command: save <serialized_line> ──────────────────────── */
/* Appends one fully formatted line to users.txt */
int saveUser(const char *serialized_line) {
    FILE *fp;
    long size = 0;
    fp = fopen(USER_FILE, "rb");
    if (fp) {
        fseek(fp, 0, SEEK_END);
        size = ftell(fp);
        fclose(fp);
    }
    fp = fopen(USER_FILE, "ab");
    if (!fp) return 0;
    if (size > 0) {
        /* Ensure file ends with newline before appending */
        FILE *chk = fopen(USER_FILE, "rb");
        char last = '\n';
        if (chk) { fseek(chk, -1, SEEK_END); last = fgetc(chk); fclose(chk); }
        if (last != '\n') fputc('\n', fp);
    }
    fprintf(fp, "%s\n", serialized_line);
    fclose(fp);
    return 1;
}

/* ── command: update <account_id> <new_password_hash> ───────── */
/* Atomic tmp+rename: replaces only the password field of one record */
int updateUserPassword(int account_id, const char *new_hash) {
    FILE *src = fopen(USER_FILE, "r");
    FILE *tmp;
    char line[MAX_LINE];
    char tmp_path[MAX_LINE];
    struct UserAccount u;
    int updated = 0;

    if (!src) return 0;
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", USER_FILE);
    tmp = fopen(tmp_path, "w");
    if (!tmp) { fclose(src); return 0; }

    while (fgets(line, sizeof(line), src)) {
        char copy[MAX_LINE];
        authSafeCopy(copy, line, sizeof(copy));
        if (parseUserLine(copy, &u) && u.id == account_id) {
            authSafeCopy(u.password, new_hash, sizeof(u.password));
            fprintf(tmp, "%d|%s|%s|%s|%d\n",
                u.id, u.username, u.password, u.role, u.doctor_id);
            updated = 1;
        } else {
            fputs(line, tmp);
        }
    }
    fclose(src); fclose(tmp);
    if (!updated) { remove(tmp_path); return 0; }
    remove(USER_FILE);
    rename(tmp_path, USER_FILE);
    return 1;
}

/* ── main ─────────────────────────────────────────────────── */

int main(int argc, char *argv[]) {
    char role[MAX_SMALL];
    int doctor_id = 0;

    if (argc < 2) { printf("Error|NoCommand"); return 1; }

    /* New commands */
    if (strcmp(argv[1], "list") == 0) {
        listUsers(); return 0;
    }
    if (strcmp(argv[1], "next-id") == 0) {
        nextUserId(); return 0;
    }
    if (strcmp(argv[1], "find-username") == 0 && argc == 3) {
        return findByUsername(argv[2]) ? 0 : 1;
    }
    if (strcmp(argv[1], "save") == 0 && argc == 3) {
        if (saveUser(argv[2])) { printf("SAVED"); return 0; }
        printf("Error|SaveFailed"); return 1;
    }
    if (strcmp(argv[1], "update") == 0 && argc == 4) {
        if (updateUserPassword(atoi(argv[2]), argv[3])) { printf("UPDATED"); return 0; }
        printf("Error|UpdateFailed"); return 1;
    }

    /* Legacy login command — kept for any existing callers */
    if (argc == 3) {
        if (login(argv[1], argv[2], role, &doctor_id)) {
            printf("OK|%s|%d", role, doctor_id);
            return 0;
        }
        printf("ERROR|InvalidCredentials");
        return 1;
    }

    printf("Error|InvalidCommand"); return 1;
}
