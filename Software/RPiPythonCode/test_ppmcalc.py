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

    def test_off_bin_peak_interpolated(self):
        # 2800.3 Hz is between bin centres; parabolic interpolation should
        # get within a fraction of the 0.667 Hz bin width.
        peaks = self._run_fft(2800.3)
        self.assertTrue(len(peaks) > 0, "Expected at least one peak")
        self.assertAlmostEqual(peaks[0][0], 2800.3, delta=0.3)

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


class TestInterpolatePeak(unittest.TestCase):

    def test_recovers_off_bin_frequency(self):
        # Pure tone between bin centres (bin width 16000/24000 = 0.667 Hz).
        # The interpolated estimate should beat the raw bin centre easily.
        import scipy.signal as sig
        fs, n, target = 16000, 24000, 2800.3
        t = np.arange(n) / fs
        x = np.sin(2 * np.pi * target * t)
        f, den = sig.periodogram(x, fs, window='hann')
        idx = int(np.argmax(den))
        freq, mag = PPMCalc.interpolate_peak(f, den, idx)
        self.assertAlmostEqual(freq, target, delta=0.2)
        self.assertGreaterEqual(mag, den[idx])

    def test_symmetric_peak_stays_at_bin_centre(self):
        f = np.array([0.0, 1.0, 2.0])
        den = np.array([1.0, 2.0, 1.0])
        freq, mag = PPMCalc.interpolate_peak(f, den, 1)
        self.assertEqual(freq, 1.0)
        self.assertEqual(mag, 2.0)

    def test_edge_indices_fall_back_to_bin_values(self):
        f = np.array([0.0, 1.0, 2.0])
        den = np.array([3.0, 2.0, 1.0])
        self.assertEqual(PPMCalc.interpolate_peak(f, den, 0), (0.0, 3.0))
        self.assertEqual(PPMCalc.interpolate_peak(f, den, 2), (2.0, 1.0))

    def test_degenerate_points_fall_back_to_bin_values(self):
        # Collinear points have no parabolic maximum.
        f = np.array([0.0, 1.0, 2.0])
        den = np.array([1.0, 1.0, 1.0])
        self.assertEqual(PPMCalc.interpolate_peak(f, den, 1), (1.0, 1.0))


class TestEstimateSNR(unittest.TestCase):

    def _periodogram(self, x, fs=16000):
        import scipy.signal as sig
        return sig.periodogram(x, fs, window='hann')

    def test_strong_tone_has_high_snr(self):
        fs, n = 16000, 24000
        t = np.arange(n) / fs
        rng = np.random.default_rng(1)
        x = np.sin(2 * np.pi * 2800 * t) + rng.normal(0, 0.05, n)
        f, den = self._periodogram(x, fs)
        snr = PPMCalc.estimate_snr(f, den, 2800)
        self.assertGreater(snr, 100)

    def test_noise_only_has_low_snr(self):
        rng = np.random.default_rng(2)
        x = rng.normal(0, 1.0, 24000)
        f, den = self._periodogram(x)
        snr = PPMCalc.estimate_snr(f, den, 2800)
        self.assertLess(snr, 50)

    def test_nan_when_no_sideband_bins(self):
        # All bins within `inner` Hz of the peak → no sideband to estimate from.
        f = np.linspace(2790, 2810, 21)
        den = np.ones_like(f)
        snr = PPMCalc.estimate_snr(f, den, 2800)
        self.assertTrue(np.isnan(snr))

    def test_median_robust_to_interference_peak(self):
        # A single strong interference spike in the sideband should barely
        # move the median-based noise estimate.
        fs, n = 16000, 24000
        t = np.arange(n) / fs
        rng = np.random.default_rng(3)
        x = np.sin(2 * np.pi * 2800 * t) + rng.normal(0, 0.05, n)
        f, den = self._periodogram(x, fs)
        snr_clean = PPMCalc.estimate_snr(f, den, 2800)
        spike = den.copy()
        spike[np.argmin(np.abs(f - 2650))] = np.max(den)   # spike in sideband
        snr_spiked = PPMCalc.estimate_snr(f, spike, 2800)
        self.assertAlmostEqual(snr_spiked / snr_clean, 1.0, delta=0.05)


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


class TestPlotFilteredEnvelope(unittest.TestCase):

    def _filtered_calc(self, **kw):
        """A PPMCalc bandpassed around make_signal()'s 2800 Hz tone."""
        signal = make_signal(**kw)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, signal)
        calc.filterSignal(2300, 3300)
        return calc

    def test_plot_file_written(self):
        calc = self._filtered_calc()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.plotFilteredEnvelope(path)
            self.assertTrue(os.path.getsize(path) > 0)
        finally:
            os.unlink(path)

    def test_log_scale_file_written(self):
        calc = self._filtered_calc()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.plotFilteredEnvelope(path, log_scale=True)
            self.assertTrue(os.path.getsize(path) > 0)
        finally:
            os.unlink(path)

    def test_recovers_decay_constant(self):
        # make_signal() decays with T2 = 0.3 s (see its `decay` term); the
        # exponential fit should recover that time constant.  Normalisation in
        # the constructor scales amplitude but leaves the decay rate unchanged.
        calc = self._filtered_calc()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            params = calc.plotFilteredEnvelope(path)
        finally:
            os.unlink(path)
        self.assertIsNotNone(params)
        _A, T2, _C = params
        self.assertAlmostEqual(T2, 0.3, delta=0.1)

    def test_flat_signal_does_not_crash(self):
        # A steady (non-decaying) tone may not admit an exponential fit; the
        # method must still write the plot and simply return None or a fit,
        # never raise — the flat envelope is itself the "no decay" answer.
        n = int(SAMPLE_RATE * DURATION_MS / 1000)
        t = np.arange(n)
        tone = (np.sin(2 * np.pi * 2800 * t / SAMPLE_RATE) * 1000 + 2048).astype(int)
        calc = PPMCalc.PPMCalc(SAMPLE_RATE, DURATION_MS, tone)
        calc.filterSignal(2300, 3300)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
            path = tf.name
        try:
            calc.plotFilteredEnvelope(path)   # must not raise
            self.assertTrue(os.path.getsize(path) > 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
