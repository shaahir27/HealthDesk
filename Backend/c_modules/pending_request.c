#include "common.h"
#include <time.h>

#define MAX_PENDING_FIELDS 12
#define MAX_NEW_FIELDS 19
#define EXPIRY_SECONDS 7200

static PendingAppointmentRequest *pending_head = NULL;
static NewPatientRequest *new_head = NULL;

static void safe_copy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

static void clean_field(char *dest, const char *src, size_t dest_size) {
    size_t i = 0;
    size_t j = 0;
    if (dest_size == 0) return;
    while (src && src[i] != '\0' && j + 1 < dest_size) {
        char ch = src[i++];
        if (ch == '|') ch = '/';
        if (ch == '\r' || ch == '\n') ch = ' ';
        dest[j++] = ch;
    }
    while (j > 0 && (dest[j - 1] == ' ' || dest[j - 1] == '\t')) j--;
    dest[j] = '\0';
}

static int split_preserve_empty(const char *line, char fields[][MAX_LINE], int max_fields) {
    int count = 0;
    int pos = 0;
    const char *p = line;

    if (max_fields <= 0) return 0;
    fields[0][0] = '\0';

    while (*p != '\0' && *p != '\n' && *p != '\r') {
        if (*p == '|') {
            fields[count][pos] = '\0';
            count++;
            if (count >= max_fields) return count;
            pos = 0;
            fields[count][0] = '\0';
        } else if (pos + 1 < MAX_LINE) {
            fields[count][pos++] = *p;
        }
        p++;
    }

    fields[count][pos] = '\0';
    return count + 1;
}

static void iso_now(char *dest, size_t dest_size, int plus_seconds) {
    time_t raw = time(NULL) + plus_seconds;
    struct tm *tm_info = localtime(&raw);
    if (tm_info == NULL) {
        safe_copy(dest, "", dest_size);
        return;
    }
    strftime(dest, dest_size, "%Y-%m-%dT%H:%M:%S", tm_info);
}

static time_t parse_iso_time(const char *value) {
    int y, m, d, hh, mm, ss;
    struct tm tm_value;
    memset(&tm_value, 0, sizeof(tm_value));

    if (sscanf(value ? value : "", "%4d-%2d-%2dT%2d:%2d:%2d", &y, &m, &d, &hh, &mm, &ss) != 6) {
        return (time_t)-1;
    }

    tm_value.tm_year = y - 1900;
    tm_value.tm_mon = m - 1;
    tm_value.tm_mday = d;
    tm_value.tm_hour = hh;
    tm_value.tm_min = mm;
    tm_value.tm_sec = ss;
    tm_value.tm_isdst = -1;
    return mktime(&tm_value);
}

static PendingAppointmentRequest *alloc_pending(void) {
    PendingAppointmentRequest *row = malloc(sizeof(PendingAppointmentRequest));
    if (row != NULL) memset(row, 0, sizeof(PendingAppointmentRequest));
    return row;
}

static NewPatientRequest *alloc_new(void) {
    NewPatientRequest *row = malloc(sizeof(NewPatientRequest));
    if (row != NULL) memset(row, 0, sizeof(NewPatientRequest));
    return row;
}

static void append_pending_node(PendingAppointmentRequest *row) {
    PendingAppointmentRequest *cur;
    row->next = NULL;
    if (pending_head == NULL) {
        pending_head = row;
        return;
    }
    cur = pending_head;
    while (cur->next != NULL) cur = cur->next;
    cur->next = row;
}

static void append_new_node(NewPatientRequest *row) {
    NewPatientRequest *cur;
    row->next = NULL;
    if (new_head == NULL) {
        new_head = row;
        return;
    }
    cur = new_head;
    while (cur->next != NULL) cur = cur->next;
    cur->next = row;
}

static int parse_pending_line(const char *line, PendingAppointmentRequest *row) {
    char fields[MAX_PENDING_FIELDS][MAX_LINE];
    if (split_preserve_empty(line, fields, MAX_PENDING_FIELDS) < MAX_PENDING_FIELDS) return 0;

    row->request_id = atoi(fields[0]);
    row->patient_id = atoi(fields[1]);
    row->doctor_id = atoi(fields[2]);
    safe_copy(row->requested_date, fields[3], sizeof(row->requested_date));
    safe_copy(row->requested_slot, fields[4], sizeof(row->requested_slot));
    safe_copy(row->reason, fields[5], sizeof(row->reason));
    safe_copy(row->visit_type, fields[6], sizeof(row->visit_type));
    safe_copy(row->status, fields[7], sizeof(row->status));
    safe_copy(row->submitted_at, fields[8], sizeof(row->submitted_at));
    safe_copy(row->expires_at, fields[9], sizeof(row->expires_at));
    safe_copy(row->receptionist_note, fields[10], sizeof(row->receptionist_note));
    row->appointment_id = atoi(fields[11]);
    return row->request_id > 0;
}

static int parse_new_line(const char *line, NewPatientRequest *row) {
    char fields[MAX_NEW_FIELDS][MAX_LINE];
    if (split_preserve_empty(line, fields, MAX_NEW_FIELDS) < MAX_NEW_FIELDS) return 0;

    row->request_id = atoi(fields[0]);
    safe_copy(row->name, fields[1], sizeof(row->name));
    safe_copy(row->age, fields[2], sizeof(row->age));
    safe_copy(row->gender, fields[3], sizeof(row->gender));
    safe_copy(row->phone, fields[4], sizeof(row->phone));
    safe_copy(row->address, fields[5], sizeof(row->address));
    safe_copy(row->department, fields[6], sizeof(row->department));
    row->doctor_id = atoi(fields[7]);
    safe_copy(row->requested_date, fields[8], sizeof(row->requested_date));
    safe_copy(row->requested_slot, fields[9], sizeof(row->requested_slot));
    safe_copy(row->reason, fields[10], sizeof(row->reason));
    safe_copy(row->visit_type, fields[11], sizeof(row->visit_type));
    safe_copy(row->priority, fields[12], sizeof(row->priority));
    safe_copy(row->status, fields[13], sizeof(row->status));
    safe_copy(row->submitted_at, fields[14], sizeof(row->submitted_at));
    safe_copy(row->expires_at, fields[15], sizeof(row->expires_at));
    safe_copy(row->receptionist_note, fields[16], sizeof(row->receptionist_note));
    row->patient_id = atoi(fields[17]);
    row->appointment_id = atoi(fields[18]);
    return row->request_id > 0;
}

static void print_pending_record(PendingAppointmentRequest *row) {
    printf("%d|%d|%d|%s|%s|%s|%s|%s|%s|%s|%s|%d",
        row->request_id, row->patient_id, row->doctor_id,
        row->requested_date, row->requested_slot, row->reason,
        row->visit_type, row->status, row->submitted_at, row->expires_at,
        row->receptionist_note, row->appointment_id);
}

static void print_new_record(NewPatientRequest *row) {
    printf("%d|%s|%s|%s|%s|%s|%s|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%d|%d",
        row->request_id, row->name, row->age, row->gender, row->phone,
        row->address, row->department, row->doctor_id, row->requested_date,
        row->requested_slot, row->reason, row->visit_type, row->priority,
        row->status, row->submitted_at, row->expires_at,
        row->receptionist_note, row->patient_id, row->appointment_id);
}

static void load_pending(void) {
    FILE *fp = fopen(PENDING_APPOINTMENTS_FILE, "r");
    char line[MAX_LINE * 2];
    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        PendingAppointmentRequest *row = alloc_pending();
        if (row != NULL && parse_pending_line(line, row)) {
            append_pending_node(row);
        } else if (row != NULL) {
            free(row);
        }
    }
    fclose(fp);
}

static void load_new(void) {
    FILE *fp = fopen(NEW_PATIENT_REQUESTS_FILE, "r");
    char line[MAX_LINE * 2];
    if (fp == NULL) return;

    while (fgets(line, sizeof(line), fp)) {
        NewPatientRequest *row = alloc_new();
        if (row != NULL && parse_new_line(line, row)) {
            append_new_node(row);
        } else if (row != NULL) {
            free(row);
        }
    }
    fclose(fp);
}

static int save_pending(void) {
    FILE *fp = fopen(PENDING_APPOINTMENTS_FILE, "w");
    PendingAppointmentRequest *cur;
    if (fp == NULL) return 0;

    cur = pending_head;
    while (cur != NULL) {
        fprintf(fp, "%d|%d|%d|%s|%s|%s|%s|%s|%s|%s|%s|%d\n",
            cur->request_id, cur->patient_id, cur->doctor_id,
            cur->requested_date, cur->requested_slot, cur->reason,
            cur->visit_type, cur->status, cur->submitted_at, cur->expires_at,
            cur->receptionist_note, cur->appointment_id);
        cur = cur->next;
    }
    fclose(fp);
    return 1;
}

static int save_new(void) {
    FILE *fp = fopen(NEW_PATIENT_REQUESTS_FILE, "w");
    NewPatientRequest *cur;
    if (fp == NULL) return 0;

    cur = new_head;
    while (cur != NULL) {
        fprintf(fp, "%d|%s|%s|%s|%s|%s|%s|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%d|%d\n",
            cur->request_id, cur->name, cur->age, cur->gender, cur->phone,
            cur->address, cur->department, cur->doctor_id, cur->requested_date,
            cur->requested_slot, cur->reason, cur->visit_type, cur->priority,
            cur->status, cur->submitted_at, cur->expires_at,
            cur->receptionist_note, cur->patient_id, cur->appointment_id);
        cur = cur->next;
    }
    fclose(fp);
    return 1;
}

static int next_pending_id(void) {
    int max_id = 0;
    PendingAppointmentRequest *cur = pending_head;
    while (cur != NULL) {
        if (cur->request_id > max_id) max_id = cur->request_id;
        cur = cur->next;
    }
    return max_id + 1;
}

static int next_new_id(void) {
    int max_id = 0;
    NewPatientRequest *cur = new_head;
    while (cur != NULL) {
        if (cur->request_id > max_id) max_id = cur->request_id;
        cur = cur->next;
    }
    return max_id + 1;
}

static void free_all(void) {
    PendingAppointmentRequest *p = pending_head;
    NewPatientRequest *n = new_head;
    while (p != NULL) {
        PendingAppointmentRequest *next = p->next;
        free(p);
        p = next;
    }
    while (n != NULL) {
        NewPatientRequest *next = n->next;
        free(n);
        n = next;
    }
}

static int is_unexpired_pending(const char *status, const char *expires_at) {
    time_t expiry;
    if (strcmp(status, "Pending") != 0) return 0;
    expiry = parse_iso_time(expires_at);
    if (expiry == (time_t)-1) return 1;
    return expiry > time(NULL);
}

static int command_list_existing(void) {
    PendingAppointmentRequest *cur;
    load_pending();
    cur = pending_head;
    while (cur != NULL) {
        print_pending_record(cur);
        printf("\n");
        cur = cur->next;
    }
    return 0;
}

static int command_list_new(void) {
    NewPatientRequest *cur;
    load_new();
    cur = new_head;
    while (cur != NULL) {
        print_new_record(cur);
        printf("\n");
        cur = cur->next;
    }
    return 0;
}

static int command_add_existing(int argc, char *argv[]) {
    PendingAppointmentRequest *row;
    if (argc < 11) {
        printf("ERROR|InvalidInput");
        return 1;
    }
    load_pending();
    row = alloc_pending();
    if (row == NULL) {
        printf("ERROR|MemoryAllocationFailed");
        return 1;
    }
    row->request_id = next_pending_id();
    row->patient_id = atoi(argv[2]);
    row->doctor_id = atoi(argv[3]);
    clean_field(row->requested_date, argv[4], sizeof(row->requested_date));
    clean_field(row->requested_slot, argv[5], sizeof(row->requested_slot));
    clean_field(row->reason, argv[6], sizeof(row->reason));
    clean_field(row->visit_type, argv[7], sizeof(row->visit_type));
    clean_field(row->status, argv[8], sizeof(row->status));
    clean_field(row->receptionist_note, argv[9], sizeof(row->receptionist_note));
    row->appointment_id = atoi(argv[10]);
    iso_now(row->submitted_at, sizeof(row->submitted_at), 0);
    iso_now(row->expires_at, sizeof(row->expires_at), EXPIRY_SECONDS);
    append_pending_node(row);
    if (!save_pending()) {
        printf("ERROR|CannotWriteFile");
        return 1;
    }
    printf("ADDED|");
    print_pending_record(row);
    return 0;
}

static int command_add_new(int argc, char *argv[]) {
    NewPatientRequest *row;
    if (argc < 14) {
        printf("ERROR|InvalidInput");
        return 1;
    }
    load_new();
    row = alloc_new();
    if (row == NULL) {
        printf("ERROR|MemoryAllocationFailed");
        return 1;
    }
    row->request_id = next_new_id();
    clean_field(row->name, argv[2], sizeof(row->name));
    clean_field(row->age, argv[3], sizeof(row->age));
    clean_field(row->gender, argv[4], sizeof(row->gender));
    clean_field(row->phone, argv[5], sizeof(row->phone));
    clean_field(row->address, argv[6], sizeof(row->address));
    clean_field(row->department, argv[7], sizeof(row->department));
    row->doctor_id = atoi(argv[8]);
    clean_field(row->requested_date, argv[9], sizeof(row->requested_date));
    clean_field(row->requested_slot, argv[10], sizeof(row->requested_slot));
    clean_field(row->reason, argv[11], sizeof(row->reason));
    clean_field(row->visit_type, argv[12], sizeof(row->visit_type));
    clean_field(row->priority, argv[13], sizeof(row->priority));
    clean_field(row->status, "Pending", sizeof(row->status));
    iso_now(row->submitted_at, sizeof(row->submitted_at), 0);
    iso_now(row->expires_at, sizeof(row->expires_at), EXPIRY_SECONDS);
    append_new_node(row);
    if (!save_new()) {
        printf("ERROR|CannotWriteFile");
        return 1;
    }
    printf("ADDED|");
    print_new_record(row);
    return 0;
}

static int command_update_existing(int argc, char *argv[]) {
    int request_id;
    PendingAppointmentRequest *cur;
    if (argc < 6) {
        printf("ERROR|InvalidInput");
        return 1;
    }
    request_id = atoi(argv[2]);
    load_pending();
    cur = pending_head;
    while (cur != NULL) {
        if (cur->request_id == request_id) {
            clean_field(cur->status, argv[3], sizeof(cur->status));
            if (strlen(argv[4]) > 0) clean_field(cur->receptionist_note, argv[4], sizeof(cur->receptionist_note));
            cur->appointment_id = atoi(argv[5]);
            if (!save_pending()) {
                printf("ERROR|CannotWriteFile");
                return 1;
            }
            printf("UPDATED|");
            print_pending_record(cur);
            return 0;
        }
        cur = cur->next;
    }
    printf("NOT_FOUND");
    return 0;
}

static int command_update_new(int argc, char *argv[]) {
    int request_id;
    NewPatientRequest *cur;
    if (argc < 7) {
        printf("ERROR|InvalidInput");
        return 1;
    }
    request_id = atoi(argv[2]);
    load_new();
    cur = new_head;
    while (cur != NULL) {
        if (cur->request_id == request_id) {
            clean_field(cur->status, argv[3], sizeof(cur->status));
            if (strlen(argv[4]) > 0) clean_field(cur->receptionist_note, argv[4], sizeof(cur->receptionist_note));
            cur->patient_id = atoi(argv[5]);
            cur->appointment_id = atoi(argv[6]);
            if (!save_new()) {
                printf("ERROR|CannotWriteFile");
                return 1;
            }
            printf("UPDATED|");
            print_new_record(cur);
            return 0;
        }
        cur = cur->next;
    }
    printf("NOT_FOUND");
    return 0;
}

static int command_soft_lock_exists(int argc, char *argv[]) {
    int doctor_id;
    PendingAppointmentRequest *p;
    NewPatientRequest *n;
    if (argc < 5) {
        printf("ERROR|InvalidInput");
        return 1;
    }
    doctor_id = atoi(argv[2]);
    load_pending();
    load_new();

    p = pending_head;
    while (p != NULL) {
        if (p->doctor_id == doctor_id &&
            strcmp(p->requested_date, argv[3]) == 0 &&
            strcmp(p->requested_slot, argv[4]) == 0 &&
            is_unexpired_pending(p->status, p->expires_at)) {
            printf("EXISTS");
            return 0;
        }
        p = p->next;
    }

    n = new_head;
    while (n != NULL) {
        if (n->doctor_id == doctor_id &&
            strcmp(n->requested_date, argv[3]) == 0 &&
            strcmp(n->requested_slot, argv[4]) == 0 &&
            is_unexpired_pending(n->status, n->expires_at)) {
            printf("EXISTS");
            return 0;
        }
        n = n->next;
    }

    printf("NOT_FOUND");
    return 0;
}

static int command_expire(void) {
    int pending_changed = 0;
    int new_changed = 0;
    time_t now = time(NULL);
    PendingAppointmentRequest *p;
    NewPatientRequest *n;

    load_pending();
    load_new();

    p = pending_head;
    while (p != NULL) {
        time_t expiry = parse_iso_time(p->expires_at);
        if (strcmp(p->status, "Pending") == 0 && expiry != (time_t)-1 && expiry <= now) {
            clean_field(p->status, "Expired", sizeof(p->status));
            clean_field(p->receptionist_note, "Request expired before it was confirmed. Please book again.", sizeof(p->receptionist_note));
            printf("EXPIRED_EXISTING|");
            print_pending_record(p);
            printf("\n");
            pending_changed = 1;
        }
        p = p->next;
    }

    n = new_head;
    while (n != NULL) {
        time_t expiry = parse_iso_time(n->expires_at);
        if (strcmp(n->status, "Pending") == 0 && expiry != (time_t)-1 && expiry <= now) {
            clean_field(n->status, "Expired", sizeof(n->status));
            clean_field(n->receptionist_note, "Request expired before it was confirmed. Please submit again.", sizeof(n->receptionist_note));
            printf("EXPIRED_NEW|");
            print_new_record(n);
            printf("\n");
            new_changed = 1;
        }
        n = n->next;
    }

    if (pending_changed && !save_pending()) {
        printf("ERROR|CannotWritePendingFile\n");
        return 1;
    }
    if (new_changed && !save_new()) {
        printf("ERROR|CannotWriteNewFile\n");
        return 1;
    }
    return 0;
}

int main(int argc, char *argv[]) {
    int result;
    if (argc < 2) {
        printf("ERROR|MissingCommand");
        return 1;
    }

    if (strcmp(argv[1], "list-existing") == 0) result = command_list_existing();
    else if (strcmp(argv[1], "list-new") == 0) result = command_list_new();
    else if (strcmp(argv[1], "add-existing") == 0) result = command_add_existing(argc, argv);
    else if (strcmp(argv[1], "add-new") == 0) result = command_add_new(argc, argv);
    else if (strcmp(argv[1], "update-existing") == 0) result = command_update_existing(argc, argv);
    else if (strcmp(argv[1], "update-new") == 0) result = command_update_new(argc, argv);
    else if (strcmp(argv[1], "soft-lock-exists") == 0) result = command_soft_lock_exists(argc, argv);
    else if (strcmp(argv[1], "expire") == 0) result = command_expire();
    else {
        printf("ERROR|UnknownCommand");
        result = 1;
    }

    free_all();
    return result;
}
