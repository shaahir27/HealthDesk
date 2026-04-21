#include "common.h"

#define MAX_APPOINTMENTS 2000
#define SLOT_COUNT 8

const char *DEFAULT_SLOTS[SLOT_COUNT] = {
    "08:30 AM", "09:30 AM", "10:30 AM", "11:40 AM",
    "02:00 PM", "04:00 PM", "06:00 PM", "08:05 PM"
};

int generateAppointmentId() {
    FILE *fp = fopen(APPOINTMENT_FILE, "r");
    int count = 0;
    char line[MAX_LINE];

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            if (strlen(line) > 1) count++;
        }
        fclose(fp);
    }

    return count + 1;
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

    if (doctorIsBlocked(doctor_id)) return "Blocked";

    for (i = 0; i < count; i++) {
        if (list[i].doctor_id == doctor_id &&
            strcmp(list[i].date, date) == 0 &&
            strcmp(list[i].time_slot, time_slot) == 0) {

            if (strcmp(list[i].status, "Cancelled") == 0) return "Available";
            if (strcmp(list[i].status, "Rescheduled") == 0) return "Available";
            if (strcmp(list[i].status, "Completed") == 0) return "Completed";
            if (strcmp(list[i].status, "No-show") == 0) return "No-show";
            return "Booked";
        }
    }

    return "Available";
}

void printSlots(int doctor_id, const char *date) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);
    int i;

    for (i = 0; i < SLOT_COUNT; i++) {
        const char *state = getSlotState(doctor_id, date, DEFAULT_SLOTS[i], list, count);
        printf("SLOT|%s|%s\n", DEFAULT_SLOTS[i], state);
    }
}

int bookSlot(int patient_id, int doctor_id, const char *date, const char *time_slot) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);
    const char *state = getSlotState(doctor_id, date, time_slot, list, count);
    FILE *fp;
    int id;

    if (strcmp(state, "Available") != 0) {
        printf("Error|SlotNotAvailable");
        return 0;
    }

    id = generateAppointmentId();

    fp = fopen(APPOINTMENT_FILE, "a");
    if (!fp) {
        printf("Error|CannotOpenFile");
        return 0;
    }

    fprintf(fp, "%d|%d|%d|%s|%s|Booked\n", id, patient_id, doctor_id, date, time_slot);
    fclose(fp);

    printf("BOOKED|%d|%d|%d|%s|%s|Booked", id, patient_id, doctor_id, date, time_slot);
    return 1;
}

int updateAppointmentStatus(int appointment_id, const char *new_status) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);
    int i;
    int found = 0;

    for (i = 0; i < count; i++) {
        if (list[i].appointment_id == appointment_id) {
            strcpy(list[i].status, new_status);
            found = 1;
            break;
        }
    }

    if (!found) {
        printf("Error|AppointmentNotFound");
        return 0;
    }

    if (!saveAppointments(list, count)) {
        printf("Error|UpdateFailed");
        return 0;
    }

    printf("UPDATED|%d|%s", appointment_id, new_status);
    return 1;
}

int rescheduleAppointment(int appointment_id, const char *new_date, const char *new_time) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);
    int i;
    int found_index = -1;
    int new_id;

    for (i = 0; i < count; i++) {
        if (list[i].appointment_id == appointment_id) {
            found_index = i;
            break;
        }
    }

    if (found_index == -1) {
        printf("Error|AppointmentNotFound");
        return 0;
    }

    if (count >= MAX_APPOINTMENTS) {
        printf("Error|AppointmentLimitReached");
        return 0;
    }

    if (strcmp(getSlotState(list[found_index].doctor_id, new_date, new_time, list, count), "Available") != 0) {
        printf("Error|NewSlotNotAvailable");
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
        return 0;
    }

    printf("RESCHEDULED|%d|%d|%s|%s", appointment_id, new_id, new_date, new_time);
    return 1;
}

void checkDoctorAvailability(int doctor_id, const char *date, const char *time_slot) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);

    printf("AVAILABILITY|%s", getSlotState(doctor_id, date, time_slot, list, count));
}

void listAppointmentsForDoctorDate(int doctor_id, const char *date) {
    struct Appointment list[MAX_APPOINTMENTS];
    int count = loadAppointments(list, MAX_APPOINTMENTS);
    int i;

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
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Error|InvalidInput");
        return 1;
    }

    if (strcmp(argv[1], "slots") == 0 && argc == 4) {
        printSlots(atoi(argv[2]), argv[3]);
    } else if (strcmp(argv[1], "book") == 0 && argc == 6) {
        bookSlot(atoi(argv[2]), atoi(argv[3]), argv[4], argv[5]);
    } else if (strcmp(argv[1], "cancel") == 0 && argc == 3) {
        updateAppointmentStatus(atoi(argv[2]), "Cancelled");
    } else if (strcmp(argv[1], "complete") == 0 && argc == 3) {
        updateAppointmentStatus(atoi(argv[2]), "Completed");
    } else if (strcmp(argv[1], "noshow") == 0 && argc == 3) {
        updateAppointmentStatus(atoi(argv[2]), "No-show");
    } else if (strcmp(argv[1], "reschedule") == 0 && argc == 5) {
        rescheduleAppointment(atoi(argv[2]), argv[3], argv[4]);
    } else if (strcmp(argv[1], "availability") == 0 && argc == 5) {
        checkDoctorAvailability(atoi(argv[2]), argv[3], argv[4]);
    } else if (strcmp(argv[1], "list") == 0 && argc == 4) {
        listAppointmentsForDoctorDate(atoi(argv[2]), argv[3]);
    } else {
        printf("Error|InvalidCommand");
        return 1;
    }

    return 0;
}
