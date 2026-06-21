"""
ppmrun.py — Main entry point for the Proton Precession Magnetometer.

Orchestrates hardware collection (via PPM.py), signal analysis (via PPMCalc.py),
and result reporting.  Can also re-analyse previously saved data files without
any hardware connection.

Usage examples
--------------
Single hardware run with default settings::

    python ppmrun.py

Tagged run with 5-cycle averaging and narrow filter::

    python ppmrun.py --tag hillside --runs 5 --low-freq 2200 --high-freq 2700

Run with background subtraction (2 coil-off acquisitions collected first)::

    python ppmrun.py --runs 3 --background-runs 2

Re-analyse an existing data file (no hardware needed)::

    python ppmrun.py --input data/ppm1.dat

Re-analyse with an existing no-sample recording as background::

    python ppmrun.py --input data/ppm1.dat --background-input data/nosample.dat

Background subtraction
----------------------
Background acquisitions sample with the coil never energised, recording only
amplifier noise and ambient interference.  Their averaged spectrum is rescaled
to the measurement noise floor and subtracted from the measurement spectrum
before peak detection, suppressing stationary interference — notably mains
harmonics: the 49th harmonic of 50 Hz (2450 Hz) falls inside the Larmor band
and cannot be removed by the bandpass filter.

Multi-run averaging
-------------------
When --runs N > 1, N complete polarise-wait-sample cycles are performed.
The periodograms from all N runs are averaged element-wise before peak
detection.  Averaging in the frequency domain does not require phase alignment
between runs (unlike averaging raw time-domain signals), and improves the
signal-to-noise ratio by approximately √N.

Output directory
----------------
Each invocation creates a timestamped subdirectory:
    <output-dir>/<tag>_YYYY_MM_DD_HH_MM_SS/

All data files, plots, and the session log are written inside this directory
so that multiple runs do not overwrite each other.
"""

import argparse
import logging
import os
import sys
from datetime import datetime

import numpy as np
import scipy.signal as sig

import PPMCalc

# Proton gyromagnetic ratio expressed as Hz per microtesla.
# Derived from γ_p = 2.67522 × 10⁸ rad/(s·T) → f = γ_p/(2π) = 42.5775 MHz/T.
# Rearranged: B [µT] = f [Hz] / 42.5775
# For reference: 57200 nT (typical mid-latitude field) → 2435 Hz.
GAMMA_HZ_PER_UT = 42.5775


def build_parser():
    """Build and return the command-line argument parser."""
    p = argparse.ArgumentParser(
        description="Proton Precession Magnetometer data collection and analysis")

    # ── Serial port ───────────────────────────────────────────────────────────
    p.add_argument("--port", default=None, metavar="DEV",
                   help="Serial port connected to the Arduino, e.g. "
                        "/dev/ttyUSB0 or /dev/ttyAMA0.  Use --list-ports "
                        "to see available ports (default: auto-detect a USB "
                        "serial adapter, falling back to /dev/serial0)")

    p.add_argument("--list-ports", action="store_true",
                   help="Scan and print all available serial ports, then exit. "
                        "Useful for finding the correct --port value when the "
                        "Arduino is connected via USB-serial adapter.")

    # ── Run control ───────────────────────────────────────────────────────────
    p.add_argument("--input", metavar="FILE",
                   help="Analyse an existing data file instead of collecting "
                        "from hardware.  The hardware timing flags are ignored.")

    p.add_argument("--tag", default="PPM", metavar="TAG",
                   help="Descriptive prefix for the output directory name, "
                        "e.g. 'new_amp' → new_amp_2024_01_15_10_30_00/ "
                        "(default: PPM)")

    p.add_argument("--runs", type=int, default=1, metavar="N",
                   help="Number of complete measurement cycles to perform and "
                        "average.  SNR improves by √N but total time scales "
                        "linearly with N (default: 1)")

    p.add_argument("--background-runs", type=int, default=0, metavar="N",
                   help="Number of background (coil-off) acquisitions to "
                        "collect before the measurement runs.  Their averaged "
                        "spectrum is subtracted from the measurement spectrum "
                        "to suppress stationary interference such as mains "
                        "harmonics — the 49th harmonic of 50 Hz (2450 Hz) "
                        "falls inside the Larmor band.  Background runs are "
                        "fast: no polarise, settle, or cool-down phase "
                        "(default: 0, no subtraction)")

    p.add_argument("--background-input", metavar="FILE",
                   help="Use an existing .dat file (e.g. a previous no-sample "
                        "recording) as the background for spectral subtraction "
                        "instead of collecting one.  Works with both hardware "
                        "runs and --input re-analysis.")

    # ── Hardware timing ───────────────────────────────────────────────────────
    p.add_argument("--on-time", type=int, default=6000, metavar="MS",
                   help="Coil polarisation duration in ms.  Longer times give "
                        "stronger initial magnetisation (diminishing returns "
                        "beyond ~2×T1 ≈ 6 s for water) (default: 6000)")

    p.add_argument("--sample-time", type=int, default=1500, metavar="MS",
                   help="ADC sampling window duration in ms.  Must not exceed "
                        "32767 / sample_rate seconds to stay within the Arduino "
                        "sample buffer (default: 1500)")

    p.add_argument("--sample-rate", type=int, default=16000, metavar="HZ",
                   help="Requested ADC sample rate in Hz.  The Arduino will "
                        "report the actual achieved rate after each run "
                        "(default: 16000)")

    p.add_argument("--delay", type=int, default=500, metavar="MS",
                   help="Delay from coil switch-off to start of ADC sampling "
                        "in ms.  Allows the large coil transient to decay so "
                        "it does not saturate the ADC input (default: 500)")

    p.add_argument("--cool-down", type=int, default=10000, metavar="MS",
                   help="MOSFET cool-down time between runs in ms.  Prevents "
                        "thermal damage to the switching transistor (default: 10000)")

    # ── Analysis parameters ───────────────────────────────────────────────────
    p.add_argument("--low-freq", type=float, default=2300, metavar="HZ",
                   help="Bandpass filter lower cutoff in Hz.  Set slightly "
                        "below the expected Larmor frequency (default: 2300)")

    p.add_argument("--high-freq", type=float, default=3300, metavar="HZ",
                   help="Bandpass filter upper cutoff in Hz.  Set slightly "
                        "above the expected Larmor frequency (default: 3300)")

    p.add_argument("--fft-threshold", type=float, default=0.0005, metavar="MAG",
                   help="Minimum periodogram power spectral density to count "
                        "as a peak.  Reduce if no peaks are found; increase "
                        "to suppress noise peaks (default: 0.0005)")

    # ── Output control ────────────────────────────────────────────────────────
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print progress messages to stdout at each pipeline "
                        "step (hardware commands, filter, FFT, peak detection)")

    p.add_argument("--no-plots", action="store_true",
                   help="Skip generating PNG graph files (faster; useful when "
                        "running many automated measurements)")

    p.add_argument("--output-dir", default="data", metavar="DIR",
                   help="Base directory under which timestamped run directories "
                        "are created (default: data/)")

    p.add_argument("--title", default=None, metavar="STR",
                   help="Title shown on the generated plots.  Defaults to the "
                        "run directory name (<tag>_<timestamp>)")

    return p


def setup_run_dir(base_dir, tag="PPM"):
    """Create and return a timestamped output directory for this run.

    The directory name is  <tag>_YYYY_MM_DD_HH_MM_SS  so that alphabetic
    sorting also gives chronological order and different tags do not collide.

    Args:
        base_dir: Parent directory (created if it does not exist).
        tag:      Descriptive prefix, e.g. 'outdoor_test'.

    Returns:
        Absolute path to the newly created run directory.
    """
    ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    run_dir = os.path.join(base_dir, f"{tag}_{ts}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def setup_logger(run_dir):
    """Configure the root 'PPM' logger to write to ppm.log in run_dir.

    Args:
        run_dir: Directory where ppm.log will be created.

    Returns:
        Configured logging.Logger instance.
    """
    log_path = os.path.join(run_dir, "ppm.log")
    logger = logging.getLogger("PPM")
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%d-%b-%Y %H:%M:%S")
    return logger


def vprint(msg, verbose):
    """Print msg to stdout only when verbose mode is enabled."""
    if verbose:
        print(msg)


def _collect_cycles(ppm, n, run_dir, logger, verbose, background=False):
    """Perform n measurement cycles on an open PPMRun and return the results.

    Each run is saved to its own numbered .dat file ("run_XX.dat", or
    "background_XX.dat" for background acquisitions) so individual cycles can
    be inspected separately if needed.

    Args:
        ppm:        An open, configured PPM.PPMRun instance.
        n:          Number of cycles to perform.
        run_dir:    Directory where data files will be saved.
        logger:     Logger instance for progress messages.
        verbose:    If True, print progress to stdout.
        background: If True, perform sample-only background acquisitions
                    (coil never energised).

    Returns:
        List of (sample_rate, sample_time_ms, signal_data) tuples, one per run.
    """
    kind = "Background" if background else "Run"
    file_prefix = "background" if background else "run"

    results = []
    for i in range(n):
        logger.info("Starting {} {}/{}".format(kind.lower(), i + 1, n))
        vprint("\n[{} {}/{}] Sending configuration to Arduino...".format(
            kind, i + 1, n), verbose)
        # Re-send configured values before each run in case the Arduino was
        # reset or powered off between runs.
        ppm.sendConfiguredValues()
        if background:
            vprint("[{} {}/{}] Sampling with coil off (noise + interference "
                   "only)...".format(kind, i + 1, n), verbose)
        else:
            vprint("[{} {}/{}] Polarising coil for {} ms...".format(
                kind, i + 1, n, ppm._on_time), verbose)
        out_path = os.path.join(run_dir, "{}_{:02d}.dat".format(file_prefix, i))
        ppm.doMeasurement(output_path=out_path, background=background)
        actual_rate = ppm.getActualSampleRate()
        n_samples = len(ppm.getSignalData())
        vprint("[{} {}/{}] Sampling complete: {} samples at {} Hz  →  {:.2f} s window".format(
            kind, i + 1, n, n_samples, actual_rate,
            n_samples / actual_rate), verbose)
        vprint("[{} {}/{}] Data saved to {}".format(kind, i + 1, n, out_path), verbose)
        results.append((
            actual_rate,
            ppm.getSampleTime(),
            ppm.getSignalData().copy()))   # copy so the array is not aliased
        logger.info("{} {}/{} complete, saved to {}".format(kind, i + 1, n, out_path))

    return results


def collect_runs(args, run_dir, logger, verbose=False):
    """Perform the configured hardware measurement cycles and return the results.

    PPM is imported here rather than at module level so that the module can be
    imported (for testing, re-analysis, etc.) on machines where pyserial is not
    installed or the serial port does not exist.

    Background acquisitions (if requested) are collected first: they need no
    polarise, settle, or cool-down phase, so they are fast, and running them
    before the first polarise pulse guarantees no residual proton signal can
    leak into the background record.

    Args:
        args:    Parsed argparse namespace with hardware timing attributes.
        run_dir: Directory where data files will be saved.
        logger:  Logger instance for progress messages.
        verbose: If True, print progress to stdout.

    Returns:
        (signal_runs, background_runs) — two lists of
        (sample_rate, sample_time_ms, signal_data) tuples.  background_runs is
        empty unless --background-runs was given.
    """
    import PPM   # deferred import — requires pyserial and a live serial port

    # --port omitted: locate the Arduino automatically (USB vendor ID match,
    # then device-name heuristic, then the Pi hardware UART).
    port = args.port
    if port is None:
        port = PPM.find_arduino_port(logger)
        vprint("Auto-detected Arduino on {}".format(port), verbose)
    vprint("Opening serial port {} at {} baud".format(port, PPM.BAUD_RATE), verbose)
    ppm = PPM.PPMRun(logger, port=port)
    ppm.configure(
        on_time=args.on_time,
        sample_time=args.sample_time,
        sample_rate=args.sample_rate,
        delay=args.delay,
        cool_down=args.cool_down)
    vprint("Hardware configured: on_time={}ms  sample_time={}ms  "
           "sample_rate={}Hz  delay={}ms  cool_down={}ms".format(
               args.on_time, args.sample_time, args.sample_rate,
               args.delay, args.cool_down), verbose)

    background_runs = []
    if args.background_runs > 0:
        background_runs = _collect_cycles(
            ppm, args.background_runs, run_dir, logger, verbose, background=True)

    signal_runs = _collect_cycles(ppm, args.runs, run_dir, logger, verbose)
    return signal_runs, background_runs


def load_input_file(filepath):
    """Load a single .dat file for re-analysis without hardware.

    The sample_time is derived from the data rather than stored in the file
    because older files may not record it explicitly.

    Args:
        filepath: Path to a .dat file written by PPM.doMeasurement().

    Returns:
        Single-element list containing (sample_rate, sample_time_ms, signal_data)
        to match the format returned by collect_runs().
    """
    sample_rate, num_samples, signal_data = PPMCalc.load_from_file(filepath)
    # Reconstruct the sampling duration from the sample count and rate.
    # This is exact because the Arduino samples at a fixed rate.
    sample_time_ms = num_samples / sample_rate * 1000
    return [(sample_rate, sample_time_ms, signal_data)]


def background_periodogram(background_data, args, verbose=False):
    """Average the Hann periodograms of one or more background acquisitions.

    Each background record is pushed through the same pipeline as a
    measurement record (PPMCalc normalisation, Butterworth bandpass, Hann
    periodogram) so that its spectrum is directly comparable with the
    measurement spectrum it will be subtracted from.

    Args:
        background_data: List of (sample_rate, sample_time_ms, signal_data)
                         tuples from background (coil-off) acquisitions.
        args:            Parsed argparse namespace with analysis parameters.
        verbose:         If True, print progress to stdout.

    Returns:
        (f_axis, averaged_den) for the averaged background spectrum, or
        (None, None) if background_data is empty.
    """
    if not background_data:
        return None, None

    averaged_den = None
    f_axis = None
    for i, (sample_rate, sample_time, signal_data) in enumerate(background_data):
        vprint("  [bg {}] Processing background record ({} samples at {} Hz)..."
               .format(i, len(signal_data), sample_rate), verbose)
        calc = PPMCalc.PPMCalc(sample_rate, sample_time, signal_data)
        calc.filterSignal(args.low_freq, args.high_freq)
        f, den = sig.periodogram(calc._signal_data, calc._sample_rate,
                                 window='hann')
        if averaged_den is None:
            averaged_den = den.copy()
            f_axis = f
        else:
            averaged_den += den
    averaged_den /= len(background_data)
    return f_axis, averaged_den


def subtract_background(f_axis, den, bg_f, bg_den, low_freq, high_freq):
    """Subtract a background spectrum from a measurement spectrum.

    PPMCalc normalises each record by its own amplitude range, so the absolute
    PSD levels of the measurement and background spectra differ even though
    they were recorded with identical hardware settings.  The background is
    therefore rescaled before subtraction: the scale factor is the median of
    the per-bin measurement/background ratio over the analysis band.  The
    median is dominated by ordinary noise bins — discrete peaks (the Larmor
    line, interference spikes) occupy too few bins to move it — so it matches
    the two noise floors without cancelling the signal peak.

    The result is clipped at zero: negative power is unphysical and would
    confuse peak detection.

    Args:
        f_axis:    Measurement frequency axis.
        den:       Measurement power spectral density.
        bg_f:      Background frequency axis (interpolated onto f_axis if it
                   differs, e.g. when the records have different lengths or
                   actual sample rates).
        bg_den:    Background power spectral density.
        low_freq:  Lower edge of the analysis band in Hz.
        high_freq: Upper edge of the analysis band in Hz.

    Returns:
        (subtracted_den, scale) — the background-subtracted PSD and the scale
        factor that was applied to the background.  Returns (den, None)
        unchanged if no usable bins were found to estimate the scale.
    """
    if len(bg_den) != len(f_axis) or not np.array_equal(bg_f, f_axis):
        bg_den = np.interp(f_axis, bg_f, bg_den)
    band = (f_axis >= low_freq) & (f_axis <= high_freq) & (bg_den > 0)
    if not band.any():
        return den, None
    scale = float(np.median(den[band] / bg_den[band]))
    return np.clip(den - scale * bg_den, 0.0, None), scale


def analyse(runs_data, args, run_dir, verbose=False, logger=None,
            background_data=None):
    """Filter signals, average periodograms across all runs, and find peaks.

    For each run:
    1. Construct a PPMCalc object (normalises and centres the signal).
    2. Optionally save a three-panel raw signal plot.
    3. Apply a Butterworth bandpass filter to reject out-of-band interference.
    4. Optionally save a three-panel filtered signal plot.
    5. Compute the periodogram (power spectral density estimate) with a Hann
       window to reduce spectral leakage, and report the run's SNR — the
       strongest in-band peak against the median noise floor ±100–300 Hz
       either side of it.

    After processing all runs, the periodograms are averaged element-wise.
    Averaging in the frequency domain is preferred over averaging the raw
    time-domain signals because it does not require the precession oscillations
    to be phase-aligned between runs — a condition that cannot be guaranteed
    since the proton phase is random at the start of each precession cycle.

    The averaged periodogram is then searched for peaks above the threshold,
    and each peak is refined to sub-bin precision by parabolic interpolation
    (PPMCalc.interpolate_peak) — the raw bin width of ~0.67 Hz corresponds to
    ~16 nT, so interpolation matters for the reported field value.

    If background_data is given, the averaged spectrum of those coil-off
    acquisitions is rescaled to the measurement noise floor and subtracted
    before peak detection (see subtract_background), suppressing stationary
    interference such as mains harmonics inside the Larmor band.  SNR is
    always estimated against the *unsubtracted* spectrum: subtraction pushes
    noise bins towards zero, which would make a peak/noise ratio measured on
    the subtracted spectrum meaninglessly large.

    Args:
        runs_data:       List of (sample_rate, sample_time_ms, signal_data)
                         tuples.
        args:            Parsed argparse namespace with analysis parameters.
        run_dir:         Directory where output files are written.
        verbose:         If True, print pipeline progress to stdout.
        logger:          Optional logging.Logger for per-run SNR records.
        background_data: Optional list of run tuples from background
                         (coil-off) acquisitions for spectral subtraction.

    Returns:
        (peaks, snr) where peaks is a list of (freq_hz, magnitude) tuples
        sorted by magnitude descending — peaks[0] is the strongest Larmor
        frequency candidate — and snr is the linear peak/noise-floor power
        ratio of the strongest peak in the averaged periodogram (NaN if no
        peaks were found).
    """
    averaged_den = None   # accumulates sum of periodograms; divided at the end
    f_axis = None         # frequency axis (same for all runs at the same rate)
    n_runs = len(runs_data)

    # Plot title: explicit --title if given, otherwise the run directory name
    # (<tag>_<timestamp>), which identifies the measurement at a glance.
    plot_title = getattr(args, "title", None) or os.path.basename(
        run_dir.rstrip("/"))

    vprint("\nAnalysis pipeline ({} run{})".format(n_runs, "s" if n_runs > 1 else ""), verbose)

    for i, (sample_rate, sample_time, signal_data) in enumerate(runs_data):
        vprint("  [{}] Normalising signal ({} samples at {} Hz)...".format(
            i, len(signal_data), sample_rate), verbose)
        calc = PPMCalc.PPMCalc(sample_rate, sample_time, signal_data)

        if not args.no_plots:
            path = os.path.join(run_dir, "original_{:02d}.png".format(i))
            vprint("  [{}] Saving raw signal plot → {}".format(i, path), verbose)
            calc.plotSignal(path, title="{} — raw, run {}".format(plot_title, i))

        vprint("  [{}] Applying Butterworth bandpass filter "
               "{:.0f}–{:.0f} Hz...".format(i, args.low_freq, args.high_freq), verbose)
        calc.filterSignal(args.low_freq, args.high_freq)

        if not args.no_plots:
            path = os.path.join(run_dir, "filtered_{:02d}.png".format(i))
            vprint("  [{}] Saving filtered signal plot → {}".format(i, path), verbose)
            calc.plotSignal(
                path, title="{} — filtered, run {}".format(plot_title, i))

        # Compute periodogram on the filtered signal.  The frequency resolution
        # is sample_rate / num_samples ≈ 1 Hz for a 16000-sample, 1-second record.
        # The Hann window suppresses spectral leakage from the record edges.
        freq_resolution = sample_rate / len(signal_data)
        vprint("  [{}] Computing periodogram (frequency resolution {:.2f} Hz "
               "≈ {:.1f} nT)...".format(i, freq_resolution,
               freq_resolution / GAMMA_HZ_PER_UT * 1000), verbose)
        f, den = sig.periodogram(calc._signal_data, calc._sample_rate,
                                 window='hann')

        # Per-run SNR: strongest bin inside the filter passband against the
        # median noise floor in the sidebands around it.  A run whose SNR is
        # near 1 (0 dB) contains no detectable precession signal.
        band_idx = np.where((f >= args.low_freq) & (f <= args.high_freq))[0]
        if band_idx.size:
            run_peak_idx = band_idx[np.argmax(den[band_idx])]
            run_snr = PPMCalc.estimate_snr(f, den, f[run_peak_idx])
            run_snr_db = (10 * np.log10(run_snr)
                          if np.isfinite(run_snr) and run_snr > 0
                          else float('nan'))
            snr_msg = ("Run {} SNR: {:.1f} dB (strongest in-band bin at "
                       "{:.1f} Hz)".format(i, run_snr_db, f[run_peak_idx]))
            vprint("  [{}] {}".format(i, snr_msg), verbose)
            if logger:
                logger.info(snr_msg)

        if averaged_den is None:
            averaged_den = den.copy()
            f_axis = f
        else:
            averaged_den += den

    # Divide by run count to get the true average (not just the sum).
    averaged_den /= n_runs
    if n_runs > 1:
        vprint("  Averaged {} periodograms (SNR improvement ≈ {:.1f}×)".format(
            n_runs, n_runs ** 0.5), verbose)

    # ── Background subtraction ────────────────────────────────────────────────
    # Keep the unsubtracted spectrum: SNR is always measured against the raw
    # noise floor (see docstring).
    raw_den = averaged_den
    background_subtracted = False
    if background_data:
        bg_f, bg_den = background_periodogram(background_data, args, verbose)
        averaged_den, scale = subtract_background(
            f_axis, averaged_den, bg_f, bg_den, args.low_freq, args.high_freq)
        if scale is not None:
            background_subtracted = True
            msg = ("Background subtraction applied: {} record{}, "
                   "noise-floor scale factor {:.3f}".format(
                       len(background_data),
                       "s" if len(background_data) != 1 else "", scale))
            vprint("  " + msg, verbose)
            if logger:
                logger.info(msg)

    # ── Peak detection ────────────────────────────────────────────────────────
    # Run before plotting so the detected peaks can be labelled on the figure.
    # find_peaks works on the full periodogram array, not just the plotted
    # window, to avoid missing a peak near the edge of the display range.
    # Each detected peak is refined to sub-bin precision by parabolic
    # interpolation before sorting.
    vprint("  Running peak detection (threshold={})...".format(
        args.fft_threshold), verbose)
    peaks_idx, _ = sig.find_peaks(averaged_den, height=args.fft_threshold)
    peaks = sorted([PPMCalc.interpolate_peak(f_axis, averaged_den, p)
                    for p in peaks_idx], key=lambda x: -x[1])
    vprint("  Found {} peak{} above threshold".format(
        len(peaks), "s" if len(peaks) != 1 else ""), verbose)

    # ── Plot the averaged FFT ─────────────────────────────────────────────────
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fft_path = os.path.join(run_dir, "fft_averaged.png")
    vprint("  Saving averaged FFT plot → {}".format(fft_path), verbose)
    # Scale Y axis to the tallest peak in the region of interest so the plot
    # is readable even when the absolute power is low.
    freq_mask = (f_axis >= args.low_freq) & (f_axis <= args.high_freq)
    y_max = np.max(averaged_den[freq_mask]) * 1.3 if freq_mask.any() else 0.01
    fig, ax = plt.subplots(figsize=(16, 6), dpi=80)
    ax.bar(f_axis, averaged_den, width=(f_axis[1] - f_axis[0]))
    ax.set_ylim([0, y_max])
    ax.set_xlim([args.low_freq, args.high_freq])
    ax.set_title(plot_title)

    # Label detected peaks inside the visible window with their frequency and
    # the implied field (B = f / γ).  The strongest peak also shows the field
    # value; the rest are frequency-only to limit clutter.  Peaks within
    # LABEL_MIN_SEP_HZ of an already-labelled (stronger) peak are skipped so the
    # spectral-leakage skirt around a strong line does not smear overlapping
    # labels together; genuinely distinct peaks (e.g. interference spurs) are
    # still labelled.  Capped at eight overall.
    LABEL_MIN_SEP_HZ = 40.0
    labelled_freqs = []
    for rank, (f_pk, mag) in enumerate(peaks):
        if rank >= 8 or not (args.low_freq <= f_pk <= args.high_freq):
            continue
        if any(abs(f_pk - lf) < LABEL_MIN_SEP_HZ for lf in labelled_freqs):
            continue
        if not labelled_freqs:   # the strongest labelled peak
            text = "{:.1f} Hz\n{:.2f} µT".format(f_pk, f_pk / GAMMA_HZ_PER_UT)
        else:
            text = "{:.1f} Hz".format(f_pk)
        labelled_freqs.append(f_pk)
        ax.annotate(text, xy=(f_pk, mag), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=8, color="red",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="red"))

    ax.set_xlabel("Frequency (Hz)")
    ylabel = "Power spectral density (averaged over {} run{}{})".format(
        n_runs, "s" if n_runs > 1 else "",
        ", background-subtracted" if background_subtracted else "")
    ax.set_ylabel(ylabel)
    fig.savefig(fft_path)
    plt.close(fig)

    # SNR of the strongest peak — the headline quality figure for the whole
    # measurement session.  Measured against the unsubtracted spectrum so the
    # noise floor is the real one, even when background subtraction located
    # the peak.
    snr = PPMCalc.estimate_snr(f_axis, raw_den, peaks[0][0]) \
        if peaks else float('nan')
    return peaks, snr


def report_peaks(peaks, logger, snr=None):
    """Print the strongest peak and compute the implied magnetic field strength.

    The Larmor relation gives:
        B [µT] = f [Hz] / γ_p     where γ_p = 42.5775 Hz/µT

    The frequency is reported to 0.01 Hz and the field to 1 nT because the
    peaks have been refined by parabolic interpolation — they are no longer
    quantised to the ~0.67 Hz (~16 nT) periodogram bin width.

    Secondary candidates above the detection threshold are also listed, which
    can help distinguish genuine signal from interference peaks.  If the
    strongest peak is not close to the expected Larmor frequency for the
    location, it is likely an interference peak rather than genuine precession.

    Args:
        peaks:  List of (freq_hz, magnitude) tuples from analyse().
        logger: Logger instance for recording the result.
        snr:    Optional linear peak/noise power ratio from analyse().
                Reported in dB alongside the field value.  SNR near 0 dB
                means the "peak" is indistinguishable from the noise floor.
    """
    if not peaks:
        msg = "No peaks found above threshold."
        print(msg)
        logger.info(msg)
        return

    best_freq, best_mag = peaks[0]
    # Convert from Hz to µT using the proton gyromagnetic ratio.
    field_ut = best_freq / GAMMA_HZ_PER_UT
    msg = "Strongest peak: {:.2f} Hz  →  B = {:.3f} µT".format(best_freq, field_ut)
    if snr is not None and np.isfinite(snr) and snr > 0:
        msg += "  (SNR {:.1f} dB)".format(10 * np.log10(snr))
    print(msg)
    logger.info(msg)

    if len(peaks) > 1:
        candidates = ", ".join(
            "{:.1f} Hz (mag={:.4f})".format(f, m) for f, m in peaks[1:])
        cand_msg = "Other candidates: " + candidates
        print(cand_msg)
        logger.info(cand_msg)


def main():
    """Parse arguments, set up the run directory, and execute the pipeline."""
    parser = build_parser()
    args = parser.parse_args()

    # --list-ports: scan and print available serial ports, then exit.
    if args.list_ports:
        import PPM
        try:
            ports = PPM.scan_ports()
        except ImportError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)
        if not ports:
            print("No serial ports found.")
        else:
            print("{:<20} {:<35} {}".format("Port", "Description", "Hardware ID"))
            print("-" * 80)
            for device, description, hwid in ports:
                print("{:<20} {:<35} {}".format(device, description, hwid))
        sys.exit(0)

    # Warn if the user specified both --input and --runs, since --runs is
    # meaningless when loading from a file (there is only one data set).
    if args.input and args.runs > 1:
        print("Warning: --runs is ignored when --input is specified.",
              file=sys.stderr)

    # Hardware background collection makes no sense in re-analysis mode, and
    # is redundant when a background file has been supplied explicitly.
    if args.background_runs > 0 and (args.input or args.background_input):
        print("Warning: --background-runs is ignored when --input or "
              "--background-input is specified.", file=sys.stderr)
        args.background_runs = 0

    run_dir = setup_run_dir(args.output_dir, args.tag)
    logger = setup_logger(run_dir)

    logger.info("**********************************")
    logger.info("Beginning PPM Run")
    logger.info("Output directory: {}".format(run_dir))
    vprint("Output directory: {}".format(run_dir), args.verbose)

    if args.input:
        logger.info("Reanalysis mode: loading {}".format(args.input))
        vprint("Reanalysis mode: loading {}".format(args.input), args.verbose)
        runs_data = load_input_file(args.input)
        background_data = []
    else:
        runs_data, background_data = collect_runs(
            args, run_dir, logger, verbose=args.verbose)

    if args.background_input:
        logger.info("Loading background from {}".format(args.background_input))
        vprint("Loading background from {}".format(args.background_input),
               args.verbose)
        background_data = load_input_file(args.background_input)

    peaks, snr = analyse(runs_data, args, run_dir, verbose=args.verbose,
                         logger=logger, background_data=background_data)
    report_peaks(peaks, logger, snr=snr)
    print("Output written to: {}".format(run_dir))


if __name__ == "__main__":
    main()
