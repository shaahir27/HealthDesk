#include "common.h"
#include <time.h>

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

int writeAllBillsFromStdin(void) {
    FILE *tmp = fopen("Backend/data/billing.tmp", "w");
    char line[MAX_LINE];
    if (tmp == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), stdin)) {
        fputs(line, tmp);
    }
    fclose(tmp);
    remove(BILLING_FILE);
    if (rename("Backend/data/billing.tmp", BILLING_FILE) != 0) {
        remove("Backend/data/billing.tmp");
        return 0;
    }
    return 1;
}

double recalculateBillTotal(double doctor_fee, double treatment_total, double lab_total, double medicine_total) {
    return doctor_fee + treatment_total + lab_total + medicine_total;
}

void printBillPreview(const char *bill_line) {
    char field[MAX_LINE];
    char bill_id[32] = "";
    char date_str[40] = "";
    char patient_id[32] = "";
    char name[MAX_NAME] = "";
    char age[16] = "";
    char gender[MAX_SMALL] = "";
    char doctor[MAX_NAME] = "";
    char department[MAX_NAME] = "";
    char doctor_fee[32] = "";
    char treatment_total[32] = "";
    char lab_total[32] = "";
    char medicine_total[32] = "";
    char total[32] = "";
    char status[32] = "";
    char medicine_notes[MAX_TEXT] = "";
    char payment_method[40] = "";
    char payment_id[84] = "";
    char paid_at[MAX_TIMESTAMP] = "";

    if (!bill_line) {
        return;
    }

    if (extractFieldPreserveEmpty(bill_line, 0, field, sizeof(field))) safeCopy(bill_id, field, sizeof(bill_id));
    if (extractFieldPreserveEmpty(bill_line, 1, field, sizeof(field))) safeCopy(date_str, field, sizeof(date_str));
    if (extractFieldPreserveEmpty(bill_line, 2, field, sizeof(field))) safeCopy(patient_id, field, sizeof(patient_id));
    if (extractFieldPreserveEmpty(bill_line, 3, field, sizeof(field))) safeCopy(name, field, sizeof(name));
    if (extractFieldPreserveEmpty(bill_line, 4, field, sizeof(field))) safeCopy(age, field, sizeof(age));
    if (extractFieldPreserveEmpty(bill_line, 5, field, sizeof(field))) safeCopy(gender, field, sizeof(gender));
    if (extractFieldPreserveEmpty(bill_line, 6, field, sizeof(field))) safeCopy(doctor, field, sizeof(doctor));
    if (extractFieldPreserveEmpty(bill_line, 7, field, sizeof(field))) safeCopy(department, field, sizeof(department));
    if (extractFieldPreserveEmpty(bill_line, 8, field, sizeof(field))) safeCopy(doctor_fee, field, sizeof(doctor_fee));
    if (extractFieldPreserveEmpty(bill_line, 9, field, sizeof(field))) safeCopy(treatment_total, field, sizeof(treatment_total));
    if (extractFieldPreserveEmpty(bill_line, 10, field, sizeof(field))) safeCopy(lab_total, field, sizeof(lab_total));
    if (extractFieldPreserveEmpty(bill_line, 11, field, sizeof(field))) safeCopy(medicine_total, field, sizeof(medicine_total));
    if (extractFieldPreserveEmpty(bill_line, 12, field, sizeof(field))) safeCopy(total, field, sizeof(total));
    if (extractFieldPreserveEmpty(bill_line, 13, field, sizeof(field))) safeCopy(status, field, sizeof(status));
    if (extractFieldPreserveEmpty(bill_line, 17, field, sizeof(field))) safeCopy(medicine_notes, field, sizeof(medicine_notes));
    if (extractFieldPreserveEmpty(bill_line, 20, field, sizeof(field))) safeCopy(payment_id, field, sizeof(payment_id));
    if (extractFieldPreserveEmpty(bill_line, 21, field, sizeof(field))) safeCopy(payment_method, field, sizeof(payment_method));
    if (extractFieldPreserveEmpty(bill_line, 22, field, sizeof(field))) safeCopy(paid_at, field, sizeof(paid_at));

    printf("=========================================================\n");
    printf("                    HEALTHDESK CLINIC\n");
    printf("=========================================================\n");
    printf("Address: Chennai\n");
    printf("Phone: +91 XXXXX XXXXX\n\n");
    printf("---------------------------------------------------------\n");
    printf("Bill ID   : %s\n", bill_id);
    printf("Date      : %s\n", date_str);
    printf("---------------------------------------------------------\n");
    printf("Patient ID: %s\n", patient_id);
    printf("Name      : %s\n", name);
    printf("Age       : %s\n", age);
    printf("Gender    : %s\n\n", gender);
    printf("Doctor    : %s\n", doctor);
    printf("Department: %s\n", department);
    printf("---------------------------------------------------------\n\n");
    printf("                   BILL DETAILS\n");
    printf("---------------------------------------------------------\n");
    printf("%-34s%s\n", "Description", "Amount (Rs)");
    printf("---------------------------------------------------------\n");
    printf("%-34s%.0f\n", "Doctor Fee", atof(doctor_fee));
    if (atof(treatment_total) > 0.0) printf("%-34s%.0f\n", "Treatments", atof(treatment_total));
    if (atof(lab_total) > 0.0) printf("%-34s%.0f\n", "Lab Tests", atof(lab_total));
    if (atof(medicine_total) > 0.0) printf("%-34s%.0f\n", "Medicines", atof(medicine_total));
    printf("\n---------------------------------------------------------\n");
    printf("%-34sRs %.0f\n", "TOTAL", atof(total));
    printf("---------------------------------------------------------\n");
    printf("Payment Status: %s\n", status);
    if (payment_method[0]) printf("Payment Method: %s\n", payment_method);
    if (payment_id[0]) printf("Payment Reference: %s\n", payment_id);
    if (paid_at[0]) printf("Paid On: %s\n", paid_at);
    if (medicine_notes[0]) printf("Medicine Notes : %s\n", medicine_notes);
    printf("\n---------------------------------------------------------\n");
    printf("         Thank you for visiting HealthDesk\n");
    printf("---------------------------------------------------------\n");
}

int hasBlockingUnpaidBill(int patient_id) {
    FILE *fp = fopen(BILLING_FILE, "r");
    char line[MAX_LINE];
    char field_patient[32], field_status[32], field_date[32];
    time_t now = time(NULL);
    struct tm *tm_now = localtime(&now);
    struct tm cutoff_tm;
    time_t cutoff;
    int y, m, d;
    if (!fp || !tm_now) return 0;
    cutoff_tm = *tm_now;
    cutoff_tm.tm_hour = 0;
    cutoff_tm.tm_min = 0;
    cutoff_tm.tm_sec = 0;
    cutoff_tm.tm_mday -= 7;
    cutoff = mktime(&cutoff_tm);
    while (fgets(line, sizeof(line), fp)) {
        if (!extractFieldPreserveEmpty(line, 2, field_patient, sizeof(field_patient))) continue;
        if (atoi(field_patient) != patient_id) continue;
        if (!extractFieldPreserveEmpty(line, 13, field_status, sizeof(field_status))) continue;
        if (!(strcmp(field_status, "PENDING") == 0 || strcmp(field_status, "INITIATED") == 0)) continue;
        if (!extractFieldPreserveEmpty(line, 1, field_date, sizeof(field_date))) continue;
        if (sscanf(field_date, "%4d-%2d-%2d", &y, &m, &d) != 3) continue;
        {
            struct tm bill_tm = {0};
            bill_tm.tm_year = y - 1900;
            bill_tm.tm_mon = m - 1;
            bill_tm.tm_mday = d;
            if (mktime(&bill_tm) < cutoff) {
                fclose(fp);
                return 1;
            }
        }
    }
    fclose(fp);
    return 0;
}

int revertStaleInitiated(void) {
    FILE *src = fopen(BILLING_FILE, "r");
    FILE *tmp = fopen("Backend/data/billing.tmp", "w");
    char line[MAX_LINE];
    int changed = 0;
    if (!src || !tmp) {
        if (src) fclose(src);
        if (tmp) fclose(tmp);
        return 0;
    }
    while (fgets(line, sizeof(line), src)) {
        char status[32];
        if (extractFieldPreserveEmpty(line, 13, status, sizeof(status)) && strcmp(status, "INITIATED") == 0) {
            char patient_id[32], name[MAX_NAME], age[16], gender[MAX_SMALL], doctor[MAX_NAME], dept[MAX_NAME];
            char date[32], bill_id[32], df[32], tt[32], lt[32], mt[32], total[32], doctor_id[32];
            char titems[MAX_LINE], litems[MAX_LINE], notes[MAX_TEXT], appt_id[32], oid[84], pid[84], method[40];
            char paid_at[MAX_TIMESTAMP], initiated_at[MAX_TIMESTAMP], adv_id[32], adv_amt[32], adv_at[MAX_TIMESTAMP];
            extractFieldPreserveEmpty(line, 0, bill_id, sizeof(bill_id));
            extractFieldPreserveEmpty(line, 1, date, sizeof(date));
            extractFieldPreserveEmpty(line, 2, patient_id, sizeof(patient_id));
            extractFieldPreserveEmpty(line, 3, name, sizeof(name));
            extractFieldPreserveEmpty(line, 4, age, sizeof(age));
            extractFieldPreserveEmpty(line, 5, gender, sizeof(gender));
            extractFieldPreserveEmpty(line, 6, doctor, sizeof(doctor));
            extractFieldPreserveEmpty(line, 7, dept, sizeof(dept));
            extractFieldPreserveEmpty(line, 8, df, sizeof(df));
            extractFieldPreserveEmpty(line, 9, tt, sizeof(tt));
            extractFieldPreserveEmpty(line, 10, lt, sizeof(lt));
            extractFieldPreserveEmpty(line, 11, mt, sizeof(mt));
            extractFieldPreserveEmpty(line, 12, total, sizeof(total));
            extractFieldPreserveEmpty(line, 14, doctor_id, sizeof(doctor_id));
            extractFieldPreserveEmpty(line, 15, titems, sizeof(titems));
            extractFieldPreserveEmpty(line, 16, litems, sizeof(litems));
            extractFieldPreserveEmpty(line, 17, notes, sizeof(notes));
            extractFieldPreserveEmpty(line, 18, appt_id, sizeof(appt_id));
            extractFieldPreserveEmpty(line, 19, oid, sizeof(oid));
            extractFieldPreserveEmpty(line, 20, pid, sizeof(pid));
            extractFieldPreserveEmpty(line, 21, method, sizeof(method));
            extractFieldPreserveEmpty(line, 22, paid_at, sizeof(paid_at));
            extractFieldPreserveEmpty(line, 23, initiated_at, sizeof(initiated_at));
            extractFieldPreserveEmpty(line, 24, adv_id, sizeof(adv_id));
            extractFieldPreserveEmpty(line, 25, adv_amt, sizeof(adv_amt));
            extractFieldPreserveEmpty(line, 26, adv_at, sizeof(adv_at));
            fprintf(tmp, "%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|PENDING|%s|%s|%s|%s|%s|||||%s|%s|%s\n",
                    bill_id, date, patient_id, name, age, gender, doctor, dept,
                    df, tt, lt, mt, total, doctor_id, titems, litems, notes, appt_id,
                    adv_id, adv_amt, adv_at);
            changed++;
        } else {
            fputs(line, tmp);
        }
    }
    fclose(src);
    fclose(tmp);
    if (changed > 0) {
        remove(BILLING_FILE);
        if (rename("Backend/data/billing.tmp", BILLING_FILE) != 0) {
            remove("Backend/data/billing.tmp");
            return 0;
        }
    } else {
        remove("Backend/data/billing.tmp");
    }
    return changed;
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

    if (strcmp(argv[1], "recalc-total") == 0 && argc == 6) {
        double doctor_fee = atof(argv[2]);
        double treatment_total = atof(argv[3]);
        double lab_total = atof(argv[4]);
        double medicine_total = atof(argv[5]);
        printf("%.2f", recalculateBillTotal(doctor_fee, treatment_total, lab_total, medicine_total));
        return 0;
    }

    if (strcmp(argv[1], "preview") == 0 && argc == 3) {
        printBillPreview(argv[2]);
        return 0;
    }

    if (strcmp(argv[1], "write-all") == 0) {
        if (writeAllBillsFromStdin()) {
            printf("OK");
            return 0;
        }
        printf("Error|WriteAllFailed");
        return 1;
    }

    if (strcmp(argv[1], "has-blocking") == 0 && argc == 3) {
        printf("%d", hasBlockingUnpaidBill(atoi(argv[2])));
        return 0;
    }

    if (strcmp(argv[1], "revert-stale") == 0) {
        printf("%d", revertStaleInitiated());
        return 0;
    }

    printf("Error|InvalidCommand");
    return 1;
}
