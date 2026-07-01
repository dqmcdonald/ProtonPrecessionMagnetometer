"""
comb_notch.py — Strip the 50 Hz mains-harmonic comb from PPM records so the
inter-harmonic gaps (where a real Larmor line can live) can be inspected cleanly.

Motivation
----------
Once conducted mains was removed by battery-powering the whole rig, the pickup
that remains is *radiated*: the sensor coil is an antenna for the building's
50 Hz magnetic field, so every strong line in a record sits on an exact multiple
of the mains frequency.  In the 2200-2600 Hz search band that is the 45th-51st
harmonics — 2250 / 2300 / 2350 / 2400 / 2450 / 2500 / 2550 Hz — and the raw
spectrum is a clean picket fence of them.

Crucially the proton Larmor frequency need NOT land on a harmonic.  For the local
model field (57198 nT) it is

    f_L = gamma/2pi * B = 42.5775 Hz/uT * 57.198 uT = 2435 Hz,

which falls in the ~50 Hz GAP between the 48th (2400 Hz) and 49th (2450 Hz)
harmonics.  So a narrow notch at every harmonic removes the interference while
leaving that gap — and any signal in it — untouched.  This tool builds exactly
that comb of notches and shows what, if anything, survives in the gap.

How it works
------------
For every mains harmonic k*f_mains inside the analysis band we apply a
second-order IIR notch (scipy.signal.iirnotch) with a fixed half-power width
``--notch-bw`` Hz, run zero-phase (filtfilt) so no causal start-up transient can
masquerade as a decaying head.  Each notch's quality factor is Q = f0 / bw, so
the notches get proportionally narrower at higher harmonics and the fixed-Hz
width keeps a constant guard band around the Larmor gap regardless of harmonic
number.

Two independent tests are then reported, the same pair that has ruled out every
candidate on this rig so far:

1. Spectrum (plot + console): after notching, is there a peak in the Larmor gap
   standing above the in-gap noise floor?  A few dB is just noise; a real line
   would tower like the harmonics did before notching.

2. Envelope decay (console): bandpass the notched signal to the gap, take the
   analytic-signal RMS envelope, and compare the first quarter of the record to
   the last.  A genuine free-induction decay falls with T2* (~1-3 s for water)
   so the ratio should exceed ~1.3; a steady residual sits at ~1.0.  If a
   ``--reference`` (matched no-sample) set is given, a real signal makes the
   sample gap-power rise above the reference — equal power means nothing to find.

Assumptions and limits
-----------------------
This tool *removes* mains and exposes the gap — it does not manufacture a signal.
If the notched gap is empty and shows no sample-vs-reference excess, the mains was
not masking a buried FID; at this sensitivity there simply is no detectable
proton line in-band, and the lever to pull is upstream hardware (more precessing
magnetisation / better coil coupling — e.g. an azimuth+tilt polarising-coil sweep
so its axis is truly perpendicular to the *local* field).  The notch is worth
keeping regardless: it makes the band clean for the day a real line appears.

Note the mains frequency is a build-site property — pass ``--mains 60`` on a
60 Hz grid.  A drifting mains would smear the harmonics off the fixed notch
centres; grid frequency is stable to well under the notch width, so fixed-centre
notches are fine here.

Usage
-----
    python comb_notch.py data/BATT_SAMP_NS2_...

    python comb_notch.py data/BATT_SAMP_EW_... \\
        --reference data/BATT_NOSAMP_EW_... \\
        --mains 50 --notch-bw 12 --field 57198 \\
        --search-low 2200 --search-high 2600 --out-dir data

Outputs (PNG, written to --out-dir):
    comb_notch_spectrum.png — averaged spectrum before vs after the comb-notch,
                              with the mains harmonics, the Larmor gap, and any
                              reference overlaid.

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

from PPMCalc import load_from_file

# Proton gyromagnetic ratio in Hz per microtesla (see PPMCalc / ppmrun).
GAMMA_HZ_PER_UT = 42.5775


def build_parser():
    """Build and return the command-line argument parser."""
    p = argparse.ArgumentParser(
        description="Notch out the 50 Hz mains-harmonic comb from PPM records "
                    "and check whether any line survives in the inter-harmonic "
                    "gap where the Larmor frequency sits.")
    p.add_argument("signal_dir", metavar="SIGNAL_DIR",
                   help="Directory of run_*.dat files to clean.")
    p.add_argument("--reference", metavar="DIR", default=None,
                   help="Optional matched no-sample run set to overlay — the "
                        "sample gap should exceed this if a real signal exists.")
    p.add_argument("--mains", type=float, default=50.0, metavar="HZ",
                   help="Mains frequency; harmonics of this are notched "
                        "(default: 50; use 60 on a 60 Hz grid).")
    p.add_argument("--notch-bw", type=float, default=12.0, metavar="HZ",
                   help="Half-power width of each notch in Hz; keep it well below "
                        "the harmonic spacing so the Larmor gap is preserved "
                        "(default: 12).")
    p.add_argument("--search-low", type=float, default=2200.0, metavar="HZ",
                   help="Lower bound of the analysis/plot band (default: 2200).")
    p.add_argument("--search-high", type=float, default=2600.0, metavar="HZ",
                   help="Upper bound of the analysis/plot band (default: 2600).")
    p.add_argument("--field", type=float, default=57198.0, metavar="NT",
                   help="Local field in nT; sets the expected Larmor frequency "
                        "and the gap that is inspected (default: 57198).")
    p.add_argument("--out-dir", default=None, metavar="DIR",
                   help="Where to write the PNG plot (default: current dir).")
    return p


def comb_notch(data, fs, mains, bw, lo, hi):
    """Zero-phase IIR notch at every mains harmonic inside the analysis band.

    Only harmonics within [lo - 2*mains, hi + 2*mains] are notched: those are the
    ones that shape the band and its guard region, which keeps the filter fast
    without leaving a skirt from a just-out-of-band harmonic.  DC is removed
    first so the notches operate on the AC pickup alone.

    Returns:
        The DC-removed, comb-notched signal as a float array.
    """
    y = data.astype(float)
    y = y - y.mean()
    nyq = fs / 2.0
    k_lo = max(1, int(np.floor((lo - 2 * mains) / mains)))
    k_hi = int(np.ceil((hi + 2 * mains) / mains))
    for k in range(k_lo, k_hi + 1):
        f0 = k * mains
        if f0 >= nyq:
            break
        # Fixed-Hz width -> Q grows with harmonic number, so the -3 dB skirts
        # stay a constant number of Hz wide and the Larmor gap is protected.
        b, a = sig.iirnotch(f0 / nyq, f0 / bw)
        y = sig.filtfilt(b, a, y)
    return y


def larmor_gap(f_larmor, mains):
    """Return (lo, hi) of the inter-harmonic gap straddling the Larmor line.

    The gap runs from the harmonic just below f_larmor to the one just above,
    inset by a quarter-harmonic on each side so the notch skirts are excluded and
    only genuinely clean spectrum is inspected.
    """
    k_below = np.floor(f_larmor / mains)
    lo = k_below * mains
    hi = (k_below + 1) * mains
    inset = mains * 0.25
    return lo + inset, hi - inset


def avg_periodogram(records, fs_list):
    """Average Hann-windowed periodograms across a set of records."""
    accum = None
    f = None
    for x, fs in zip(records, fs_list):
        f, den = sig.periodogram(x, fs, window='hann')
        accum = den if accum is None else accum + den
    return f, accum / len(records)


def gap_power(records, fs_list, lo, hi):
    """Integrated PSD inside the gap [lo, hi], averaged across records."""
    vals = []
    for x, fs in zip(records, fs_list):
        f, den = sig.periodogram(x, fs, window='hann')
        band = (f >= lo) & (f <= hi)
        vals.append(np.trapz(den[band], f[band]))
    return float(np.mean(vals))


def gap_decay_ratio(records, fs_list, lo, hi, win=800):
    """Mean first-quarter / last-quarter envelope ratio inside the gap.

    Bandpasses each record to the gap, takes the analytic-signal RMS envelope in
    fixed windows, and returns the average ratio of the first quarter of the
    record to the last.  Zero-phase filtering (filtfilt) is used so there is no
    causal transient to fake a decaying head.  A free-induction decay gives a
    ratio well above 1; a steady residual gives ~1.
    """
    ratios = []
    for x, fs in zip(records, fs_list):
        b, a = sig.butter(4, [lo, hi], fs=fs, btype='band')
        y = sig.filtfilt(b, a, x)
        env = np.abs(sig.hilbert(y))
        nb = len(env) // win
        rms = np.sqrt(np.mean(env[:nb * win].reshape(nb, win) ** 2, axis=1))
        q = max(1, nb // 4)
        ratios.append(rms[:q].mean() / rms[-q:].mean())
    return float(np.mean(ratios)), float(np.min(ratios)), float(np.max(ratios))


def load_dir(folder):
    """Load every run_*.dat in a directory as (raw_int_array, sample_rate) pairs."""
    files = sorted(glob.glob(os.path.join(folder, "run_*.dat")))
    if not files:
        raise FileNotFoundError("No run_*.dat files found in {!r}".format(folder))
    out = []
    for fp in files:
        fs, _, data = load_from_file(fp)
        out.append((data, fs))
    return out


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = args.out_dir or "."

    f_larmor = GAMMA_HZ_PER_UT * args.field / 1000.0   # nT -> uT -> Hz
    gap_lo, gap_hi = larmor_gap(f_larmor, args.mains)

    sig_raw = load_dir(args.signal_dir)
    fs_list = [fs for _, fs in sig_raw]

    # DC-removed original vs comb-notched, per run.
    orig = [d.astype(float) - d.astype(float).mean() for d, _ in sig_raw]
    notched = [comb_notch(d, fs, args.mains, args.notch_bw,
                          args.search_low, args.search_high)
               for (d, fs) in sig_raw]

    f_o, d_o = avg_periodogram(orig, fs_list)
    f_n, d_n = avg_periodogram(notched, fs_list)

    # ── Spectrum: before vs after the comb-notch ────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 6), dpi=90)
    mask = (f_o >= args.search_low) & (f_o <= args.search_high)
    ax.semilogy(f_o[mask], d_o[mask], lw=1.0, color='0.6',
                label="Before (mains comb)")
    ax.semilogy(f_n[mask], d_n[mask], lw=1.1, color='C0',
                label="After {:.0f} Hz comb-notch".format(args.mains))
    if args.reference:
        ref_raw = load_dir(args.reference)
        ref_notched = [comb_notch(d, fs, args.mains, args.notch_bw,
                                  args.search_low, args.search_high)
                       for (d, fs) in ref_raw]
        f_r, d_r = avg_periodogram(ref_notched, [fs for _, fs in ref_raw])
        mr = (f_r >= args.search_low) & (f_r <= args.search_high)
        ax.semilogy(f_r[mr], d_r[mr], lw=1.0, color='C3', alpha=0.7,
                    label="Reference, notched (no sample)")
    # Mark every mains harmonic in view, plus the Larmor line and its gap.
    k_lo = int(np.ceil(args.search_low / args.mains))
    k_hi = int(np.floor(args.search_high / args.mains))
    for k in range(k_lo, k_hi + 1):
        ax.axvline(k * args.mains, color='r', ls=':', lw=0.5)
    ax.axvspan(gap_lo, gap_hi, color='g', alpha=0.15,
               label="Larmor gap ({:.0f}-{:.0f} Hz)".format(gap_lo, gap_hi))
    ax.axvline(f_larmor, color='g', lw=1.2,
               label="Expected Larmor {:.0f} Hz".format(f_larmor))
    ax.set_xlim(args.search_low, args.search_high)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Averaged power spectral density")
    ax.set_title("Comb-notch: spectrum before vs after\n"
                 "A peak surviving in the green Larmor gap is the candidate "
                 "signal; a flat floor there means nothing to find")
    ax.legend()
    fig.tight_layout()
    spec_path = os.path.join(out_dir, "comb_notch_spectrum.png")
    fig.savefig(spec_path)
    plt.close(fig)

    # ── Console summary: is there anything in the gap? ──────────────────────
    band = (f_n >= gap_lo) & (f_n <= gap_hi)
    peak_i = np.where(band)[0][np.argmax(d_n[band])]
    peak_f = f_n[peak_i]
    gap_db = 10.0 * np.log10(d_n[peak_i] / np.median(d_n[band]))
    r_mean, r_min, r_max = gap_decay_ratio(notched, fs_list, gap_lo, gap_hi)
    sig_gp = gap_power(notched, fs_list, gap_lo, gap_hi)

    print("Notched {} run(s); mains {:.0f} Hz, notch width {:.0f} Hz.".format(
        len(sig_raw), args.mains, args.notch_bw))
    print("Larmor {:.0f} Hz sits in gap {:.0f}-{:.0f} Hz.".format(
        f_larmor, gap_lo, gap_hi))
    print("Gap after notch: strongest bin {:.1f} Hz at {:.1f} dB over in-gap "
          "median (a few dB = noise, not a line).".format(peak_f, gap_db))
    print("Gap envelope first/last-quarter ratio: mean {:.2f} "
          "(range {:.2f}-{:.2f}); >1.3 would indicate an FID.".format(
              r_mean, r_min, r_max))
    if args.reference:
        ref_gp = gap_power(ref_notched, [fs for _, fs in ref_raw], gap_lo, gap_hi)
        print("Gap power sample {:.3g} vs reference {:.3g} "
              "({:+.0f}%); a real signal makes sample exceed reference.".format(
                  sig_gp, ref_gp, 100.0 * (sig_gp - ref_gp) / ref_gp))
    print("Wrote:\n  {}".format(spec_path))


if __name__ == "__main__":
    main()
