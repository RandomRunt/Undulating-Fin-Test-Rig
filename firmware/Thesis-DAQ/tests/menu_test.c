// Host tests exercise the actual menu logic with fake I2C, PWM and USB APIs.
#include "../main/main.c"

esp_err_t sensors_init(i2c_master_bus_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t sensors_deinit(void) { return ESP_OK; }
esp_err_t sensors_read_power(power_sample_t *sample) { *sample = (power_sample_t){12, 2, 24}; return ESP_OK; }
esp_err_t sensors_read_force(int32_t *raw) { *raw = 123; return ESP_OK; }

int main(void)
{
    power_sample_t power = {12, 2, 24};
    mode = MENU;
    print_sample(12345, &power, 123, ESP_OK, ESP_OK);
    assert(captured[0] == 0); // Startup/menu must not continuously print samples.
    mode = PWM_TEST;
    print_sample(12345, &power, 123, ESP_OK, ESP_OK);
    assert(captured[0] == 0); // Test without data must stay quiet between step notices.

    mode = FORMATTED;
    print_sample(12345, &power, 123, ESP_OK, ESP_OK);
    assert(strstr(captured, "Timestamp: 12345 us, Force: 123 counts (uncalibrated), Power: 24.0000 W, Current PWM: 1500 us"));
    captured[0] = 0;
    mode = CSV;
    print_sample(12345, &power, 123, ESP_OK, ESP_OK);
    assert(strstr(captured, "12345,123,,12.0000,2.0000,24.0000,1500,ESP_OK,ESP_OK,0"));

    for (int m = MENU; m <= PWM_SETTINGS; ++m) {
        mode = (app_mode_t)m;
        pulse_us = 1650;
        collecting = true;
        command("exit", 0);
        assert(mode == MENU && pulse_us == 1500 && !collecting);
        captured[0] = 0;
    }
    mode = FORMATTED;
    incoming = "ex";
    poll_commands(0);
    assert(mode == FORMATTED); // 'x' inside 'exit' must not be interpreted separately.
    incoming = "it\r\n";
    poll_commands(0);
    assert(mode == MENU);
    captured[0] = 0;

    mode = PWM_SETTINGS;
    command("set 1800 50 3", 0);
    assert(sweep_max == 1800 && sweep_step == 50 && sweep_seconds == 3);
    command("set 1800 0 3", 0);
    command("set 1950 50 3", 0);
    command("set 1800 70 3", 0);
    assert(sweep_max == 1800 && sweep_step == 50 && sweep_seconds == 3);
    captured[0] = 0;

    mode = PIN_SETTINGS;
    command("pins 8 9 3", 0);
    command("pins 0 0 3", 0);
    assert(sda_gpio == 0 && scl_gpio == 1 && esc_gpio == 3);
    command("pins 4 5 3", 0);
    assert(sda_gpio == 4 && scl_gpio == 5 && esc_gpio == 3 && sensors_ready);
    captured[0] = 0;

    mode = CALIBRATION;
    command("tare", 0);
    for (int i = 0; i < CALIBRATION_SAMPLES; ++i) collect_sample(1000);
    assert(tared && point_count == 1 && tare_counts == 1000);
    command("point 10", 0);
    for (int i = 0; i < CALIBRATION_SAMPLES; ++i) collect_sample(2000);
    command("point 20", 0);
    for (int i = 0; i < CALIBRATION_SAMPLES; ++i) collect_sample(3000);
    command("fit", 0);
    assert(calibrated && fabs(newtons_per_count - 0.01) < 1e-9 && fabs(tare_counts - 1000) < 1e-9);
    command("tare", 0);
    for (int i = 0; i < CALIBRATION_SAMPLES; ++i) collect_sample(1100);
    assert(calibrated && tare_counts == 1100 && fabs(newtons_per_count - 0.01) < 1e-9);
    captured[0] = 0;

    return_to_menu(NULL);
    sensors_ready = true;
    esc_ready_at = 0;
    sweep_max = 1600;
    sweep_step = 50;
    sweep_seconds = 1;
    last_power = last_force = 10000000;
    command("4", 10000000);
    assert(mode == PWM_TEST && pulse_us == 1500);
    update_pwm(10400000);
    assert(pulse_us == 1500); // No early step before the hold expires.
    last_power = last_force = 11000000;
    update_pwm(11000000);
    assert(pulse_us == 1550);
    last_power = last_force = 12000000;
    update_pwm(12000000);
    assert(pulse_us == 1600);
    last_power = last_force = 13000000;
    update_pwm(13000000);
    assert(mode == MENU && pulse_us == 1500);
    command("5", 13000000);
    assert(mode == PWM_DATA);
    update_pwm(13600000);
    assert(mode == MENU && pulse_us == 1500); // Stale sensors stop the test.
    puts("Menu, output, exit, pin/PWM validation, calibration and sweep tests passed.");
    return 0;
}
