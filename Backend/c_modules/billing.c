#include "common.h"

#define BILLING_FIELD_COUNT 19

void safeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

int nextBillId() {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];
    int max_id = 999;

    if (fp == NULL) {
        return max_id + 1;
    }

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;
        int bill_id;

        safeCopy(buffer, line, sizeof(buffer));
        token = strtok(buffer, "|");
        if (token == NULL) continue;

        bill_id = atoi(token);
        if (bill_id > max_id) {
            max_id = bill_id;
        }
    }

    fclose(fp);
    return max_id + 1;
}

int extractFieldPreserveEmpty(const char *line, int target_index, char *out, size_t out_size) {
    int field_index = 0;
    size_t out_pos = 0;

    if (out_size == 0) return 0;
    out[0] = '\0';

    while (1) {
        char ch = *line;

        if (field_index == target_index && ch != '\0' && ch != '\n' && ch != '|') {
            if (out_pos + 1 < out_size) {
                out[out_pos++] = ch;
            }
        }

        if (ch == '|' || ch == '\n' || ch == '\0') {
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

int parseAppointmentId(const char *line) {
    char field_value[MAX_LINE];

    if (extractFieldPreserveEmpty(line, 18, field_value, sizeof(field_value))) {
        return atoi(field_value);
    }

    return 0;
}

void listBills() {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        printf("%s", line);
    }

    fclose(fp);
}

int findBillById(int bill_id) {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;

        safeCopy(buffer, line, sizeof(buffer));
        token = strtok(buffer, "|");
        if (token == NULL) continue;

        if (atoi(token) == bill_id) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int findBillByAppointmentId(int appointment_id) {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (parseAppointmentId(line) == appointment_id) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int findBillByOrderId(const char *order_id) {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];
    char field_value[MAX_LINE];

    if (fp == NULL) return 0;

    while (fgets(line, sizeof(line), fp)) {
        if (!extractFieldPreserveEmpty(line, 19, field_value, sizeof(field_value))) continue;
        if (strcmp(field_value, order_id ? order_id : "") == 0) {
            printf("%s", line);
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

int saveBillLine(const char *serialized_line) {
    FILE *fp = fopen(BILLING_FILE, "a");

    if (fp == NULL) return 0;

    fprintf(fp, "%s\n", serialized_line);
    fclose(fp);
    return 1;
}

int updateBillLine(int bill_id, const char *serialized_line) {
    FILE *src = fopen(BILLING_FILE, "r");
    FILE *tmp;
    char line[MAX_LINE];
    char buffer[MAX_LINE];
    char *token;
    int updated = 0;

    if (src == NULL) return 0;

    tmp = fopen("Backend/data/billing.tmp", "w");
    if (tmp == NULL) {
        fclose(src);
        return 0;
    }

    while (fgets(line, sizeof(line), src)) {
        safeCopy(buffer, line, sizeof(buffer));
        token = strtok(buffer, "|");
        if (token != NULL && atoi(token) == bill_id) {
            fprintf(tmp, "%s\n", serialized_line ? serialized_line : "");
            updated = 1;
        } else {
            fputs(line, tmp);
        }
    }

    fclose(src);
    fclose(tmp);

    if (!updated) {
        remove("Backend/data/billing.tmp");
        return 0;
    }

    remove(BILLING_FILE);
    if (rename("Backend/data/billing.tmp", BILLING_FILE) != 0) {
        remove("Backend/data/billing.tmp");
        return 0;
    }

    return 1;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Error|InvalidInput");
        return 1;
    }

    if (strcmp(argv[1], "next-id") == 0) {
        printf("%d", nextBillId());
        return 0;
    }

    if (strcmp(argv[1], "list") == 0) {
        listBills();
        return 0;
    }

    if (strcmp(argv[1], "find-id") == 0 && argc == 3) {
        return findBillById(atoi(argv[2])) ? 0 : 1;
    }

    if (strcmp(argv[1], "find-appointment") == 0 && argc == 3) {
        return findBillByAppointmentId(atoi(argv[2])) ? 0 : 1;
    }

    if (strcmp(argv[1], "find-order") == 0 && argc == 3) {
        return findBillByOrderId(argv[2]) ? 0 : 1;
    }

    if (strcmp(argv[1], "save") == 0 && argc == 3) {
        if (saveBillLine(argv[2])) {
            printf("SAVED");
            return 0;
        }
        printf("Error|SaveFailed");
        return 1;
    }

    if (strcmp(argv[1], "update") == 0 && argc == 4) {
        if (updateBillLine(atoi(argv[2]), argv[3])) {
            printf("UPDATED");
            return 0;
        }
        printf("Error|UpdateFailed");
        return 1;
    }

    printf("Error|InvalidCommand");
    return 1;
}
