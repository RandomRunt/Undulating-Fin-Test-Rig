#include <inttypes.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sensors.h"

// C3 Super Mini: GPIO0 -> both SDA pins; GPIO1 -> both SCL pins.
// Both breakout VIN pins -> 3V3; all signal grounds -> GND.
// GPIO3 -> Basic ESC white signal wire; ESC signal ground -> ESP32 GND.
// ESC motor power comes from its own supply, never from an ESP32 GPIO.
// GPIO8/9 share LED/BOOT and boot strapping; GPIO18/19 are native USB.
#define DEFAULT_SDA GPIO_NUM_0
#define DEFAULT_SCL GPIO_NUM_1
#define DEFAULT_ESC GPIO_NUM_3
#define NEUTRAL_US 1500
#define MAX_FORWARD_US 1900
#define PWM_PERIOD_US 20000 // 50 Hz servo pulses, not motor switching PWM.
#define PWM_COUNTS 16384   // 14-bit resolution: about 1.22 us per count.
#define SAMPLE_INTERVAL_US 50000 // Approximately 20 Hz; sensors are not synchronized.
#define STALE_US 500000
#define CALIBRATION_SAMPLES 40
#define MAX_CALIBRATION_POINTS 8

typedef enum {
    MENU, CALIBRATION, FORMATTED, CSV, PWM_TEST, PWM_DATA, PIN_SETTINGS, PWM_SETTINGS
} app_mode_t;

static app_mode_t mode = MENU;
static int sda_gpio = DEFAULT_SDA, scl_gpio = DEFAULT_SCL, esc_gpio = DEFAULT_ESC;
static int pulse_us = NEUTRAL_US;
static int sweep_max = 1700, sweep_step = 50, sweep_seconds = 5;
static int64_t step_deadline, esc_ready_at, last_power, last_force;
static bool sensors_ready;
static i2c_master_bus_handle_t bus;
static double tare_counts, newtons_per_count;
static bool tared, calibrated;
static bool collecting, collecting_tare;
static int collection_count, point_count;
static double collection_sum, applied_force_N;
static int64_t collection_started;
static double point_counts[MAX_CALIBRATION_POINTS], point_forces[MAX_CALIBRATION_POINTS];
static unsigned dropped_lines;

static void output(const char *format, ...)
{
    char line[256];
    va_list args;
    va_start(args, format);
    int length = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    // A stalled laptop must not block ESC control; report lost output in CSV.
    if (length > 0 && length < (int)sizeof(line)) {
        if (usb_serial_jtag_write_bytes(line, length, 0) != length) ++dropped_lines;
    }
}

static uint32_t pulse_to_duty(int us)
{
    return ((uint32_t)us * PWM_COUNTS + PWM_PERIOD_US / 2) / PWM_PERIOD_US;
}

static void set_pulse(int us)
{
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, pulse_to_duty(us)));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0));
    pulse_us = us; // Commanded width; hardware rounds to approximately 1.22 us steps.
}

static bool pwm_active(void)
{
    return mode == PWM_TEST || mode == PWM_DATA;
}

static void update_pwm(int64_t now);

static void show_menu(void)
{
    output("\nThesis DAQ - choose a number, then Enter\n");
    output("1. Calibrate force sensor\n");
    output("2. Print formatted timestamped sensor output\n");
    output("3. Print unformatted timestamped sensor output (CSV)\n");
    output("4. Perform PWM test\n");
    output("5. Perform PWM test with timestamped data printing\n");
    output("6. Current pin settings\n");
    output("7. PWM test settings\n");
    output("Type exit + Enter in any mode to stop and return here.\n> ");
}

static void return_to_menu(const char *reason)
{
    set_pulse(NEUTRAL_US);
    collecting = false;
    mode = MENU;
    if (reason) output("\n%s\n", reason);
    show_menu();
}

static void update_pwm(int64_t now)
{
    if (!pwm_active()) return;
    if (now - last_power > STALE_US || now - last_force > STALE_US) {
        return_to_menu("PWM test stopped: sensor data stale.");
    } else if (now >= step_deadline) {
        if (pulse_us >= sweep_max) return_to_menu("PWM test complete.");
        else {
            set_pulse(pulse_us + sweep_step);
            step_deadline = now + (int64_t)sweep_seconds * 1000000;
            output("PWM step: %d us\n", pulse_us);
        }
    }
}

static void show_pins(void)
{
    output("SDA: GPIO%d, SCL: GPIO%d, ESC signal: GPIO%d\n", sda_gpio, scl_gpio, esc_gpio);
    output("Both sensor VIN pins: 3V3; all signal grounds: GND.\n");
    output("To change: pins <SDA GPIO> <SCL GPIO> <ESC GPIO>, e.g. pins 0 1 3\n");
    output("Stop motor power before rewiring. Settings reset on reboot. Type exit to return.\n");
}

static void show_pwm_settings(void)
{
    output("Start/stop: 1500 us; maximum: %d us; increment: %d us; hold: %d s; frequency: 50 Hz\n",
           sweep_max, sweep_step, sweep_seconds);
    output("To change: set <maximum_us> <increment_us> <hold_seconds>, e.g. set 1700 50 5\n");
    output("Max 1500..1900; positive increment dividing the range; hold 1..60 s. Type exit to return.\n");
}

static void show_calibration(void)
{
    output("ESC is neutral. Apply calibration forces along the rig's measurement axis.\n");
    output("Remove the applied force, then type tare and wait for completion.\n");
    output("Apply a known force; type point <newtons> to record it, e.g. point 9.80665\n");
    output("Repeat for several loads, then type fit. Each point averages 40 fresh readings.\n");
    output("Commands: tare | point <N> | fit | show | exit. Calibration is RAM-only.\n");
}

static bool allowed_pin(int pin)
{
    // Restrict to exposed GPIOs without USB, boot-strapping, LED or BOOT conflicts.
    return pin == 0 || pin == 1 || (pin >= 3 && pin <= 7) ||
           pin == 10 || pin == 20 || pin == 21;
}

static esp_err_t configure_sensors(void)
{
    const i2c_master_bus_config_t config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = sda_gpio,
        .scl_io_num = scl_gpio,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false, // Adafruit boards supply pull-ups.
    };
    esp_err_t err = i2c_new_master_bus(&config, &bus);
    if (err == ESP_OK) err = sensors_init(bus);
    sensors_ready = err == ESP_OK;
    last_power = last_force = 0;
    return err;
}

static esp_err_t configure_esc(void)
{
    const ledc_channel_config_t channel = {
        .gpio_num = esc_gpio,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = pulse_to_duty(NEUTRAL_US),
    };
    esp_err_t err = ledc_channel_config(&channel);
    pulse_us = NEUTRAL_US;
    esc_ready_at = esp_timer_get_time() + 5000000;
    return err;
}

static void change_pins(int sda, int scl, int esc)
{
    if (!allowed_pin(sda) || !allowed_pin(scl) || !allowed_pin(esc) ||
        sda == scl || sda == esc || scl == esc) {
        output("Use three different GPIOs from: 0, 1, 3, 4, 5, 6, 7, 10, 20, 21.\n");
        return;
    }
    set_pulse(NEUTRAL_US);
    // Remove old device handles before deleting their bus and releasing its pins.
    ESP_ERROR_CHECK(sensors_deinit());
    if (bus) ESP_ERROR_CHECK(i2c_del_master_bus(bus));
    bus = NULL;
    // Leave the old signal pin LOW, so it does not retain a second PWM output.
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0));
    sda_gpio = sda;
    scl_gpio = scl;
    esc_gpio = esc;
    ESP_ERROR_CHECK(configure_esc());
    esp_err_t err = configure_sensors();
    // Moving sensor pins requires rechecking force calibration on the wired rig.
    tared = calibrated = false;
    point_count = 0;
    show_pins();
    output("Sensor initialization: %s\n", esp_err_to_name(err));
}

static void begin_collection(bool tare, double force, int64_t now)
{
    if (!sensors_ready || collecting || (!tare && (!tared || point_count >= MAX_CALIBRATION_POINTS))) {
        output("Need healthy sensors, a completed tare, and a free point slot (max 8).\n");
        return;
    }
    collecting = true;
    collecting_tare = tare;
    collection_count = 0;
    collection_sum = 0;
    applied_force_N = force;
    collection_started = now;
    output("Recording %.6g N; hold steady until the point summary appears.\n", force);
}

static void collect_sample(int32_t raw)
{
    if (!collecting) return;
    collection_sum += raw;
    if (++collection_count < CALIBRATION_SAMPLES) return;
    double mean = collection_sum / CALIBRATION_SAMPLES;
    if (collecting_tare) {
        tare_counts = mean;
        tared = true;
        // Keep a previously fitted scale when re-zeroing; start a new point dataset.
        point_count = 0;
    }
    point_counts[point_count] = mean;
    point_forces[point_count++] = applied_force_N;
    collecting = false;
    output("Point %d: force=%.6g N, mean_raw=%.3f counts\n", point_count, applied_force_N, mean);
    output("Apply next force and enter point <N>, or fit; exit returns to the menu.\n");
}

static void fit_calibration(void)
{
    if (collecting || point_count < 2) {
        output("Finish recording at least zero and one loaded point first.\n");
        return;
    }
    double mean_x = 0, mean_y = 0, xx = 0, xy = 0;
    for (int i = 0; i < point_count; ++i) {
        mean_x += point_counts[i] / point_count;
        mean_y += point_forces[i] / point_count;
    }
    for (int i = 0; i < point_count; ++i) {
        double dx = point_counts[i] - mean_x;
        xx += dx * dx;
        xy += dx * (point_forces[i] - mean_y);
    }
    // Fit force = slope * counts + intercept, then express it using a zero offset.
    double slope = xx > 0 ? xy / xx : 0;
    if (xx < 10000 || !isfinite(slope) || fabs(slope) < 1e-15) {
        output("Fit rejected: insufficient load variation or invalid calibration points.\n");
        return;
    }
    newtons_per_count = slope;
    tare_counts = mean_x - mean_y / slope;
    calibrated = tared = true;
    output("Calibration fitted: tare_counts=%.6f, newtons_per_count=%.9g (RAM only)\n",
           tare_counts, newtons_per_count);
    for (int i = 0; i < point_count; ++i) {
        output("Point %d residual: %.6g N\n", i + 1,
               (point_counts[i] - tare_counts) * slope - point_forces[i]);
    }
}

static void print_sample(int64_t now, const power_sample_t *power, int32_t raw,
                         esp_err_t power_status, esp_err_t force_status)
{
    if (mode != FORMATTED && mode != CSV && mode != PWM_DATA) return;
    char raw_text[24] = "", force_text[48] = "unavailable";
    if (force_status == ESP_OK) {
        snprintf(raw_text, sizeof(raw_text), "%" PRId32, raw);
        if (calibrated) snprintf(force_text, sizeof(force_text), "%.6f", (raw - tare_counts) * newtons_per_count);
        else snprintf(force_text, sizeof(force_text), "%" PRId32 " counts (uncalibrated)", raw);
    }
    if (mode == FORMATTED || mode == PWM_DATA) {
        output("Timestamp: %" PRId64 " us, Force: %s%s, Power: %.4f W, Current PWM: %d us\n",
               now, force_text, calibrated && force_status == ESP_OK ? " N" : "", power->power_W, pulse_us);
    } else {
        // CSV keeps raw counts and read status, so later analysis can identify missing data.
        char calibrated_text[32] = "";
        if (calibrated && force_status == ESP_OK) {
            snprintf(calibrated_text, sizeof(calibrated_text), "%.6f", (raw - tare_counts) * newtons_per_count);
        }
        output("%" PRId64 ",%s,%s,%.4f,%.4f,%.4f,%d,%s,%s,%u\n", now,
               raw_text, calibrated_text, power->voltage_V, power->current_A, power->power_W,
               pulse_us, esp_err_to_name(power_status), esp_err_to_name(force_status), dropped_lines);
    }
}

static void command(const char *line, int64_t now)
{
    // Match whole commands: treating every 'x' as stop would break the word 'exit'.
    if (strcmp(line, "exit") == 0 || strcmp(line, "stop") == 0) {
        return_to_menu("Returned to neutral.");
        return;
    }
    int a, b, c;
    double force;
    char extra;
    if (mode == MENU) {
        if (strcmp(line, "1") == 0) {
            mode = CALIBRATION;
            show_calibration();
        } else if (strcmp(line, "2") == 0 || strcmp(line, "3") == 0) {
            if (!sensors_ready) {
                output("Sensors are not initialized; check wiring and option 6.\n> ");
                return;
            }
            mode = line[0] == '2' ? FORMATTED : CSV;
            output("Printing sensor data; type exit + Enter to stop.\n");
            if (mode == CSV) output("time_us,force_raw,force_N,voltage_V,current_A,power_W,pulse_us,power_status,force_status,dropped_lines\n");
        } else if (strcmp(line, "4") == 0 || strcmp(line, "5") == 0) {
            if (!sensors_ready || now < esc_ready_at || !last_power || !last_force ||
                now - last_power > STALE_US || now - last_force > STALE_US) {
                output("Wait for healthy sensors and five seconds of neutral ESC initialization.\n> ");
                return;
            }
            mode = line[0] == '4' ? PWM_TEST : PWM_DATA;
            set_pulse(NEUTRAL_US);
            step_deadline = now + (int64_t)sweep_seconds * 1000000;
            output("PWM test started: 1500..%d us, step %d us, hold %d s. Type exit to stop.\n",
                   sweep_max, sweep_step, sweep_seconds);
        } else if (strcmp(line, "6") == 0) {
            mode = PIN_SETTINGS;
            show_pins();
        } else if (strcmp(line, "7") == 0) {
            mode = PWM_SETTINGS;
            show_pwm_settings();
        } else {
            output("Choose 1..7, then Enter.\n> ");
        }
    } else if (mode == CALIBRATION) {
        if (strcmp(line, "tare") == 0) begin_collection(true, 0, now);
        else if (sscanf(line, "point %lf %c", &force, &extra) == 1 && isfinite(force) && force != 0) {
            begin_collection(false, force, now);
        } else if (strcmp(line, "fit") == 0) fit_calibration();
        else if (strcmp(line, "show") == 0) {
            output("Calibrated: %s; tare=%.6f; N/count=%.9g; points=%d\n",
                   calibrated ? "yes" : "no", tare_counts, newtons_per_count, point_count);
        } else output("Use tare, point <nonzero N>, fit, show, or exit.\n");
    } else if (mode == PIN_SETTINGS) {
        if (sscanf(line, "pins %d %d %d %c", &a, &b, &c, &extra) == 3) change_pins(a, b, c);
        else show_pins();
    } else if (mode == PWM_SETTINGS) {
        if (sscanf(line, "set %d %d %d %c", &a, &b, &c, &extra) == 3 &&
            a >= NEUTRAL_US && a <= MAX_FORWARD_US && b >= 1 && b <= 400 &&
            (a - NEUTRAL_US) % b == 0 && c >= 1 && c <= 60) {
            sweep_max = a;
            sweep_step = b;
            sweep_seconds = c;
        } else output("Invalid settings; settings were not changed.\n");
        show_pwm_settings();
    } else output("Type exit + Enter to stop and return to the menu.\n");
}

static void poll_commands(int64_t now)
{
    static char line[80];
    static size_t used;
    static bool overflow;
    char input[80];
    int count = usb_serial_jtag_read_bytes(input, sizeof(input), 0);
    for (int i = 0; i < count; ++i) {
        char ch = input[i];
        // Echo while navigating, but keep streaming CSV free of typed characters.
        bool echo = mode == MENU || mode == CALIBRATION || mode == PIN_SETTINGS || mode == PWM_SETTINGS;
        if (ch == '\r' || ch == '\n') {
            if (echo && (used || overflow)) output("\n");
            if (overflow) output("Command too long; try again.\n");
            else if (used) {
                line[used] = '\0';
                command(line, now);
            }
            used = 0;
            overflow = false;
        } else if (ch == '\b' || ch == 127) {
            if (used) {
                --used;
                if (echo) output("\b \b");
            }
        } else if (ch >= 32 && ch <= 126) {
            if (used < sizeof(line) - 1) {
                line[used++] = ch;
                if (echo) output("%c", ch);
            }
            else overflow = true; // Discard the entire oversized command.
        }
    }
}

void app_main(void)
{
    // Hardware generates PWM independently; neutral is established before I2C setup.
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_14_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 50,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    ESP_ERROR_CHECK(configure_esc());
    usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 4096, .rx_buffer_size = 256};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    esp_err_t init = configure_sensors();
    if (init != ESP_OK) output("Sensor initialization failed: %s; check wiring via option 6.\n", esp_err_to_name(init));
    show_menu();
    int64_t next_sample = 0;
    bool was_connected = false;
    while (1) {
        int64_t now = esp_timer_get_time();
        bool connected = usb_serial_jtag_is_connected();
        if (connected && !was_connected) show_menu();
        if (!connected && was_connected) return_to_menu("USB disconnected.");
        was_connected = connected;
        poll_commands(now);

        // Read quietly even at the menu, so PWM tests can check sensor freshness.
        if (sensors_ready && now >= next_sample) {
            next_sample = now + SAMPLE_INTERVAL_US;
            power_sample_t power = {NAN, NAN, NAN};
            int32_t raw = 0;
            esp_err_t p = sensors_read_power(&power);
            if (p != ESP_OK) power = (power_sample_t){NAN, NAN, NAN};
            else last_power = esp_timer_get_time();
            esp_err_t f = sensors_read_force(&raw);
            if (f == ESP_OK) {
                last_force = esp_timer_get_time();
                collect_sample(raw);
            }
            print_sample(now, &power, raw, p, f);
            if (pwm_active() && ((p != ESP_OK && p != ESP_ERR_NOT_FINISHED) ||
                                 (f != ESP_OK && f != ESP_ERR_NOT_FINISHED))) {
                return_to_menu("PWM test stopped: sensor read error.");
            }
        }
        now = esp_timer_get_time();
        if (collecting && now - collection_started > 5000000) {
            collecting = false;
            output("Calibration point timed out; check the force sensor and retry.\n");
        }
        update_pwm(now);
        // One task owns sensors, menu and PWM state, avoiding shared-state locks.
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
