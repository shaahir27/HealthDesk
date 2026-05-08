#include "common.h"
#include <time.h>

#define MAX_APPOINTMENTS 50000
#define SLOT_COUNT 8
#define APPOINTMENT_STACK_FILE "Backend/data/appointment_action_stack.txt"

struct AppointmentAction {
    char timestamp[40];
    char action[32];
    int old_appointment_id;
    int old_patient_id;
    int old_doctor_id;
    char old_date[20];
    char old_time_slot[20];
    char old_status[MAX_SMALL];
    int new_appointment_id;
    char new_date[20];
    char new_time_slot[20];
    char new_status[MAX_SMALL];
};

struct AppointmentActionNode {
    struct AppointmentAction data;
    struct AppointmentActionNode *next;
};

const char *DEFAULT_SLOTS[SLOT_COUNT] = {
    "08:30 AM", "09:30 AM", "10:30 AM", "11:40 AM",
    "02:00 PM", "04:00 PM", "06:00 PM", "08:05 PM"
};

void safeCopyAppointment(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

void printAppointmentAction(struct AppointmentAction action) {
    printf("%s|%s|%d|%d|%d|%s|%s|%s|%d|%s|%s|%s\n",
        action.timestamp,
        action.action,
        action.old_appointment_id,
        action.old_patient_id,
        action.old_doctor_id,
        action.old_date,
        action.old_time_slot,
        action.old_status,
        action.new_appointment_id,
        action.new_date,
        action.new_time_slot,
        action.new_status
    );
}

int extractAppointmentActionField(const char *line, int target_index, char *out, size_t out_size) {
    int field_index = 0;
    size_t out_pos = 0;

    if (line == NULL || out_size == 0) return 0;
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

int parseAppointmentActionLine(char *line, struct AppointmentAction *action) {
    char field[MAX_LINE];

    if (line == NULL || action == NULL) return 0;
    memset(action, 0, sizeof(*action));

    if (!extractAppointmentActionField(line, 0, action->timestamp, sizeof(action->timestamp))) return 0;
    if (!extractAppointmentActionField(line, 1, action->action, sizeof(action->action))) return 0;
    if (!extractAppointmentActionField(line, 2, field, sizeof(field))) return 0;
    action->old_appointment_id = atoi(field);
    if (!extractAppointmentActionField(line, 3, field, sizeof(field))) return 0;
    action->old_patient_id = atoi(field);
    if (!extractAppointmentActionField(line, 4, field, sizeof(field))) return 0;
    action->old_doctor_id = atoi(field);
    if (!extractAppointmentActionField(line, 5, action->old_date, sizeof(action->old_date))) return 0;
    if (!extractAppointmentActionField(line, 6, action->old_time_slot, sizeof(action->old_time_slot))) return 0;
    if (!extractAppointmentActionField(line, 7, action->old_status, sizeof(action->old_status))) return 0;
    if (!extractAppointmentActionField(line, 8, field, sizeof(field))) return 0;
    action->new_appointment_id = atoi(field);
    if (!extractAppointmentActionField(line, 9, action->new_date, sizeof(action->new_date))) return 0;
    if (!extractAppointmentActionField(line, 10, action->new_time_slot, sizeof(action->new_time_slot))) return 0;
    if (!extractAppointmentActionField(line, 11, action->new_status, sizeof(action->new_status))) return 0;

    return 1;
}

int stackPushNode(struct AppointmentActionNode **top, struct AppointmentAction action) {
    struct AppointmentActionNode *node = malloc(sizeof(struct AppointmentActionNode));
    if (node == NULL) return 0;

    node->data = action;
    node->next = *top;
    *top = node;
    return 1;
}

void freeAppointmentActionStack(struct AppointmentActionNode *top) {
    while (top != NULL) {
        struct AppointmentActionNode *next = top->next;
        free(top);
        top = next;
    }
}

struct AppointmentActionNode* reverseAppointmentActionStack(struct AppointmentActionNode *top) {
    struct AppointmentActionNode *prev = NULL;
    struct AppointmentActionNode *current = top;

    while (current != NULL) {
        struct AppointmentActionNode *next = current->next;
        current->next = prev;
        prev = current;
        current = next;
    }

    return prev;
}

struct AppointmentActionNode* loadAppointmentActionStack(void) {
    FILE *fp = fopen(APPOINTMENT_STACK_FILE, "r");
    char line[MAX_LINE];
    struct AppointmentActionNode *top = NULL;

    if (fp == NULL) return NULL;

    while (fgets(line, sizeof(line), fp)) {
        struct AppointmentAction action;
        if (parseAppointmentActionLine(line, &action)) {
            stackPushNode(&top, action);
        }
    }

    fclose(fp);
    return top;
}

void saveAppointmentActionStack(struct AppointmentActionNode *top) {
    FILE *fp;
    struct AppointmentActionNode *oldest_first = reverseAppointmentActionStack(top);
    struct AppointmentActionNode *current = oldest_first;

    fp = fopen(APPOINTMENT_STACK_FILE, "w");
    if (fp == NULL) {
        reverseAppointmentActionStack(oldest_first);
        return;
    }

    while (current != NULL) {
        fprintf(fp, "%s|%s|%d|%d|%d|%s|%s|%s|%d|%s|%s|%s\n",
            current->data.timestamp,
            current->data.action,
            current->data.old_appointment_id,
            current->data.old_patient_id,
            current->data.old_doctor_id,
            current->data.old_date,
            current->data.old_time_slot,
            current->data.old_status,
            current->data.new_appointment_id,
            current->data.new_date,
            current->data.new_time_slot,
            current->data.new_status
        );
        current = current->next;
    }

    fclose(fp);
    reverseAppointmentActionStack(oldest_first);
}

void pushAppointmentAction(const char *action_name, struct Appointment old_appt,
                           int new_appointment_id, const char *new_date,
                           const char *new_time, const char *new_status) {
    struct AppointmentActionNode *top = loadAppointmentActionStack();
    struct AppointmentAction action;
    time_t now;
    struct tm *tm_now;

    memset(&action, 0, sizeof(action));
    now = time(NULL);
    tm_now = localtime(&now);
    if (tm_now != NULL) {
        strftime(action.timestamp, sizeof(action.timestamp), "%Y-%m-%dT%H:%M:%S", tm_now);
    }

    safeCopyAppointment(action.action, action_name, sizeof(action.action));
    action.old_appointment_id = old_appt.appointment_id;
    action.old_patient_id = old_appt.patient_id;
    action.old_doctor_id = old_appt.doctor_id;
    safeCopyAppointment(action.old_date, old_appt.date, sizeof(action.old_date));
    safeCopyAppointment(action.old_time_slot, old_appt.time_slot, sizeof(action.old_time_slot));
    safeCopyAppointment(action.old_status, old_appt.status, sizeof(action.old_status));
    action.new_appointment_id = new_appointment_id;
    safeCopyAppointment(action.new_date, new_date, sizeof(action.new_date));
    safeCopyAppointment(action.new_time_slot, new_time, sizeof(action.new_time_slot));
    safeCopyAppointment(action.new_status, new_status, sizeof(action.new_status));

    if (stackPushNode(&top, action)) {
        saveAppointmentActionStack(top);
    }
    freeAppointmentActionStack(top);
}

void printAppointmentActionStack(void) {
    struct AppointmentActionNode *top = loadAppointmentActionStack();
    struct AppointmentActionNode *oldest_first = reverseAppointmentActionStack(top);
    struct AppointmentActionNode *current = oldest_first;

    while (current != NULL) {
        printAppointmentAction(current->data);
        current = current->next;
    }

    reverseAppointmentActionStack(oldest_first);
    freeAppointmentActionStack(top);
}

void peekAppointmentActionStack(void) {
    struct AppointmentActionNode *top = loadAppointmentActionStack();

    if (top != NULL) {
        printAppointmentAction(top->data);
    }

    freeAppointmentActionStack(top);
}

int validSlot(const char *time_slot) {
    int i;
    for (i = 0; i < SLOT_COUNT; i++) {
        if (strcmp(DEFAULT_SLOTS[i], time_slot) == 0) return 1;
    }
    return 0;
}

int validDate(const char *date) {
    int y, m, d;
    char tail;
    if (sscanf(date, "%4d-%2d-%2d%c", &y, &m, &d, &tail) != 3) return 0;
    if (y < 1900 || m < 1 || m > 12 || d < 1 || d > 31) return 0;
    if ((m == 4 || m == 6 || m == 9 || m == 11) && d > 30) return 0;
    if (m == 2) {
        int leap = (y % 400 == 0) || (y % 4 == 0 && y % 100 != 0);
        if (d > (leap ? 29 : 28)) return 0;
    }

    time_t now = time(NULL);
    struct tm *today = localtime(&now);
    if (today == NULL) return 0;

    if (y < today->tm_year + 1900) return 0;
    if (y == today->tm_year + 1900 && m < today->tm_mon + 1) return 0;
    if (y == today->tm_year + 1900 && m == today->tm_mon + 1 && d < today->tm_mday) return 0;
    return 1;
}

int generateAppointmentId() {
    FILE *fp = fopen(APPOINTMENT_FILE, "r");
    int max_id = 0;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            char buffer[MAX_LINE];
            char *token;

            strcpy(buffer, line);
            token = strtok(buffer, "|");
            if (token != NULL && atoi(token) > max_id) {
                max_id = atoi(token);
            }
        }
        fclose(fp);
    }

    return max_id + 1;
}

int loadAppointments(struct Appointment *list, int max_count) {
    FILE *fp = fopen(APPOINTMENT_FILE, "r");
    char line[MAX_LINE];
    int count = 0;

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp) && count < max_count) {
        char buffer[MAX_LINE];
        strcpy(buffer, line);

        char *token = strtok(buffer, "|");
        if (!token) continue;
        list[count].appointment_id = atoi(token);

        token = strtok(NULL, "|");
        if (!token) continue;
        list[count].patient_id = atoi(token);

        token = strtok(NULL, "|");
        if (!token) continue;
        list[count].doctor_id = atoi(token);

        token = strtok(NULL, "|");
        if (!token) continue;
        strcpy(list[count].date, token);

        token = strtok(NULL, "|");
        if (!token) continue;
        strcpy(list[count].time_slot, token);

        token = strtok(NULL, "\n");
        if (!token) continue;
        strcpy(list[count].status, token);

        count++;
    }

    fclose(fp);
    return count;
}

int saveAppointments(struct Appointment *list, int count) {
    FILE *fp = fopen(APPOINTMENT_FILE, "w");
    int i;

    if (!fp) return 0;

    for (i = 0; i < count; i++) {
        fprintf(fp, "%d|%d|%d|%s|%s|%s\n",
            list[i].appointment_id,
            list[i].patient_id,
            list[i].doctor_id,
            list[i].date,
            list[i].time_slot,
            list[i].status
        );
    }

    fclose(fp);
    return 1;
}

int isTodayDate(const char *date) {
    int y, m, d;
    time_t now;
    struct tm *today;

    if (sscanf(date, "%4d-%2d-%2d", &y, &m, &d) != 3) return 0;

    now = time(NULL);
    today = localtime(&now);
    if (today == NULL) return 0;

    return y == today->tm_year + 1900 &&
           m == today->tm_mon + 1 &&
           d == today->tm_mday;
}

int doctorIsBlocked(int doctor_id, const char *date) {
    FILE *fp = fopen(DOCTOR_FILE, "r");
    char line[MAX_LINE];

    if (!fp) return 0;

    while (fgets(line, sizeof(line), fp)) {
        char buffer[MAX_LINE];
        char *token;
        int id;
        char daily[MAX_SMALL];
        char current[MAX_SMALL];

        strcpy(buffer, line);

        token = strtok(buffer, "|");
        if (!token) continue;
        id = atoi(token);
        if (id != doctor_id) continue;

        strtok(NULL, "|");
        strtok(NULL, "|");
        strtok(NULL, "|");

        token = strtok(NULL, "|");
        if (!token) break;
        strcpy(daily, token);

        token = strtok(NULL, "\n");
        if (!token) break;
        strcpy(current, token);

        fclose(fp);

        if (!isTodayDate(date)) return 0;
        if (strcmp(daily, "Unavailable") == 0 || strcmp(daily, "Off") == 0) return 1;
        if (strcmp(current, "Emergency") == 0) return 1;
        return 0;
    }

    fclose(fp);
    return 0;
}

const char* getSlotState(int doctor_id, const char *date, const char *time_slot, struct Appointment *list, int count) {
    int i;
    const char *state = "Available";

    if (doctorIsBlocked(doctor_id, date)) return "Blocked";

    for (i = 0; i < count; i++) {
        if (list[i].doctor_id == doctor_id &&
            strcmp(list[i].date, date) == 0 &&
            strcmp(list[i].time_slot, time_slot) == 0) {

            if (strcmp(list[i].status, "Cancelled") == 0 ||
                strcmp(list[i].status, "Rescheduled") == 0) {
                state = "Available";
            } else if (strcmp(list[i].status, "Completed") == 0) {
                state = "Completed";
            } else if (strcmp(list[i].status, "No-show") == 0) {
                state = "No-show";
            } else {
                state = "Booked";
            }
        }
    }

    return state;
}

void printSlots(int doctor_id, const char *date) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) return;

    count = loadAppointments(list, MAX_APPOINTMENTS);

    for (i = 0; i < SLOT_COUNT; i++) {
        const char *state = getSlotState(doctor_id, date, DEFAULT_SLOTS[i], list, count);
        printf("SLOT|%s|%s\n", DEFAULT_SLOTS[i], state);
    }

    free(list);
}

int bookSlot(int patient_id, int doctor_id, const char *date, const char *time_slot) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    const char *state;
    FILE *fp;
    int id;

    if (list == NULL) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);
    state = getSlotState(doctor_id, date, time_slot, list, count);

    if (patient_id <= 0 || doctor_id <= 0 || !validDate(date) || !validSlot(time_slot)) {
        printf("Error|InvalidInput");
        free(list);
        return 0;
    }

    if (strcmp(state, "Available") != 0) {
        printf("Error|SlotNotAvailable");
        free(list);
        return 0;
    }

    id = generateAppointmentId();

    fp = fopen(APPOINTMENT_FILE, "a");
    if (!fp) {
        printf("Error|CannotOpenFile");
        free(list);
        return 0;
    }

    fprintf(fp, "%d|%d|%d|%s|%s|Booked\n", id, patient_id, doctor_id, date, time_slot);
    fclose(fp);

    {
        struct Appointment old_appt;
        old_appt.appointment_id = 0;
        old_appt.patient_id = patient_id;
        old_appt.doctor_id = doctor_id;
        strcpy(old_appt.date, "");
        strcpy(old_appt.time_slot, "");
        strcpy(old_appt.status, "NEW");
        pushAppointmentAction("book", old_appt, id, date, time_slot, "Booked");
    }

    printf("BOOKED|%d|%d|%d|%s|%s|Booked", id, patient_id, doctor_id, date, time_slot);
    free(list);
    return 1;
}

int updateAppointmentStatus(int appointment_id, const char *new_status) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;
    int found = 0;

    if (list == NULL) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);

    for (i = 0; i < count; i++) {
        if (list[i].appointment_id == appointment_id) {
            struct Appointment old_appt = list[i];
            strcpy(list[i].status, new_status);
            found = 1;
            if (!saveAppointments(list, count)) {
                printf("Error|UpdateFailed");
                free(list);
                return 0;
            }
            pushAppointmentAction("status", old_appt, appointment_id, old_appt.date, old_appt.time_slot, new_status);
            break;
        }
    }

    if (!found) {
        printf("Error|AppointmentNotFound");
        free(list);
        return 0;
    }

    printf("UPDATED|%d|%s", appointment_id, new_status);
    free(list);
    return 1;
}

int rescheduleAppointment(int appointment_id, const char *new_date, const char *new_time) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;
    int found_index = -1;
    int new_id;

    if (list == NULL) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);

    for (i = 0; i < count; i++) {
        if (list[i].appointment_id == appointment_id) {
            found_index = i;
            break;
        }
    }

    if (found_index == -1) {
        printf("Error|AppointmentNotFound");
        free(list);
        return 0;
    }

    if (!validDate(new_date) || !validSlot(new_time)) {
        printf("Error|InvalidInput");
        free(list);
        return 0;
    }

    if (strcmp(list[found_index].status, "Completed") == 0 ||
        strcmp(list[found_index].status, "Cancelled") == 0 ||
        strcmp(list[found_index].status, "Rescheduled") == 0) {
        printf("Error|AppointmentNotActive");
        free(list);
        return 0;
    }

    if (count >= MAX_APPOINTMENTS) {
        printf("Error|AppointmentLimitReached");
        free(list);
        return 0;
    }

    if (strcmp(getSlotState(list[found_index].doctor_id, new_date, new_time, list, count), "Available") != 0) {
        printf("Error|NewSlotNotAvailable");
        free(list);
        return 0;
    }

    new_id = generateAppointmentId();

    {
        struct Appointment old_appt = list[found_index];
        strcpy(list[found_index].status, "Rescheduled");
        list[count].appointment_id = new_id;
        list[count].patient_id = list[found_index].patient_id;
        list[count].doctor_id = list[found_index].doctor_id;
        strcpy(list[count].date, new_date);
        strcpy(list[count].time_slot, new_time);
        strcpy(list[count].status, "Booked");
        count++;

        if (!saveAppointments(list, count)) {
            printf("Error|UpdateFailed");
            free(list);
            return 0;
        }

        pushAppointmentAction("reschedule", old_appt, new_id, new_date, new_time, "Booked");
    }

    printf("RESCHEDULED|%d|%d|%s|%s", appointment_id, new_id, new_date, new_time);
    free(list);
    return 1;
}

void checkDoctorAvailability(int doctor_id, const char *date, const char *time_slot) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;

    if (list == NULL) {
        printf("AVAILABILITY|Blocked");
        return;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);

    printf("AVAILABILITY|%s", getSlotState(doctor_id, date, time_slot, list, count));
    free(list);
}

void listAppointmentsForDoctorDate(int doctor_id, const char *date) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) return;

    count = loadAppointments(list, MAX_APPOINTMENTS);

    for (i = 0; i < count; i++) {
        if (list[i].doctor_id == doctor_id && strcmp(list[i].date, date) == 0) {
            printf("APPOINTMENT|%d|%d|%d|%s|%s|%s\n",
                list[i].appointment_id,
                list[i].patient_id,
                list[i].doctor_id,
                list[i].date,
                list[i].time_slot,
                list[i].status
            );
        }
    }

    free(list);
}

void listAllAppointments(void) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) return;

    count = loadAppointments(list, MAX_APPOINTMENTS);
    for (i = 0; i < count; i++) {
        printf("%d|%d|%d|%s|%s|%s\n",
            list[i].appointment_id,
            list[i].patient_id,
            list[i].doctor_id,
            list[i].date,
            list[i].time_slot,
            list[i].status
        );
    }

    free(list);
}

int findAppointmentById(int appointment_id) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);
    for (i = 0; i < count; i++) {
        if (list[i].appointment_id == appointment_id) {
            printf("%d|%d|%d|%s|%s|%s",
                list[i].appointment_id,
                list[i].patient_id,
                list[i].doctor_id,
                list[i].date,
                list[i].time_slot,
                list[i].status
            );
            free(list);
            return 1;
        }
    }

    free(list);
    return 0;
}

void listAppointmentsForPatient(int patient_id) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) return;

    count = loadAppointments(list, MAX_APPOINTMENTS);
    for (i = 0; i < count; i++) {
        if (list[i].patient_id == patient_id) {
            printf("%d|%d|%d|%s|%s|%s\n",
                list[i].appointment_id,
                list[i].patient_id,
                list[i].doctor_id,
                list[i].date,
                list[i].time_slot,
                list[i].status
            );
        }
    }

    free(list);
}

int findBookedAppointmentForPatientDate(int patient_id, const char *date) {
    struct Appointment *list = malloc(sizeof(struct Appointment) * MAX_APPOINTMENTS);
    int count;
    int i;

    if (list == NULL) {
        printf("Error|MemoryAllocationFailed");
        return 0;
    }

    count = loadAppointments(list, MAX_APPOINTMENTS);
    for (i = 0; i < count; i++) {
        if (list[i].patient_id == patient_id &&
            strcmp(list[i].date, date) == 0 &&
            strcmp(list[i].status, "Booked") == 0) {
            printf("%d|%d|%d|%s|%s|%s",
                list[i].appointment_id,
                list[i].patient_id,
                list[i].doctor_id,
                list[i].date,
                list[i].time_slot,
                list[i].status
            );
            free(list);
            return 1;
        }
    }

    free(list);
    return 0;
}

int commandWriteAll(void) {
    FILE *out = fopen("Backend/data/appointment.tmp", "w");
    char line[MAX_LINE];
    if (!out) return 0;
    while (fgets(line, sizeof(line), stdin)) {
        fputs(line, out);
    }
    fclose(out);
    remove(APPOINTMENT_FILE);
    if (rename("Backend/data/appointment.tmp", APPOINTMENT_FILE) != 0) {
        remove("Backend/data/appointment.tmp");
        return 0;
    }
    return 1;
}

int parseSlotMinutes(const char *time_slot) {
    int hour = 0, minute = 0;
    char ampm[3] = {0};
    if (!time_slot) return -1;
    if (sscanf(time_slot, "%d:%d %2s", &hour, &minute, ampm) != 3) return -1;
    if (hour < 1 || hour > 12 || minute < 0 || minute > 59) return -1;
    if (strcmp(ampm, "PM") == 0 && hour != 12) hour += 12;
    if (strcmp(ampm, "AM") == 0 && hour == 12) hour = 0;
    return hour * 60 + minute;
}

int slotInPast(const char *date, const char *time_slot) {
    int y = 0, m = 0, d = 0;
    time_t now = time(NULL);
    struct tm *tm_now = localtime(&now);
    int slot_minutes;
    int now_minutes;
    if (!tm_now) return 0;
    if (sscanf(date, "%4d-%2d-%2d", &y, &m, &d) != 3) return 0;
    if (y < tm_now->tm_year + 1900) return 1;
    if (y > tm_now->tm_year + 1900) return 0;
    if (m < tm_now->tm_mon + 1) return 1;
    if (m > tm_now->tm_mon + 1) return 0;
    if (d < tm_now->tm_mday) return 1;
    if (d > tm_now->tm_mday) return 0;
    slot_minutes = parseSlotMinutes(time_slot);
    if (slot_minutes < 0) return 0;
    now_minutes = (tm_now->tm_hour * 60) + tm_now->tm_min;
    return slot_minutes <= now_minutes;
}

int main(int argc, char *argv[]) {
    int ok = 0;

    if (argc < 2) {
        printf("Error|InvalidInput");
        return 1;
    }

    if (strcmp(argv[1], "slots") == 0 && argc == 4) {
        printSlots(atoi(argv[2]), argv[3]);
        ok = 1;
    } else if (strcmp(argv[1], "book") == 0 && argc == 6) {
        ok = bookSlot(atoi(argv[2]), atoi(argv[3]), argv[4], argv[5]);
    } else if (strcmp(argv[1], "cancel") == 0 && argc == 3) {
        ok = updateAppointmentStatus(atoi(argv[2]), "Cancelled");
    } else if (strcmp(argv[1], "complete") == 0 && argc == 3) {
        ok = updateAppointmentStatus(atoi(argv[2]), "Completed");
    } else if (strcmp(argv[1], "noshow") == 0 && argc == 3) {
        ok = updateAppointmentStatus(atoi(argv[2]), "No-show");
    } else if (strcmp(argv[1], "reschedule") == 0 && argc == 5) {
        ok = rescheduleAppointment(atoi(argv[2]), argv[3], argv[4]);
    } else if (strcmp(argv[1], "availability") == 0 && argc == 5) {
        checkDoctorAvailability(atoi(argv[2]), argv[3], argv[4]);
        ok = 1;
    } else if (strcmp(argv[1], "list") == 0 && argc == 4) {
        listAppointmentsForDoctorDate(atoi(argv[2]), argv[3]);
        ok = 1;
    } else if (strcmp(argv[1], "list-all") == 0) {
        listAllAppointments();
        ok = 1;
    } else if (strcmp(argv[1], "history-stack") == 0) {
        printAppointmentActionStack();
        ok = 1;
    } else if (strcmp(argv[1], "peek-stack") == 0) {
        peekAppointmentActionStack();
        ok = 1;
    } else if (strcmp(argv[1], "find-id") == 0 && argc == 3) {
        ok = findAppointmentById(atoi(argv[2]));
    } else if (strcmp(argv[1], "list-for-patient") == 0 && argc == 3) {
        listAppointmentsForPatient(atoi(argv[2]));
        ok = 1;
    } else if (strcmp(argv[1], "find-booked-patient-date") == 0 && argc == 4) {
        ok = findBookedAppointmentForPatientDate(atoi(argv[2]), argv[3]);
    } else if (strcmp(argv[1], "write-all") == 0) {
        ok = commandWriteAll();
        if (ok) printf("OK");
    } else if (strcmp(argv[1], "slot-in-past") == 0 && argc == 4) {
        printf("%d", slotInPast(argv[2], argv[3]));
        ok = 1;
    } else if (strcmp(argv[1], "auto-reassign") == 0 && argc == 3) {
        /* Placeholder command to match migration contract; reassignment stays orchestrated in Python. */
        (void)argv;
        ok = 1;
    } else {
        printf("Error|InvalidCommand");
        return 1;
    }

    return ok ? 0 : 1;
}
