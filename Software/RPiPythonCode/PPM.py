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
7. Arduino sends back the actual sample rate and sample count, then
   transmits each ADC value on its own line.
8. After sampling, the MOSFET is allowed to cool for COOL_DOWN milliseconds
   before another measurement can be requested.

Serial protocol
---------------
All commands are ASCII strings terminated with '\\n'.
The Arduino echoes an acknowledgement on each command.
On EXECU the Arduino eventually replies with two header lines (actual sample
rate, then number of samples) followed by one ADC integer per line.
"""

import serial
import serial.tools.list_ports
import time
import numpy as np


# ── Serial port configuration ─────────────────────────────────────────────────

BAUD_RATE = 57600        # Must match the baud rate compiled into the Arduino firmware.
DEFAULT_PORT = '/dev/serial0'  # Raspberry Pi hardware UART; override with --port.

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
    """
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description, p.hwid) for p in sorted(ports)]


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

        The sleep duration is computed from the configured hardware parameters
        rather than being hardcoded, so that it remains correct if on_time or
        other timings are changed via configure().  A 2-second buffer is added
        to account for Arduino processing overhead and inter-byte gaps.

        Args:
            output_path: Path to write the raw data file.  The directory must
                         already exist.

        Data file format written:
            Line 1: num_samples (integer)
            Line 2: actual_sample_rate (integer, Hz)
            Lines 3+: one ADC integer per line
        """
        self.sendCommand(EXECUTE_COMMAND)

        # Wait for the Arduino to complete the full hardware cycle before
        # attempting to read results.  The total cycle time is:
        #   ON_TIME (polarise) + DELAY (transient settle) + SAMPLE_TIME (ADC)
        # The extra 2000 ms absorbs Arduino processing overhead and serial
        # buffering delays.
        total_wait = (self._on_time + self._delay + self._sample_time + 2000) / 1000
        time.sleep(total_wait)

        # The Arduino sends the actual sample rate first, then the number of
        # samples actually collected.  The actual rate may differ from the
        # requested rate due to timer quantisation in the Arduino firmware.
        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        self._actual_sample_rate = int(resp)
        self.log("Actual Sample Rate:  '{}' samples/s".format(self._actual_sample_rate))

        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        num_samples = int(resp)
        self.log("Number of samples: '{}'".format(num_samples))

        self._signal_data = np.zeros(num_samples)

        # Read each ADC sample and write it to the output file simultaneously
        # to avoid buffering all samples in memory before writing.
        with open(output_path, mode='w', encoding="utf-8") as f:
            # Header: num_samples then actual_sample_rate, matching the order
            # expected by PPMCalc.load_from_file().
            f.write("{}\n".format(num_samples))
            f.write("{}\n".format(self._actual_sample_rate))

            for i in range(num_samples):
                resp = self._ser.readline()
                resp = resp.decode('utf-8').strip()
                self._signal_data[i] = int(resp)
                f.write("{}\n".format(int(resp)))

        self.log("Received '{}' samples".format(num_samples))
