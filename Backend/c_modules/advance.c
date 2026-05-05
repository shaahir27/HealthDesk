#include "common.h"

/* ADVANCE_FILE and BOOKING_INTENT_FILE are now defined in common.h */
#define ADVANCE_TEMP_FILE "Backend/data/advances.tmp"
#define BOOKING_INTENT_TEMP_FILE "Backend/data/pending_booking_intents.tmp"
#define FIELD_BUFFER 2048

static void safe_copy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

static void strip_newline(char *text) {
    size_t len;
    if (text == NULL) return;
    len = strlen(text);
    while (len > 0 && (text[len - 1] == '\n' || text[len - 1] == '\r')) {
        text[--len] = '\0';
    }
}

static int extract_field(const char *line, int target_index, char *out, size_t out_size) {
    int field_index = 0;
    size_t out_pos = 0;

    if (line == NULL || out == NULL || out_size == 0) return 0;
    out[0] = '\0';

    while (1) {
        char ch = *line;

        if (field_index == target_index && ch != '\0' && ch != '\n' && ch != '\r' && ch != '|') {
            if (out_pos + 1 < out_size) {
                out[out_pos++] = ch;
            }
        }

        if (ch == '|' || ch == '\0' || ch == '\n' || ch == '\r') {
            if (field_index == target_index) {
                out[out_pos] = '\0';
                return 1;
            }
            if (ch == '|') {
                field_index++;
                line++;
                continue;
            }
            break;
        }

        line++;
    }

    return 0;
}

static int append_line(const char *path, const char *line) {
    FILE *fp = fopen(path, "a");
    if (fp == NULL) return 0;
    fprintf(fp, "%s\n", line ? line : "");
    fclose(fp);
    return 1;
}

static int replace_file(const char *source_path, const char *temp_path) {
    remove(source_path);
    if (rename(temp_path, source_path) != 0) {
        remove(temp_path);
        return 0;
    }
    return 1;
}

static int next_advance_id(void) {
    FILE *fp = fopen(ADVANCE_FILE, "r");
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];
    int max_id = 0;

    if (fp == NULL) return 1;

    while (fgets(line, sizeof(line), fp)) {
        if (extract_field(line, 0, field, sizeof(field))) {
            int current = atoi(field);
            if (current > max_id) max_id = current;
        }
    }

    fclose(fp);
    return max_id + 1;
}

static int list_file(const char *path) {
    FILE *fp = fopen(path, "r");
    char line[FIELD_BUFFER];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        printf("%s", line);
    }

    fclose(fp);
    return 1;
}

static int find_advance_by_id(int advance_id) {
    FILE *fp = fopen(ADVANCE_FILE, "r");
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (extract_field(line, 0, field, sizeof(field)) && atoi(field) == advance_id) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

static int find_advance_by_appointment_id(int appointment_id) {
    FILE *fp = fopen(ADVANCE_FILE, "r");
    char line[FIELD_BUFFER];
    char appointment_field[FIELD_BUFFER];
    char status_field[FIELD_BUFFER];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (!extract_field(line, 2, appointment_field, sizeof(appointment_field))) continue;
        if (atoi(appointment_field) != appointment_id) continue;
        if (!extract_field(line, 6, status_field, sizeof(status_field))) continue;
        if (strcmp(status_field, "PAID") == 0 || strcmp(status_field, "PENDING_PAYMENT") == 0) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

static int find_advance_by_order_id(const char *order_id) {
    FILE *fp = fopen(ADVANCE_FILE, "r");
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (!extract_field(line, 7, field, sizeof(field))) continue;
        if (strcmp(field, order_id ? order_id : "") == 0) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

static int update_advance_line(int advance_id, const char *serialized_line) {
    FILE *src = fopen(ADVANCE_FILE, "r");
    FILE *tmp;
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];
    int updated = 0;

    if (src == NULL) return 0;

    tmp = fopen(ADVANCE_TEMP_FILE, "w");
    if (tmp == NULL) {
        fclose(src);
        return 0;
    }

    while (fgets(line, sizeof(line), src)) {
        if (extract_field(line, 0, field, sizeof(field)) && atoi(field) == advance_id) {
            fprintf(tmp, "%s\n", serialized_line ? serialized_line : "");
            updated = 1;
        } else {
            fputs(line, tmp);
        }
    }

    fclose(src);
    fclose(tmp);

    if (!updated) {
        remove(ADVANCE_TEMP_FILE);
        return 0;
    }

    return replace_file(ADVANCE_FILE, ADVANCE_TEMP_FILE);
}

static int pop_booking_intent(int advance_id) {
    FILE *src = fopen(BOOKING_INTENT_FILE, "r");
    FILE *tmp;
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];
    char found[FIELD_BUFFER];
    int matched = 0;

    if (src == NULL) return 0;

    tmp = fopen(BOOKING_INTENT_TEMP_FILE, "w");
    if (tmp == NULL) {
        fclose(src);
        return 0;
    }

    found[0] = '\0';
    while (fgets(line, sizeof(line), src)) {
        if (extract_field(line, 0, field, sizeof(field)) && atoi(field) == advance_id) {
            safe_copy(found, line, sizeof(found));
            strip_newline(found);
            matched = 1;
        } else {
            fputs(line, tmp);
        }
    }

    fclose(src);
    fclose(tmp);

    if (!replace_file(BOOKING_INTENT_FILE, BOOKING_INTENT_TEMP_FILE)) {
        return 0;
    }

    if (!matched) return 0;

    printf("%s", found);
    return 1;
}

/* Find a booking intent by advance_id WITHOUT removing it from the file.
   Prints the matching line to stdout. Returns 1 if found, 0 otherwise. */
static int find_booking_intent(int advance_id) {
    FILE *fp = fopen(BOOKING_INTENT_FILE, "r");
    char line[FIELD_BUFFER];
    char field[FIELD_BUFFER];
    if (fp == NULL) return 0;
    while (fgets(line, sizeof(line), fp)) {
        if (extract_field(line, 0, field, sizeof(field)) && atoi(field) == advance_id) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }
    fclose(fp);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Error|InvalidInput");
        return 1;
    }

    if (strcmp(argv[1], "next-id") == 0) {
        printf("%d", next_advance_id());
        return 0;
    }

    if (strcmp(argv[1], "list") == 0) {
        list_file(ADVANCE_FILE);
        return 0;
    }

    if (strcmp(argv[1], "find-id") == 0 && argc == 3) {
        return find_advance_by_id(atoi(argv[2])) ? 0 : 1;
    }

    if (strcmp(argv[1], "find-appointment") == 0 && argc == 3) {
        return find_advance_by_appointment_id(atoi(argv[2])) ? 0 : 1;
    }

    if (strcmp(argv[1], "find-order") == 0 && argc == 3) {
        return find_advance_by_order_id(argv[2]) ? 0 : 1;
    }

    if (strcmp(argv[1], "save") == 0 && argc == 3) {
        if (append_line(ADVANCE_FILE, argv[2])) {
            printf("SAVED");
            return 0;
        }
        printf("Error|SaveFailed");
        return 1;
    }

    if (strcmp(argv[1], "update") == 0 && argc == 4) {
        if (update_advance_line(atoi(argv[2]), argv[3])) {
            printf("UPDATED");
            return 0;
        }
        printf("Error|UpdateFailed");
        return 1;
    }

    /* Booking intent commands (spec names) */
    if ((strcmp(argv[1], "intent-save") == 0 || strcmp(argv[1], "save-intent") == 0) && argc == 3) {
        if (append_line(BOOKING_INTENT_FILE, argv[2])) {
            printf("SAVED");
            return 0;
        }
        printf("Error|SaveFailed");
        return 1;
    }

    if ((strcmp(argv[1], "intent-pop") == 0 || strcmp(argv[1], "pop-intent") == 0) && argc == 3) {
        return pop_booking_intent(atoi(argv[2])) ? 0 : 1;
    }

    if (strcmp(argv[1], "intent-find") == 0 && argc == 3) {
        return find_booking_intent(atoi(argv[2])) ? 0 : 1;
    }

    printf("Error|InvalidCommand");
    return 1;
}
