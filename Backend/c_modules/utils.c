#include "common.h"
#include <ctype.h>
#include <time.h>

static void safeCopy(char *dest, const char *src, size_t dest_size) {
    if (dest_size == 0) {
        return;
    }
    strncpy(dest, src ? src : "", dest_size - 1);
    dest[dest_size - 1] = '\0';
}

int normalizePhone(const char *phone, char *out, size_t out_size) {
    size_t j = 0;
    if (out_size == 0) {
        return 0;
    }
    if (!phone) {
        out[0] = '\0';
        return 0;
    }
    for (size_t i = 0; phone[i] && (j + 1) < out_size; i++) {
        if (isdigit((unsigned char)phone[i])) {
            out[j++] = phone[i];
        }
    }
    out[j] = '\0';
    return (int)j;
}

int isValidPatientPhone(const char *phone) {
    if (!phone) {
        return 0;
    }
    int len = 0;
    for (int i = 0; phone[i]; i++) {
        if (!isdigit((unsigned char)phone[i])) {
            return 0;
        }
        len++;
    }
    return len == 10;
}

int isValidPhone(const char *phone) {
    return isValidPatientPhone(phone);
}

int isValidAge(const char *age_str) {
    int age = 0;
    if (!age_str || !age_str[0]) return 0;
    for (int i = 0; age_str[i]; i++) {
        if (!isdigit((unsigned char)age_str[i])) return 0;
    }
    age = atoi(age_str);
    return age > 0 && age <= 120;
}

void maskPhone(const char *phone, char *out, size_t out_size) {
    char normalized[MAX_PHONE];
    normalizePhone(phone, normalized, sizeof(normalized));
    if (strlen(normalized) != 10) {
        safeCopy(out, normalized, out_size);
        return;
    }
    snprintf(out, out_size, "%.2sXXXXX%.3s", normalized, normalized + 7);
}

int parseIsoDate(const char *date_str, int *year, int *month, int *day) {
    if (!date_str || !year || !month || !day) {
        return 0;
    }
    if (sscanf(date_str, "%4d-%2d-%2d", year, month, day) != 3) {
        return 0;
    }
    if (*month < 1 || *month > 12 || *day < 1 || *day > 31) {
        return 0;
    }
    return 1;
}

int isFutureOrToday(const char *date_str) {
    int year = 0, month = 0, day = 0;
    time_t now;
    struct tm *today_ptr;
    struct tm today_tm;
    if (!parseIsoDate(date_str, &year, &month, &day)) {
        return 0;
    }
    now = time(NULL);
    today_ptr = localtime(&now);
    if (!today_ptr) {
        return 0;
    }
    today_tm = *today_ptr;
    if (year != (today_tm.tm_year + 1900)) {
        return year > (today_tm.tm_year + 1900);
    }
    if (month != (today_tm.tm_mon + 1)) {
        return month > (today_tm.tm_mon + 1);
    }
    return day >= today_tm.tm_mday;
}

void formatHumanDate(const char *date_str, char *out, size_t out_size) {
    int year = 0, month = 0, day = 0;
    struct tm tm_date;
    if (out_size == 0) {
        return;
    }
    if (!parseIsoDate(date_str, &year, &month, &day)) {
        safeCopy(out, date_str ? date_str : "", out_size);
        return;
    }
    memset(&tm_date, 0, sizeof(tm_date));
    tm_date.tm_year = year - 1900;
    tm_date.tm_mon = month - 1;
    tm_date.tm_mday = day;
    if (mktime(&tm_date) == (time_t)-1) {
        safeCopy(out, date_str ? date_str : "", out_size);
        return;
    }
    strftime(out, out_size, "%A, %d %B %Y", &tm_date);
}

void isoNow(char *out, size_t out_size) {
    time_t now;
    struct tm *now_ptr;
    struct tm now_tm;
    if (out_size == 0) {
        return;
    }
    now = time(NULL);
    now_ptr = localtime(&now);
    if (!now_ptr) {
        out[0] = '\0';
        return;
    }
    now_tm = *now_ptr;
    strftime(out, out_size, "%Y-%m-%dT%H:%M:%S", &now_tm);
}

int parseIsoDatetime(const char *value, struct tm *out_tm) {
    int y = 0, m = 0, d = 0, hh = 0, mm = 0, ss = 0;
    if (!value || !out_tm) return 0;
    if (sscanf(value, "%4d-%2d-%2dT%2d:%2d:%2d", &y, &m, &d, &hh, &mm, &ss) < 5 &&
        sscanf(value, "%4d-%2d-%2d %2d:%2d:%2d", &y, &m, &d, &hh, &mm, &ss) < 5 &&
        sscanf(value, "%4d-%2d-%2dT%2d:%2d", &y, &m, &d, &hh, &mm) < 5) {
        return 0;
    }
    memset(out_tm, 0, sizeof(*out_tm));
    out_tm->tm_year = y - 1900;
    out_tm->tm_mon = m - 1;
    out_tm->tm_mday = d;
    out_tm->tm_hour = hh;
    out_tm->tm_min = mm;
    out_tm->tm_sec = ss;
    return 1;
}

void remainingTimeLabel(const char *expires_at_iso, char *out, size_t out_size) {
    struct tm expiry_tm;
    time_t now = time(NULL);
    time_t expiry_time;
    long diff_seconds;
    int minutes, hours, mins;
    if (out_size == 0) return;
    if (!parseIsoDatetime(expires_at_iso, &expiry_tm)) {
        out[0] = '\0';
        return;
    }
    expiry_time = mktime(&expiry_tm);
    if (expiry_time == (time_t)-1) {
        out[0] = '\0';
        return;
    }
    diff_seconds = (long)difftime(expiry_time, now);
    if (diff_seconds <= 0) {
        snprintf(out, out_size, "Expired");
        return;
    }
    minutes = (int)(diff_seconds / 60);
    hours = minutes / 60;
    mins = minutes % 60;
    if (hours > 0) snprintf(out, out_size, "Expires in %dh %dm", hours, mins);
    else snprintf(out, out_size, "Expires in %dm", mins);
}

void statusLabelForPatient(const char *status, char *out, size_t out_size) {
    const char *s = status ? status : "";
    if (strcmp(s, "Booked") == 0) snprintf(out, out_size, "Confirmed");
    else if (strcmp(s, "Pending") == 0) snprintf(out, out_size, "Pending Confirmation");
    else if (strcmp(s, "Cancelled") == 0) snprintf(out, out_size, "Cancelled");
    else if (strcmp(s, "Completed") == 0) snprintf(out, out_size, "Visit completed");
    else if (strcmp(s, "No-show") == 0) snprintf(out, out_size, "Appointment not attended");
    else if (strcmp(s, "Rescheduled") == 0) snprintf(out, out_size, "Rescheduled");
    else snprintf(out, out_size, "%s", s[0] ? s : "Unknown");
}

void stripDoctorTitle(const char *name, char *out, size_t out_size) {
    const char *src = name ? name : "";
    while (*src == ' ') src++;
    if ((src[0] == 'd' || src[0] == 'D') && (src[1] == 'r' || src[1] == 'R')) {
        src += 2;
        if (*src == '.') src++;
        if (*src == ' ') src++;
    }
    snprintf(out, out_size, "%s", src);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: utils.exe <command> [args]\n");
        return 1;
    }

    if (strcmp(argv[1], "normalize-phone") == 0 && argc >= 3) {
        char out[MAX_PHONE];
        normalizePhone(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "valid-patient-phone") == 0 && argc >= 3) {
        char normalized[MAX_PHONE];
        normalizePhone(argv[2], normalized, sizeof(normalized));
        printf("%d\n", isValidPatientPhone(normalized));
        return 0;
    }

    if (strcmp(argv[1], "mask-phone") == 0 && argc >= 3) {
        char out[MAX_PHONE + 8];
        maskPhone(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "iso-now") == 0) {
        char out[MAX_TIMESTAMP];
        isoNow(out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "future-or-today") == 0 && argc >= 3) {
        printf("%d\n", isFutureOrToday(argv[2]));
        return 0;
    }

    if (strcmp(argv[1], "format-date") == 0 && argc >= 3) {
        char out[80];
        formatHumanDate(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "valid-phone") == 0 && argc >= 3) {
        char normalized[MAX_PHONE];
        normalizePhone(argv[2], normalized, sizeof(normalized));
        printf("%d\n", isValidPhone(normalized));
        return 0;
    }

    if (strcmp(argv[1], "valid-age") == 0 && argc >= 3) {
        printf("%d\n", isValidAge(argv[2]));
        return 0;
    }

    if (strcmp(argv[1], "remaining-time") == 0 && argc >= 3) {
        char out[64];
        remainingTimeLabel(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "parse-datetime") == 0 && argc >= 3) {
        struct tm parsed;
        char out[40];
        if (!parseIsoDatetime(argv[2], &parsed)) {
            printf("\n");
            return 0;
        }
        strftime(out, sizeof(out), "%Y-%m-%dT%H:%M:%S", &parsed);
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "status-label") == 0 && argc >= 3) {
        char out[64];
        statusLabelForPatient(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    if (strcmp(argv[1], "strip-title") == 0 && argc >= 3) {
        char out[MAX_NAME];
        stripDoctorTitle(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }

    fprintf(stderr, "Unknown command: %s\n", argv[1]);
    return 1;
}
