"""
compare_runs.py — Overlay two PPM run sets to test for a genuine precession signal.

The single most diagnostic test for the Proton Precession Magnetometer is a
*differential* one: record the same way twice, changing only the one thing that
should switch the proton signal on or off (typically sample present vs absent,
or polarising pulse on vs off), then overlay the results.  A real Larmor signal
must satisfy two conditions that no interference line or resonance can fake:

1. It appears in the "signal" condition and *disappears* in the "reference"
   condition.  A spectral peak that is present in both at the same strength is
   environmental/electronic, not the protons — removing the sample cannot remove
   a coil/amplifier/mains artefact.

2. Its amplitude *decays* across the record with the spin-spin relaxation time
   constant T2 (~1-3 s for tap water).  A steady-amplitude line — e.g. a tuned
   tank ringing continuously on broadband noise, or a mains harmonic — does not
   decay.  Over a 1.5 s window a real signal's RMS envelope starts high and falls
   toward the noise floor; an artefact's envelope is flat.

This script reprocesses every run_*.dat file in each of two directories through
the *same* PPMCalc pipeline (normalise → Butterworth bandpass → Hann-windowed
periodogram), averages across the runs in each set, and writes two overlay plots:

- compare_spectrum.png — averaged power spectral density, both sets overlaid,
  with the expected Larmor frequency marked.  Look for a peak that rises in the
  signal set but not the reference set, at the expected frequency.
- compare_envelope.png — filtered RMS amplitude vs time into the record, both
  sets overlaid.  Look for the signal set starting above the reference set and
  decaying toward it.  Overlapping flat traces mean no precession is present.

Frequency-domain averaging (rather than averaging raw time-domain signals) is
used because the precession phase is not repeatable between runs — only the
power spectrum is.  This matches pprun.py's multi-run averaging and improves SNR
by roughly √N.

Usage
-----
    python compare_runs.py data/SAMPLE_WIDE_... data/NO_SAMPLE_WIDE_...

    python compare_runs.py data/with_sample data/no_sample \\
        --labels "With sample" "No sample" \\
        --low-freq 2000 --high-freq 4000 \\
        --field 57198 --out-dir data

The plotting uses the non-interactive Agg backend so it runs headlessly on the
Raspberry Pi without a display.
"""

import argparse
import glob
import os

import numpy as np
import scipy.signal as sig
import matplotlib
matplotlib.use('Agg')   # non-interactive backend; must precede pyplot import
import matplotlib.pyplot as plt

from PPMCalc import PPMCalc, load_from_file

# Proton gyromagnetic ratio in Hz per microtesla (f = γ_p/2π · B, see PPMCalc).
# B = 57198 nT (this site) → 2435 Hz.
GAMMA_HZ_PER_UT = 42.5775


def build_parser():
    """Build and return the command-line argument parser."""
    p = argparse.ArgumentParser(
        description="Overlay two PPM run sets (e.g. sample vs no-sample) to "
                    "test for a real, decaying precession signal.")
    p.add_argument("signal_dir", metavar="SIGNAL_DIR",
                   help="Directory of run_*.dat files for the 'signal' "
                        "condition (e.g. sample present, polarising on).")
    p.add_argument("reference_dir", metavar="REFERENCE_DIR",
                   help="Directory of run_*.dat files for the 'reference' "
                        "condition (e.g. no sample, polarising off).")
    p.add_argument("--labels", nargs=2, metavar=("SIG", "REF"),
                   default=None,
                   help="Legend labels for the two sets "
                        "(default: derived from directory names).")
    p.add_argument("--low-freq", type=float, default=2000.0, metavar="HZ",
                   help="Bandpass lower cutoff / spectrum left edge in Hz "
                        "(default: 2000).")
    p.add_argument("--high-freq", type=float, default=4000.0, metavar="HZ",
                   help="Bandpass upper cutoff / spectrum right edge in Hz "
                        "(default: 4000).")
    p.add_argument("--field", type=float, default=None, metavar="NT",
                   help="Local field in nT, to mark the expected Larmor "
                        "frequency on the spectrum plot (e.g. 57198).")
    p.add_argument("--env-window", type=int, default=600, metavar="SAMPLES",
                   help="RMS block size for the envelope plot in samples "
                        "(default: 600, ~37 ms at 16 kHz).")
    p.add_argument("--out-dir", default=None, metavar="DIR",
                   help="Where to write compare_spectrum.png / "
                        "compare_envelope.png (default: current directory).")
    return p


def load_filtered(folder, low, high):
    """Load and bandpass-filter every run_*.dat in a directory.

    Each file is run through the full PPMCalc front end (range normalisation,
    DC removal, Butterworth bandpass) so the two sets are processed identically
    to the live pipeline and to each other.

    Args:
        folder: Directory containing run_*.dat files.
        low:    Bandpass lower -3 dB cutoff in Hz.
        high:   Bandpass upper -3 dB cutoff in Hz.

    Returns:
        List of (sample_rate, filtered_signal) tuples, one per run file.

    Raises:
        FileNotFoundError: if the directory contains no run_*.dat files.
    """
    files = sorted(glob.glob(os.path.join(folder, "run_*.dat")))
    if not files:
        raise FileNotFoundError(
            "No run_*.dat files found in {!r}".format(folder))
    runs = []
    for fp in files:
        sample_rate, _, data = load_from_file(fp)
        calc = PPMCalc(sample_rate, 1500, data)
        calc.filterSignal(low, high)
        # Reach past the public API for the filtered samples; this is an
        # offline analysis tool tightly coupled to PPMCalc internals.
        runs.append((sample_rate, calc._signal_data))
    return runs


def averaged_spectrum(runs):
    """Average Hann-windowed periodograms across a set of runs.

    Phase is not repeatable between polarise-wait-sample cycles, so we average
    power spectra (phase-insensitive) rather than raw waveforms.  The noise
    floor falls by ~√N relative to a single run while a coherent line stays put.

    Args:
        runs: List of (sample_rate, signal) tuples from load_filtered().

    Returns:
        (freq_axis, averaged_psd) numpy arrays.
    """
    accum = None
    for sample_rate, signal in runs:
        f, den = sig.periodogram(signal, sample_rate, window='hann')
        accum = den if accum is None else accum + den
    return f, accum / len(runs)


def averaged_envelope(runs, window):
    """Average the filtered-RMS amplitude envelope across a set of runs.

    Splits each run into non-overlapping blocks of `window` samples and takes
    the RMS of each block, giving amplitude vs time.  Averaging the per-run
    envelopes smooths block-to-block noise while preserving any genuine T2
    decay (which sits at the same time offset in every run, measured from the
    end of the polarising pulse).

    Args:
        runs:   List of (sample_rate, signal) tuples from load_filtered().
        window: Block size in samples.

    Returns:
        (time_axis_s, averaged_rms) numpy arrays.  The time axis is taken from
        the last run processed; all runs share the same length and rate.
    """
    per_run = []
    times = None
    for sample_rate, signal in runs:
        n_blocks = len(signal) // window
        blocks = signal[:n_blocks * window].reshape(n_blocks, window)
        per_run.append(np.sqrt(np.mean(blocks ** 2, axis=1)))
        times = (np.arange(n_blocks) + 0.5) * window / sample_rate
    return times, np.mean(per_run, axis=0)


def main(argv=None):
    args = build_parser().parse_args(argv)

    sig_label, ref_label = args.labels or (
        os.path.basename(os.path.normpath(args.signal_dir)),
        os.path.basename(os.path.normpath(args.reference_dir)))
    out_dir = args.out_dir or "."

    sig_runs = load_filtered(args.signal_dir, args.low_freq, args.high_freq)
    ref_runs = load_filtered(args.reference_dir, args.low_freq, args.high_freq)

    # ── Spectrum overlay ────────────────────────────────────────────────────
    fs, ds = averaged_spectrum(sig_runs)
    fr, dr = averaged_spectrum(ref_runs)
    mask = (fs >= args.low_freq) & (fs <= args.high_freq)

    fig, ax = plt.subplots(figsize=(14, 6), dpi=90)
    ax.plot(fs[mask], ds[mask], lw=1.1, color='C0',
            label="{} (n={})".format(sig_label, len(sig_runs)))
    ax.plot(fr[mask], dr[mask], lw=1.1, color='C3', alpha=0.8,
            label="{} (n={})".format(ref_label, len(ref_runs)))
    if args.field is not None:
        f_larmor = GAMMA_HZ_PER_UT * args.field / 1000.0  # nT → µT → Hz
        ax.axvline(f_larmor, color='k', ls='--', lw=1,
                   label="Expected Larmor {:.0f} Hz".format(f_larmor))
    ax.set_xlim(args.low_freq, args.high_freq)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Averaged power spectral density")
    ax.set_title("Averaged spectrum: {} vs {}\n"
                 "A real Larmor peak rises in one set only, at the marked "
                 "frequency".format(sig_label, ref_label))
    ax.legend()
    fig.tight_layout()
    spec_path = os.path.join(out_dir, "compare_spectrum.png")
    fig.savefig(spec_path)
    plt.close(fig)

    # ── Envelope overlay ────────────────────────────────────────────────────
    ts, es = averaged_envelope(sig_runs, args.env_window)
    tr, er = averaged_envelope(ref_runs, args.env_window)

    fig, ax = plt.subplots(figsize=(14, 6), dpi=90)
    ax.plot(ts * 1000.0, es, 'o-', ms=4, color='C0',
            label="{} (n={})".format(sig_label, len(sig_runs)))
    ax.plot(tr * 1000.0, er, 's-', ms=4, color='C3', alpha=0.8,
            label="{} (n={})".format(ref_label, len(ref_runs)))
    ax.set_ylim(0, max(es.max(), er.max()) * 1.25)
    ax.set_xlabel("Time into record (ms)")
    ax.set_ylabel("Filtered RMS amplitude")
    ax.set_title("Amplitude envelope: {} vs {}\n"
                 "A real signal starts above the reference and decays (T2); "
                 "flat overlapping traces = steady interference".format(
                     sig_label, ref_label))
    ax.legend()
    fig.tight_layout()
    env_path = os.path.join(out_dir, "compare_envelope.png")
    fig.savefig(env_path)
    plt.close(fig)

    # ── Console summary ─────────────────────────────────────────────────────
    sig_peak = fs[mask][np.argmax(ds[mask])]
    ref_peak = fr[mask][np.argmax(dr[mask])]
    print("Signal set    : {:2d} runs, peak {:7.1f} Hz, start/end RMS {:.2f}".format(
        len(sig_runs), sig_peak, es[0] / es[-1]))
    print("Reference set : {:2d} runs, peak {:7.1f} Hz, start/end RMS {:.2f}".format(
        len(ref_runs), ref_peak, er[0] / er[-1]))
    print("Wrote:\n  {}\n  {}".format(spec_path, env_path))


if __name__ == "__main__":
    main()
