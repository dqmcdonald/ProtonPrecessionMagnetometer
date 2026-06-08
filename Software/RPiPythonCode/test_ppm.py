"""Tests for PPM.py — hardware interface (serial port is mocked).

pyserial is only available on the Raspberry Pi target, so we stub the whole
'serial' module in sys.modules before importing PPM.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Stub out the serial module so PPM can be imported without pyserial installed
_serial_stub = MagicMock()
sys.modules.setdefault('serial', _serial_stub)

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
        ppm._ser.readline.side_effect = (
            [b"OK\n"] +                                    # EXECUTE command ACK
            [b"16000\n"] +                                 # actual_sample_rate
            ["{}\n".format(n_samples).encode()] +          # num_samples
            [b"512\n"] * n_samples
        )

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
        responses = (
            [b"OK\n"] +                               # EXECUTE command ACK
            ["{}\n".format(sample_rate).encode()] +   # actual_sample_rate
            ["{}\n".format(n_samples).encode()] +     # num_samples
            [b"512\n"] * n_samples
        )
        ppm._ser.readline.side_effect = responses

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


if __name__ == "__main__":
    unittest.main()
