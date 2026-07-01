# Orientation sweep — finding the polarising-coil angle that gives an FID

**Why this is the next move.** With mains combed out (`comb_notch.py`) the
2200–2600 Hz band is clean and still shows *no* decaying, sample-dependent line.
That points upstream of interference to signal *generation*: a proton FID only
appears when the polarising-coil axis is roughly **perpendicular to the local
field**. If the axis is parallel, the magnetisation stays along the field after
quench and never precesses → zero FID. On this basalt site the true field
direction is shifted from the IGRF model by the local crustal anomaly, so the
best angle must be found empirically, not calculated.

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
| `delay` | `100` ms | Dead time after quench before sampling. Keep **as short as the quench ring allows** (ring is gone <10 ms) so the FID head is captured; try lowering toward 50 ms if the start of the record looks clean. |
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
```

## If the whole sweep is still flat

Then orientation is not the limiter and the gap is truly source-coupling:
filling factor / T2\* (sample volume, degassing) or insufficient precessing
magnetisation. Next levers then: bigger/again-degassed sample, verify the
polarisation LED fires each pulse, and re-check quench speed under load.
