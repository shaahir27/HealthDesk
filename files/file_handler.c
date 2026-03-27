#include <stdio.h>
#include <string.h>

struct jobcard {
	char reg_no[20];
	char make[20];
	char model[20];
	char owner_name[20];
};

int main(int argc, char *argv[]){
	
	if (argc != 5){
		
		printf("Usage: ./app reg_no make model owner_name\n");
		return 1;
	}
	
	struct jobcard j;
	
	strcpy(j.reg_no, argv[1]);
	strcpy(j.make, argv[2]);
	strcpy(j.model, argv[3]);
	strcpy(j.owner_name, argv[4]);
	
	FILE *fp = fopen("vehicles.dat", "ab");
	if (fp == NULL){
		printf("\nError opening the file!");
		return 1;
		
	}
	
	fwrite(&j, sizeof(struct jobcard), 1, fp);
	fclose(fp);
	printf("\nData written successfully");
	return 0;
}
