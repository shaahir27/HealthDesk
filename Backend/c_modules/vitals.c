#include "common.h"
#include <ctype.h>

void safeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) return;
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

int extractField(const char *line, int target_index, char *out, size_t out_size) {
    int field_index = 0;
    size_t out_pos = 0;

    if (!line || out_size == 0) return 0;
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

int parseVitalsLine(char *line, Vitals *v) {
    char field[MAX_LINE];

    if (!line || !v) return 0;

    if (!extractField(line, 0, field, sizeof(field))) return 0;
    v->vitals_id = atoi(field);
    if (!extractField(line, 1, field, sizeof(field))) return 0;
    v->patient_id = atoi(field);
    if (!extractField(line, 2, field, sizeof(field))) return 0;
    v->doctor_id = atoi(field);
    if (!extractField(line, 3, field, sizeof(field))) return 0;
    v->token = atoi(field);
    if (!extractField(line, 4, v->recorded_at, sizeof(v->recorded_at))) return 0;
    if (!extractField(line, 5, v->temperature, sizeof(v->temperature))) return 0;
    if (!extractField(line, 6, v->bp_systolic, sizeof(v->bp_systolic))) return 0;
    if (!extractField(line, 7, v->bp_diastolic, sizeof(v->bp_diastolic))) return 0;
    if (!extractField(line, 8, v->pulse_rate, sizeof(v->pulse_rate))) return 0;
    if (!extractField(line, 9, v->weight, sizeof(v->weight))) return 0;
    if (!extractField(line, 10, v->oxygen_level, sizeof(v->oxygen_level))) return 0;
    if (!extractField(line, 11, v->sugar_level, sizeof(v->sugar_level))) return 0;
    if (!extractField(line, 12, v->allergy_conditions, sizeof(v->allergy_conditions))) return 0;
    if (!extractField(line, 13, v->health_conditions, sizeof(v->health_conditions))) return 0;
    if (!extractField(line, 14, v->notes, sizeof(v->notes))) return 0;
    if (!extractField(line, 15, v->smoking_habit, sizeof(v->smoking_habit))) {
        v->smoking_habit[0] = '\0';
    }
    if (!extractField(line, 16, v->drinking_habit, sizeof(v->drinking_habit))) {
        v->drinking_habit[0] = '\0';
    }

    return 1;
}

int isBlank(const char *value) {
    int i;
    if (value == NULL) return 1;
    for (i = 0; value[i]; i++) {
        if (!isspace((unsigned char)value[i])) return 0;
    }
    return 1;
}

int parseOptionalNumber(const char *value, double *out) {
    char *end = NULL;
    double parsed;
    if (isBlank(value)) return 1;
    parsed = strtod(value, &end);
    if (end == value) return 0;
    while (end && *end) {
        if (!isspace((unsigned char)*end)) return 0;
        end++;
    }
    if (out) *out = parsed;
    return 1;
}

int numberInRange(const char *value, double min, double max) {
    double parsed = 0.0;
    if (!parseOptionalNumber(value, &parsed)) return 0;
    if (isBlank(value)) return 1;
    return parsed >= min && parsed <= max;
}

int allowedChoice(const char *value, const char *a, const char *b, const char *c) {
    if (isBlank(value)) return 1;
    return strcmp(value, a) == 0 || strcmp(value, b) == 0 || strcmp(value, c) == 0;
}

int validateVitals(char *input) {
    Vitals v;
    char buffer[MAX_LINE];

    if (!input || strlen(input) >= MAX_LINE) {
        printf("Error|Vitals record is too long.");
        return 0;
    }

    safeCopy(buffer, input, sizeof(buffer));
    if (!parseVitalsLine(buffer, &v)) {
        printf("Error|Vitals record is incomplete.");
        return 0;
    }

    if (v.patient_id <= 0 || v.doctor_id <= 0 || v.token < 0) {
        printf("Error|Patient, doctor, and token details are required.");
        return 0;
    }
    if (!numberInRange(v.temperature, 90.0, 110.0)) {
        printf("Error|Temperature must be between 90 and 110 F.");
        return 0;
    }
    if (!numberInRange(v.bp_systolic, 50.0, 250.0)) {
        printf("Error|Systolic BP must be between 50 and 250.");
        return 0;
    }
    if (!numberInRange(v.bp_diastolic, 30.0, 160.0)) {
        printf("Error|Diastolic BP must be between 30 and 160.");
        return 0;
    }
    if (!numberInRange(v.pulse_rate, 30.0, 220.0)) {
        printf("Error|Pulse rate must be between 30 and 220.");
        return 0;
    }
    if (!numberInRange(v.weight, 1.0, 300.0)) {
        printf("Error|Weight must be between 1 and 300 kg.");
        return 0;
    }
    if (!numberInRange(v.oxygen_level, 50.0, 100.0)) {
        printf("Error|Oxygen level must be between 50 and 100 percent.");
        return 0;
    }
    if (!numberInRange(v.sugar_level, 20.0, 600.0)) {
        printf("Error|Sugar level must be between 20 and 600.");
        return 0;
    }
    if (!allowedChoice(v.smoking_habit, "Non-smoker", "Occasional", "Regular")) {
        printf("Error|Choose a valid smoking habit.");
        return 0;
    }
    if (!allowedChoice(v.drinking_habit, "Non-drinker", "Occasional", "Regular")) {
        printf("Error|Choose a valid drinking habit.");
        return 0;
    }

    printf("OK");
    return 1;
}

void printVitals(Vitals v) {
    printf("%d|%d|%d|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n",
        v.vitals_id,
        v.patient_id,
        v.doctor_id,
        v.token,
        v.recorded_at,
        v.temperature,
        v.bp_systolic,
        v.bp_diastolic,
        v.pulse_rate,
        v.weight,
        v.oxygen_level,
        v.sugar_level,
        v.allergy_conditions,
        v.health_conditions,
        v.notes,
        v.smoking_habit,
        v.drinking_habit
    );
}

int getNextId() {
    FILE *fp;
    int max_id = 0;
    char line[MAX_LINE];
    Vitals v;

    fp = fopen(VITALS_FILE, "r");

    if (fp != NULL) {
        while (fgets(line, sizeof(line), fp)) {
            if (parseVitalsLine(line, &v) && v.vitals_id > max_id) {
                max_id = v.vitals_id;
            }
        }
        fclose(fp);
    }

    return max_id + 1;
}

void saveVitals(char *input) {
    FILE *fp = fopen(VITALS_FILE, "a");
    if (fp == NULL) {
        printf("Error|SaveFailed");
        return;
    }

    /* Check if file is empty or ends with newline */
    fseek(fp, 0, SEEK_END);
    long file_size = ftell(fp);
    
    if (file_size > 0) {
        fseek(fp, file_size - 1, SEEK_SET);
        char last_char;
        if (fread(&last_char, 1, 1, fp) == 1 && last_char != '\n') {
            fprintf(fp, "\n");
        }
    }

    fprintf(fp, "%s\n", input);
    fclose(fp);
    printf("SAVED");
}

void findPatient(int patient_id) {
    FILE *fp;
    char line[MAX_LINE];
    Vitals v;
    Vitals last_found = {0};
    int found = 0;

    fp = fopen(VITALS_FILE, "r");
    if (fp == NULL) {
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        if (parseVitalsLine(line, &v) && v.patient_id == patient_id) {
            found = 1;
            last_found = v;
        }
    }

    fclose(fp);

    if (found) {
        printVitals(last_found);
    }
}

void findPatientDoctor(int patient_id, int doctor_id) {
    FILE *fp;
    char line[MAX_LINE];
    Vitals v;
    Vitals last_found = {0};
    int found = 0;

    fp = fopen(VITALS_FILE, "r");
    if (fp == NULL) {
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        if (parseVitalsLine(line, &v) && v.patient_id == patient_id && v.doctor_id == doctor_id) {
            found = 1;
            last_found = v;
        }
    }

    fclose(fp);

    if (found) {
        printVitals(last_found);
    }
}

void listDoctorVitals(int doctor_id) {
    FILE *fp;
    char line[MAX_LINE];
    Vitals v;

    fp = fopen(VITALS_FILE, "r");
    if (fp == NULL) {
        return;
    }

    while (fgets(line, sizeof(line), fp)) {
        if (parseVitalsLine(line, &v) && v.doctor_id == doctor_id) {
            printVitals(v);
            printf("\n");
        }
    }

    fclose(fp);
}

int main(int argc, char *argv[]) {
    if (argc < 2) return 1;

    if (strcmp(argv[1], "next-id") == 0) {
        printf("%d", getNextId());
    }
    else if (strcmp(argv[1], "save") == 0 && argc == 3) {
        saveVitals(argv[2]);
    }
    else if (strcmp(argv[1], "validate") == 0 && argc == 3) {
        return validateVitals(argv[2]) ? 0 : 1;
    }
    else if (strcmp(argv[1], "find-patient") == 0 && argc == 3) {
        findPatient(atoi(argv[2]));
    }
    else if (strcmp(argv[1], "find-patient-doctor") == 0 && argc == 4) {
        findPatientDoctor(atoi(argv[2]), atoi(argv[3]));
    }
    else if (strcmp(argv[1], "list-doctor") == 0 && argc == 3) {
        listDoctorVitals(atoi(argv[2]));
    }
    else if (strcmp(argv[1], "list-all") == 0) {
        FILE *fp = fopen(VITALS_FILE, "r");
        char line[MAX_LINE];
        Vitals v;
        if (fp != NULL) {
            while (fgets(line, sizeof(line), fp)) {
                if (parseVitalsLine(line, &v)) {
                    printVitals(v);
                    printf("\n");
                }
            }
            fclose(fp);
        }
    }
    else {
        return 1;
    }

    return 0;
}
