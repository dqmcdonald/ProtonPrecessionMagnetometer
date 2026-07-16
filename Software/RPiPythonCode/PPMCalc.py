"""
PPMCalc.py — Signal processing and analysis for the Proton Precession Magnetometer.

After the polarising coil is switched off, the proton spins precess around
Earth's magnetic field at the Larmor frequency:

    f_L = (γ_p / 2π) · B      γ_p / 2π = 42.5775 MHz/T

For Earth's field (~57 µT at mid-latitudes) this gives f_L ≈ 2435 Hz.  The
precession amplitude decays exponentially with time constant T2 (spin-spin
relaxation), typically 1-3 s for tap water.

This module provides:
- load_from_file()     — parse a .dat file saved by PPM.doMeasurement()
- interpolate_peak()   — sub-bin peak frequency by parabolic interpolation
- estimate_snr()       — spectral peak SNR against the nearby noise floor
- PPMCalc class        — normalisation, filtering, plotting, and FFT analysis

All plotting uses the non-interactive Agg backend so the code runs headlessly
on a Raspberry Pi without a display.
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')   # non-interactive backend; must be set before pyplot import
import matplotlib.pyplot as plt
import scipy.signal as sig
import scipy.optimize as opt
from scipy.signal import butter, lfilter


# ── Filter helpers ────────────────────────────────────────────────────────────

def butter_bandpass(lowcut, highcut, fs, order=5):
    """Design a Butterworth bandpass filter and return its (b, a) coefficients.

    A Butterworth filter is maximally flat in the passband (no ripple), which
    preserves the relative amplitudes of frequency components near the Larmor
    peak.  Order 5 gives steep roll-off while remaining stable when applied
    with lfilter; very high orders can produce numerically unstable coefficients.

    Args:
        lowcut:  Lower -3 dB frequency in Hz.
        highcut: Upper -3 dB frequency in Hz.
        fs:      Sample rate in Hz.
        order:   Filter order (default 5).

    Returns:
        (b, a) IIR filter coefficient arrays.
    """
    return butter(order, [lowcut, highcut], fs=fs, btype='band')


def butter_bandpass_filter(data, lowcut, highcut, fs, order=5):
    """Apply a Butterworth bandpass filter to a 1-D signal.

    Uses lfilter (causal, single-pass) rather than sosfiltfilt (zero-phase)
    because phase is not critical for Larmor frequency extraction — we only
    care about which frequencies have power, not their phases.

    Args:
        data:    1-D numpy array of signal samples.
        lowcut:  Lower -3 dB cutoff in Hz.
        highcut: Upper -3 dB cutoff in Hz.
        fs:      Sample rate in Hz.
        order:   Filter order (default 5).

    Returns:
        Filtered signal as a 1-D numpy array (same length as data).
    """
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    y = lfilter(b, a, data)
    return y


# ── Spectral helpers ──────────────────────────────────────────────────────────

def interpolate_peak(f, den, idx):
    """Refine a periodogram peak position by parabolic interpolation.

    The discrete periodogram quantises frequency to bins of width fs / N —
    about 0.67 Hz (≈ 16 nT) for a 1.5 s record at 16 kHz.  Fitting a parabola
    through the peak bin and its two neighbours and taking the vertex recovers
    the underlying peak position to a small fraction of a bin, typically a
    10-50× improvement in frequency precision at no extra measurement cost.

    Args:
        f:   Frequency axis from scipy.signal.periodogram.
        den: Power spectral density array (same length as f).
        idx: Index of a local maximum in den (e.g. from find_peaks).

    Returns:
        (freq_hz, magnitude) of the interpolated peak.  Falls back to the raw
        bin values when idx is at either end of the array or the three points
        do not form a maximum (degenerate / collinear).
    """
    if idx <= 0 or idx >= len(den) - 1:
        return f[idx], den[idx]
    y1, y2, y3 = den[idx - 1], den[idx], den[idx + 1]
    curvature = y1 - 2.0 * y2 + y3
    if curvature >= 0:
        # Not a parabolic maximum — flat top or degenerate points.
        return f[idx], den[idx]
    delta = 0.5 * (y1 - y3) / curvature
    # For a true local maximum the vertex lies within half a bin of idx;
    # clamp anyway to guard against pathological side-lobe shapes.
    delta = float(np.clip(delta, -0.5, 0.5))
    freq = f[idx] + delta * (f[1] - f[0])
    mag = y2 - 0.25 * (y1 - y3) * delta
    return freq, mag


def estimate_snr(f, den, peak_freq, inner=100.0, outer=300.0):
    """Estimate the SNR of a spectral peak against the nearby noise floor.

    The noise floor is taken as the median PSD in the two sidebands between
    `inner` and `outer` Hz either side of the peak.  The median (rather than
    the mean) is robust to other discrete peaks — e.g. mains harmonics —
    falling inside the sidebands.

    The default sideband (±100–300 Hz) is chosen to sit inside the default
    bandpass filter window when the peak is near the centre of the band, so
    the noise estimate is not biased low by the filter's stopband attenuation.

    Args:
        f:         Frequency axis from scipy.signal.periodogram.
        den:       Power spectral density array (same length as f).
        peak_freq: Peak frequency in Hz (bin-centre or interpolated).
        inner:     Inner edge of the noise sidebands, Hz from the peak.
        outer:     Outer edge of the noise sidebands, Hz from the peak.

    Returns:
        Linear power ratio peak/noise (use 10·log10 for dB).  Returns NaN if
        no frequency bins fall inside the sidebands, and +inf if the sideband
        median is zero.
    """
    offset = np.abs(f - peak_freq)
    sideband = (offset >= inner) & (offset <= outer)
    if not sideband.any():
        return float('nan')
    noise_floor = np.median(den[sideband])
    peak_power = den[np.argmin(offset)]
    if noise_floor <= 0:
        return float('inf')
    return float(peak_power / noise_floor)


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_from_file(filepath):
    """Parse a PPM data file written by PPM.doMeasurement().

    File format (plain text):
        Line 1: num_samples  (integer)
        Line 2: sample_rate  (integer, Hz — the actual rate from the Arduino)
        Lines 3+: one raw ADC integer per line

    Args:
        filepath: Path to the .dat file.

    Returns:
        (sample_rate, num_samples, signal_data) where signal_data is a numpy
        array of dtype int64 with length num_samples.
    """
    with open(filepath, mode='r', encoding='utf-8') as f:
        num_samples = int(f.readline().strip())
        sample_rate = int(f.readline().strip())
        data = np.array([int(f.readline().strip()) for _ in range(num_samples)])
    return sample_rate, num_samples, data


# ── Analysis class ────────────────────────────────────────────────────────────

class PPMCalc:
    """Signal processing pipeline for a single PPM data set.

    Takes raw ADC samples, normalises them, and provides methods for filtering,
    plotting, and FFT-based Larmor frequency extraction.

    The constructor normalises the signal to the range [-0.5, +0.5] so that
    results are comparable across measurements made with different ADC gain
    settings or signal strengths.

    Args:
        sample_rate: Actual ADC sample rate in Hz (use getActualSampleRate()
                     from PPMRun, not the requested rate).
        sample_time: Nominal sampling duration in milliseconds.  Used only
                     as metadata; the time axis is built from the actual data
                     length and sample_rate.
        signal_data: 1-D array-like of raw ADC integer counts.
        lg:          Optional logging.Logger instance.
    """

    def __init__(self, sample_rate, sample_time, signal_data, lg=None):
        self._logger = lg
        self._sample_rate = int(sample_rate)
        self._sample_time = sample_time / 1000  # store in seconds for internal use

        # Work on a float copy so the caller's array is never modified.
        self._signal_data = signal_data.copy().astype(float)

        # Normalise to [0, 1] then shift mean to zero.
        # Step 1 — range normalisation: removes differences in ADC offset voltage
        #   and gain between measurement sessions.
        # Step 2 — mean subtraction: removes the DC bias, which would otherwise
        #   produce a large spike at 0 Hz in the FFT and mask low-frequency content.
        data_range = np.max(self._signal_data) - np.min(self._signal_data)
        self._signal_data = (self._signal_data - np.min(self._signal_data)) / data_range
        self._signal_data -= np.mean(self._signal_data)

        # Build the time axis from the actual number of samples rather than
        # from sample_time.  The two can disagree slightly because the Arduino's
        # timer quantisation means it may collect a few more or fewer samples
        # than the nominal sample_time * sample_rate product suggests.
        self._time = np.arange(len(self._signal_data)) / self._sample_rate

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, msg):
        """Write msg to the logger if one was provided."""
        if self._logger:
            self._logger.info(msg)

    # ── Plotting ──────────────────────────────────────────────────────────────

    def plotSignal(self, file_name, window=150, title=None):
        """Save a three-panel plot of the signal at the start, middle, and end.

        Showing three windows with a shared Y axis makes the exponential decay
        of the precession signal immediately visible — strong oscillation at
        the start should shrink toward the noise floor by the end.

        If the signal looks the same in all three panels the precession is
        either absent (hardware problem) or its decay time constant is much
        longer than the sampling window.

        Args:
            file_name: Output PNG path.
            window:    Number of samples to show in each panel (default 150,
                       ≈ 9 ms at 16000 Hz, ~23 precession cycles at 2.4 kHz —
                       few enough that individual oscillations stay legible
                       instead of smearing into a solid block).
            title:     Optional figure title (suptitle) spanning the panels.
        """
        n = len(self._signal_data)
        half = window // 2
        mid = n // 2

        # Each slice is (label, slice object) so we can loop cleanly.
        slices = [
            ("Start",  slice(0, min(window, n))),
            ("Middle", slice(max(0, mid - half), min(n, mid + half))),
            ("End",    slice(max(0, n - window), n)),
        ]

        # sharey=True enforces a common Y scale across all three panels,
        # which is essential for visually comparing amplitudes.
        fig, axes = plt.subplots(1, 3, figsize=(20, 5), dpi=80, sharey=True)
        for ax, (label, sl) in zip(axes, slices):
            # Plot time in milliseconds.  At the Larmor frequency (~2.4 kHz) the
            # period is only ~0.4 ms, so a seconds axis packs dozens of cycles
            # between tick labels and the waveform reads as a solid block; ms
            # ticks make the individual oscillations visible.
            ax.plot(self._time[sl] * 1000.0, self._signal_data[sl])
            ax.set_title(label)
            ax.set_xlabel("Time (ms)")
        axes[0].set_ylabel("Amplitude")
        if title:
            fig.suptitle(title)
        # Leave headroom at the top for the suptitle so it does not overlap the
        # panel titles ("Start"/"Middle"/"End").
        fig.tight_layout(rect=[0, 0, 1, 0.95] if title else None)
        fig.savefig(file_name)
        plt.close(fig)   # release memory; important in multi-run loops

    def plotAmplitudeEnvelope(self, file_name, window=500):
        """Plot RMS amplitude in successive windows across the full signal.

        Divides the signal into non-overlapping blocks of `window` samples,
        computes the root-mean-square amplitude of each block, and plots the
        result against time.  Also attempts to fit an exponential decay model:

            A · exp(−t / τ) + C

        where τ is the T2 relaxation time constant, A is the initial precession
        amplitude, and C is the noise floor.

        The fit will only be meaningful if the SNR is high enough that the
        decay stands out above the noise.  With current hardware the decay is
        often masked by noise; in that case the fit parameters should be
        ignored.

        Args:
            file_name: Output PNG path.
            window:    Number of samples per RMS block (default 500, ≈ 31 ms).

        Returns:
            (A, tau, C) fit parameters as floats, or None if the fit failed.
        """
        data = self._signal_data
        # Trim to a whole number of windows, then reshape so each row is one block.
        n_windows = len(data) // window
        trimmed = data[:n_windows * window].reshape(n_windows, window)
        rms = np.sqrt(np.mean(trimmed ** 2, axis=1))
        # Time of each window's centre point
        t_centres = (np.arange(n_windows) + 0.5) * window / self._sample_rate

        fig, ax = plt.subplots(figsize=(16, 5), dpi=80)
        ax.plot(t_centres, rms, 'o', markersize=4, label="RMS amplitude")

        fit_params = None
        try:
            def decay(t, A, tau, C):
                """Exponential decay model with noise floor C."""
                return A * np.exp(-t / tau) + C

            # Initial guess: amplitude from first-to-last difference, time
            # constant from one-third of the record length, noise floor from
            # the last window.
            p0 = [rms[0] - rms[-1], t_centres[-1] / 3, rms[-1]]
            popt, _ = opt.curve_fit(decay, t_centres, rms, p0=p0, maxfev=5000)
            A, tau, C = popt
            t_fit = np.linspace(t_centres[0], t_centres[-1], 300)
            ax.plot(t_fit, decay(t_fit, *popt), '-',
                    label="Fit: A={:.3f}, τ={:.3f}s, C={:.3f}".format(A, tau, C))
            fit_params = (A, tau, C)
        except Exception:
            # curve_fit can fail if the data is too noisy or the initial guess
            # is far from the true parameters.  Silently skip the fit line.
            pass

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("RMS amplitude")
        ax.set_title("Signal amplitude envelope")
        ax.legend()
        fig.tight_layout()
        fig.savefig(file_name)
        plt.close(fig)
        return fit_params

    def plotFilteredEnvelope(self, file_name, title=None, log_scale=False,
                             smooth_ms=20.0, fit_start_s=0.03):
        """Plot the whole filtered record in one axis with its decay envelope.

        This is the single-plot companion to plotSignal()'s three-panel view.
        The filtered signal must already be bandpass-filtered (call
        filterSignal() first) — this method does not filter, so it shows exactly
        what went into the FFT.

        Over the full ~2 s window the Larmor oscillation (~2.4 kHz ⇒ ~4800
        cycles) is far too dense to resolve, so the raw trace collapses into a
        solid band; what the eye actually reads is the *height* of that band,
        i.e. the precession amplitude.  On top of it we draw:

          * the analytic-signal (Hilbert) envelope, ±, which is the instantaneous
            amplitude of the oscillation — the FID decay curve itself;
          * an exponential fit  A·exp(−t / T2*) + C, where T2* is the effective
            transverse relaxation time (spin dephasing plus static-field
            inhomogeneity across the sample) and C is the noise floor the
            envelope relaxes toward.

        A genuine proton FID shows a clearly falling envelope (T2* of order
        1 s for water); a steady interference tone gives a flat band, and pure
        noise gives a flat band at the noise floor.  So this plot is both a
        presentation of the signal and a go/no-go test for whether it decays.

        The Hilbert envelope of a noisy narrowband signal is itself noisy, so it
        is smoothed with a short moving-average (smooth_ms) — long enough to
        ride over the ~0.4 ms Larmor period but far shorter than T2*, so the
        decay is untouched.  The exponential fit skips the first fit_start_s of
        the record because the Butterworth filter needs a few cycles to reach
        steady state (its transient start-up would otherwise bias A upward).

        Args:
            file_name:   Output PNG path.
            title:       Optional figure title.
            log_scale:   If True, plot the envelope on a log Y axis instead of
                         the ± waveform.  A single-exponential decay is a
                         straight line on a log axis until it bends over into
                         the horizontal noise floor C, which makes the
                         exponential character (and the value of C) obvious.
            smooth_ms:   Moving-average window for the envelope, in ms.
            fit_start_s: Skip this much of the record before fitting, to avoid
                         the filter's start-up transient.

        Returns:
            (A, T2, C) fit parameters as floats, or None if the fit failed.
        """
        sigd = self._signal_data
        t = self._time

        # Analytic-signal envelope = |signal + i·Hilbert(signal)|.  This is the
        # instantaneous amplitude of the narrowband oscillation, independent of
        # its phase, so it traces the FID decay directly.
        envelope = np.abs(sig.hilbert(sigd))

        # Smooth with a moving average whose length spans several Larmor cycles
        # (so per-cycle ripple is averaged out) but a small fraction of T2*.
        win = max(1, int(smooth_ms / 1000.0 * self._sample_rate))
        smoothed = np.convolve(envelope, np.ones(win) / win, mode='same')

        # Fit A·exp(−t/T2*) + C to the settled part of the envelope.
        fit_params = None
        fit_mask = t > fit_start_s
        try:
            def decay(tt, A, T2, C):
                return A * np.exp(-tt / T2) + C

            # Initial guess: amplitude from first-settled minus last sample,
            # T2* ~ 1 s (typical for water), noise floor from the final value.
            p0 = [smoothed[fit_mask][0] - smoothed[-1], 1.0, smoothed[-1]]
            popt, _ = opt.curve_fit(decay, t[fit_mask], smoothed[fit_mask],
                                    p0=p0, maxfev=10000)
            fit_params = tuple(float(v) for v in popt)
        except Exception:
            # A flat or noise-only envelope may not fit an exponential; that is
            # itself the "no decay" answer, so fail quietly and still draw the
            # envelope so the flatness is visible.
            popt = None

        fig, ax = plt.subplots(figsize=(15, 5.5), dpi=100)

        if log_scale:
            # Log Y: a pure exponential is a straight line; the bend to the
            # horizontal is where the signal reaches the noise floor C.
            ax.semilogy(t, smoothed, color='#c0392b', lw=1.4,
                        label="amplitude envelope (Hilbert)")
            if popt is not None:
                A, T2, C = popt
                ax.semilogy(t[fit_mask], decay(t[fit_mask], *popt), 'k--',
                            lw=1.5, label="exp fit:  T2* = {:.2f} s".format(T2))
                ax.axhline(C, color='0.6', lw=0.8, ls=':',
                           label="noise floor  C = {:.3f}".format(C))
            ax.set_ylabel("Envelope amplitude (log)")
        else:
            # Linear: full waveform as a translucent band + envelope ± + fit ±.
            ax.plot(t, sigd, lw=0.3, color='#4a7fb5', alpha=0.55,
                    label="filtered signal")
            ax.plot(t,  smoothed, color='#c0392b', lw=1.5,
                    label="amplitude envelope (Hilbert)")
            ax.plot(t, -smoothed, color='#c0392b', lw=1.5)
            if popt is not None:
                A, T2, C = popt
                tf = np.linspace(t[fit_mask][0], t[-1], 400)
                ax.plot(tf,  decay(tf, *popt), 'k--', lw=1.5,
                        label="exp fit:  T2* = {:.2f} s".format(T2))
                ax.plot(tf, -decay(tf, *popt), 'k--', lw=1.5)
            ax.axhline(0, color='0.7', lw=0.6)
            ax.set_ylabel("Amplitude")

        ax.set_xlabel("Time since quench (s)")
        ax.set_xlim(0, t[-1])
        if title:
            ax.set_title(title)
        ax.legend(loc='upper right', fontsize=9)
        fig.tight_layout()
        fig.savefig(file_name)
        plt.close(fig)   # release memory; important in multi-run loops
        return fit_params

    # ── Filtering ─────────────────────────────────────────────────────────────

    def filterSignal(self, lower, upper, order=5):
        """Apply a Butterworth bandpass filter in place.

        Replaces self._signal_data with the filtered version.  Call this
        before doFFT() to reject out-of-band noise and interference that
        would otherwise obscure the Larmor peak.

        The default filter window (2300–3300 Hz) is chosen to bracket the
        expected Larmor frequency for Earth's field at mid-to-high latitudes
        (~2200–2600 Hz equatorial to ~2500–3000 Hz polar) while rejecting
        mains harmonics (50/100/150 Hz, etc.) and higher-frequency ADC noise.

        Args:
            lower: Lower -3 dB cutoff in Hz.
            upper: Upper -3 dB cutoff in Hz.
            order: Butterworth filter order (default 5).
        """
        self._signal_data = butter_bandpass_filter(
            self._signal_data, lower, upper, self._sample_rate, order)

    # ── Frequency analysis ────────────────────────────────────────────────────

    def doFFT(self, filename, low_freq=2600, high_freq=3400, threshold=0.02,
              title=None):
        """Compute a periodogram, save a plot, and return detected peaks.

        Uses scipy.signal.periodogram rather than a bare FFT because the
        periodogram normalises the power spectral density by the sample rate,
        making peak magnitudes comparable across measurements with different
        numbers of samples or sample rates.  A Hann window is applied to
        reduce spectral leakage from the record edges, which would otherwise
        smear power away from the Larmor peak into neighbouring bins.

        Detected peaks are refined by parabolic interpolation (see
        interpolate_peak), so the returned frequencies are not quantised to
        the periodogram bin width.

        The plot X axis is limited to [low_freq, high_freq] so only the region
        of interest around the Larmor frequency is visible.  The Y axis scales
        automatically to the data in that window.

        Peak detection uses scipy.signal.find_peaks with a minimum height
        threshold.  The appropriate threshold depends on signal strength; the
        default (0.02) was calibrated for a high-SNR reference signal.  For
        typical hardware the threshold may need to be much lower (≈ 0.0005).

        Args:
            filename:   Output PNG path for the FFT plot.
            low_freq:   Lower frequency bound for the plot in Hz (default 2600).
            high_freq:  Upper frequency bound for the plot in Hz (default 3400).
            threshold:  Minimum periodogram magnitude to qualify as a peak.
            title:      Optional plot title.

        Returns:
            List of (freq_hz, magnitude) tuples sorted by magnitude descending.
            The first element is the strongest candidate for the Larmor frequency.
            Returns an empty list if no peaks exceed the threshold.
        """
        f, den = sig.periodogram(self._signal_data, self._sample_rate,
                                 window='hann')

        # Detect peaks first so they can be annotated on the plot below.
        # Refine each peak to sub-bin precision, then sort strongest first so
        # that peaks[0] is always the best candidate.
        peaks_idx, _ = sig.find_peaks(den, height=threshold)
        peaks = sorted([interpolate_peak(f, den, p) for p in peaks_idx],
                       key=lambda x: -x[1])

        # Scale the Y axis to the tallest peak in the visible frequency window
        # so the plot is readable regardless of absolute signal level.
        freq_mask = (f >= low_freq) & (f <= high_freq)
        y_max = np.max(den[freq_mask]) * 1.3 if freq_mask.any() else 0.1

        fig, ax = plt.subplots(figsize=(16, 6), dpi=80)
        ax.bar(f, den, width=(f[1] - f[0]))
        ax.set_ylim([0, y_max])
        ax.set_xlim([low_freq, high_freq])

        # Label each detected peak inside the plotted window with its frequency.
        # Limited to the eight strongest so a noisy spectrum (low threshold)
        # does not bury the plot under annotations.  Peaks within
        # LABEL_MIN_SEP_HZ of an already-labelled (stronger) peak are skipped so
        # the spectral-leakage skirt around a strong line does not smear
        # overlapping labels together.
        LABEL_MIN_SEP_HZ = 40.0
        labelled_freqs = []
        for rank, (f_pk, mag) in enumerate(peaks):
            if rank >= 8 or not (low_freq <= f_pk <= high_freq):
                continue
            if any(abs(f_pk - lf) < LABEL_MIN_SEP_HZ for lf in labelled_freqs):
                continue
            labelled_freqs.append(f_pk)
            ax.annotate("{:.1f} Hz".format(f_pk), xy=(f_pk, mag),
                        xytext=(0, 8), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color="red",
                        arrowprops=dict(arrowstyle="-", lw=0.5, color="red"))

        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Power spectral density")
        if title:
            ax.set_title(title)
        fig.savefig(filename)
        plt.close(fig)
        return peaks
