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
    char gender[20];
    char phone[11];
    char address[200];
    char symptoms[200];
    char visit_type[20];
    char priority[20];
    char department[30];
};