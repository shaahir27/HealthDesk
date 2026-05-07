#include "common.h"

int parseVitalsLine(char *line, Vitals *v) {
    char buffer[MAX_LINE];
    char *token;

    strcpy(buffer, line);

    token = strtok(buffer, "|");
    if (token == NULL) return 0;
    v->vitals_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    v->patient_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    v->doctor_id = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    v->token = atoi(token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->recorded_at, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->temperature, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->bp_systolic, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->bp_diastolic, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->pulse_rate, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->weight, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->oxygen_level, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->sugar_level, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->allergy_conditions, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->health_conditions, token);

    token = strtok(NULL, "|");
    if (token == NULL) return 0;
    strcpy(v->notes, token);

    token = strtok(NULL, "|");
    if (token != NULL) strcpy(v->smoking_habit, token);
    else strcpy(v->smoking_habit, "");

    token = strtok(NULL, "\n");
    if (token != NULL) strcpy(v->drinking_habit, token);
    else strcpy(v->drinking_habit, "");

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
