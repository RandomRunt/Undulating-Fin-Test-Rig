#pragma once

#include <stdint.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

typedef struct {
    float voltage_V;
    float current_A;
    float power_W;
} power_sample_t;

esp_err_t sensors_init(i2c_master_bus_handle_t bus);
esp_err_t sensors_deinit(void);
// ESP_ERR_NOT_FINISHED means the ADC has not produced a fresh sample yet.
esp_err_t sensors_read_power(power_sample_t *sample);
esp_err_t sensors_read_force(int32_t *raw);
