#include <stdio.h>
#include <string.h>
#include <stdlib.h>

struct Patient;
struct Doctor;
struct Queue;
struct Diagnosis;
struct Billing;

struct Patient {
    int id;
    char name[30];
    int age;
    char gender[10];
    char phone[10];
    char address[100];
    char symptoms[50];
    char visit_type[20];
    char priority[20];
};