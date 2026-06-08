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
    with patch.object(PPM.serial, 'Serial', return_value=MagicMock()):
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


class TestSleepCalculation(unittest.TestCase):
    """doMeasurement() sleep should equal (on_time + delay + sample_time + 2000) / 1000."""

    def _expected_sleep(self, on_time, delay, sample_time):
        return (on_time + delay + sample_time + 2000) / 1000

    def test_default_sleep(self):
        expected = self._expected_sleep(6000, 500, 1500)  # = 10.0 s
        self.assertAlmostEqual(expected, 10.0)

    def test_custom_sleep(self):
        expected = self._expected_sleep(3000, 200, 800)  # = 6.0 s
        self.assertAlmostEqual(expected, 6.0)

    def _sleep_used_in_measurement(self, on_time, sample_time, delay):
        ppm = make_ppm(on_time=on_time, sample_time=sample_time, delay=delay)
        n_samples = 100
        attach_serial_frame(ppm, make_data_frame(16000, n_samples))

        with patch("time.sleep") as mock_sleep, \
             patch("builtins.open", unittest.mock.mock_open()):
            ppm.doMeasurement(output_path="/dev/null")
        return mock_sleep.call_args[0][0]

    def test_sleep_matches_formula_defaults(self):
        elapsed = self._sleep_used_in_measurement(6000, 1500, 500)
        self.assertAlmostEqual(elapsed, self._expected_sleep(6000, 500, 1500))

    def test_sleep_matches_formula_custom(self):
        elapsed = self._sleep_used_in_measurement(3000, 800, 200)
        self.assertAlmostEqual(elapsed, self._expected_sleep(3000, 200, 800))


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
