"""
PPM.py — Hardware interface for the Proton Precession Magnetometer.

This module handles all communication with the Arduino Pro Mini that controls
the polarising coil and ADC sampling.  The Raspberry Pi acts as a host
controller: it sends configuration commands over serial, triggers a measurement,
then reads back the raw ADC samples.

Measurement sequence
--------------------
1. Host sends configuration commands (ON_TIME, SAMPLE_TIME, etc.).
2. Host sends EXECU to start the measurement cycle.
3. Arduino energises the polarising coil for ON_TIME milliseconds.
   The strong DC field aligns the proton spins in the water sample.
4. After ON_TIME, the coil is switched off.  The protons are left with a net
   magnetisation pointing along the (now absent) coil field.
5. After DELAY milliseconds, the Arduino begins ADC sampling.
   The protons precess around Earth's field at the Larmor frequency:
       f = γ · B / (2π)   where γ = 2.675 × 10⁸ rad/(s·T)
   For Earth's field (~57 µT) this is approximately 2435 Hz.
6. Sampling continues for SAMPLE_TIME milliseconds at SAMPLE_RATE Hz.
7. Arduino sends back the actual sample rate, the sample count, and all ADC
   values as a single binary frame (see "Serial protocol" below).
8. After sampling, the MOSFET is allowed to cool for COOL_DOWN milliseconds
   before another measurement can be requested.

Serial protocol
---------------
Command/control is ASCII: all commands are strings terminated with '\\n' and
the Arduino echoes an acknowledgement line on each command.

Measurement data is returned as a single little-endian binary frame.  This is
roughly 3× more compact than the old line-based ASCII format and removes
per-sample text parsing, which matters for the tens of thousands of samples in
a typical run.  After EXECU the Arduino eventually sends:

    bytes 0-3  : marker b'PPMD'
    bytes 4-7  : actual_sample_rate (uint32)
    bytes 8-11 : num_samples        (uint32)
    then num_samples × int16 samples (signed, two's complement)

The on-disk ``.dat`` files remain plain text (see PPMCalc.load_from_file); only
the over-the-wire transfer is binary.
"""

import os
import serial
import struct
import time
import numpy as np


# ── Binary data frame ─────────────────────────────────────────────────────────

# Marker that precedes every binary measurement frame.  Lets the host resync to
# the start of the data even if a stray byte (e.g. a late command ack) is left
# in the serial buffer.
DATA_MARKER = b"PPMD"


# ── Serial port configuration ─────────────────────────────────────────────────

# Must match the baud rate compiled into the Arduino firmware.  250000 is an
# exact divisor of both the 8 MHz and 16 MHz AVR clocks (0% baud-rate error,
# unlike 57600/115200) and moves the ~48 KB binary frame in ~1.9 s instead of
# ~8.3 s at 57600.
BAUD_RATE = 250000
DEFAULT_PORT = '/dev/serial0'  # Raspberry Pi hardware UART; override with --port.

# USB vendor IDs that identify an Arduino or the USB-serial bridge chips
# commonly found on Arduino boards and programming adapters.  A Pro Mini has
# no USB hardware of its own, so it enumerates as its programming adapter —
# typically an FTDI FT232R.
ARDUINO_USB_VIDS = {
    0x2341,  # Arduino SA
    0x2A03,  # Arduino.org
    0x1B4F,  # SparkFun
    0x0403,  # FTDI (FT232R — classic Pro Mini programming adapter)
    0x1A86,  # WCH CH340 (common on clone boards/adapters)
    0x10C4,  # Silicon Labs CP210x
}

# ── Arduino command strings ───────────────────────────────────────────────────
# Each command is a 5-character token.  The Arduino parser matches on these
# exact strings so they must not be changed without updating the firmware.

ON_TIME_COMMAND    = "ONTIM"
SAMPLE_TIME_COMMAND = "SAMPT"
SAMPLE_RATE_COMMAND = "SAMRA"
DELAY_COMMAND      = "DELAY"
COOL_DOWN_COMMAND  = "COOLD"
EXECUTE_COMMAND    = "EXECU"

# ── Default hardware parameters ───────────────────────────────────────────────

# Six seconds of polarisation gives the proton spins time to align with the
# coil field.  The alignment follows an exponential approach with time constant
# T1 (spin-lattice relaxation, ~3 s for tap water), so 6 s ≈ 2 × T1 captures
# most of the available magnetisation without waiting unnecessarily long.
ON_TIME_DEFAULT = 6000        # ms

# 1500 ms at 16000 Hz = 24000 samples (≤ 32 K hardware buffer limit).
# The proton precession signal decays with time constant T2 (spin-spin
# relaxation, ~1-3 s for tap water), so sampling for longer than ~2 s gives
# diminishing returns.
SAMPLE_TIME_DEFAULT = 1500    # ms

# The Arduino ADC can sustain roughly 16000 samples/s with the current
# firmware.  The actual achieved rate is reported back after each measurement
# and may differ slightly; use getActualSampleRate() for analysis, not this
# requested value.
SAMPLE_RATE_DEFAULT = 16000   # samples/s

# A short delay between coil switch-off and the start of sampling lets the
# large coil transient decay so it does not saturate the ADC input.
DELAY_DEFAULT = 500           # ms

# The MOSFET that switches the polarising coil carries a large current burst
# and needs time to cool before the next cycle to avoid thermal damage.
COOL_DOWN_DEFAULT = 10000     # ms


def scan_ports():
    """Return a list of available serial ports with their descriptions.

    Uses pyserial's port enumeration to find all serial interfaces visible to
    the OS.  On a Raspberry Pi the hardware UART appears as /dev/serial0 (or
    /dev/ttyAMA0 / /dev/ttyS0 depending on model and config.txt settings).
    USB-serial adapters appear as /dev/ttyUSB0 or /dev/ttyACM0.  On macOS
    development machines they appear as /dev/tty.usbserial-XXXXX.

    Each returned tuple contains:
        (device, description, hwid)
    where hwid includes the USB vendor:product ID for USB-serial adapters,
    which can help identify an Arduino connected via USB.

    Returns:
        List of (device, description, hwid) tuples, one per available port.
        Returns an empty list if no ports are found.

    Raises:
        ImportError: if pyserial is not installed or serial.tools is missing.
    """
    try:
        import serial.tools.list_ports
    except ImportError:
        raise ImportError(
            "serial.tools.list_ports not found. "
            "Install or upgrade pyserial:  pip install --upgrade pyserial")
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description, p.hwid) for p in sorted(ports)]


def find_arduino_port(lg=None):
    """Auto-detect the serial port the Arduino is connected to.

    Detection strategy, in order of preference:

    1. USB serial interfaces whose vendor ID matches a known Arduino or
       USB-serial bridge chip (see ARDUINO_USB_VIDS).
    2. Any port whose device name looks like a USB serial adapter
       (ttyUSB*/ttyACM* on Linux, tty.usbserial*/tty.usbmodem* on macOS),
       to cover adapters with unrecognised vendor IDs.
    3. The Raspberry Pi hardware UART (DEFAULT_PORT), if it exists.  A direct
       UART connection has no USB descriptor to recognise, so its mere
       presence is the fallback when no USB adapter is found.

    If several USB candidates are found, the first (sorted by device name) is
    used and the alternatives are logged; pass an explicit port to PPMRun (the
    --port CLI option) to override.

    Args:
        lg: Optional logging.Logger for reporting the choice made.

    Returns:
        Device path string, e.g. '/dev/tty.usbserial-A906H87T'.

    Raises:
        IOError: if no plausible Arduino port can be found.
    """
    import serial.tools.list_ports

    def log(msg):
        if lg:
            lg.info(msg)

    ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)

    candidates = [p.device for p in ports if p.vid in ARDUINO_USB_VIDS]
    if not candidates:
        usb_names = ('ttyUSB', 'ttyACM', 'usbserial', 'usbmodem')
        candidates = [p.device for p in ports
                      if any(name in p.device for name in usb_names)]

    if candidates:
        if len(candidates) > 1:
            log("Multiple USB serial adapters found ({}); using {}. "
                "Use --port to override.".format(
                    ", ".join(candidates), candidates[0]))
        else:
            log("Auto-detected Arduino on {}".format(candidates[0]))
        return candidates[0]

    if os.path.exists(DEFAULT_PORT):
        log("No USB serial adapter found; falling back to hardware UART "
            "{}".format(DEFAULT_PORT))
        return DEFAULT_PORT

    raise IOError(
        "Could not auto-detect the Arduino: no USB serial adapter found and "
        "{} does not exist.  Use --list-ports to see available ports and "
        "--port to specify one explicitly.".format(DEFAULT_PORT))


class PPMRun:
    """Controls the PPM hardware through a serial connection to the Arduino.

    Typical usage::

        ppm = PPMRun(logger)
        ppm.configure(on_time=8000)        # override individual parameters
        ppm.sendConfiguredValues()         # upload settings to Arduino
        ppm.doMeasurement("run_00.dat")    # trigger and collect one cycle
        data = ppm.getSignalData()         # numpy array of raw ADC counts
        rate = ppm.getActualSampleRate()   # Hz as measured by the Arduino
    """

    def __init__(self, lg=None, port=DEFAULT_PORT):
        """Open the serial port and initialise default hardware parameters.

        Args:
            lg:   A Python logging.Logger instance.  Pass None to suppress
                  logging (useful in tests).
            port: Serial port device path.  Defaults to DEFAULT_PORT
                  (/dev/serial0).  Override with the --port CLI argument or
                  use scan_ports() to discover available ports first.

        Note: The serial port is opened immediately.  If the port does not
        exist (e.g. on a development PC without the Arduino connected) this
        will raise serial.SerialException.  The port buffers are flushed on
        open to discard any stale data from a previous run.
        """
        self._ser = serial.Serial(port, BAUD_RATE, timeout=1)
        # Flush both buffers in case there is leftover data from a previous
        # session or a crashed run.
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()

        self._logger = lg
        self._signal_data = None          # populated by doMeasurement()

        # Store configured timing as instance attributes so that doMeasurement()
        # can compute the correct sleep duration dynamically rather than using
        # a hardcoded constant.
        self._sample_rate  = SAMPLE_RATE_DEFAULT
        self._sample_time  = SAMPLE_TIME_DEFAULT
        self._actual_sample_rate = SAMPLE_RATE_DEFAULT  # updated after each run
        self._on_time   = ON_TIME_DEFAULT
        self._delay     = DELAY_DEFAULT
        self._cool_down = COOL_DOWN_DEFAULT

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure(self, on_time=None, sample_time=None, sample_rate=None,
                  delay=None, cool_down=None):
        """Override one or more hardware timing parameters.

        Only the keyword arguments that are explicitly supplied are updated;
        the rest keep their current values.  Call sendConfiguredValues() after
        this to upload the new settings to the Arduino.

        Args:
            on_time:     Coil polarisation duration in ms.
            sample_time: ADC sampling window duration in ms.
            sample_rate: Requested ADC sample rate in samples/s.
            delay:       Delay from coil-off to start of sampling in ms.
            cool_down:   MOSFET cool-down time between runs in ms.
        """
        if on_time is not None:
            self._on_time = on_time
        if sample_time is not None:
            self._sample_time = sample_time
        if sample_rate is not None:
            self._sample_rate = sample_rate
        if delay is not None:
            self._delay = delay
        if cool_down is not None:
            self._cool_down = cool_down

    # ── Accessors ─────────────────────────────────────────────────────────────

    def getSignalData(self):
        """Return the raw ADC samples from the last measurement as a numpy array."""
        return self._signal_data

    def getSampleRate(self):
        """Return the *requested* sample rate in samples/s."""
        return self._sample_rate

    def getActualSampleRate(self):
        """Return the *measured* sample rate reported by the Arduino after the
        last measurement.  Use this value — not getSampleRate() — when
        constructing a PPMCalc object, as the actual rate determines the
        correct frequency axis for the FFT.
        """
        return self._actual_sample_rate

    def getSampleTime(self):
        """Return the configured sampling window duration in ms."""
        return self._sample_time

    # ── Internal helpers ──────────────────────────────────────────────────────

    def log(self, msg):
        """Write msg to the logger if one was provided."""
        if self._logger:
            self._logger.info(msg)

    def send(self, text):
        """Send a single ASCII command and read back the Arduino's acknowledgement.

        The Arduino echoes one line per command.  This acknowledgement is read
        and logged but its content is not validated — the Arduino is trusted to
        accept every well-formed command.

        Args:
            text: The command string to send (without trailing newline).
        """
        self._ser.write("{}\n".format(text).encode('utf-8'))
        self.log("Sending command:   '{}'".format(text))
        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        self.log("Received response: '{}'".format(resp))

    def _read_exact(self, n):
        """Read exactly n bytes from the serial port, blocking until they arrive.

        pyserial's read(n) returns up to n bytes but may return fewer if its
        timeout elapses mid-transfer.  This loops until all n bytes have been
        collected, raising IOError if a read returns nothing (the Arduino has
        gone silent), so a truncated frame fails fast rather than corrupting the
        sample array.

        Args:
            n: Number of bytes to read.

        Returns:
            A bytes object of length n.

        Raises:
            IOError: if the serial port times out before n bytes are received.
        """
        buf = bytearray()
        while len(buf) < n:
            chunk = self._ser.read(n - len(buf))
            if not chunk:
                raise IOError(
                    "Timed out reading binary data: expected {} bytes, "
                    "got {}".format(n, len(buf)))
            buf.extend(chunk)
        return bytes(buf)

    def _sync_to_marker(self, timeout_s):
        """Consume bytes from the serial port up to and including DATA_MARKER.

        The marker lets the host find the start of the binary frame even if a
        stray byte (such as a late command acknowledgement) precedes it.  Uses
        a sliding window so the marker is detected at any byte offset.

        An empty read (the 1 s serial timeout expiring) is retried rather than
        treated as a failure, until timeout_s has elapsed overall.  This
        matters from the second run of a multi-run session onwards: an EXECU
        sent while the Arduino is still in its MOSFET cool-down phase is
        queued by the firmware and only executed when cool-down completes, so
        the data frame can legitimately arrive up to a full cool-down period
        later than the nominal measurement cycle time.

        Args:
            timeout_s: Overall deadline in seconds.  IOError is raised if the
                       marker has not appeared after this long.

        Raises:
            IOError: if the marker is not seen within timeout_s.
        """
        deadline = time.monotonic() + timeout_s
        window = bytearray()
        while True:
            byte = self._ser.read(1)
            if not byte:
                if time.monotonic() >= deadline:
                    raise IOError(
                        "Timed out waiting for binary data marker "
                        "after {:.1f} s".format(timeout_s))
                continue
            window.extend(byte)
            if len(window) > len(DATA_MARKER):
                del window[0]
            if window == DATA_MARKER:
                return

    def sendCommand(self, command, value=None):
        """Format and send a command with an optional integer parameter.

        Args:
            command: The 5-character command token (e.g. "ONTIM").
            value:   Optional integer value (e.g. 6000).  If None, the command
                     is sent without a parameter (used for EXECU).
        """
        if value is not None:
            text = "{} {}".format(command, value)
        else:
            text = command
        self.send(text)

    # ── Hardware setup ────────────────────────────────────────────────────────

    def sendDefaultValues(self):
        """Upload the compile-time default parameters to the Arduino.

        Useful for a quick reset to known-good settings without needing a
        PPMRun.configure() call.
        """
        self.sendCommand(ON_TIME_COMMAND,    ON_TIME_DEFAULT)
        self.sendCommand(SAMPLE_TIME_COMMAND, SAMPLE_TIME_DEFAULT)
        self.sendCommand(SAMPLE_RATE_COMMAND, SAMPLE_RATE_DEFAULT)
        self.sendCommand(DELAY_COMMAND,      DELAY_DEFAULT)
        self.sendCommand(COOL_DOWN_COMMAND,  COOL_DOWN_DEFAULT)

    def sendConfiguredValues(self):
        """Upload the currently configured parameters to the Arduino.

        Call this after configure() and before doMeasurement() to ensure the
        Arduino is using the same timing values as the host.
        """
        self.sendCommand(ON_TIME_COMMAND,    self._on_time)
        self.sendCommand(SAMPLE_TIME_COMMAND, self._sample_time)
        self.sendCommand(SAMPLE_RATE_COMMAND, self._sample_rate)
        self.sendCommand(DELAY_COMMAND,      self._delay)
        self.sendCommand(COOL_DOWN_COMMAND,  self._cool_down)

    # ── Measurement ───────────────────────────────────────────────────────────

    def doMeasurement(self, output_path="ppm.dat"):
        """Trigger a full polarise-wait-sample cycle and save the results.

        Sends EXECU to the Arduino, waits for the hardware cycle to complete,
        then reads the sample rate, sample count, and all ADC values from the
        serial port.  The raw data is saved to output_path in a plain-text
        format that can be reloaded by PPMCalc.load_from_file().

        The serial port is read continuously from the moment EXECU is sent,
        rather than sleeping through the hardware cycle.  This keeps the OS
        receive buffer drained: at 250000 baud the entire data frame arrives
        faster than the measurement cycle completes, and a host that is not
        reading loses everything beyond the OS buffer size (~16 KB on macOS).

        The overall deadline for the data marker is computed from the
        configured hardware parameters: cool_down (an EXECU sent during the
        previous run's cool-down is queued by the firmware until cool-down
        completes) + on_time + delay + sample_time, plus a 2-second margin
        for Arduino processing overhead.

        Args:
            output_path: Path to write the raw data file.  The directory must
                         already exist.

        Data file format written:
            Line 1: num_samples (integer)
            Line 2: actual_sample_rate (integer, Hz)
            Lines 3+: one ADC integer per line
        """
        self.sendCommand(EXECUTE_COMMAND)

        # Start reading immediately instead of sleeping through the hardware
        # cycle.  At 250000 baud the full ~48 KB frame arrives in under 2 s,
        # which is faster than the measurement cycle itself — a blind sleep
        # here lets the frame land in the OS serial receive buffer (~16 KB on
        # macOS) and everything past the buffer limit is silently dropped.
        # _sync_to_marker() polls the port, draining it as data arrives.
        #
        # The deadline covers the worst case: an EXECU sent during the
        # previous run's cool-down is queued by the firmware and only starts
        # when cool-down completes, followed by the full polarise + settle +
        # sample cycle.  The extra 2000 ms absorbs Arduino processing
        # overhead and serial buffering delays.
        #
        # The measurement is returned as one binary frame:
        #   marker b'PPMD', uint32 actual_sample_rate, uint32 num_samples,
        #   then num_samples × int16 (all little-endian).
        # The actual rate may differ from the requested rate due to timer
        # quantisation in the Arduino firmware.
        marker_timeout = (self._cool_down + self._on_time + self._delay +
                          self._sample_time + 2000) / 1000
        self._sync_to_marker(marker_timeout)
        header = self._read_exact(8)
        self._actual_sample_rate, num_samples = struct.unpack("<II", header)
        self.log("Actual Sample Rate:  '{}' samples/s".format(self._actual_sample_rate))
        self.log("Number of samples: '{}'".format(num_samples))

        raw = self._read_exact(num_samples * 2)
        # Interpret the payload as signed little-endian 16-bit ADC counts.
        # .copy() detaches the array from the read-only frombuffer backing
        # buffer so downstream code can modify it freely.
        self._signal_data = np.frombuffer(raw, dtype="<i2").astype(np.int64).copy()

        # The on-disk format stays plain text so PPMCalc.load_from_file() and
        # the existing .dat data files are unaffected.  Header order is
        # num_samples then actual_sample_rate, matching load_from_file().
        with open(output_path, mode='w', encoding="utf-8") as f:
            f.write("{}\n".format(num_samples))
            f.write("{}\n".format(self._actual_sample_rate))
            for value in self._signal_data:
                f.write("{}\n".format(int(value)))

        self.log("Received '{}' samples".format(num_samples))
