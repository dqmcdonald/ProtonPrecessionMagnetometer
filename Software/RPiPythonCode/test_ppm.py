"""Tests for PPM.py — hardware interface (serial port is mocked).

pyserial is only available on the Raspberry Pi target, so we stub the whole
'serial' module in sys.modules before importing PPM.
"""
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Stub out pyserial and its submodules so PPM can be imported without pyserial.
# All three entries are needed: 'import serial', 'import serial.tools', and
# 'import serial.tools.list_ports' each look up their own key in sys.modules.
_serial_stub = MagicMock()
sys.modules.setdefault('serial', _serial_stub)
sys.modules.setdefault('serial.tools', MagicMock())
sys.modules.setdefault('serial.tools.list_ports', MagicMock())

import PPM  # noqa: E402 — must come after the stub


def make_ppm(on_time=6000, sample_time=1500, sample_rate=16000,
             delay=500, cool_down=10000):
    """Return a PPMRun with the serial constructor stubbed out."""
    with patch.object(PPM.serial, 'Serial') as mock_serial:
        # __init__ waits for the boot banner via readline(); hand it back so the
        # constructor returns immediately instead of polling until the timeout.
        mock_serial.return_value.readline.return_value = (
            b"Proton Precession Magnetometer - Coil Controller\n")
        ppm = PPM.PPMRun()
    ppm._ser = MagicMock()
    ppm.configure(on_time=on_time, sample_time=sample_time,
                  sample_rate=sample_rate, delay=delay, cool_down=cool_down)
    return ppm


def make_data_frame(actual_sample_rate, n_samples, value=512):
    """Build the binary measurement frame the Arduino sends after EXECU.

    Layout (little-endian): marker b'PPMD', uint32 actual_sample_rate,
    uint32 num_samples, then n_samples × int16.
    """
    return (PPM.DATA_MARKER
            + struct.pack("<II", actual_sample_rate, n_samples)
            + struct.pack("<{}h".format(n_samples), *([value] * n_samples)))


def attach_serial_frame(ppm, frame, ack=b"OK EXECU\n"):
    """Wire ppm._ser so readline() returns command acks and read() yields frame.

    Command acknowledgements (consumed by send()) come from readline(); the
    binary measurement frame is handed out byte-for-byte by read().
    """
    buf = {"data": frame}

    def fake_read(size=1):
        chunk = buf["data"][:size]
        buf["data"] = buf["data"][size:]
        return chunk

    ppm._ser.readline.return_value = ack
    ppm._ser.read.side_effect = fake_read


def fake_port(device, vid=None):
    """Stand-in for a pyserial ListPortInfo with just the fields we use."""
    from types import SimpleNamespace
    return SimpleNamespace(device=device, vid=vid)


class TestFindArduinoPort(unittest.TestCase):
    """find_arduino_port() picks USB adapters by vendor ID, then by device
    name, then falls back to the Pi hardware UART."""

    def _detect(self, ports, serial0_exists=False):
        with patch.object(PPM.serial.tools.list_ports, 'comports',
                          return_value=ports), \
             patch("PPM.os.path.exists", return_value=serial0_exists):
            return PPM.find_arduino_port()

    def test_known_vid_preferred(self):
        ports = [fake_port('/dev/tty.Bluetooth-Incoming-Port'),
                 fake_port('/dev/tty.usbserial-A906H87T', vid=0x0403)]  # FTDI
        self.assertEqual(self._detect(ports), '/dev/tty.usbserial-A906H87T')

    def test_device_name_fallback_for_unknown_vid(self):
        ports = [fake_port('/dev/ttyUSB0', vid=0x9999)]
        self.assertEqual(self._detect(ports), '/dev/ttyUSB0')

    def test_multiple_candidates_first_sorted_wins(self):
        ports = [fake_port('/dev/ttyUSB1', vid=0x1A86),
                 fake_port('/dev/ttyUSB0', vid=0x0403)]
        self.assertEqual(self._detect(ports), '/dev/ttyUSB0')

    def test_hardware_uart_fallback(self):
        # No USB adapters at all, but /dev/serial0 exists (Raspberry Pi).
        ports = [fake_port('/dev/tty.Bluetooth-Incoming-Port')]
        self.assertEqual(self._detect(ports, serial0_exists=True),
                         PPM.DEFAULT_PORT)

    def test_nothing_found_raises(self):
        with self.assertRaises(IOError):
            self._detect([], serial0_exists=False)


class TestWaitForReady(unittest.TestCase):
    """The boot-banner handshake that prevents lost first-run settings."""

    BANNER = b"Proton Precession Magnetometer - Coil Controller\n"

    def test_returns_on_banner_and_flushes(self):
        ppm = make_ppm()
        ppm._ser.readline.return_value = self.BANNER
        ppm._wait_for_ready(2.0)
        ppm._ser.reset_input_buffer.assert_called_once()

    def test_skips_boot_noise_until_banner(self):
        ppm = make_ppm()
        # Empty reads (still booting) then the banner.
        ppm._ser.readline.side_effect = [b"", b"", self.BANNER]
        ppm._wait_for_ready(2.0)
        self.assertEqual(ppm._ser.readline.call_count, 3)
        ppm._ser.reset_input_buffer.assert_called_once()

    def test_timeout_is_not_fatal_and_still_flushes(self):
        ppm = make_ppm()
        ppm._ser.readline.return_value = b""   # banner never arrives
        ppm._wait_for_ready(0.05)              # short deadline keeps the test fast
        ppm._ser.reset_input_buffer.assert_called_once()


class TestConfigure(unittest.TestCase):

    def test_defaults(self):
        ppm = make_ppm()
        import PPM
        self.assertEqual(ppm._on_time, PPM.ON_TIME_DEFAULT)
        self.assertEqual(ppm._sample_time, PPM.SAMPLE_TIME_DEFAULT)
        self.assertEqual(ppm._sample_rate, PPM.SAMPLE_RATE_DEFAULT)
        self.assertEqual(ppm._delay, PPM.DELAY_DEFAULT)
        self.assertEqual(ppm._cool_down, PPM.COOL_DOWN_DEFAULT)

    def test_configure_partial(self):
        ppm = make_ppm()
        ppm.configure(on_time=3000)
        self.assertEqual(ppm._on_time, 3000)
        import PPM
        self.assertEqual(ppm._sample_time, PPM.SAMPLE_TIME_DEFAULT)

    def test_configure_all(self):
        ppm = make_ppm(on_time=2000, sample_time=1000, sample_rate=8000,
                       delay=200, cool_down=5000)
        self.assertEqual(ppm._on_time, 2000)
        self.assertEqual(ppm._sample_time, 1000)
        self.assertEqual(ppm._sample_rate, 8000)
        self.assertEqual(ppm._delay, 200)
        self.assertEqual(ppm._cool_down, 5000)


class TestMarkerDeadline(unittest.TestCase):
    """doMeasurement() must not sleep before reading (the OS serial buffer
    would overflow at 250000 baud) and must allow cool_down + the full
    hardware cycle + margin before declaring the marker lost."""

    def _measure(self, on_time=6000, sample_time=1500, delay=500,
                 cool_down=10000):
        ppm = make_ppm(on_time=on_time, sample_time=sample_time,
                       delay=delay, cool_down=cool_down)
        attach_serial_frame(ppm, make_data_frame(16000, 10))
        with patch.object(ppm, '_sync_to_marker',
                          wraps=ppm._sync_to_marker) as sync_spy, \
             patch("time.sleep") as mock_sleep, \
             patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        return sync_spy, mock_sleep

    def test_no_blind_sleep_before_reading(self):
        _, mock_sleep = self._measure()
        mock_sleep.assert_not_called()

    def test_deadline_formula_defaults(self):
        sync_spy, _ = self._measure(6000, 1500, 500, 10000)
        self.assertAlmostEqual(sync_spy.call_args[0][0], 20.0)

    def test_deadline_formula_custom(self):
        sync_spy, _ = self._measure(2000, 1000, 200, 5000)
        self.assertAlmostEqual(sync_spy.call_args[0][0], 10.2)


class TestBackgroundMeasurement(unittest.TestCase):
    """doMeasurement(background=True) sends BKGND and uses the shorter
    deadline: cool_down + sample_time + margin (no polarise or settle phase)."""

    def _measure(self, background, **kwargs):
        ppm = make_ppm(**kwargs)
        attach_serial_frame(ppm, make_data_frame(16000, 10), ack=b"OK BKGND\n")
        with patch.object(ppm, '_sync_to_marker',
                          wraps=ppm._sync_to_marker) as sync_spy, \
             patch("time.sleep"), \
             patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null", background=background)
        return ppm, sync_spy

    def test_sends_bkgnd_command(self):
        ppm, _ = self._measure(background=True)
        sent = [c[0][0].decode() for c in ppm._ser.write.call_args_list]
        self.assertTrue(any("BKGND" in s for s in sent))
        self.assertFalse(any("EXECU" in s for s in sent))

    def test_default_sends_execu(self):
        ppm, _ = self._measure(background=False)
        sent = [c[0][0].decode() for c in ppm._ser.write.call_args_list]
        self.assertTrue(any("EXECU" in s for s in sent))
        self.assertFalse(any("BKGND" in s for s in sent))

    def test_background_deadline_excludes_polarise_and_settle(self):
        # cool_down=10000 + sample_time=1500 + 2000 margin = 13.5 s
        _, sync_spy = self._measure(background=True)
        self.assertAlmostEqual(sync_spy.call_args[0][0], 13.5)

    def test_background_data_decoded_normally(self):
        ppm, _ = self._measure(background=True)
        self.assertEqual(len(ppm.getSignalData()), 10)
        self.assertEqual(ppm.getActualSampleRate(), 16000)


class TestSendConfiguredValues(unittest.TestCase):

    def test_commands_sent(self):
        import PPM
        ppm = make_ppm(on_time=3000, sample_time=1000, sample_rate=8000,
                       delay=200, cool_down=5000)
        ppm._ser.readline.return_value = b"OK\n"
        ppm.sendConfiguredValues()

        sent = [c[0][0].decode() for c in ppm._ser.write.call_args_list]
        self.assertTrue(any("ONTIM 3000" in s for s in sent))
        self.assertTrue(any("SAMPT 1000" in s for s in sent))
        self.assertTrue(any("SAMRA 8000" in s for s in sent))
        self.assertTrue(any("DELAY 200" in s for s in sent))
        self.assertTrue(any("COOLD 5000" in s for s in sent))


class TestDoMeasurement(unittest.TestCase):

    def _run_measurement(self, n_samples=50, sample_rate=16000):
        ppm = make_ppm()
        attach_serial_frame(ppm, make_data_frame(sample_rate, n_samples))

        with patch("time.sleep"), \
             patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        return ppm

    def test_signal_data_shape(self):
        ppm = self._run_measurement(n_samples=50)
        self.assertEqual(len(ppm.getSignalData()), 50)

    def test_signal_values(self):
        ppm = self._run_measurement(n_samples=10)
        np.testing.assert_array_equal(ppm.getSignalData(), np.full(10, 512))

    def test_actual_sample_rate_stored(self):
        ppm = self._run_measurement(sample_rate=15800)
        self.assertEqual(ppm.getActualSampleRate(), 15800)

    def test_signed_values_decoded(self):
        """Negative two's-complement ADC counts round-trip correctly."""
        ppm = make_ppm()
        n = 4
        frame = (PPM.DATA_MARKER + struct.pack("<II", 16000, n)
                 + struct.pack("<4h", -32768, -1, 0, 32767))
        attach_serial_frame(ppm, frame)
        with patch("time.sleep"), patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        np.testing.assert_array_equal(
            ppm.getSignalData(), np.array([-32768, -1, 0, 32767]))

    def test_resync_skips_leading_garbage(self):
        """A stray byte before the marker is skipped, not parsed as data."""
        ppm = make_ppm()
        frame = b"\x00" + make_data_frame(16000, 5)
        attach_serial_frame(ppm, frame)
        with patch("time.sleep"), patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        self.assertEqual(len(ppm.getSignalData()), 5)
        self.assertEqual(ppm.getActualSampleRate(), 16000)

    def test_truncated_frame_raises(self):
        """A frame that ends early fails fast instead of hanging or corrupting."""
        ppm = make_ppm()
        # Declares 5 samples but only supplies 2 before the buffer runs dry.
        frame = (PPM.DATA_MARKER + struct.pack("<II", 16000, 5)
                 + struct.pack("<2h", 1, 2))
        attach_serial_frame(ppm, frame)
        ppm._ser.read.side_effect = None  # override; empty reads after data drains
        data = {"buf": bytearray(frame)}

        def draining_read(size=1):
            chunk = bytes(data["buf"][:size])
            del data["buf"][:size]
            return chunk  # returns b"" once exhausted -> _read_exact raises

        ppm._ser.read.side_effect = draining_read
        with patch("time.sleep"), patch("builtins.open", unittest.mock.mock_open()):
            with self.assertRaises(IOError):
                ppm.doMeasurement(output_path="/dev/null")

    def test_marker_wait_survives_cool_down(self):
        """Empty reads before the marker (Arduino still cooling) are retried.

        From run 2 onwards the firmware queues an EXECU received during
        cool-down, so the data frame arrives later than the nominal cycle
        time.  Each empty read simulates the 1 s serial timeout expiring while
        the Arduino is still cooling; the sync must keep waiting rather than
        raise.
        """
        ppm = make_ppm()
        frame = make_data_frame(16000, 5)
        empty_reads = [b"", b"", b""]
        buf = {"data": frame}

        def fake_read(size=1):
            if empty_reads:
                return empty_reads.pop(0)
            chunk = buf["data"][:size]
            buf["data"] = buf["data"][size:]
            return chunk

        ppm._ser.readline.return_value = b"OK EXECU\n"
        ppm._ser.read.side_effect = fake_read
        with patch("time.sleep"), patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        self.assertEqual(len(ppm.getSignalData()), 5)
        self.assertEqual(ppm.getActualSampleRate(), 16000)

    def test_marker_timeout_raises_after_deadline(self):
        """If the marker never arrives, _sync_to_marker raises once the
        overall deadline has passed instead of waiting forever."""
        ppm = make_ppm()
        ppm._ser.read.return_value = b""
        with self.assertRaises(IOError):
            ppm._sync_to_marker(0)

    def test_file_written_as_plaintext(self):
        """The .dat file stays plain text: num_samples, rate, then one int/line."""
        ppm = make_ppm()
        frame = (PPM.DATA_MARKER + struct.pack("<II", 16000, 3)
                 + struct.pack("<3h", 10, -20, 30))
        attach_serial_frame(ppm, frame)
        m = unittest.mock.mock_open()
        with patch("time.sleep"), patch("builtins.open", m):
            ppm.doMeasurement(output_path="/dev/null")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertEqual(written, "3\n16000\n10\n-20\n30\n")


if __name__ == "__main__":
    unittest.main()
