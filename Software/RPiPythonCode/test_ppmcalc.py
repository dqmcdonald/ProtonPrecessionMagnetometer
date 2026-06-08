"""Tests for PPMCalc.py — signal processing and file I/O."""
import os
import tempfile
import unittest

import numpy as np

import PPMCalc


SAMPLE_RATE = 16000
DURATION_MS = 1500


def make_signal(freq_hz=2800, sample_rate=SAMPLE_RATE, duration_ms=DURATION_MS,
                noise=0.05):
    """Synthetic decaying sine at freq_hz, scaled to integer ADC range."""
    n = int(sample_rate * duration_ms / 1000)
    t = np.arange(n)
    decay = np.exp(-t / (sample_rate * 0.3))
    clean = np.sin(2 * np.pi * freq_hz * t / sample_rate) * decay
    rng = np.random.default_rng(42)
    noisy = clean + rng.normal(0, noise, n)
    # Scale to a plausible ADC range centred around a DC offset
    return (noisy * 1000 + 2048).astype(int)


def write_dat_file(path, sample_rate, signal):
    with open(path, "w") as f:
        f.write("{}\n".format(len(signal)))
        f.write("{}\n".format(sample_rate))
        for v in signal:
            f.write("{}\n".format(int(v)))


class TestLoadFromFile(unittest.TestCase):

    def test_roundtrip(self):
        signal = make_signal()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.dat', delete=False) as tf:
            path = tf.name
        try:
            write_dat_file(path, SAMPLE_RATE, signal)
            sr, ns, data = PPMCalc.load_from_file(path)
            self.assertEqual(sr, SAMPLE_RATE)
            self.assertEqual(ns, len(signal))
            np.testing.assert_array_equal(data, signal)
        finally:
            os.unlink(path)

    def test_loads_real_file(self):
        path = os.path.join(os.path.dirname(__file__), "data", "ppm1.dat")
        if not os.path.exists(path):
            self.skipTest("data/ppm1.dat not present")
        sr, ns, data = PPMCalc.load_from_file(path)
        self.assertGreater(sr, 0)
        self.assertEqual(ns, len(data))
        self.assertEqual(ns, 16000)


class TestPPMCalcInit(unittest.TestCase):

    def setUp(self):
        self.signal = make_signal()
        self.calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, self.signal)

    def test_time_axis_matches_signal_length(self):
        self.assertEqual(len(self.calc._time), len(self.calc._signal_data))

    def test_signal_centred_around_zero(self):
        self.assertAlmostEqual(np.mean(self.calc._signal_data), 0.0, places=10)

    def test_signal_normalised_range(self):
        # After normalisation to [0,1] and mean-centring, values stay bounded
        self.assertLessEqual(np.max(self.calc._signal_data), 1.0)
        self.assertGreaterEqual(np.min(self.calc._signal_data), -1.0)

    def test_time_axis_step(self):
        dt = self.calc._time[1] - self.calc._time[0]
        self.assertAlmostEqual(dt, 1.0 / SAMPLE_RATE, places=10)

    def test_accepts_numpy_array(self):
        arr = np.array(self.signal, dtype=float)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, arr)
        self.assertEqual(len(calc._signal_data), len(arr))

    def test_does_not_mutate_input(self):
        original = self.signal.copy()
        PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, self.signal)
        np.testing.assert_array_equal(self.signal, original)


class TestFilterSignal(unittest.TestCase):

    def test_filter_preserves_length(self):
        signal = make_signal(freq_hz=2800)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        n_before = len(calc._signal_data)
        calc.filterSignal(2300, 3300)
        self.assertEqual(len(calc._signal_data), n_before)

    def test_filter_attenuates_out_of_band(self):
        # Signal at 500 Hz should be heavily attenuated by a 2300–3300 Hz bandpass
        signal = make_signal(freq_hz=500)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        power_before = np.var(calc._signal_data)
        calc.filterSignal(2300, 3300)
        power_after = np.var(calc._signal_data)
        self.assertLess(power_after, power_before * 0.01)

    def test_filter_passes_in_band(self):
        # Signal at 2800 Hz should survive the 2300–3300 Hz bandpass
        signal = make_signal(freq_hz=2800, noise=0.001)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        power_before = np.var(calc._signal_data)
        calc.filterSignal(2300, 3300)
        power_after = np.var(calc._signal_data)
        self.assertGreater(power_after, power_before * 0.1)


class TestDoFFT(unittest.TestCase):

    def _run_fft(self, freq_hz, threshold=0.0001):
        signal = make_signal(freq_hz=freq_hz, noise=0.001)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        calc.filterSignal(2300, 3300)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            peaks = calc.doFFT(path, low_freq=2300, high_freq=3300,
                               threshold=threshold)
        finally:
            os.unlink(path)
        return peaks

    def test_returns_list(self):
        peaks = self._run_fft(2800)
        self.assertIsInstance(peaks, list)

    def test_peak_near_signal_frequency(self):
        target = 2800
        peaks = self._run_fft(target)
        self.assertTrue(len(peaks) > 0, "Expected at least one peak")
        best_freq, _ = peaks[0]
        self.assertAlmostEqual(best_freq, target, delta=50)

    def test_peaks_sorted_by_magnitude_descending(self):
        peaks = self._run_fft(2800)
        if len(peaks) > 1:
            magnitudes = [m for _, m in peaks]
            self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))

    def test_empty_when_threshold_too_high(self):
        peaks = self._run_fft(2800, threshold=9999)
        self.assertEqual(peaks, [])

    def test_plot_file_written(self):
        signal = make_signal(freq_hz=2800)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.doFFT(path)
            self.assertTrue(os.path.getsize(path) > 0)
        finally:
            os.unlink(path)


class TestPlotSignal(unittest.TestCase):

    def test_plot_file_written(self):
        signal = make_signal()
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.plotSignal(path, window=100)
            self.assertTrue(os.path.getsize(path) > 0)
        finally:
            os.unlink(path)

    def test_window_larger_than_signal(self):
        # Should not crash when window > signal length
        signal = make_signal()
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.plotSignal(path, window=10_000_000)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
