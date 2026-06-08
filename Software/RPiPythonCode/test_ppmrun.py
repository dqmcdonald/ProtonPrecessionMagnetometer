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

    def test_freq_flags(self):
        args = self.parse(["--low-freq", "2500", "--high-freq", "3100"])
        self.assertEqual(args.low_freq, 2500)
        self.assertEqual(args.high_freq, 3100)

    def test_no_plots_flag(self):
        args = self.parse(["--no-plots"])
        self.assertTrue(args.no_plots)

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

    def _capture_report(self, peaks):
        import logging
        logger = logging.getLogger("test_report")
        with patch("builtins.print") as mock_print:
            ppmrun.report_peaks(peaks, logger)
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


class TestAnalyse(unittest.TestCase):

    def test_returns_peaks_list(self):
        signal = make_signal(freq_hz=2800, noise=0.001)
        runs_data = [(16000, 1500, signal)]
        args = ppmrun.build_parser().parse_args(
            ["--no-plots", "--fft-threshold", "0.0001"])

        with tempfile.TemporaryDirectory() as run_dir:
            args_patched = ppmrun.build_parser().parse_args(
                ["--no-plots", "--fft-threshold", "0.0001",
                 "--low-freq", "2300", "--high-freq", "3300"])
            peaks = ppmrun.analyse(runs_data, args_patched, run_dir)

        self.assertIsInstance(peaks, list)
        if peaks:
            self.assertAlmostEqual(peaks[0][0], 2800, delta=60)

    def test_fft_plot_written(self):
        signal = make_signal(freq_hz=2800)
        runs_data = [(16000, 1500, signal)]
        args = ppmrun.build_parser().parse_args(
            ["--fft-threshold", "0.0001",
             "--low-freq", "2300", "--high-freq", "3300"])

        with tempfile.TemporaryDirectory() as run_dir:
            ppmrun.analyse(runs_data, args, run_dir)
            self.assertTrue(os.path.exists(os.path.join(run_dir, "fft_averaged.png")))


if __name__ == "__main__":
    unittest.main()
