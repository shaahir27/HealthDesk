#include "common.h"

/*
 * prescription.exe — Structured prescription storage
 *
 * Commands:
 *   save-header <serialised_header_line>  → SAVED|<id>
 *   save-med    <serialised_med_line>     → SAVED
 *   find-appointment <appointment_id>     → header line or empty
 *   find-meds   <prescription_id>         → MED lines for that prescription
 *   next-id                               → next available prescription_id
 */

static int get_next_id(void) {
    FILE *fp = fopen(PRESCRIPTION_FILE, "rb");
    if (!fp) return 1;
    int max_id = 0;
    char line[MAX_LINE];
    while (fgets(line, sizeof(line), fp)) {
        /* Skip MED lines and blank lines */
        if (strncmp(line, "MED|", 4) == 0) continue;
        char *trimmed = line;
        while (*trimmed == ' ' || *trimmed == '\t') trimmed++;
        if (*trimmed == '\n' || *trimmed == '\r' || *trimmed == '\0') continue;
        int id = atoi(trimmed);
        if (id > max_id) max_id = id;
    }
    fclose(fp);
    return max_id + 1;
}

static void ensure_trailing_newline(FILE *fp) {
    fseek(fp, 0, SEEK_END);
    long size = ftell(fp);
    if (size > 0) {
        fseek(fp, -1, SEEK_END);
        int ch = fgetc(fp);
        if (ch != '\n') {
            fputc('\n', fp);
        }
        fseek(fp, 0, SEEK_END);
    }
}

static int save_header(const char *serialised_line) {
    FILE *fp = fopen(PRESCRIPTION_FILE, "ab");
    if (!fp) {
        fprintf(stderr, "Error|CannotOpenFile\n");
        return 1;
    }
    ensure_trailing_newline(fp);
    fprintf(fp, "%s\n", serialised_line);
    fclose(fp);

    /* Extract the prescription_id from the line (first field) */
    int id = atoi(serialised_line);
    printf("SAVED|%d\n", id);
    return 0;
}

static int save_med(const char *serialised_line) {
    FILE *fp = fopen(PRESCRIPTION_FILE, "ab");
    if (!fp) {
        fprintf(stderr, "Error|CannotOpenFile\n");
        return 1;
    }
    ensure_trailing_newline(fp);
    fprintf(fp, "MED|%s\n", serialised_line);
    fclose(fp);

    printf("SAVED\n");
    return 0;
}

static int find_appointment(int appointment_id) {
    FILE *fp = fopen(PRESCRIPTION_FILE, "rb");
    if (!fp) return 0;   /* No file = no results, not an error */
    char line[MAX_LINE];
    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "MED|", 4) == 0) continue;
        char *trimmed = line;
        while (*trimmed == ' ' || *trimmed == '\t') trimmed++;
        if (*trimmed == '\n' || *trimmed == '\r' || *trimmed == '\0') continue;

        /* Fields: prescription_id|appointment_id|... */
        char *p = strchr(trimmed, '|');
        if (!p) continue;
        int appt_id = atoi(p + 1);
        if (appt_id == appointment_id) {
            /* Remove trailing newline */
            size_t len = strlen(trimmed);
            while (len > 0 && (trimmed[len - 1] == '\n' || trimmed[len - 1] == '\r'))
                trimmed[--len] = '\0';
            printf("%s\n", trimmed);
            fclose(fp);
            return 0;
        }
    }
    fclose(fp);
    return 0;  /* Empty output if not found */
}

static int find_meds(int prescription_id) {
    FILE *fp = fopen(PRESCRIPTION_FILE, "rb");
    if (!fp) return 0;
    char line[MAX_LINE];
    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "MED|", 4) != 0) continue;

        /* MED|prescription_id|... */
        int med_rx_id = atoi(line + 4);
        if (med_rx_id == prescription_id) {
            size_t len = strlen(line);
            while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
                line[--len] = '\0';
            printf("%s\n", line);
        }
    }
    fclose(fp);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: prescription <command> [args...]\n");
        return 1;
    }

    if (strcmp(argv[1], "next-id") == 0) {
        printf("%d\n", get_next_id());
        return 0;
    }

    if (strcmp(argv[1], "save-header") == 0 && argc >= 3) {
        return save_header(argv[2]);
    }

    if (strcmp(argv[1], "save-med") == 0 && argc >= 3) {
        return save_med(argv[2]);
    }

    if (strcmp(argv[1], "find-appointment") == 0 && argc >= 3) {
        return find_appointment(atoi(argv[2]));
    }

    if (strcmp(argv[1], "find-meds") == 0 && argc >= 3) {
        return find_meds(atoi(argv[2]));
    }

    fprintf(stderr, "Error|UnknownCommand\n");
    return 1;
}
