#include <stdio.h>

struct jobcard {
    char reg_no[20];
    char make[20];
    char model[20];
    char owner_name[20];
};

int main() {
    FILE *fp = fopen("vehicles.dat", "rb");

    if (fp == NULL) {
        printf("Error opening file\n");
        return 1;
    }

    struct jobcard j;

    while (fread(&j, sizeof(struct jobcard), 1, fp) == 1) {
        printf("\n--- Jobcard ---\n");
        printf("Reg No: %s\n", j.reg_no);
        printf("Make: %s\n", j.make);
        printf("Model: %s\n", j.model);
        printf("Owner: %s\n", j.owner_name);
    }

    fclose(fp);
    return 0;
}
