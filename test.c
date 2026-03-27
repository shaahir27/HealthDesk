#include <stdio.h>

int main(int argc, char *argv[]){
    
    if(argc < 2){
        printf("No input recieved\n");
        return 1;
    }

    printf("Recieved: %s", argv[1]);
}