#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_NOT_FINISHED 1
#define ESP_ERROR_CHECK(expr) assert((expr) == ESP_OK)
#define GPIO_NUM_0 0
#define GPIO_NUM_1 1
#define GPIO_NUM_3 3
#define LEDC_LOW_SPEED_MODE 0
#define LEDC_CHANNEL_0 0
#define LEDC_TIMER_0 0
#define LEDC_TIMER_14_BIT 14
#define LEDC_AUTO_CLK 0
#define I2C_NUM_0 0
#define I2C_CLK_SRC_DEFAULT 0
#define pdMS_TO_TICKS(ms) (ms)
typedef void *i2c_master_bus_handle_t;
typedef struct { int i2c_port, sda_io_num, scl_io_num, clk_source, glitch_ignore_cnt; struct { bool enable_internal_pullup; } flags; } i2c_master_bus_config_t;
typedef struct { int gpio_num, speed_mode, channel, timer_sel; uint32_t duty; } ledc_channel_config_t;
typedef struct { int speed_mode, duty_resolution, timer_num, freq_hz, clk_cfg; } ledc_timer_config_t;
typedef struct { int tx_buffer_size, rx_buffer_size; } usb_serial_jtag_driver_config_t;
static char captured[32768];
static const char *incoming;
static int64_t fake_time;
static int usb_serial_jtag_write_bytes(const void *text, size_t length, int ticks) {
    (void)ticks;
    size_t used = strlen(captured);
    assert(used + length < sizeof(captured));
    memcpy(captured + used, text, length);
    captured[used + length] = 0;
    return (int)length;
}
static int usb_serial_jtag_read_bytes(void *buffer, size_t length, int ticks) {
    (void)ticks;
    if (!incoming) return 0;
    size_t count = strlen(incoming);
    if (count > length) count = length;
    memcpy(buffer, incoming, count);
    incoming += count;
    return (int)count;
}
static bool usb_serial_jtag_is_connected(void) { return true; }
static esp_err_t usb_serial_jtag_driver_install(usb_serial_jtag_driver_config_t *c) { (void)c; return ESP_OK; }
static int64_t esp_timer_get_time(void) { return fake_time; }
static void vTaskDelay(int ticks) { fake_time += (int64_t)ticks * 1000; }
static esp_err_t ledc_set_duty(int a, int b, uint32_t duty) { (void)a; (void)b; assert(duty < 16384); return ESP_OK; }
static esp_err_t ledc_update_duty(int a, int b) { (void)a; (void)b; return ESP_OK; }
static esp_err_t ledc_stop(int a, int b, int c) { (void)a; (void)b; (void)c; return ESP_OK; }
static esp_err_t ledc_timer_config(const ledc_timer_config_t *c) { (void)c; return ESP_OK; }
static esp_err_t ledc_channel_config(const ledc_channel_config_t *c) { (void)c; return ESP_OK; }
static esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t *c, i2c_master_bus_handle_t *b) { (void)c; *b = (void *)1; return ESP_OK; }
static esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t b) { (void)b; return ESP_OK; }
static const char *esp_err_to_name(esp_err_t e) { return e == ESP_OK ? "ESP_OK" : "ESP_ERR_NOT_FINISHED"; }
