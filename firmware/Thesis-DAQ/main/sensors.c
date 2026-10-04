#include "sensors.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// Native ESP-IDF register access; no Arduino framework is required.
// Register references: TI INA260 datasheet and Nuvoton NAU7802 datasheet.
// Adafruit's drivers also document the breakout initialization settings:
// https://github.com/adafruit/Adafruit_INA260
// https://github.com/adafruit/Adafruit_NAU7802
static const char *TAG = "sensors";
static i2c_master_dev_handle_t ina260;
static i2c_master_dev_handle_t nau7802;

esp_err_t sensors_deinit(void)
{
    // Pin changes must release device handles before the I2C bus is deleted.
    if (ina260) {
        ESP_RETURN_ON_ERROR(i2c_master_bus_rm_device(ina260), TAG, "INA detach");
        ina260 = NULL;
    }
    if (nau7802) {
        ESP_RETURN_ON_ERROR(i2c_master_bus_rm_device(nau7802), TAG, "NAU detach");
        nau7802 = NULL;
    }
    return ESP_OK;
}

static esp_err_t read_reg(i2c_master_dev_handle_t dev, uint8_t reg,
                          uint8_t *data, size_t length)
{
    // A repeated START keeps the register selection and read in one transaction.
    return i2c_master_transmit_receive(dev, &reg, 1, data, length, 50);
}

static esp_err_t write8(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t value)
{
    uint8_t data[] = {reg, value};
    return i2c_master_transmit(dev, data, sizeof(data), 50);
}

static esp_err_t read16(uint8_t reg, uint16_t *value)
{
    uint8_t data[2];
    esp_err_t err = read_reg(ina260, reg, data, sizeof(data));
    if (err == ESP_OK) {
        // INA260 registers transmit the most significant byte first.
        *value = ((uint16_t)data[0] << 8) | data[1];
    }
    return err;
}

static esp_err_t write16(uint8_t reg, uint16_t value)
{
    uint8_t data[] = {reg, value >> 8, value & 0xff};
    return i2c_master_transmit(ina260, data, sizeof(data), 50);
}

static esp_err_t update8(uint8_t reg, uint8_t mask, uint8_t value)
{
    uint8_t old;
    ESP_RETURN_ON_ERROR(read_reg(nau7802, reg, &old, 1), TAG, "NAU read");
    // Preserve unrelated settings when changing individual register fields.
    return write8(nau7802, reg, (old & ~mask) | (value & mask));
}

esp_err_t sensors_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = 0x40,
        .scl_speed_hz = 100000, // Start at 100 kHz for short bench wiring.
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &config, &ina260), TAG, "INA attach");
    config.device_address = 0x2a;
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &config, &nau7802), TAG, "NAU attach");

    uint16_t manufacturer, chip;
    ESP_RETURN_ON_ERROR(read16(0xfe, &manufacturer), TAG, "INA ID");
    ESP_RETURN_ON_ERROR(read16(0xff, &chip), TAG, "INA ID");
    if (manufacturer != 0x5449 || (chip >> 4) != 0x227) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    ESP_RETURN_ON_ERROR(write16(0x00, 0x8000), TAG, "INA reset");
    vTaskDelay(pdMS_TO_TICKS(10));
    // 0x6123: triggered voltage/current, 1.1 ms each, no ADC averaging.
    // One completed conversion stays stable while we read its three registers.
    ESP_RETURN_ON_ERROR(write16(0x00, 0x6123), TAG, "INA config");

    ESP_RETURN_ON_ERROR(write8(nau7802, 0x00, 0x01), TAG, "NAU reset");
    vTaskDelay(pdMS_TO_TICKS(10));
    ESP_RETURN_ON_ERROR(write8(nau7802, 0x00, 0x06), TAG, "NAU power");
    vTaskDelay(pdMS_TO_TICKS(600)); // Allow analog circuitry to settle.
    uint8_t value;
    ESP_RETURN_ON_ERROR(read_reg(nau7802, 0x00, &value, 1), TAG, "NAU ready");
    if (!(value & 0x08)) {
        return ESP_ERR_TIMEOUT;
    }
    ESP_RETURN_ON_ERROR(read_reg(nau7802, 0x1f, &value, 1), TAG, "NAU ID");
    if ((value & 0x0f) != 0x0f) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    // 3.0 V bridge excitation fits a 3.3 V supply; gain 128 suits small bridge signals.
    ESP_RETURN_ON_ERROR(write8(nau7802, 0x01, (5 << 3) | 7), TAG, "NAU gain/LDO");
    ESP_RETURN_ON_ERROR(update8(0x00, 0x90, 0x90), TAG, "NAU LDO/start");
    // Channel 1, 80 samples/s. We log a subset at 20 Hz, not every conversion.
    ESP_RETURN_ON_ERROR(write8(nau7802, 0x02, 0x30), TAG, "NAU rate");
    ESP_RETURN_ON_ERROR(update8(0x15, 0x30, 0x30), TAG, "NAU chopper");
    ESP_RETURN_ON_ERROR(update8(0x1b, 0x40, 0x00), TAG, "NAU capacitor mode");
    vTaskDelay(pdMS_TO_TICKS(100));
    // Internal ADC calibration is separate from calibrating counts into newtons.
    ESP_RETURN_ON_ERROR(update8(0x02, 0x07, 0x04), TAG, "NAU calibration start");
    for (int attempt = 0; attempt < 200; ++attempt) {
        vTaskDelay(pdMS_TO_TICKS(10));
        ESP_RETURN_ON_ERROR(read_reg(nau7802, 0x02, &value, 1), TAG, "NAU calibration");
        // CALS stays high while calibration runs, then clears on completion.
        if (!(value & 0x04)) {
            return (value & 0x08) ? ESP_ERR_INVALID_RESPONSE : ESP_OK;
        }
    }
    return ESP_ERR_TIMEOUT;
}

esp_err_t sensors_read_power(power_sample_t *sample)
{
    uint16_t status, current, voltage, power;
    ESP_RETURN_ON_ERROR(read16(0x06, &status), TAG, "INA status");
    if (!(status & 0x08)) {
        return ESP_ERR_NOT_FINISHED; // Conversion-ready flag; reading clears it.
    }
    if (status & 0x04) {
        return ESP_ERR_INVALID_RESPONSE; // Math overflow: do not log a valid result.
    }
    ESP_RETURN_ON_ERROR(read16(0x01, &current), TAG, "INA current");
    ESP_RETURN_ON_ERROR(read16(0x02, &voltage), TAG, "INA voltage");
    ESP_RETURN_ON_ERROR(read16(0x03, &power), TAG, "INA power");
    // Datasheet scaling, in SI units. Current uses signed two's-complement.
    sample->current_A = (int16_t)current * 0.00125f;
    sample->voltage_V = voltage * 0.00125f;
    sample->power_W = power * 0.01f;
    // Trigger the NEXT pair now; it completes before the next 20 Hz log slot.
    // It is not synchronized with the load-cell conversion or software timestamp.
    esp_err_t err = write16(0x00, 0x6123);
    if (err != ESP_OK) {
        return err;
    }
    return ESP_OK;
}

esp_err_t sensors_read_force(int32_t *raw)
{
    uint8_t status, data[3];
    ESP_RETURN_ON_ERROR(read_reg(nau7802, 0x00, &status, 1), TAG, "NAU status");
    if (!(status & 0x20)) {
        return ESP_ERR_NOT_FINISHED;
    }
    ESP_RETURN_ON_ERROR(read_reg(nau7802, 0x12, data, sizeof(data)), TAG, "NAU data");
    int32_t value = ((int32_t)data[0] << 16) | ((int32_t)data[1] << 8) | data[2];
    // Convert a signed 24-bit ADC value into a signed 32-bit C integer.
    *raw = (value & 0x800000) ? value - 0x1000000 : value;
    return ESP_OK;
}
