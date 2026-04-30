#include "common.h"
#include <time.h>

#define MAX_APPOINTMENTS 50000
#define SLOT_COUNT 8

const char *DEFAULT_SLOTS[SLOT_COUNT] = {
    "08:30 AM", "09:30 AM", "10:30 AM", "11:40 AM",
    "02:00 PM", "04:00 PM", "06:00 PM", "08:05 PM"
};

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

int doctorIsBlocked(int doctor_id) {
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

    if (doctorIsBlocked(doctor_id)) return "Blocked";

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
            strcpy(list[i].status, new_status);
            found = 1;
            break;
        }
    }

    if (!found) {
        printf("Error|AppointmentNotFound");
        free(list);
        return 0;
    }

    if (!saveAppointments(list, count)) {
        printf("Error|UpdateFailed");
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
    } else {
        printf("Error|InvalidCommand");
        return 1;
    }

    return ok ? 0 : 1;
}
