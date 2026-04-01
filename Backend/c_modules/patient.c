#include "common.h"

int generate_id(FILE *fp){

    // Reading and Writing data in file

    int count = 0;
    char line[1024];

    fp = fopen("Backend/data/patients.txt", "r");

    if(fp != NULL){
        while(fgets(line, sizeof(line), fp)){
                count++;
            }
        fclose(fp);
    }

    return count + 1;
}

int main(int argc, char *argv[]){

    if(argc < 2){
        printf("Invalid Input\n");
        return 1;
    }

    struct Patient p;

    char data[750];
    strcpy(data, argv[1]);

    char *token;

    //Parse data
    token = strtok(data, "|");
    strcpy(p.name, token);

    token = strtok(NULL, "|");
    p.age = atoi(token);

    token = strtok(NULL, "|");
    strcpy(p.gender, token);

    token = strtok(NULL, "|");
    strcpy(p.phone, token);

    token = strtok(NULL, "|");
    strcpy(p.address, token);

    token = strtok(NULL, "|");
    strcpy(p.symptoms, token);

    token = strtok(NULL, "|");
    strcpy(p.visit_type, token);

    token = strtok(NULL, "|");
    strcpy(p.priority, token);

    token =strtok(NULL, "|");
    strcpy(p.department, token);

    FILE *fp;

    p.id = generate_id(fp);

    fp = fopen("Backend/data/patients.txt", "a");

    fprintf(fp, "%d|%s|%d|%s|%s|%s|%s|%s|%s|%s\n",
            p.id, p.name, p.age, p.gender, p.phone,
            p.address, p.symptoms, p.visit_type, p.priority, p.department);

    fclose(fp);
    

    // This is the Output that will be displayed in the page
    printf("%d|%s|%s", p.id, p.visit_type, p.priority);

    return 0;
}