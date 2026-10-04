#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void)
{
    vTaskDelay(1000 / portTICK_PERIOD_MS);
    printf("Hello, World!\n");

    while(1) {
        printf("Task is running...\n");
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }


}
