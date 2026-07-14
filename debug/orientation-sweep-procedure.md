# Orientation sweep — finding the polarising-coil angle that gives an FID

**Why this is the next move.** With mains combed out (`comb_notch.py`) the
2200–2600 Hz band is clean and still shows *no* decaying, sample-dependent line.
That points upstream of interference to signal *generation*: a proton FID only
appears when the polarising-coil axis is roughly **perpendicular to the local
field**. If the axis is parallel, the magnetisation stays along the field after
quench and never precesses → zero FID. On this basalt site the true field
direction is shifted from the IGRF model by the local crustal anomaly, so the
best angle must be found empirically, not calculated.

## Prerequisite: find a low-mains site — mains floor vs distance

The orientation sweep assumes a **quiet spot**. Everything so far is radiated
50 Hz pickup (battery power removed the conducted path but the coil still acts as
an antenna for the building's mains field). Now that the whole rig runs on
battery, the biggest free lever is **distance** — do this field trip *before* the
orientation sweep and treat it as its own measurement, not a hopeful relocation.

**Physics / what to expect.** House wiring carries live + neutral with near-equal
opposite currents, so it radiates as a magnetic dipole/quadrupole: field falls
~**1/r² to 1/r³**, much faster than a single conductor's 1/r. The near-house
battery baseline was ~**424 counts** of mains-line RMS in 2200–2600 Hz (already
just under the ~580 broadband floor). A 10× distance gain should sink the
harmonics well below the floor and stop them being the sharpest lines in the band
— an obvious, early win.

**The catch — it's not only the house.** The dominant radiator is often the
*overhead distribution / service-drop lines along the road*, or a buried feeder,
which can beat the panel. Aim for "far from **all** mains conductors," and keep
clear of cars, wire fences, rebar, and buried pipes (ferrous → distorts the local
field *and* re-radiates pickup).

**Procedure — change one variable (distance) at a time.**

1. **Fix everything but position.** Same coil, same orientation as the near-house
   battery runs, same tuned tank, same `ppm.ini`, same battery. This isolates
   distance so the comparison is clean — do **not** also change angle here.
2. **Capture a no-sample baseline at each distance.** No-sample (or coil-*pulsed*
   no-sample) is all you need — the goal is to measure the mains floor, not hunt a
   peak yet. Suggested stops: **~3 m (repeat of near-house), 10 m, 30 m, 50 m**,
   as far as the ground/leads allow.
3. **Read the mains-line RMS immediately**, before moving on — the 2200–2600 Hz
   line level (and the strong low harmonics like 450/750 Hz) versus the 424-count
   near-house number tells you at each stop whether distance is working. A clean
   ~1/r²-ish falloff confirms radiated pickup and reveals the **knee** where the
   harmonics drop under the broadband floor — that distance is your sweep site.

Log each stop so the falloff is on record:

| Distance from house | Bearing / notes (overhead lines? fences?) | Mains-line RMS (2200–2600, counts) | Below broadband floor? |
|---|---|---|---|
| ~3 m (near-house ref) | — | ~424 | ≈ at floor |
| 10 m |  |  |  |
| 30 m |  |  |  |
| 50 m |  |  |  |

To get the RMS number, `comb_notch.py` already prints per-harmonic PSD for a run;
compare the in-band harmonic level between stops (same front-end/settings makes
raw counts directly comparable, as in the 2026-07-01 battery-vs-mains check).

**This is a gradient-vs-balance test (the sensor is already a gradiometer).** The
two sensor coils are wired in series-opposition (verified 2026-06-13: signal only
when a source is inside *one* coil, null for a uniform/centred source), so uniform
ambient mains is already rejected — the pair responds only to the field *gradient*
across its baseline. A localized mains source's field falls ~1/r²–1/r³ but its
gradient falls one more power of r (~1/r³–1/r⁴), so the residual should drop
*faster* with distance than a single coil would. Read the falloff accordingly:
- **Mains drops hard as you move out** → it was the near-field *gradient*; distance
  is the right lever, keep going.
- **Mains barely moves** → the gradiometer already rejects the uniform part and
  you're limited by **coil balance** (area·turns/spacing mismatch leaking
  common-mode) or **downstream coupling** (mains into the transformer/amp/leads,
  not the coils). Neither is fixed by distance — the next levers become a
  gradiometer **balance trim** or **transformer/amp shielding**, and it's worth
  quantifying the pair's CMRR (dB a uniform field is suppressed vs one coil).

**Judge success by the floor, not by a peak.** The point of the trip is to prove
the mains floor dropped. *Then* — at the quietest stop, with orientation now free
to vary — resume the science and run the orientation/tilt sweep below. If a real
FID appears at ~2435 Hz (off the comb, decaying, sample-dependent), *that's* the
detection; a quiet site is what finally lets it show. Don't conflate "moved away"
with "found signal."

## The geometry

The same coil polarises and detects, so one criterion covers both: **coil axis ⊥
to the local field vector.** For the model field (inclination 68°35′, pointing
down-and-magnetic-north) a **horizontal axis pointing magnetic East–West** is
automatically ⊥ to both the vertical and the north components — that is the
theoretical optimum and the sweep's centre point. The anomaly can rotate the
field's declination and tilt its plane, so search **azimuth and tilt around E–W**,
not just the horizontal plane.

## Procedure

1. **Fix everything except angle.** Keep the rig in the same low-mains spot
   (away from the service entry), same sample (degassed water), same tuned tank,
   same battery power. Use a non-magnetic mount; keep tools/phone/operator ≳1 m
   away during each capture. Mark each orientation so it is repeatable.

2. **Coarse azimuth sweep, coil horizontal.** Capture at magnetic azimuth
   ≈ **60°, 75°, 90° (E–W), 105°, 120°** (i.e. ±30° around E–W in ~15° steps).
   Sample runs only at this stage — the goal is to spot which angle first shows a
   gap peak that *decays*.

3. **Add tilt at the best azimuth.** Take the strongest azimuth from step 2 and
   sweep coil **tilt ±30° in ~15° steps** (nose up/down from horizontal). The
   anomaly means the true ⊥ plane is usually a few degrees off horizontal.

4. **Confirm at the winner.** At the best azimuth+tilt, take a full
   **sample + matched no-sample** pair (see settings) for the real discriminator.

## Reading each capture — the discriminators

Do **not** trust the single-shot "SNR / strongest bin" line; empty runs hit
30+ dB on mains. A real signal must pass **all three**:

```
python comb_notch.py data/<sample_run> --reference data/<nosample_run> --field 57198
```

- **Gap peak:** a line in the green Larmor gap standing well above the in-gap
  floor (not the 2–3 dB seen so far).
- **Decay:** gap-envelope first/last-quarter ratio **> ~1.3** (an FID falls with
  T2\* ≈ 1–2 s; steady interference sits at ~1.0).
- **Sample excess:** sample gap-power **above** the matched no-sample reference.

The orientation that first makes these three light up together is the answer.

## Best ppmrun.py settings

The committed `ppm.ini` is already close to optimal — the defaults below are what
it ships with; the notes say why and what to try nudging.

| Setting | Value | Why |
|---|---|---|
| `on-time` | `6000` ms | Polarise ~2–3× T1 (water T1 ≈ 2–3 s) → near-saturated magnetisation. Little gained past this. |
| `delay` | `100` ms | Dead time after quench before sampling. Keep **as short as the quench ring allows** (ring is gone <10 ms; scope shows the tank settling in ~150–200 µs) so the FID head is captured. At the confirm step also take a **`--delay 30`** run (see below) — on basalt T2\* may be only ~100–300 ms, so 70 ms less dead time is a meaningful fraction of the whole decay. |
| `sample-time` | `2000` ms | Long enough to *see the decay* across the window — essential for the decay test. |
| `sample-rate` | `16000` Hz | Nyquist 8 kHz; 2435 Hz well oversampled. |
| `runs` | `6`–`8` | Coherent averaging lifts a weak FID out of noise; use more at the confirm step. |
| `cool-down` | `10000` ms | Let coil/driver settle between runs. |
| `low-freq` / `high-freq` | `2200` / `2600` | Wide band (≈51.7–61 µT) covers the basalt-shifted Larmor. **Search wide; let the real peak reveal itself — don't tune to a number.** |
| `fft-threshold` | `0.0005` | As shipped. |

**Background:** prefer a **coil-*pulsed* no-sample** run as `--background-input`
over `--background-runs` (BKGND). The in-band lines are pulse-induced, so the
coil-off BKGND removes only ~4% of them while a pulsed empty run reproduces ~63%
(see 2026-06-28 debug notes). For the sweep, the simplest robust discriminator is
the **sample-vs-no-sample gap comparison** in `comb_notch.py` above.

Example confirm-step commands:

```
# sample at chosen orientation
python ppmrun.py --tag SAMP_AZ90_TILT10 --runs 8

# matched no-sample, same orientation, coil still pulsed
python ppmrun.py --tag NOSAMP_AZ90_TILT10 --runs 8

# short-delay probe: same orientation, catch a fast-decaying FID head
python ppmrun.py --tag SAMP_AZ90_TILT10_D30 --runs 8 --delay 30
```

The `--delay 30` run is the discriminator for a **short-T2\* FID**. If the
100 ms and 30 ms runs give the same gap power, no fast-decaying head is being
missed and dead time is not the limiter. If the 30 ms run shows **more** gap
power *and* a stronger decay (first/last-quarter ratio > ~1.3) than the 100 ms
run, a fast FID is being clipped off the front at 100 ms — shorten `delay` in
`ppm.ini` and re-confirm. Before trusting 30 ms, eyeball the first ~10 ms of a
raw record for ADC railing; the quench ring clears <10 ms, but this delay has
not yet been checked empirically below 150 ms.

## If the whole sweep is still flat

Then orientation is not the limiter and the gap is truly source-coupling:
filling factor / T2\* (sample volume, degassing) or insufficient precessing
magnetisation. Next levers then: bigger/again-degassed sample, verify the
polarisation LED fires each pulse, and re-check quench speed under load. Also
re-run the whole sweep at **`--delay 30`** — a T2\* short enough to vanish
before 100 ms would make a *real* FID look flat at every orientation, and the
shorter dead time is the only thing that recovers it.
