# Analysis & Pulse-Program Ideas

Ideas for extending the PPM's signal analysis, with implementation status.

The current pipeline (as of June 2026): normalise → Butterworth bandpass →
Hann-windowed periodogram (averaged over runs, optionally
background-subtracted) → peak detection with parabolic sub-bin interpolation →
field + SNR report.  Plus the block-RMS envelope/T2 fit in
`PPMCalc.plotAmplitudeEnvelope()`.

Context for the numbers below: at 16 000 Hz for 1.5 s the FFT bin width is
~0.67 Hz, which corresponds to ~16 nT.  That was the resolution floor until
peak interpolation (§1.1) was added; the remaining items in §1 push toward
the Cramér–Rao limit, which is far below one bin.

## Status at a glance

| Item | Section | Status |
|------|---------|--------|
| Parabolic peak interpolation | §1.1 | ✅ Implemented |
| Hann windowing | §2.5 | ✅ Implemented |
| Per-run SNR reporting | §3.1 | ✅ Implemented |
| Background acquisition (`BKGND`) | §4.1 | ✅ Implemented |
| Background spectral subtraction | §2.4 | ✅ Implemented |
| Hilbert envelope / phase-slope estimation | §1.2 | Next up |
| Zero-phase SOS filtering | §2.1, §2.2 | Next up (with §1.2) |
| Decaying-sinusoid time-domain fit | §1.3 | Planned |
| Zero-crossing counting | §1.4 | Planned |
| Spectrogram diagnostics | §1.5 | Planned |
| Mains harmonic notching | §2.3 | Superseded in practice by §2.4 |
| Matched (exponential) windowing | §2.5 | Planned |
| Lorentzian lineshape fit (B ± σ) | §3.2 | Planned |
| Cross-run statistics / Allan deviation | §3.3 | Planned |
| IGRF sanity check | §3.4 | Planned |
| Robust normalisation | §3.5 | Planned (small fix) |
| T1 measurement sweep | §4.2 | Planned (Pi-side only) |
| Delay sweep | §4.3 | Planned (Pi-side only) |
| Continuous logging mode | §4.4 | Planned |
| Polarity alternation / phase cycling | §4.5 | Idea (needs H-bridge hardware) |
| Earth's-field NMR pulse sequences | §4.6 | Out of scope |
| Timer-paced ADC sampling | §5 | Planned (firmware) |

---

## 1. Better frequency estimation (beyond the raw FFT peak)

### 1.1 Parabolic interpolation of the FFT peak  *(cheapest win — IMPLEMENTED)*

> Implemented as `PPMCalc.interpolate_peak()`; applied in both
> `PPMCalc.doFFT()` and `ppmrun.analyse()`.

Fit a parabola (or Gaussian) through the peak periodogram bin and its two
neighbours; the vertex gives a sub-bin frequency estimate. Typically 10–50×
better precision than the bin centre, for a few lines of code in
`PPMCalc.doFFT()`:

```python
# y1, y2, y3 = den at bins k-1, k, k+1
delta = 0.5 * (y1 - y3) / (y1 - 2 * y2 + y3)   # offset in bins, |delta| < 0.5
f_est = f[k] + delta * (f[1] - f[0])
```

### 1.2 Hilbert-transform phase-slope estimation

Take `scipy.signal.hilbert` of the bandpassed signal, unwrap the instantaneous
phase, and fit a straight line of phase vs. time — the slope is 2πf. For a
single decaying sinusoid in noise this approaches the Cramér–Rao bound and is
the standard technique in modern PPM firmware.

Bonus: the magnitude of the analytic signal is a **per-sample amplitude
envelope** — a much better input to the T2 exponential fit than the 31 ms
block-RMS currently used.

Caveat: phase-based methods care about filter phase distortion, so this path
needs zero-phase filtering (see §2.2). Also restrict the phase fit to the
early, high-SNR part of the record (e.g. while the Hilbert envelope is above
2–3× the noise floor) — once the signal decays into noise the phase walks
randomly and degrades the fit.

### 1.3 Direct nonlinear fit of a decaying sinusoid

Fit the time-domain model

    s(t) = A · exp(−t/τ) · sin(2πft + φ) + C

with `scipy.optimize.curve_fit`, seeded by the FFT peak (f) and Hilbert
envelope (A, τ). This is the statistically optimal estimator and returns
f, T2*, and amplitude **with uncertainties** in a single fit.

### 1.4 Zero-crossing / period counting

The classic commercial-PPM technique: count N zero crossings of the filtered
signal over a measured elapsed time, f = N / (2·T). Simple and robust, and a
good cross-check against the spectral estimate — disagreement between the two
is itself a useful data-quality flag.

### 1.5 Spectrogram (STFT)  *(diagnostic gold)*

Plot frequency vs. time over the record with `scipy.signal.spectrogram`:

- clean precession → a single horizontal ridge decaying in brightness;
- field gradients across the bottle → a broadened ridge (shortened T2*);
- field changing mid-measurement → a drifting ridge;
- interference → ridges that **don't** decay.

A ~15-line `plotSpectrogram()` method on `PPMCalc` would make most hardware
problems visible at a glance.

---

## 2. Filtering improvements

### 2.1 Second-order sections

An order-5 bandpass in `(b, a)` transfer-function form at fs = 16 kHz is on
the edge of numerical stability. Use `butter(..., output='sos')` +
`scipy.signal.sosfilt` — drop-in replacement, numerically safe at any order.

### 2.2 Zero-phase filtering

`sosfiltfilt` instead of `lfilter`. Phase doesn't matter for the periodogram
(as the current code notes), but it **does** matter for the Hilbert
phase-slope and time-domain-fit methods (§1.2, §1.3). `filtfilt` also removes
the filter's startup transient from the front of the record, which currently
eats some of the highest-SNR early samples.

### 2.3 Mains harmonic notching

**The 49th harmonic of 50 Hz is 2450 Hz — essentially on top of the expected
Larmor frequency (~2435 Hz at 57 µT).** The bandpass cannot reject it.
Options:

- `scipy.signal.iircomb` at 50 Hz (notches every harmonic), or individual
  `iirnotch` filters at 2400 / 2450 / 2500 Hz;
- but a notch exactly at f_L costs signal, so the better mitigation is usually
  background subtraction (§2.4 — now implemented, making explicit notching
  largely unnecessary; revisit only if non-stationary interference appears
  that subtraction cannot remove).

### 2.4 Background spectral subtraction  *(IMPLEMENTED)*

Record a background run in the same session (no sample, or no polarise pulse —
see §4.1) and subtract its periodogram from the measurement periodogram.
Amplifier noise and mains interference are stationary across the two; the
precession peak is not. This suppresses the harmonic comb without touching the
signal. Existing recordings such as `nosample.dat` / `newamp_no_sample.dat`
can be used as the background via `--background-input`.

> Implemented: `--background-runs N` collects coil-off acquisitions before
> the measurement runs; `--background-input FILE` uses an existing recording
> (works in `--input` re-analysis mode too).  The background spectrum is
> rescaled to the measurement noise floor (median per-bin ratio over the
> analysis band) and subtracted before peak detection; SNR is still reported
> against the unsubtracted floor.  See `ppmrun.subtract_background()`.

### 2.5 Windowing / matched weighting  *(Hann window IMPLEMENTED)*

- `sig.periodogram(..., window='hann')` reduces spectral leakage from the
  record edges. *(Now used by `PPMCalc.doFFT()` and `ppmrun.analyse()`.)*
- Better still for a decaying signal: weight the data by the expected
  `exp(−t/τ)` envelope (a *matched* window). Maximises peak SNR at the cost of
  some linewidth.

---

## 3. Characterising the data (quality metrics worth reporting)

### 3.1 Per-run SNR  *(IMPLEMENTED)*

Peak power divided by the median PSD in a sideband (e.g. ±100–300 Hz away from
the peak). Reporting this on every run makes thresholds like
`--fft-threshold` self-calibrating, and lets the code declare "no signal"
explicitly instead of returning the tallest noise spike.

> Implemented as `PPMCalc.estimate_snr()`; `ppmrun.analyse()` logs the SNR of
> every run and the final report includes the averaged-spectrum SNR in dB.

### 3.2 Lorentzian lineshape fit

A free-induction decay has a Lorentzian spectral lineshape with
FWHM = 1/(π·T2*). Fitting it gives centre frequency, linewidth, and amplitude
with a covariance matrix — so the result can be reported as **B ± σ in nT**,
not just B. A linewidth much wider than the envelope-fit τ predicts indicates
field gradients across the bottle (a coil-geometry/positioning problem that
can be acted on).

### 3.3 Cross-run statistics & Allan deviation

With `--runs N`, also report the per-run frequency estimates and their
scatter — the standard deviation across runs is the real-world repeatability.
For long sessions an Allan deviation plot distinguishes white noise (more
averaging helps) from drift (it doesn't), and tells you the optimum averaging
time.

### 3.4 IGRF sanity check

The expected field at a given lat/long is a one-call lookup (e.g. the
`ppigrf` package). Flag any peak more than a few µT from the IGRF prediction —
this automatically catches interference masquerading as signal.

### 3.5 Robust normalisation  *(small fix)*

The max–min normalisation in `PPMCalc.__init__` is fragile: a single transient
spike (e.g. residual coil kick) sets the scale for the whole record.
Normalising by the standard deviation is more robust and changes nothing else
downstream.

---

## 4. Pulse programs

The firmware implements two sequences: the full measurement cycle
(polarise → settle → sample, `EXECU`) and the background acquisition
(sample only, `BKGND`, §4.1).  The existing command set already supports
several further "programs" orchestrated entirely from the Pi, plus a couple
needing firmware or hardware changes.

### 4.1 Background acquisition  *(IMPLEMENTED)*

A sample-only mode that skips the polarise phase entirely. Companion to
spectral subtraction (§2.4), and a clean noise-floor characterisation of the
amplifier chain.

> Implemented as the dedicated firmware command `BKGND`: sample + transmit
> only, coil never energised, no settle delay or cool-down (queued like EXECU
> if received during cool-down).  On the Pi side,
> `PPMRun.doMeasurement(background=True)` triggers it.

### 4.2 T1 measurement  *(Pi-side only)*

Sweep `--on-time` (e.g. 0.5, 1, 2, 4, 8 s) and fit signal amplitude vs.
polarise time to `A·(1 − exp(−t/T1))`. Answers whether 6 s of polarisation is
actually buying anything for the sample in use, and is a good figure of merit
when comparing samples (tap water vs. doped water, etc.).

### 4.3 Delay sweep  *(Pi-side only)*

Sweep `--delay` downward to find how early sampling can start before the coil
transient saturates the ADC. The early signal is the strongest — every 100 ms
of unnecessary delay costs roughly `exp(−0.1/τ)` of amplitude, significant
when T2* is short.

### 4.4 Continuous logging mode  *(Pi-side)*

Repeat cycles indefinitely, appending a timestamped `(time, B, σ_B, SNR)` row
to a CSV per cycle. This turns the instrument from a one-shot device into a
magnetometer that can see diurnal field variation and magnetic storms —
arguably the most rewarding payoff for a PPM — and is what makes the Allan
deviation analysis (§3.3) meaningful.

### 4.5 Polarity alternation / phase cycling  *(hardware + firmware)*

With an H-bridge coil driver, alternating the polarisation direction flips the
sign of the precession signal but not of coherent interference; subtracting
consecutive pairs cancels the interference. A bigger project, but the
canonical PPM trick for noisy/urban environments.

### 4.6 True Earth's-field NMR sequences  *(out of scope, for reference)*

Spin echoes and 90° AC pulses would allow measuring real T2 rather than T2*,
but require an audio-frequency excitation coil and transmit chain — a
different instrument, really. Noted here as the boundary of what a
polarise-and-listen PPM can do.

---

## 5. Firmware note: timer-paced sampling

`recordSignal()` free-runs the ADC loop with no pacing — the RTC interrupt
measures the *average* rate, but per-sample jitter (e.g. the RTC ISR firing
mid-loop) acts like phase noise and broadens the spectral line. Timer-paced
sampling (wait on a timer compare flag before each conversion) makes the
sample spacing uniform. Worth doing before chasing sub-bin
frequency-estimation gains (§1), since jitter sets a floor on what those
methods can achieve.

---

## Suggested priority order

1. ~~**Parabolic peak interpolation + per-run SNR + Hann window** (§1.1, §3.1,
   §2.5) — an afternoon's work, large precision win.~~ **Done.**
2. ~~**Background acquisition pulse program + spectral subtraction** (§4.1,
   §2.4) — the best interference fix given the 2450 Hz mains harmonic.~~
   **Done.**
3. **Hilbert envelope / phase-slope analysis** (§1.2) with zero-phase SOS
   filtering (§2.1, §2.2).
4. **Continuous logging mode** (§4.4) with cross-run statistics (§3.3).
5. Everything else as interest and hardware time allow.
