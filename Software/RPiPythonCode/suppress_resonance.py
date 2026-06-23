"""
suppress_resonance.py — Peel a steady resonance line off a PPM record to expose
any decaying precession signal hiding underneath it.

Motivation
----------
The pickup tank (and the amplifier around it) forms a high-Q resonator.  Excited
continuously by ambient and microphonic noise it rings at its resonant frequency
with *roughly constant* amplitude for the whole record — it does not decay.  A
genuine proton precession signal, by contrast, decays exponentially with the
spin-spin relaxation time constant T2 (~1-3 s for tap water):

    s(t) = A · exp(-t / T2) · cos(2π f_L t + φ)

That difference in time behaviour is the lever this tool uses.  Because the
proton signal has died away by the *end* of the record, the tail is dominated by
the steady resonance.  So we:

1. Estimate the steady line's frequency from the tail spectrum (where the proton
   contribution is smallest).
2. Least-squares fit a *constant-amplitude* sinusoid (in-phase + quadrature) to
   the tail at that frequency, recovering its amplitude and phase against a
   global time origin.
3. Extrapolate that constant-amplitude sinusoid back across the *whole* record
   and subtract it.

Whatever the tail-fit cannot explain stays behind: broadband noise, plus — if it
exists — the decaying precession head in the first few hundred milliseconds.
Repeating the peel for the next-strongest tail line (``--n-components``) removes
several steady tones (e.g. the 2380 / 2650 / 3050 Hz family seen in this rig).

Assumptions and limits
-----------------------
The subtraction is exact only for a *coherent* steady line — one whose phase is
continuous across the record (a true ringing resonance or a coherent interferer
such as a mains harmonic).  A purely noise-excited resonance has a slowly
wandering phase, so a single tail-fitted sinusoid cancels only its coherent part;
the narrowband-noise pedestal is reduced, not erased.  This tool therefore
*suppresses* the line and improves contrast — it does not manufacture a signal.
If the residual head shows no excess over a matched no-sample recording, there is
no precession signal to find (yet), and the lever to pull is hardware: retune the
tank onto the true Larmor frequency so it amplifies the protons instead of
attenuating them.

Once the tank is retuned so the resonance and the Larmor line coincide, a notch
filter would kill both — this decay-based peel is then the *only* way to separate
them, which is the situation this script is built for.

Usage
-----
    python suppress_resonance.py data/SAMPLE_WIDE_...

    python suppress_resonance.py data/SAMPLE_WIDE_... \\
        --reference data/NO_SAMPLE_WIDE_... \\
        --field 57198 --n-components 3 --tail-frac 0.4 \\
        --out-dir data

Outputs (PNG, written to --out-dir):
    suppress_spectrum.png — averaged spectrum before vs after the peel, with the
                            expected Larmor frequency and any reference overlaid.
    suppress_envelope.png — filtered RMS envelope of the residual; a decaying
                            head that rises above the reference is a candidate
                            precession signal.

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

from PPMCalc import load_from_file, interpolate_peak

# Proton gyromagnetic ratio in Hz per microtesla (see PPMCalc / ppmrun).
GAMMA_HZ_PER_UT = 42.5775


def build_parser():
    """Build and return the command-line argument parser."""
    p = argparse.ArgumentParser(
        description="Subtract the steady tank/amp resonance from PPM records by "
                    "fitting it on the (proton-free) tail, exposing any "
                    "decaying precession signal underneath.")
    p.add_argument("signal_dir", metavar="SIGNAL_DIR",
                   help="Directory of run_*.dat files to clean.")
    p.add_argument("--reference", metavar="DIR", default=None,
                   help="Optional matched no-sample (or polarise-off) run set "
                        "to overlay for comparison — the residual head should "
                        "exceed this if a real signal is present.")
    p.add_argument("--n-components", type=int, default=1, metavar="K",
                   help="Number of steady tones to peel off, strongest first "
                        "(default: 1).")
    p.add_argument("--tail-frac", type=float, default=0.4, metavar="F",
                   help="Fraction of the record (from the end) used to fit the "
                        "steady line, where the proton signal has decayed away "
                        "(default: 0.4).")
    p.add_argument("--search-low", type=float, default=2000.0, metavar="HZ",
                   help="Lower bound when searching the tail for steady lines "
                        "(default: 2000).")
    p.add_argument("--search-high", type=float, default=4000.0, metavar="HZ",
                   help="Upper bound when searching the tail for steady lines "
                        "(default: 4000).")
    p.add_argument("--env-band", type=float, nargs=2, default=None,
                   metavar=("LO", "HI"),
                   help="Bandpass (Hz) for the residual envelope plot.  Default: "
                        "a +/-40 Hz window around the expected Larmor frequency "
                        "if --field is given, else the full search band.")
    p.add_argument("--field", type=float, default=None, metavar="NT",
                   help="Local field in nT, to mark the expected Larmor "
                        "frequency and centre the envelope band (e.g. 57198).")
    p.add_argument("--out-dir", default=None, metavar="DIR",
                   help="Where to write the PNG plots (default: current dir).")
    return p


def normalise(data):
    """Range-normalise to [-0.5, 0.5] and remove DC, matching PPMCalc.

    Done here directly (rather than via PPMCalc) so the residual is returned as
    a plain array we can fit and subtract sinusoids from without the bandpass
    filtering PPMCalc applies in place.
    """
    x = data.astype(float)
    span = x.max() - x.min()
    x = (x - x.min()) / span
    return x - x.mean()


def estimate_line_freq(x, fs, lo, hi):
    """Find the strongest spectral line of x within [lo, hi] Hz.

    Used on the record tail, where the proton signal has decayed, so the
    strongest line is the steady resonance.  The bin is refined by parabolic
    interpolation so the subtracted frequency is not quantised to the FFT grid —
    important because a small frequency error leaves a large uncancelled residual
    for a long record.

    Returns:
        Interpolated peak frequency in Hz, or None if no bins fall in the band.
    """
    f, den = sig.periodogram(x, fs, window='hann')
    band = (f >= lo) & (f <= hi)
    if not band.any():
        return None
    idx_band = np.where(band)[0]
    idx = idx_band[np.argmax(den[idx_band])]
    freq, _ = interpolate_peak(f, den, idx)
    return freq


def fit_steady_sinusoid(x, fs, freq, tail_frac):
    """Least-squares fit a constant-amplitude sinusoid at `freq` over the tail.

    Models the steady line as a · cos(ωt) + b · sin(ωt) with ω = 2π·freq and a
    *global* time origin (t = n/fs from the start of the record).  Fitting the
    in-phase (a) and quadrature (b) parts is linear, so a single lstsq solve
    recovers the amplitude and phase with no initial guess.  Fitting on the tail
    only keeps the (decayed) proton signal from biasing the estimate.

    Returns:
        (a, b) coefficients of the global-time sinusoid.
    """
    n = len(x)
    t = np.arange(n) / fs
    start = int(n * (1.0 - tail_frac))
    tt = t[start:]
    # Design matrix for the tail; solve for [a, b] in a·cos + b·sin.
    M = np.column_stack((np.cos(2 * np.pi * freq * tt),
                         np.sin(2 * np.pi * freq * tt)))
    (a, b), *_ = np.linalg.lstsq(M, x[start:], rcond=None)
    return a, b


def peel_resonance(data, fs, n_components, tail_frac, lo, hi):
    """Remove the K strongest steady tail lines from one record.

    Iteratively: find the strongest line in the tail spectrum, fit it as a
    constant-amplitude sinusoid over the tail, subtract that sinusoid from the
    *whole* record, and repeat on the residual.  Because each subtracted tone is
    constant-amplitude, a decaying component at (or near) the same frequency is
    left almost untouched — only its small steady part is removed.

    Returns:
        (residual, freqs) where residual is the cleaned full-length signal and
        freqs is the list of frequencies peeled, strongest first.
    """
    x = normalise(data)
    n = len(x)
    t = np.arange(n) / fs
    freqs = []
    for _ in range(max(1, n_components)):
        freq = estimate_line_freq(x, fs, lo, hi)
        if freq is None:
            break
        a, b = fit_steady_sinusoid(x, fs, freq, tail_frac)
        x = x - (a * np.cos(2 * np.pi * freq * t) + b * np.sin(2 * np.pi * freq * t))
        freqs.append(freq)
    return x, freqs


def avg_periodogram(records, fs_list):
    """Average Hann-windowed periodograms across a set of (already-cleaned) records."""
    accum = None
    f = None
    for x, fs in zip(records, fs_list):
        f, den = sig.periodogram(x, fs, window='hann')
        accum = den if accum is None else accum + den
    return f, accum / len(records)


def avg_envelope(records, fs_list, lo, hi, win=400):
    """Average the zero-phase-filtered RMS envelope across records.

    Uses filtfilt (zero-phase) so there is no causal filter start-up transient
    to masquerade as a decaying head — essential when the whole point is to
    judge the residual's early-time amplitude.
    """
    b, a = None, None
    per_run = []
    times = None
    for x, fs in zip(records, fs_list):
        b, a = sig.butter(4, [lo, hi], fs=fs, btype='band')
        y = sig.filtfilt(b, a, x)
        nb = len(y) // win
        per_run.append(np.sqrt(np.mean(y[:nb * win].reshape(nb, win) ** 2, axis=1)))
        times = (np.arange(nb) + 0.5) * win / fs
    return times, np.mean(per_run, axis=0)


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

    f_larmor = None
    if args.field is not None:
        f_larmor = GAMMA_HZ_PER_UT * args.field / 1000.0   # nT → µT → Hz

    # Envelope band: tight around Larmor if known, else the full search band.
    if args.env_band is not None:
        env_lo, env_hi = args.env_band
    elif f_larmor is not None:
        env_lo, env_hi = f_larmor - 40.0, f_larmor + 40.0
    else:
        env_lo, env_hi = args.search_low, args.search_high

    sig_raw = load_dir(args.signal_dir)
    fs_list = [fs for _, fs in sig_raw]

    # Original (DC-removed, unfiltered) and peeled versions of each run.
    orig = [normalise(d) for d, _ in sig_raw]
    peeled = []
    peeled_freqs = []
    for (d, fs) in sig_raw:
        x, freqs = peel_resonance(d, fs, args.n_components, args.tail_frac,
                                  args.search_low, args.search_high)
        peeled.append(x)
        peeled_freqs.append(freqs)

    f_o, d_o = avg_periodogram(orig, fs_list)
    f_p, d_p = avg_periodogram(peeled, fs_list)

    # ── Spectrum: before vs after peel ──────────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 6), dpi=90)
    mask = (f_o >= args.search_low) & (f_o <= args.search_high)
    ax.plot(f_o[mask], d_o[mask], lw=1.1, color='0.6', label="Before (raw)")
    ax.plot(f_p[mask], d_p[mask], lw=1.1, color='C0', label="After peel")
    if args.reference:
        ref_raw = load_dir(args.reference)
        ref_norm = [normalise(d) for d, _ in ref_raw]
        f_r, d_r = avg_periodogram(ref_norm, [fs for _, fs in ref_raw])
        mr = (f_r >= args.search_low) & (f_r <= args.search_high)
        ax.plot(f_r[mr], d_r[mr], lw=1.0, color='C3', alpha=0.7,
                label="Reference (no sample)")
    if f_larmor is not None:
        ax.axvline(f_larmor, color='k', ls='--', lw=1,
                   label="Expected Larmor {:.0f} Hz".format(f_larmor))
    ax.set_xlim(args.search_low, args.search_high)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Averaged power spectral density")
    ax.set_title("Resonance peel: spectrum before vs after\n"
                 "A surviving peak only after the resonance is removed is the "
                 "candidate signal")
    ax.legend()
    fig.tight_layout()
    spec_path = os.path.join(out_dir, "suppress_spectrum.png")
    fig.savefig(spec_path)
    plt.close(fig)

    # ── Envelope: residual head near the Larmor frequency ───────────────────
    t_p, e_p = avg_envelope(peeled, fs_list, env_lo, env_hi)
    fig, ax = plt.subplots(figsize=(14, 6), dpi=90)
    ax.plot(t_p * 1000.0, e_p, 'o-', ms=4, color='C0',
            label="Residual ({} ({:.0f}-{:.0f} Hz)".format(
                os.path.basename(os.path.normpath(args.signal_dir)),
                env_lo, env_hi))
    ref_ratio = None
    if args.reference:
        ref_peeled = []
        ref_fs = []
        for (d, fs) in ref_raw:
            x, _ = peel_resonance(d, fs, args.n_components, args.tail_frac,
                                  args.search_low, args.search_high)
            ref_peeled.append(x)
            ref_fs.append(fs)
        t_r, e_r = avg_envelope(ref_peeled, ref_fs, env_lo, env_hi)
        ax.plot(t_r * 1000.0, e_r, 's-', ms=4, color='C3', alpha=0.7,
                label="Residual (reference)")
        ref_ratio = e_r[:3].mean() / e_r[-3:].mean()
    ax.set_ylim(0, e_p.max() * 1.3)
    ax.set_xlabel("Time into record (ms)")
    ax.set_ylabel("Residual filtered RMS amplitude")
    ax.set_title("Resonance peel: residual envelope ({:.0f}-{:.0f} Hz)\n"
                 "A decaying head that beats the reference = candidate "
                 "precession signal".format(env_lo, env_hi))
    ax.legend()
    fig.tight_layout()
    env_path = os.path.join(out_dir, "suppress_envelope.png")
    fig.savefig(env_path)
    plt.close(fig)

    # ── Console summary ─────────────────────────────────────────────────────
    sig_ratio = e_p[:3].mean() / e_p[-3:].mean()
    avg_first = np.mean([fr[0] for fr in peeled_freqs if fr])
    print("Peeled {} tone(s)/run; strongest line ~{:.1f} Hz".format(
        args.n_components, avg_first))
    print("Residual envelope start/end ratio (signal): {:.2f}".format(sig_ratio))
    if ref_ratio is not None:
        print("Residual envelope start/end ratio (reference): {:.2f}".format(ref_ratio))
        print("  -> a real signal makes the signal head rise above the "
              "reference; similar ratios mean nothing left to find.")
    print("Wrote:\n  {}\n  {}".format(spec_path, env_path))


if __name__ == "__main__":
    main()
