"""Recording switches and settled power-test analysis, without serial hardware."""

import csv
import io
import math
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from SerialLogger import CSVRecorder, run_console
from PlotRecording import read_recording, summarise


HEADER = ("time_us,force_raw,force_N,voltage_V,current_A,power_W,pulse_us,"
          "power_status,force_status,dropped_lines")
POWER_HEADER = HEADER + ",target_power_W,filtered_power_W,power_settled,test_step"


class RecordingTests(unittest.TestCase):
    def test_csv_toggle_resumes_without_new_device_header(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = CSVRecorder(directory, report=lambda _: None, enabled=False)
            recorder.consume(POWER_HEADER)
            recorder.consume("1000000,1000,1,12,1,12,1550,ESP_OK,ESP_OK,0,12,12,1,1")
            self.assertEqual(list(Path(directory).glob("*.csv")), [])
            recorder.set_enabled(True)
            recorder.consume("2000000,1001,1.01,12,1,12,1552,ESP_OK,ESP_OK,0,12,12,1,1")
            recorder.set_enabled(False)
            recorder.consume("3000000,1002,1.02,12,1,12,1554,ESP_OK,ESP_OK,0,12,12,1,1")
            recorder.set_enabled(True)
            recorder.consume("4000000,1003,1.03,12,1,12,1556,ESP_OK,ESP_OK,0,12,12,1,1")
            recorder.consume("Returned to neutral.")
            files = sorted(Path(directory).glob("*.csv"))
            self.assertEqual(len(files), 2)
            rows = []
            for path in files:
                with path.open(newline="") as stream:
                    rows.extend(csv.DictReader(stream))
            self.assertEqual([r["time_us"] for r in rows], ["2000000", "4000000"])
            self.assertEqual(rows[1]["target_power_W"], "12")
            self.assertEqual(rows[1]["pulse_us"], "1556")
            recorder.set_enabled(False)
            recorder.set_enabled(True)
            self.assertEqual(len(list(Path(directory).glob("*.csv"))), 2)

    def test_csv_restart_clock_and_invalid_header(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = CSVRecorder(directory, report=lambda _: None)
            recorder.consume(HEADER)
            recorder.consume("200,1000,,12,1,12,1550,ESP_OK,ESP_OK,0")
            recorder.consume("100,1000,,12,1,12,1550,ESP_OK,ESP_OK,0")
            recorder.consume("time_us,unsupported")
            self.assertIsNone(recorder.stream)
            self.assertIsNone(recorder.header)
            self.assertEqual(len(list(Path(directory).glob("*.csv"))), 2)

    def test_console_toggle_commands_stay_local(self):
        class Port:
            in_waiting = 1

            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(data)

            def read(self, size):
                return b""

        commands = queue.Queue()
        for command in ("/csv off", "/csv", "/csv on", "/quit"):
            commands.put(command)
        port = Port()
        transcript = io.BytesIO()
        with tempfile.TemporaryDirectory() as directory:
            recorder = CSVRecorder(directory, report=lambda _: None)
            with patch("SerialLogger.time.monotonic", side_effect=range(100)), patch("sys.stdout", io.StringIO()):
                run_console(port, recorder, transcript, commands)
            self.assertTrue(recorder.enabled)
        self.assertEqual(port.writes, [b"11\n", b"exit\n", b"exit\n"])
        self.assertIn(b"[HOST COMMAND] 11", transcript.getvalue())
        self.assertIn(b"[LOGGER COMMAND] /csv off", transcript.getvalue())

    def test_connect_requests_menu_and_records_an_existing_csv_stream(self):
        commands = queue.Queue()

        class Port:
            in_waiting = 4096

            def __init__(self):
                self.writes = []
                self.sent = False

            def write(self, data):
                self.writes.append(data)

            def read(self, size):
                if self.sent:
                    return b""
                self.sent = True
                commands.put("/quit")
                # Option 11 reprints the menu and header while retaining mode 8.
                return ("Menu repeated; current mode continues.\n"
                        "Thesis DAQ - choose a number, then Enter\n"
                        "11. Repeat menu options\n> \n" + POWER_HEADER + "\n"
                        "1000000,1000,1,12,1,12,1550,ESP_OK,ESP_OK,0,12,12,1,1\n").encode()

        port = Port()
        transcript = io.BytesIO()
        with tempfile.TemporaryDirectory() as directory:
            recorder = CSVRecorder(directory, report=lambda _: None)
            with patch("SerialLogger.time.monotonic", side_effect=range(100)), patch("sys.stdout", io.StringIO()):
                run_console(port, recorder, transcript, commands)
            files = list(Path(directory).glob("*.csv"))
            self.assertEqual(len(files), 1)
            with files[0].open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["target_power_W"], "12")
        self.assertEqual(port.writes, [b"11\n", b"exit\n", b"exit\n"])
        self.assertNotIn(b"3\n", port.writes)

    def test_power_summary_ignores_pwm_changes_and_unsettled_rows(self):
        lines = [POWER_HEADER]
        for target, step in ((5, 1), (10, 2)):
            for i in range(8):
                timestamp = ((step - 1) * 8 + i) * 1000000
                # Continuously changing PWM must not reset the settling window.
                settled = int(i >= 2)
                status = "ESP_OK" if i != 7 else "ESP_ERR_NOT_FINISHED"
                lines.append(f"{timestamp},1000,{target / 2},12,1,{target},"
                             f"{1540 + i},ESP_OK,{status},0,{target},{target},{settled},{step}")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "power.csv"
            path.write_text("\n".join(lines), encoding="utf-8")
            samples, malformed, dropped = read_recording(path)
        result = summarise(samples)
        self.assertEqual((malformed, dropped), (0, 0))
        self.assertEqual([r["target_power_W"] for r in result], [5, 10])
        self.assertEqual([r["samples"] for r in result], [6, 6])
        self.assertEqual([r["paired_samples"] for r in result], [5, 5])
        self.assertEqual([r["force_per_watt_N_W"] for r in result], [0.5, 0.5])

    def test_formatted_power_and_external_calibration(self):
        text = ("Timestamp: 1000000 us, Force: 123 counts (uncalibrated), Voltage: 12.0000 V, "
                "Current: 0.4000 A, Power: 5.0000 W, Current PWM: 1550 us, "
                "Target: 5.000 W, Filtered: 5.000 W, Settled: 1, Step: 1\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "power.log"
            path.write_text(text, encoding="utf-8")
            samples, _, _ = read_recording(path, {"tare_counts": 100, "newtons_per_count": 0.1})
        self.assertAlmostEqual(samples[0]["force_N"], 2.3)
        self.assertEqual(samples[0]["target_power_W"], 5)
        self.assertTrue(samples[0]["power_settled"])
        self.assertAlmostEqual(summarise(samples, 0)[0]["force_per_watt_N_W"], 0.46)

    def test_legacy_output_and_reboot_boundaries(self):
        text = HEADER + "\n" + "\n".join(
            f"{t},123,2,12,1,10,1550,ESP_OK,ESP_OK,0" for t in
            (1000000, 2000000, 3000000, 1000000, 2000000))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.csv"
            path.write_text(text, encoding="utf-8")
            samples, _, _ = read_recording(path)
        result = summarise(samples)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["samples"], 3)
        self.assertTrue(math.isnan(result[0]["target_power_W"]))
        self.assertEqual(result[0]["force_per_watt_N_W"], 0.2)

    def test_no_settled_samples_are_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsettled.csv"
            path.write_text(POWER_HEADER + "\n0,123,2,12,1,10,1550,ESP_OK,ESP_OK,0,5,10,0,1\n"
                            "1000000,123,2,12,1,10,1552,ESP_OK,ESP_OK,0,5,10,0,1\n",
                            encoding="utf-8")
            samples, _, _ = read_recording(path)
        self.assertEqual(summarise(samples), [])


if __name__ == "__main__":
    unittest.main()
