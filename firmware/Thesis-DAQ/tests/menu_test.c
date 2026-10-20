// Host tests exercise the actual menu logic with fake I2C, PWM and USB APIs.
#include "../main/main.c"

esp_err_t sensors_init(i2c_master_bus_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t sensors_deinit(void) { return ESP_OK; }
esp_err_t sensors_read_power(power_sample_t *sample) { *sample = (power_sample_t){12, 2, 24}; return ESP_OK; }
esp_err_t sensors_read_force(int32_t *raw) { *raw = 123; return ESP_OK; }

static void start_power_test(const char *option, int64_t now)
{
    mode = MENU;
    sensors_ready = true;
    esc_ready_at = 0;
    last_power = last_force = now;
    captured[0] = 0;
    command(option, now);
}

static void test_menu_repeat(void)
{
    for (int m = MENU; m <= POWER_SETTINGS; ++m) {
        mode = (app_mode_t)m;
        pulse_us = 1600;
        collecting = true;
        step_deadline = 12345678;
        power_step_started = 23456789;
        int points_before = point_count;
        captured[0] = 0;
        command("11", 10000000);
        assert(mode == (app_mode_t)m && pulse_us == 1600 && collecting);
        assert(step_deadline == 12345678 && power_step_started == 23456789);
        assert(point_count == points_before);
        assert(strstr(captured, "11. Repeat menu options"));
        assert(!strstr(captured, "Power test started") && !strstr(captured, "Printing sensor data"));
        bool has_header = strstr(captured, "time_us,force_raw,force_N") != NULL;
        assert(has_header == (m == CSV || m == POWER_RAW));
        if (m == POWER_RAW) assert(strstr(captured, "power_settled,test_step\n"));
    }
    mode = MENU;
    pulse_us = NEUTRAL_US;
    collecting = false;
    captured[0] = 0;
}

static void test_power_control(void)
{
    mode = POWER_SETTINGS;
    command("set 5 15 5 5", 0);
    assert(power_start_W == 5 && power_max_W == 15 && power_step_W == 5 && power_hold_seconds == 5);
    command("set 5 14 5 5", 0);
    command("set nan 15 5 5", 0);
    command("set 5 inf 5 5", 0);
    command("set 5 15 0 5", 0);
    command("set 0.0001 0.0001 1 5", 0);
    command("set 5 15 0.0001 5", 0);
    command("set 5 25 5 5", 0);
    command("set 5 15 5 0", 0);
    command("limits 1950 10 25", 0);
    command("limits 1700 16 25", 0);
    command("limits 1700 nan 25", 0);
    command("limits 1700 10 15", 0);
    assert(power_max_W == 15 && power_step_W == 5 && power_hold_seconds == 5);
    assert(power_max_pwm == 1700 && power_current_limit_A == 11 && power_limit_W == 25);
    command("limits 1800 8 30", 0);
    assert(power_max_pwm == 1800 && power_current_limit_A == 8 && power_limit_W == 30);
    command("limits 1700 11 25", 0);
    command("set 3 9 3 4", 0);
    assert(power_start_W == 3 && power_max_W == 9 && power_step_W == 3 && power_hold_seconds == 4);
    command("set 5 15 5 5", 0);
    command("timing 3 45", 0);
    command("timing 0 10", 0);
    assert(power_settle_seconds == 3 && power_timeout_seconds == 45);
    command("timing 2 60", 0);

    calibrated = false;
    start_power_test("9", 10000000);
    assert(mode == MENU && strstr(captured, "Calibrate force"));
    start_power_test("8", 10000000);
    assert(mode == POWER_RAW && strstr(captured, "target_power_W,filtered_power_W,power_settled,test_step"));
    power_sample_t power = {12, 0.4f, 4.8f};
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    captured[0] = 0;
    print_sample(10000000, &power, 2000, ESP_OK, ESP_OK);
    assert(strstr(captured, "10000000,2000,,") && strstr(captured, ",5.000,4.8000,0,1\n"));
    calibrated = true;
    command("exit", 10000000);
    start_power_test("9", 10000000);
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    captured[0] = 0;
    print_sample(10000000, &power, 2000, ESP_OK, ESP_OK);
    assert(strstr(captured, " N, Voltage:") && strstr(captured, "Target: 5.000 W, Filtered: 4.800 W, Settled: 0, Step: 1"));
    command("exit", 10000000);

    // Different loads need different PWM commands for the same watt targets.
    int final_commands[2] = {0, 0};
    for (int device = 0; device < 2; ++device) {
        double gain = device == 0 ? 0.10 : 0.16;
        double watts = 0.2;
        int64_t now = 10000000;
        start_power_test(device == 0 ? "8" : "9", now);
        int settled_steps[3] = {0, 0, 0};
        for (int tick = 0; tick < 2400 && power_active(); ++tick) {
            now += 50000;
            // Simulated motor lag and a one-sample delay, at the actual 20 Hz read rate.
            double demand = 0.2 + gain * (pulse_us - NEUTRAL_US);
            power = (power_sample_t){12, (float)(watts / 12), (float)watts};
            watts += 0.15 * (demand - watts);
            last_power = last_force = now;
            observe_power(now, &power, ESP_OK, ESP_OK);
            assert(power_active());
            if (power_settled) {
                ++settled_steps[power_step_index];
                assert(fabs(filtered_power_W - target_power_W) <= power_tolerance());
                if (power_step_index == 2) final_commands[device] = pulse_us;
            }
            int previous_pulse = pulse_us;
            update_power(now);
            if (power_active()) {
                assert(pulse_us >= NEUTRAL_US && pulse_us <= power_max_pwm);
                assert(abs(pulse_us - previous_pulse) <= 2);
            }
            captured[0] = 0;
        }
        assert(mode == MENU && pulse_us == NEUTRAL_US);
        for (int step = 0; step < 3; ++step) assert(settled_steps[step] >= 99);
    }
    assert(final_commands[0] > final_commands[1]);

    start_power_test("8", 10000000);
    power = (power_sample_t){12, 1, 1};
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    update_power(10000000);
    int previous_pulse = pulse_us;
    update_power(10000000); // Same reading must never generate another correction.
    assert(pulse_us == previous_pulse);
    pulse_us = power_max_pwm;
    last_power = last_force = 10100000;
    observe_power(10100000, &power, ESP_OK, ESP_OK);
    update_power(10100000);
    assert(pulse_us == power_max_pwm);
    update_power(10700000);
    assert(mode == MENU && pulse_us == NEUTRAL_US); // Stale-data shutdown.

    // Isolate current protection from the independent watt cutoff: 10 A can run,
    // while reaching 11 A trips, including the exact threshold.
    power_limit_W = 200;
    start_power_test("8", 10000000);
    power = (power_sample_t){11.1f, 10, 111};
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    assert(mode == POWER_RAW);
    power = (power_sample_t){11.1f, 11, 122.1f};
    observe_power(10050000, &power, ESP_OK, ESP_OK);
    assert(mode == MENU && pulse_us == NEUTRAL_US);
    start_power_test("8", 10000000);
    power = (power_sample_t){11.1f, 11.1f, 123.21f};
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    assert(mode == MENU && pulse_us == NEUTRAL_US);
    power_limit_W = 25;

    const power_sample_t faults[] = {{12, 11, 20}, {12, 1, 25}, {12, -1, 5}, {NAN, 1, 5}, {12, 1, NAN}};
    for (unsigned i = 0; i < sizeof(faults) / sizeof(faults[0]); ++i) {
        start_power_test("8", 10000000);
        observe_power(10000000, &faults[i], ESP_OK, ESP_OK);
        assert(mode == MENU && pulse_us == NEUTRAL_US);
    }
    start_power_test("8", 10000000);
    observe_power(10000000, &power, 2, ESP_OK);
    assert(mode == MENU && pulse_us == NEUTRAL_US);

    start_power_test("8", 10000000);
    power = (power_sample_t){12, 0.4f, 5};
    observe_power(10000000, &power, ESP_OK, ESP_OK);
    observe_power(12100000, &power, ESP_OK, ESP_OK);
    assert(power_settled);
    observe_power(12200000, &power, ESP_ERR_NOT_FINISHED, ESP_OK);
    assert(!power_settled && !power_in_band_since);
    observe_power(12300000, &power, ESP_OK, ESP_OK);
    assert(!power_settled);
    observe_power(12400000, &power, ESP_OK, ESP_ERR_NOT_FINISHED);
    assert(!power_settled && !power_in_band_since);
    int64_t timeout = power_step_started + (int64_t)(power_timeout_seconds + power_settle_seconds + power_hold_seconds) * 1000000 + 1;
    last_power = last_force = timeout;
    update_power(timeout);
    assert(mode == MENU && pulse_us == NEUTRAL_US && strstr(captured, "timeout"));
    captured[0] = 0;
}

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
    assert(strstr(captured, "Timestamp: 12345 us, Force: 123 counts (uncalibrated), Voltage: 12.0000 V, Current: 2.0000 A, Power: 24.0000 W, Current PWM: 1500 us"));
    captured[0] = 0;
    mode = CSV;
    print_sample(12345, &power, 123, ESP_OK, ESP_OK);
    assert(strstr(captured, "12345,123,,12.0000,2.0000,24.0000,1500,ESP_OK,ESP_OK,0"));

    for (int m = MENU; m <= POWER_SETTINGS; ++m) {
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
    test_menu_repeat();
    test_power_control();
    puts("Menu, output, CSV, calibration, PWM and power-control simulation/fault tests passed.");
    return 0;
}
