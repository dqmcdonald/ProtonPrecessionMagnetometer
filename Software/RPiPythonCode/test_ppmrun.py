"""Tests for ppmrun.py — CLI argument parsing and utility functions."""
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import ppmrun
import PPMCalc


def make_signal(freq_hz=2800, sample_rate=16000, duration_ms=1500, noise=0.005):
    n = int(sample_rate * duration_ms / 1000)
    t = np.arange(n)
    decay = np.exp(-t / (sample_rate * 0.3))
    rng = np.random.default_rng(0)
    sig = np.sin(2 * np.pi * freq_hz * t / sample_rate) * decay
    sig += rng.normal(0, noise, n)
    return (sig * 1000 + 2048).astype(int)


class TestArgumentParser(unittest.TestCase):

    def parse(self, args):
        return ppmrun.build_parser().parse_args(args)

    def test_defaults(self):
        args = self.parse([])
        self.assertIsNone(args.input)
        self.assertEqual(args.runs, 1)
        self.assertEqual(args.on_time, 6000)
        self.assertEqual(args.sample_time, 1500)
        self.assertEqual(args.sample_rate, 16000)
        self.assertEqual(args.delay, 500)
        self.assertEqual(args.cool_down, 10000)
        self.assertEqual(args.low_freq, 2300)
        self.assertEqual(args.high_freq, 3300)
        self.assertFalse(args.no_plots)
        self.assertEqual(args.output_dir, "data")

    def test_input_flag(self):
        args = self.parse(["--input", "data/ppm1.dat"])
        self.assertEqual(args.input, "data/ppm1.dat")

    def test_runs_flag(self):
        args = self.parse(["--runs", "5"])
        self.assertEqual(args.runs, 5)

    def test_background_defaults(self):
        args = self.parse([])
        self.assertEqual(args.background_runs, 0)
        self.assertIsNone(args.background_input)

    def test_background_flags(self):
        args = self.parse(["--background-runs", "3",
                           "--background-input", "data/nosample.dat"])
        self.assertEqual(args.background_runs, 3)
        self.assertEqual(args.background_input, "data/nosample.dat")

    def test_freq_flags(self):
        args = self.parse(["--low-freq", "2500", "--high-freq", "3100"])
        self.assertEqual(args.low_freq, 2500)
        self.assertEqual(args.high_freq, 3100)

    def test_no_plots_flag(self):
        args = self.parse(["--no-plots"])
        self.assertTrue(args.no_plots)

    def test_verbose_flag(self):
        args = self.parse(["-v"])
        self.assertTrue(args.verbose)

    def test_verbose_default_false(self):
        args = self.parse([])
        self.assertFalse(args.verbose)

    def test_port_default_is_autodetect(self):
        # None means "auto-detect": collect_runs() calls PPM.find_arduino_port().
        args = self.parse([])
        self.assertIsNone(args.port)

    def test_port_flag(self):
        args = self.parse(["--port", "/dev/ttyUSB0"])
        self.assertEqual(args.port, "/dev/ttyUSB0")

    def test_list_ports_flag(self):
        args = self.parse(["--list-ports"])
        self.assertTrue(args.list_ports)

    def test_hardware_timing_flags(self):
        args = self.parse(["--on-time", "3000", "--sample-time", "1000",
                           "--sample-rate", "8000", "--delay", "200",
                           "--cool-down", "5000"])
        self.assertEqual(args.on_time, 3000)
        self.assertEqual(args.sample_time, 1000)
        self.assertEqual(args.sample_rate, 8000)
        self.assertEqual(args.delay, 200)
        self.assertEqual(args.cool_down, 5000)


class TestSetupRunDir(unittest.TestCase):

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as base:
            run_dir = ppmrun.setup_run_dir(base)
            self.assertTrue(os.path.isdir(run_dir))

    def test_directory_name_format(self):
        with tempfile.TemporaryDirectory() as base:
            run_dir = ppmrun.setup_run_dir(base)
            name = os.path.basename(run_dir)
            self.assertTrue(name.startswith("PPM_"), name)
            self.assertEqual(len(name), len("PPM_") + 19)

    def test_custom_tag(self):
        with tempfile.TemporaryDirectory() as base:
            run_dir = ppmrun.setup_run_dir(base, tag="new_amp")
            name = os.path.basename(run_dir)
            self.assertTrue(name.startswith("new_amp_"), name)
            self.assertEqual(len(name), len("new_amp_") + 19)

    def test_two_dirs_are_unique(self):
        with tempfile.TemporaryDirectory() as base:
            d1 = ppmrun.setup_run_dir(base)
            import time; time.sleep(1.1)
            d2 = ppmrun.setup_run_dir(base)
            self.assertNotEqual(d1, d2)


class TestLoadInputFile(unittest.TestCase):

    def _write_dat(self, path, sample_rate, signal):
        with open(path, "w") as f:
            f.write("{}\n".format(len(signal)))
            f.write("{}\n".format(sample_rate))
            for v in signal:
                f.write("{}\n".format(int(v)))

    def test_returns_single_entry(self):
        signal = make_signal()
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False, mode='w') as tf:
            path = tf.name
        try:
            self._write_dat(path, 16000, signal)
            result = ppmrun.load_input_file(path)
            self.assertEqual(len(result), 1)
        finally:
            os.unlink(path)

    def test_sample_rate_preserved(self):
        signal = make_signal(sample_rate=15800)
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False, mode='w') as tf:
            path = tf.name
        try:
            self._write_dat(path, 15800, signal)
            sr, sample_time_ms, data = ppmrun.load_input_file(path)[0]
            self.assertEqual(sr, 15800)
        finally:
            os.unlink(path)

    def test_sample_time_derived_from_count_and_rate(self):
        sr = 16000
        signal = make_signal(sample_rate=sr, duration_ms=1500)
        expected_ms = len(signal) / sr * 1000
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False, mode='w') as tf:
            path = tf.name
        try:
            self._write_dat(path, sr, signal)
            _, sample_time_ms, _ = ppmrun.load_input_file(path)[0]
            self.assertAlmostEqual(sample_time_ms, expected_ms, places=3)
        finally:
            os.unlink(path)


class TestReportPeaks(unittest.TestCase):

    def _capture_report(self, peaks, snr=None):
        import logging
        logger = logging.getLogger("test_report")
        with patch("builtins.print") as mock_print:
            ppmrun.report_peaks(peaks, logger, snr=snr)
        return [str(c[0][0]) for c in mock_print.call_args_list]

    def test_no_peaks(self):
        lines = self._capture_report([])
        self.assertEqual(len(lines), 1)
        self.assertIn("No peaks", lines[0])

    def test_single_peak_field_strength(self):
        peaks = [(2849.3, 0.0019)]
        lines = self._capture_report(peaks)
        self.assertTrue(any("2849" in l for l in lines))
        self.assertTrue(any("66.9" in l or "66.92" in l for l in lines))
        self.assertTrue(any("µT" in l for l in lines))

    def test_multiple_peaks_shows_candidates(self):
        peaks = [(2849.3, 0.0019), (3049.1, 0.001), (2749.8, 0.0006)]
        lines = self._capture_report(peaks)
        self.assertTrue(any("candidate" in l.lower() for l in lines))

    def test_snr_reported_in_db(self):
        peaks = [(2849.3, 0.0019)]
        lines = self._capture_report(peaks, snr=100.0)   # 100× power = 20 dB
        self.assertTrue(any("SNR" in l and "20.0 dB" in l for l in lines))

    def test_snr_omitted_when_not_given(self):
        peaks = [(2849.3, 0.0019)]
        lines = self._capture_report(peaks)
        self.assertFalse(any("SNR" in l for l in lines))

    def test_snr_omitted_when_nan(self):
        peaks = [(2849.3, 0.0019)]
        lines = self._capture_report(peaks, snr=float('nan'))
        self.assertFalse(any("SNR" in l for l in lines))


class TestAnalyse(unittest.TestCase):

    def test_returns_peaks_list_and_snr(self):
        signal = make_signal(freq_hz=2800, noise=0.001)
        runs_data = [(16000, 1500, signal)]

        with tempfile.TemporaryDirectory() as run_dir:
            args = ppmrun.build_parser().parse_args(
                ["--no-plots", "--fft-threshold", "0.0001",
                 "--low-freq", "2300", "--high-freq", "3300"])
            peaks, snr = ppmrun.analyse(runs_data, args, run_dir)

        self.assertIsInstance(peaks, list)
        if peaks:
            self.assertAlmostEqual(peaks[0][0], 2800, delta=60)
            # A clean synthetic tone should stand far above the noise floor.
            self.assertGreater(snr, 100)

    def test_snr_nan_when_no_peaks(self):
        signal = make_signal(freq_hz=2800, noise=0.001)
        runs_data = [(16000, 1500, signal)]

        with tempfile.TemporaryDirectory() as run_dir:
            args = ppmrun.build_parser().parse_args(
                ["--no-plots", "--fft-threshold", "9999",
                 "--low-freq", "2300", "--high-freq", "3300"])
            peaks, snr = ppmrun.analyse(runs_data, args, run_dir)

        self.assertEqual(peaks, [])
        self.assertTrue(np.isnan(snr))

    def test_interpolated_peak_close_to_off_bin_frequency(self):
        # 2800.3 Hz is not a bin centre (bin width 16000/24000 = 0.667 Hz);
        # parabolic interpolation should land much closer than half a bin.
        signal = make_signal(freq_hz=2800.3, noise=0.001)
        runs_data = [(16000, 1500, signal)]

        with tempfile.TemporaryDirectory() as run_dir:
            args = ppmrun.build_parser().parse_args(
                ["--no-plots", "--fft-threshold", "0.0001",
                 "--low-freq", "2300", "--high-freq", "3300"])
            peaks, _ = ppmrun.analyse(runs_data, args, run_dir)

        self.assertTrue(len(peaks) > 0, "Expected at least one peak")
        self.assertAlmostEqual(peaks[0][0], 2800.3, delta=0.3)

    def test_fft_plot_written(self):
        signal = make_signal(freq_hz=2800)
        runs_data = [(16000, 1500, signal)]
        args = ppmrun.build_parser().parse_args(
            ["--fft-threshold", "0.0001",
             "--low-freq", "2300", "--high-freq", "3300"])

        with tempfile.TemporaryDirectory() as run_dir:
            ppmrun.analyse(runs_data, args, run_dir)
            self.assertTrue(os.path.exists(os.path.join(run_dir, "fft_averaged.png")))


class TestBackgroundSubtraction(unittest.TestCase):
    """Background spectral subtraction removes stationary interference that
    appears in both the measurement and the coil-off background record."""

    FS = 16000
    N = 24000

    def _make_records(self):
        """Signal run: interference tone + weaker decaying precession tone.
        Background run: the same interference, different noise realisation."""
        t = np.arange(self.N) / self.FS
        interference = 1.0 * np.sin(2 * np.pi * 2950 * t)
        precession = 0.5 * np.sin(2 * np.pi * 2800 * t) * np.exp(-t / 0.5)
        rng_sig = np.random.default_rng(10)
        rng_bg = np.random.default_rng(11)
        sig_run = ((interference + precession
                    + rng_sig.normal(0, 0.05, self.N)) * 1000 + 2048).astype(int)
        bg_run = ((interference
                   + rng_bg.normal(0, 0.05, self.N)) * 1000 + 2048).astype(int)
        return sig_run, bg_run

    def _args(self):
        return ppmrun.build_parser().parse_args(
            ["--no-plots", "--fft-threshold", "1e-7",
             "--low-freq", "2300", "--high-freq", "3300"])

    def test_interference_dominates_without_subtraction(self):
        sig_run, _ = self._make_records()
        with tempfile.TemporaryDirectory() as run_dir:
            peaks, _ = ppmrun.analyse([(self.FS, 1500, sig_run)],
                                      self._args(), run_dir)
        self.assertTrue(len(peaks) > 0)
        self.assertAlmostEqual(peaks[0][0], 2950, delta=2)

    def test_subtraction_recovers_precession_peak(self):
        sig_run, bg_run = self._make_records()
        with tempfile.TemporaryDirectory() as run_dir:
            peaks, snr = ppmrun.analyse(
                [(self.FS, 1500, sig_run)], self._args(), run_dir,
                background_data=[(self.FS, 1500, bg_run)])
        self.assertTrue(len(peaks) > 0)
        self.assertAlmostEqual(peaks[0][0], 2800, delta=2)

    def test_background_periodogram_empty_returns_none(self):
        f, den = ppmrun.background_periodogram([], self._args())
        self.assertIsNone(f)
        self.assertIsNone(den)

    def test_subtract_background_interpolates_mismatched_axis(self):
        # Background recorded at a slightly different actual sample rate has
        # a different frequency axis; subtraction must interpolate, not fail.
        f_axis = np.linspace(0, 8000, 1001)
        den = np.ones_like(f_axis)
        bg_f = np.linspace(0, 8000, 901)
        bg_den = np.ones_like(bg_f) * 0.5
        result, scale = ppmrun.subtract_background(
            f_axis, den, bg_f, bg_den, 2300, 3300)
        self.assertEqual(len(result), len(f_axis))
        self.assertAlmostEqual(scale, 2.0)
        # Noise floor matched: 1.0 - 2.0 * 0.5 = 0
        band = (f_axis >= 2300) & (f_axis <= 3300)
        np.testing.assert_allclose(result[band], 0.0, atol=1e-12)

    def test_subtracted_spectrum_never_negative(self):
        sig_run, bg_run = self._make_records()
        f, den = ppmrun.background_periodogram(
            [(self.FS, 1500, bg_run)], self._args())
        # Subtract a deliberately oversized background from a weak spectrum.
        result, _ = ppmrun.subtract_background(
            f, np.full_like(den, np.median(den)), f, den * 100, 2300, 3300)
        self.assertGreaterEqual(result.min(), 0.0)


if __name__ == "__main__":
    unittest.main()
