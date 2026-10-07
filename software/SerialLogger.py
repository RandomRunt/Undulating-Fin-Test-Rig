"""Interactive Thesis-DAQ serial console with automatic CSV recording.

Install: python -m pip install pyserial
List ports: python software/SerialLogger.py --list-ports
Connect: python software/SerialLogger.py --port COM5
Select firmware option 3 for CSV. Type exit to return to its menu, /quit to quit.
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import queue
import re
import sys
import threading
import time


REQUIRED_COLUMNS = {"time_us", "force_raw", "force_N", "voltage_V", "current_A",
                    "power_W", "pulse_us", "power_status", "force_status", "dropped_lines"}


class CSVRecorder:
    """Consume complete serial lines; preserve the firmware's CSV schema."""

    def __init__(self, directory, name="daq", report=print):
        self.directory = Path(directory)
        self.name = name
        self.report = report
        self.stream = None
        self.header = None
        self.rows = 0
        self.sequence = 0
        self.last_time = None

    def start(self, header):
        self.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        while True:
            self.sequence += 1
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.path = self.directory / f"{self.name}_{stamp}_{self.sequence:03d}.csv"
            try:
                self.stream = self.path.open("x", encoding="utf-8", newline="")
                break
            except FileExistsError:
                continue
        self.header = header
        self.writer = csv.writer(self.stream)
        self.writer.writerow(header)
        self.stream.flush()
        self.rows = 0
        self.last_time = None
        self.report(f"\n[logger] Recording {self.path}")

    def consume(self, line):
        # Firmware prompts can precede echoed commands, but never CSV rows.
        line = line.strip()
        row = next(csv.reader([line]))
        if row and row[0] == "time_us":
            if REQUIRED_COLUMNS.issubset(row) and len(row) == len(set(row)):
                self.start(row)
            else:
                self.close()
                self.report("[logger] Unsupported CSV header; retained in transcript only.")
            return
        if "Thesis DAQ - choose a number" in line or line == "Returned to neutral.":
            self.close()
            return
        if self.stream is None or not row:
            return
        try:
            timestamp = int(row[0])
        except ValueError:
            return
        if len(row) != len(self.header) or timestamp < 0:
            self.report("[logger] Malformed CSV row omitted; see transcript.")
            return
        # A reboot or restarted clock must not mix time axes in one recording.
        if self.last_time is not None and timestamp < self.last_time:
            self.report("[logger] Device timestamp restarted; opening a new recording.")
            self.start(self.header)
        self.writer.writerow(row)
        self.stream.flush()
        self.rows += 1
        self.last_time = timestamp

    def close(self):
        if self.stream is not None:
            stream, self.stream = self.stream, None
            stream.close()
            self.report(f"\n[logger] Saved {self.rows} rows to {self.path}")


class LineBuffer:
    """Keep partial serial reads until a complete newline-terminated row arrives."""

    def __init__(self, consume):
        self.pending = b""
        self.consume = consume

    def feed(self, data):
        self.pending += data
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            self.consume(line.decode("utf-8", errors="replace").rstrip("\r"))
        if len(self.pending) > 65536:
            raise ValueError("Serial line exceeds 64 KiB; check baud rate and firmware")


def read_keyboard(commands):
    while True:
        line = sys.stdin.readline()
        if not line:
            commands.put("/quit")
            return
        commands.put(line.rstrip("\r\n"))


def run_console(port, recorder, transcript, commands):
    """Serial I/O and file writing stay on one thread; only keyboard input blocks."""
    buffer = LineBuffer(recorder.consume)
    quit_at = None
    try:
        while quit_at is None or time.monotonic() < quit_at:
            try:
                command = commands.get_nowait() if quit_at is None else None
            except queue.Empty:
                command = None
            if command is not None:
                if command == "/quit":
                    command = "exit"
                    quit_at = time.monotonic() + 0.5
                elif command == "/help":
                    print("\n[logger] Firmware commands: 1..7, exit, tare, point <N>, fit, show.")
                    print("[logger] Select 3 for CSV; /quit closes the console. All other input goes to ESP.")
                    continue
                port.write((command + "\n").encode("utf-8"))
                transcript.write(f"\n[HOST COMMAND] {command}\n".encode("utf-8"))
                transcript.flush()
            data = port.read(min(max(port.in_waiting, 1), 4096))
            if data:
                transcript.write(data)
                transcript.flush()
                sys.stdout.write(data.decode("utf-8", errors="replace"))
                sys.stdout.flush()
                buffer.feed(data)
    finally:
        # Best effort on Ctrl+C, disconnect, or disk failure; never claim an ACK.
        try:
            port.write(b"exit\n")
        except (OSError, ValueError):
            pass
        recorder.close()
        if buffer.pending.strip():
            print("\n[logger] Incomplete final line retained in transcript only.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="ESP native USB serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("recordings"))
    parser.add_argument("--name", default="daq", help="Filename label, e.g. zero or load_1kg")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        parser.error("--name must contain only letters, digits, underscores or hyphens")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        parser.error("Install the serial dependency: python -m pip install pyserial")
    if args.list_ports:
        ports = list(list_ports.comports())
        for port in ports:
            print(f"{port.device}: {port.description} [{port.hwid}]")
        if not ports:
            print("No serial ports found.")
        return 0
    if not args.port:
        parser.error("Use --port COM5 (or --list-ports to find the device)")
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        transcript_path = args.output_dir / f"{args.name}_{stamp}_terminal.log"
        # RTS low avoids intentionally asserting reset; DTR indicates a connected host.
        port = serial.Serial(port=None, baudrate=args.baud, timeout=0.1, write_timeout=1)
        port.port = args.port
        port.rts = False
        port.dtr = True
        with port:
            with transcript_path.open("xb") as transcript:
                print(f"Connected to {args.port}. Terminal transcript: {transcript_path}")
                print("Select 3 for automatic CSV recording. exit: firmware menu; /quit: close console.")
                print("If already streaming, enter exit then 3 to capture a fresh CSV header.")
                commands = queue.Queue()
                threading.Thread(target=read_keyboard, args=(commands,), daemon=True).start()
                run_console(port, CSVRecorder(args.output_dir, args.name), transcript, commands)
    except KeyboardInterrupt:
        print("\n[logger] Console stopped; sent exit if the connection was available.")
    except (OSError, ValueError, serial.SerialException) as error:
        print(f"\n[logger] {error}\nClose ESP-IDF Monitor if the port is busy.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
