"""
averaging_convergence.py — How many runs are worth averaging?

The pipeline averages power spectra across runs.  Because the FID phase is not
repeatable between quenches the averaging is *incoherent*, so the noise floor
smooths as √N and the detectability of a fixed-frequency line improves only
~5·log10(N) dB — fast diminishing returns.  Worse, averaging fights only the
*random* noise: a steady interferer (the tank resonance, a mains harmonic) is
present at full strength in every run and never averages away, so past some N
the result stops improving entirely.

This tool makes that concrete for a *real* run set.  It loads every run_*.dat in
a directory, locks onto the strongest in-band line of the full N-run average as
"the candidate", then replays the cumulative average over the first 1, 2, 3, …,
N runs and measures, at that fixed frequency:

- the candidate SNR (dB) vs number of runs averaged, against the ideal √N curve
  anchored at the single-run value.  Tracking the ideal line ⇒ you are
  random-noise-limited and more runs still help; flattening *below* it ⇒ you
  have hit an interference / systematic floor that more runs will not move.
- the noise-floor estimate vs N, against the ideal 1/√N curve — the same story
  from the noise side: still falling ⇒ keep averaging; flat ⇒ stop.

Read the knee off the plot: the run count where the SNR curve bends away from
the √N line is the point of diminishing returns for *your* noise.

Usage
-----
    python averaging_convergence.py data/SAMPLED150_..._11_06_10

    python averaging_convergence.py data/SOME_RUN \\
        --low-freq 2200 --high-freq 2600 --field 57198 \\
        --freq 2387 --out-dir data

Writes averaging_convergence.png to --out-dir (or the current directory).
Plotting uses the non-interactive Agg backend so it runs headlessly on the Pi.
"""

import argparse
import glob
import os

import numpy as np
import scipy.signal as sig
import matplotlib
matplotlib.use('Agg')   # non-interactive backend; must precede pyplot import
import matplotlib.pyplot as plt

from PPMCalc import PPMCalc, load_from_file, estimate_snr

GAMMA_HZ_PER_UT = 42.5775   # Hz per µT (see PPMCalc / ppmrun)


def build_parser():
    """Build and return the command-line argument parser."""
    p = argparse.ArgumentParser(
        description="Plot candidate-peak SNR and noise floor versus the number "
                    "of averaged runs, to find the point of diminishing returns.")
    p.add_argument("run_dir", metavar="RUN_DIR",
                   help="Directory of run_*.dat files (a single measurement "
                        "set) to study.")
    p.add_argument("--low-freq", type=float, default=2000.0, metavar="HZ",
                   help="Bandpass lower cutoff / candidate search edge "
                        "(default: 2000).")
    p.add_argument("--high-freq", type=float, default=4000.0, metavar="HZ",
                   help="Bandpass upper cutoff / candidate search edge "
                        "(default: 4000).")
    p.add_argument("--freq", type=float, default=None, metavar="HZ",
                   help="Track this exact candidate frequency instead of the "
                        "strongest line in the full-average spectrum.")
    p.add_argument("--field", type=float, default=None, metavar="NT",
                   help="Local field in nT, only used to annotate the implied "
                        "Larmor frequency for context (e.g. 57198).")
    p.add_argument("--out-dir", default=None, metavar="DIR",
                   help="Where to write averaging_convergence.png "
                        "(default: current directory).")
    return p


def load_periodograms(folder, low, high):
    """Return (ref_freq, list_of_psd) for every run, on a common frequency grid.

    Each run is processed through the same PPMCalc front end as the live
    pipeline (range normalise, DC removal, Butterworth bandpass) and turned into
    a Hann-windowed periodogram.  Runs can differ by a sample, so every PSD is
    interpolated onto the first run's frequency axis before being returned —
    this lets the caller average any subset by simple element-wise mean.

    Returns:
        (ref_freq, psds) where psds is a list of numpy arrays aligned to
        ref_freq, in run-file order.

    Raises:
        FileNotFoundError: if the directory contains no run_*.dat files.
    """
    files = sorted(glob.glob(os.path.join(folder, "run_*.dat")))
    if not files:
        raise FileNotFoundError(
            "No run_*.dat files found in {!r}".format(folder))
    ref_freq = None
    psds = []
    for fp in files:
        sample_rate, _, data = load_from_file(fp)
        calc = PPMCalc(sample_rate, 1500, data)
        calc.filterSignal(low, high)
        f, den = sig.periodogram(calc._signal_data, sample_rate, window='hann')
        if ref_freq is None:
            ref_freq = f
            psds.append(den)
        else:
            # Align to the first run's grid; np.interp needs ascending x (it is).
            psds.append(np.interp(ref_freq, f, den))
    return ref_freq, psds


def noise_floor(freq, den, peak_freq, inner=100.0, outer=300.0):
    """Median PSD in the ±inner–outer Hz sidebands around peak_freq."""
    offset = np.abs(freq - peak_freq)
    sideband = (offset >= inner) & (offset <= outer)
    return float(np.median(den[sideband])) if sideband.any() else float('nan')


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = args.out_dir or "."

    ref_freq, psds = load_periodograms(args.run_dir, args.low_freq,
                                       args.high_freq)
    n_runs = len(psds)
    full_avg = np.mean(psds, axis=0)

    # Lock onto the candidate frequency: an explicit --freq, else the strongest
    # in-band line of the full N-run average (the most stable estimate we have).
    band = (ref_freq >= args.low_freq) & (ref_freq <= args.high_freq)
    if args.freq is not None:
        target = args.freq
    else:
        target = ref_freq[band][np.argmax(full_avg[band])]

    # Replay the cumulative average over the first k runs and measure the
    # candidate at the fixed target frequency each time.
    counts = np.arange(1, n_runs + 1)
    snr_db = []
    floors = []
    for k in counts:
        avg_k = np.mean(psds[:k], axis=0)
        ratio = estimate_snr(ref_freq, avg_k, target)
        snr_db.append(10.0 * np.log10(ratio) if ratio and ratio > 0
                      else float('nan'))
        floors.append(noise_floor(ref_freq, avg_k, target))
    snr_db = np.array(snr_db)
    floors = np.array(floors)

    # Ideal references anchored at the single-run value.
    ideal_snr = snr_db[0] + 5.0 * np.log10(counts)      # +5·log10(N) dB
    ideal_floor = floors[0] / np.sqrt(counts)           # noise floor ∝ 1/√N

    larmor_note = ""
    if args.field is not None:
        larmor_note = "   (model Larmor {:.0f} Hz)".format(
            GAMMA_HZ_PER_UT * args.field / 1000.0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), dpi=90, sharex=True)

    ax1.plot(counts, snr_db, 'o-', color='C0', label="measured")
    ax1.plot(counts, ideal_snr, '--', color='0.5',
             label="ideal √N (+5·log₁₀N dB)")
    ax1.set_ylabel("Candidate SNR (dB)")
    ax1.set_title("Averaging convergence for {}\n"
                  "candidate {:.1f} Hz{}  —  curve bending below √N = "
                  "interference-limited".format(
                      os.path.basename(os.path.normpath(args.run_dir)),
                      target, larmor_note))
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(counts, floors, 's-', color='C1', label="measured floor")
    ax2.plot(counts, ideal_floor, '--', color='0.5', label="ideal 1/√N")
    ax2.set_xlabel("Number of runs averaged")
    ax2.set_ylabel("Noise-floor PSD (median, sidebands)")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path = os.path.join(out_dir, "averaging_convergence.png")
    fig.savefig(out_path)
    plt.close(fig)

    # Console summary: where does the SNR stop tracking the ideal?
    print("Run set: {} ({} runs)".format(args.run_dir, n_runs))
    print("Candidate frequency: {:.1f} Hz".format(target))
    print("  N   SNR(dB)  ideal(dB)  gap")
    for k, s, i in zip(counts, snr_db, ideal_snr):
        print("  {:<3d} {:6.1f}   {:6.1f}   {:+.1f}".format(k, s, i, s - i))
    print("Wrote: {}".format(out_path))


if __name__ == "__main__":
    main()
