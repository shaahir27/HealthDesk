#include "common.h"

int generate_id(const char *filename) {

    // Reading and Writing data in file
    FILE *fp;
    int count = 0;
    char line[1024];

    fp = fopen(filename, "r");

    if(fp != NULL){
        while(fgets(line, sizeof(line), fp)){
                count++;
            }
        fclose(fp);
    }

    return count + 1;
}

void parse_patient_data(const char *data, struct Patient *p) {
    char buffer[MAX_LINE];
    strncpy(buffer, data, sizeof(buffer) - 1);
    buffer[sizeof(buffer) - 1] = '\0';

    char *token;

    //Parse data
    token = strtok(buffer, "|");
    strcpy(p->name, token);

    token = strtok(NULL, "|");
    p->age = atoi(token);

    token = strtok(NULL, "|");
    strcpy(p->gender, token);

    token = strtok(NULL, "|");
    strcpy(p->phone, token);

    token = strtok(NULL, "|");
    strcpy(p->address, token);

    token = strtok(NULL, "|");
    strcpy(p->symptoms, token);

    token = strtok(NULL, "|");
    strcpy(p->visit_type, token);

    token = strtok(NULL, "|");
    strcpy(p->priority, token);

    token =strtok(NULL, "|");
    strcpy(p->department, token);
    
}

int main(int argc, char *argv[]){

    if(argc < 2){
        printf("Invalid Input\n");
        return 1;
    }

    struct Patient p;

    parse_patient_data(argv[1], &p);    

    FILE *fp;

    p.id = generate_id(PATIENT_FILE);

    fp = fopen(PATIENT_FILE, "a");

    if(fp == NULL){
        printf("Error opening file\n");
        return 1;
    }

    fprintf(fp, "%d|%s|%d|%s|%s|%s|%s|%s|%s|%s\n",
            p.id, p.name, p.age, p.gender, p.phone,
            p.address, p.symptoms, p.visit_type, p.priority, p.department);

    fclose(fp);
    

    // This is the Output that will be displayed in the page
    printf("%d|%s|%s", p.id, p.visit_type, p.priority);

    return 0;
}