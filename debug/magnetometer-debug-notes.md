# Proton Precession Magnetometer — Debugging Notes

Source: *Signals from the Subatomic World: How to Build a Proton Precession
Magnetometer* (Stefan & J. Richard Hollos, Exstrom Laboratories, ©2008) —
file `signalsfromsubatomicworld.pdf` in /Users/que/Documents/EBooks.

Generated from a debugging discussion on 2026-06-03.

---

## ⇒ START HERE — CURRENT STATUS & TOP NEXT STEP (as of 2026-06-24)

**The whole signal chain is verified EXCEPT one link.** Everything below has been
tested and exonerated over this log:

- **Polarization** — 8.6 A coil current, ~90 G field (compass + Hall sensor),
  fast **non-adiabatic quench ~120 µs** ≪ the 411 µs Larmor period (6/12, 6/23). ✓
- **Sensor-coil cancellation** (series-opposition gradiometer) — spatial-null
  test passes (6/13). ✓
- **Amplifier** — book INA217 amp restored; the chronic 7.7 kHz oscillation is
  gone (6/21). ✓
- **Acquisition → FFT → frequency/field calibration** — an injected sig-gen tone
  is detected at the right frequency and back-calculates the right field, 52–60 dB
  SNR (6/13, 6/21). ✓
- **Sensor tank resonance** — measured L ≈ 5.4 mH, low Q ≈ 5 (BW ≈ 500 Hz),
  tunable via the SW1 bank (6/19, 6/21). ✓

**The one untested link = is a real precessing magnetization actually being
generated and presented to the sensor?** None of the above tests touch this, and
it comes down almost entirely to **ORIENTATION**.

### TOP NEXT STEP: empirically find the coil orientation

Signal ∝ the angle θ between the coil axis and the **local** field — **maximal
when the axis is perpendicular to the field, exactly ZERO when parallel**
(≈ sin²θ). This is the only remaining *all-or-nothing* variable: it can null the
signal to zero with perfect electronics, which is exactly the "works, but same
with/without sample" symptom. After the non-adiabatic quench the magnetization
points along the old polarizing axis; only its component transverse to Earth's
field precesses, so an axis near parallel to the field detects nothing.

**⚠ GEOMETRY TRAP — "tilt to 68°" may be aligning the axis ALONG the field
(zero signal).** The rule is *axis ⊥ field*. The field points magnetic-north and
dips ~68.5° below horizontal, so the field *line* runs S-and-up at 68.5°. Pointing
the coil **south, tilted up ~68.5°** lays the axis right along that line →
antiparallel to B → sin²θ ≈ 0 → **no precession**, with perfect electronics. The
correct meridian-plane tilt is the *complement*: axis at **(90° − I) ≈ 21.5° from
horizontal** (= 68.5° from vertical), NOT 68.5° from horizontal. "Tilt to the
inclination" is the classic mis-statement that flips exactly this — check whether
the rig's 68° was measured from horizontal or vertical.

**FOOLPROOF FIX — point the axis horizontal, magnetic EAST–WEST.** The field lies
in the N–S vertical (meridian) plane, so it has **zero E–W component**; therefore
*any horizontal axis pointing magnetic E–W is automatically ⊥ to the field*
(θ = 90°, the optimum) **regardless of the inclination**. Set the coil axis
horizontal, perpendicular to the compass needle. No inclination number needed,
and immune to the basalt anomaly in the *dip*. **Try this first.**

**Basalt twist — do NOT trust the 68°35′ model inclination.** That angle is from
the IGRF *model*; the 2380 Hz line already shows the local field is offset
~1000+ nT from the model (basalt crustal anomaly), and a crustal anomaly tilts
the field *direction* too, not just its magnitude. **Find the right tilt by
experiment, not calculation** — and cross-check the local dip independently:
- **Dip needle / dip circle** — magnetised needle on a *horizontal* pivot swinging
  in the meridian plane settles at the true local inclination (anomaly included).
  Cheap to build (needle + low-friction axle + protractor). The classic
  independent inclination measurement.
- **Smartphone 3-axis magnetometer app** — reads the field vector incl. dip;
  crude (±few µT, needs figure-8 calibration, keep away from metal) but free and
  genuinely independent; enough to flag a gross anomaly.
- On basalt the rock can deflect the **compass itself** — check magnetic north
  from two spots a few metres apart; if the needle swings, lean on the on-rig
  max-signal sweep, not a single compass reading.
- (Declination needs an independent *true* north — shadow at solar noon, Polaris,
  or a GPS-tracked straight line — but the rig doesn't need it; the compass needle
  already gives the local horizontal field direction the E–W trick uses.)

How:
1. Start from the **E–W horizontal** axis above. Then take a `sample` + matched
   `no-sample` pair at a grid of tilts around it (≈ ±30° in ~10–15° steps; add a
   couple of azimuths if the platform allows) to map the response.
2. At each, run `Software/RPiPythonCode/compare_runs.py --per-run` and **search
   WIDE in frequency (~2200–2600 Hz)** — hunt for the one peak that is *both*
   sample-dependent *and* decaying (per-run decay ≫ 1 at a stable freq), wherever
   it lands.
3. The orientation where that decaying, sample-only peak emerges/maximizes is the
   answer — and it simultaneously gives you the true local field *direction*
   (worth having, since the model value is untrustworthy on basalt).

**Stack the cheap signal-maximizers first** so the sweep has something to show:
- **Fill the sensor coil bore** (filling factor, ~3–5× / 10–14 dB) — conformal bag
  per the 2026-06-13 "Sample volume / filling factor" entry; **one coil only**
  (gradiometer).
- **Keep DELAY short (~150 ms)** — longer only loses FID to T2\* decay (basalt
  gradients likely shorten T2\*); see the 6/24 addendum's delay analysis.
- Distilled/degassed, bubble-free water; non-magnetic everything.

**If a full orientation sweep still shows nothing** → the remaining axis is raw
signal strength / dephasing: T2\* too short from basalt gradients (try a *smaller*
sample in the most homogeneous part of the bore — trades filling factor for line
width), or polarization not uniformly covering the sample. Second-order; settle
orientation first.

*(Rationale and the supporting measurements are in the 2026-06-24 follow-up +
addendum below. Tools: `compare_runs.py` for sample-vs-no-sample overlays,
`suppress_resonance.py` to peel the steady tank line once a co-located signal is
suspected.)*

---

## The symptom

> "I get the same signal whether or not there's a sample in the coil. The
> value depends on which capacitors are selected via the DIP switch."

## What that symptom means

The thing whose amplitude tracks the DIP switch is the **LC tank resonating**,
not the proton signal:

- Sample/canceling coils (L ≈ 2 × 3.5 mH ≈ 7 mH) + the selected capacitor form
  a resonant circuit at **f = 1/(2π√LC)**.
- Change the cap → change resonant frequency → change how the ~3.8-million-gain
  amplifier responds to whatever broadband energy is around. This happens with
  or without a sample, because it has nothing to do with protons.

The **real** proton precession signal is different:
- A *transient* that decays over ~1–3 s (free induction decay).
- *Differential* — only appears because the bottle is in ONE of the two coils.
- *Microvolts* — invisible without the Chapter 7 processing.
- Only visible **after** bandpass filter + FFT.

Book's own go/no-go test (p. 108): take an FFT WITH the sample and one WITHOUT;
the proton peak should appear/disappear. "Same with/without" means we're seeing
background (tank ringing or oscillation), **not** precession. So the real
question is *"why is there no precession signal underneath the background?"*

Two failure classes: **(A) not measuring the right thing**, and **(B) not
generating a precession signal at all.**

---

## Decisive test #1: short the amplifier input

Disconnect the coils, **short the amp input**, run a normal acquisition + FFT.

- Output still tuned & tracks the DIP switch  → amplifier + tank loop is
  **self-oscillating** (3.8M gain + resonant input near a resonant audio
  transformer → huge loop gain at the tank frequency if input couples to
  output). This fits the symptom perfectly. Fix = §5.5 layout rules: input one
  end / output the other, short leads, full ground plane, and if needed a
  grounded tin/copper wall physically separating input from output.
- Output goes quiet  → amp is fine; problem is upstream (polarization /
  geometry — see checklist 3–4).

## Decisive test #2: plot the time-domain data (not just a number/FFT)

- Constant amplitude, never decays  → amplifier **oscillation**.
- Fast decay (tens of ms), sample-independent  → harmless **tank ring-down**
  from the switching transient (should be ~gone after the 0.1 s trigger delay).
- Slower decay over ~1–2 s, present ONLY with the sample  → that's the real
  **FID**. 

---

## Prioritized debug checklist

1. **Confirm detection method (cheapest first).** Are you reading a raw scope
   amplitude / single number, or the with-vs-without-sample FFT comparison?
   The µV signal is invisible without averaging + 6th-order Butterworth
   bandpass (≈2100–2400 Hz) + FFT, after dropping the first ~2000 transient
   points. Always compare TWO FFTs (sample vs no-sample).

2. **Rule out amplifier oscillation** — the input-short test above. Top suspect
   given the exact symptom.

3. **Verify polarization is actually happening** (no polarization → no signal):
   - **Easiest check first — the built-in indicator LED.** The pulse controller
     has a 2N3906 + LED on AT90S2313 pin PB0 that lights *whenever polarization
     current is applied to the coil* (book p.38). Watch it during a pulse: no
     light → the pulse/firmware/serial command isn't driving the coil and
     there's nothing to detect. Light → current is at least being commanded.
   - Measure current through the **polarizing coil** during the pulse — design
     value ~9.6 A (12 V Meanwell ÷ [1.1 Ω coil + 0.15 Ω MOSFETs]). Clamp meter
     or scope the coil voltage.
   - Scope the **turn-off** across the polarizing coil — must collapse fast &
     clean. Design quenches ~10 A with a ~270 V flyback, which across L=4.3 mH
     gives dI/dt = 270/0.0043 ≈ 63 A/ms → current gone in ~160 µs. Too-slow
     (adiabatic) cutoff → magnetization just follows the field down → ZERO
     precession; the book states this explicitly in Ch3.1. Watch for
     MOSFET-heating slowdown (on-resistance rises with temp → current drops →
     weaker signal over long pulse trains; p.35 + Ch7.1.2).
   - Use a real pulse length (worked example uses 6 s) and confirm the pulse
     sequence + 0.1 s trigger delay are firing.

4. **Verify geometry & orientation (a top cause of a dead null):**
   - Sample bottle in ONE sensor coil only; sensor coils sit INSIDE the
     polarizing coil (Fig 4.6).
   - **The polarizing-coil axis MUST be ~perpendicular to Earth's field** — the
     whole point of the tiltable platform. In the N hemisphere, tilt the coil to
     the local **magnetic inclination angle** (≈65° in Longmont CO; get yours
     from IGRF/NOAA, §2.4). If the polarizing field is parallel/anti-parallel to
     Earth's field the magnetization is never knocked off-axis, so there is **no
     precession to detect** — which produces exactly the "same with/without
     sample" symptom. Re-tilt and retest a few angles around the calculated one.
   - Polarization field should be ≈75 Gauss (B≈0.0075 T) at the coil center
     (p.23); a weak field gives a weak/null signal.

5. **Verify coil cancellation wiring** (p. 60–61 test): put both coils inside
   the polarizing coil, drive the POLARIZING coil from a sig-gen at ~2 kHz.
   Amp output should be **greatly reduced** if the two coils are wound opposite
   & series-connected correctly. If it's large instead, the coils are adding
   (wired wrong) → reverse one coil's connection.

6. **Sample & environment:** deionized/distilled water, bottle full (deionized
   gives a bigger peak, p. 112). Move away from mains/motors/vehicles/rebar;
   coils on a wood/plastic stand off the ground (p. 59).

7. **Tune to the actual local frequency:** estimate field (GPS → IGRF/NOAA
   calculator, §5.7) → precession frequency → pick caps near it. This only
   *amplifies* a real signal; it can't create one (hence lower priority).

---

## Best bets

Output tracks cap selection and is sample-independent → two most likely roots:

1. **Amplifier (+ tank) self-oscillating** — input-short test settles it in
   ~5 minutes.
2. **No precession being generated** — polarization current absent, turn-off
   too slow, or polarizing coil parallel to Earth's field — *combined with*
   reading raw amplitude instead of the with/without-sample FFT.

## To narrow it down, report back:
- (a) How you currently read the "signal" — raw scope trace vs. the ADL → FFT
  pipeline.
- (b) What you see when you SHORT the amp input.
- (c) What the polarizing-coil **turn-off** waveform looks like on a scope.

---

## Update 2026-06-10 — turn-off waveforms captured (ppm_data/)

**New evidence:**
- Energized coil deflects a compass from ~600 mm → polarization field is real
  and strong. Failure class B narrows to the **turn-off**, not the pulse.
- `SDS00011.png` (no coil, 2 V/div, 5 ms/div): output decays 9.88 V → 40 mV
  over 5.4 ms (τ ≈ 1 ms). Switch opens fine; node bleed-down, nothing more.
- `SDS00012.png` (coil attached, 5 V/div, 5 ms/div): from +12 V, fast negative
  flyback spike (scope Pk-Pk > 50 V, spike too fast to render), then an
  **underdamped ring at ~41.5 Hz settling over ~24 ms**.

**Verdict — the quench is ~100× too slow.** The protons feel the *current*
(field), and current is still sloshing for ~24 ms. The Larmor period is
~0.45 ms (≈2.2 kHz), so the field decays over ~50 precession periods →
**adiabatic** → magnetization follows the field down → **zero FID**. The book
design quenches in ~160 µs (270 V across 4.3 mH), i.e. under half a precession
period. This fully explains "same signal with/without sample."

**What the 41.5 Hz ring implies:** f = 1/(2π√LC) with L = 4.3 mH →
C ≈ 3.4 mF. Millifarads = power-supply bulk capacitance, not parasitics. After
turn-off the coil is still exchanging energy with the supply's output caps —
the circuit is NOT being cleanly broken. Likewise the flyback being clamped at
~tens of volts instead of ~270 V says something is providing a current path.

**Suspects, in order:**
1. An added flyback diode / TVS / snubber across the coil or the FETs. A
   natural "protection" addition — but here the high-voltage flyback IS the
   mechanism; it must be allowed to happen. Remove it.
2. MOSFET body diodes conducting the flyback back into the supply caps —
   check the stack matches the book: 8× IRF6215 p-channel as two
   parallel-of-four banks **in series**, oriented to block ~300 V. A single
   bank (150 V) or wrong orientation clamps/recirculates.
3. FETs avalanching at low voltage (under-rated substitutes).
4. Slow gate turn-off through the 4N35 (slow opto) leaving the FETs in linear
   mode — would slow the quench but predicts a ramp, not a 41 Hz ring; lower
   probability.

**Next measurements:**
- Note where the probe was connected (across coil vs drain–ground).
- Re-capture turn-off at ~500 µs/div, single-shot, trigger on falling edge,
  to see the true spike amplitude and the first millisecond.
- **Best test: 0.05–0.1 Ω shunt in the coil's ground leg, scope across it** —
  that's the current = the field. Goal: current reaches zero in ≲0.5 ms and
  stays there.
- Inspect/remove any diode, TVS, or capacitor across the coil or FET stack.
- ⚠ **Scope safety:** shots were taken with the probe at 1X. Once fixed, this
  node swings to ~−270 V — beyond most 1X probe ratings. Use 10X.

Still open (secondary): the input-short test for amplifier self-oscillation.
The slow quench explains the *absence* of an FID; the DIP-tracking background
may additionally be amp oscillation. Both can be true.

### Follow-up 2026-06-10: probe placement confirmed + shunt sizing

**Probe was connected directly across the coil** — so the 41.5 Hz ring IS the
coil voltage, hence the coil current/field really does slosh for ~24 ms.
Diagnosis confirmed; no probe-placement ambiguity left.

This sharpens the suspect list: a cleanly opened switch with nothing across
the coil would ring at tens of kHz (nF parasitics, hundreds of volts). Seeing
41 Hz requires ~3.4 mF effectively across the coil terminals — supply-bulk-cap
scale — so during turn-off a closed loop still connects the coil to big
capacitance (clamp diode, snubber, or a topology that leaves the supply in
the loop).

**Quick checks to find the path:**
1. Power off, disconnect the coil, DMM in **diode-test mode across the board's
   coil output terminals** (both polarities): ~0.5 V either way = a diode
   across the output. Capacitance mode on the same terminals: mF-scale = bulk
   caps sitting across it.
2. Compare the pulse controller against the book's Ch. 3 schematic: high-side
   switch, 8× IRF6215 p-channel, two parallel-of-four banks in series (300 V
   blocking). A low-side N-FET variant, a single 150 V bank, or any added
   protection diode/TVS would each produce exactly the observed waveform.
   *(Asked user which MOSFETs/topology they built — answer pending.)*
3. Current-shunt capture to verify any fix.

**Shunt resistor sizing (~10 A):**
- 0.1 Ω → 10 W continuous (gives 1 V at 10 A — easy to scope);
  0.05 Ω → 5 W. The 6 s energize counts as continuous thermally — size for
  full power with headroom, don't rely on pulse ratings.
- Best DIY option: **ten 1 Ω / 2–3 W metal-film resistors in parallel** =
  0.1 Ω, 20–30 W, very low inductance.
- Or a purpose-made non-inductive power shunt (TO-220 thick-film,
  0.05–0.1 Ω, 25–50 W on a small heatsink).
- **Avoid a single wirewound ceramic-block resistor** — inductive, and the
  measurement target is a ~100 µs current edge (1 µH of shunt inductance
  fakes a spike on the edge).
- A 1–2 s energize is enough for this test (only the turn-off matters) and
  keeps the shunt cool. The added 0.1 Ω drops loop current ~8% — irrelevant
  for diagnosis; remove the shunt for real measurements later.

### Follow-up 2026-06-10 (later): MOSFET bank schematic/PCB reviewed — bank is per-book; suspicion moves to the GATE DRIVE

User added `ppm_data/MMPMosfetBankSchematic.pdf` and `PPMMosfetBankPCB.pdf`
(KiCad, "PPM Mosfet Bank", Dec 2024). **The bank matches the book's Fig 3.1
(p. 37) exactly:** 8× IRF6215; J2 "12V In" → Q1–Q4 sources; Q1–Q4 drains →
Q5–Q8 sources (mid node); Q5–Q8 drains → J3 "To Coil"; all 8 gates commoned
to J1 "Gate Out". No diode, TVS, snubber, or capacitor anywhere on the board.
PCB traces are adequately wide. **The bank board cannot by itself produce a
41 Hz / 24 ms ring — there's nothing on it but FETs.**

**Conclusion: the slow quench must come from (a) the gate drive, or (b)
damaged FETs.** Most likely (a): if the gate bus rises from ~1 V to ~12 V
slowly (ms-scale), the FETs crawl through their linear region for tens of ms,
acting as a varying resistor that keeps the coil connected to the supply's
bulk caps → exactly the observed clamped flyback + 41 Hz ring through ~3.4 mF.

**The book's gate drive (Fig 3.1, p. 36–37):** gate bus pulled up to the SAME
+12 V rail through R2 = 470 Ω; 4N35 output transistor pulls it down via
R1 = 330 Ω; AT90S2313 PB0 drives the 4N35 LED (PB0 high → opto off → gate
≈ 12 V → Vgs ≈ 0 → FETs OFF; PB0 low → opto on → gate ≈ 1 V → Vgs ≈ −11 V →
ON). Turn-off speed per book values: τ ≈ R2 × ΣCiss ≈ 470 Ω × ~15 nF ≈ 7 µs.
Anything slower than ~100 µs at the gate is a problem; ms-scale = smoking gun.

**Note:** SDS00011 (no coil, τ ≈ 1 ms decay) is ambiguous — that decay is
equally consistent with the 1 MΩ probe discharging ~1 nF of FET/cable
capacitance OR with a ~1 ms slow gate. The gate measurement resolves it.

**Decisive next measurements:**
1. **Scope the gate bus (J1, referenced to supply ground) across a turn-off.**
   Expect a clean ~1 V → ~12 V step in tens of µs. Slow ramp / RC crawl /
   wiggle → gate-drive problem found.
2. Compare the user's gate-drive circuit against book Fig 3.1 (R2 470 Ω to
   the same +12 V, 4N35, R1 330 Ω). Watch for: larger pull-up resistor, any
   capacitor on the gate bus, long unreferenced gate wiring (J1 is a single
   pin — gate return is via the power leads), or a different driver entirely.
   *(Asked user for their gate-drive schematic.)*
3. After any fix: check FETs for gate-oxide damage (DMM gate-source leakage),
   since during a proper −270 V flyback the upper bank's Vgs can be driven
   far past the ±20 V rating if the gate is held stiffly — the book's
   high-impedance 470 Ω drive lets the gate get dragged along; a stiff/buffered
   driver would not, and can punch through the oxide on the first real quench.

### Follow-up 2026-06-10 (later still): controller schematic reviewed + DMM result decoded

**DMM diode-mode across the coil terminals: ~1.1 V conducting + → −, open
− → +.** Decoded: 1.1 V ≈ two ~0.55 V body-diode drops in series — the path
J3 → Q5-8 body diodes → mid → Q1-4 body diodes → +12 rail. This (a) confirms
the two-banks-in-series wiring is real and correctly oriented, and (b) shows
**no clamp diode in the flyback direction** (− → + is open; flyback drives J3
*below* ground, and nothing conducts that way). Bank exonerated again.

**Controller (`PulseControllerSchematic.pdf`, Arduino Pro Mini based):**
MOSFET Trigger section is essentially the book's circuit: R1 = 470 Ω pull-up
from +12 V to the gate bus (J5 "MOSFET Gates"), 4N35 output transistor pulls
the bus low to turn FETs on; LED driven from +3.3 V via R2 = 100 Ω
(≈21 mA), switched by Arduino pin D4 (replaces AT90S2313 PB0). C5 = 1 µF
50 V ceramic drawn near the +12 V entry. Healthy turn-off: opto storage
(tens of µs) + Miller-limited drain slew (~40 µs) + 270 V quench (~160 µs)
→ total well under the 0.45 ms Larmor period. So *as drawn* this should work
— meaning a build/placement fault is likely. **Two specific checks:**

1. **Where does C5 actually connect on the PCB?** If it sits on the GATE side
   of R1 (gate bus to GND) instead of the +12 V rail side, turn-off slows to
   τ ≈ 470 Ω × 1 µF ≈ 0.5 ms — enough to push the quench adiabatic. Verify
   which R1 pad C5's trace ties to.
2. **Is R1 present/intact?** Power off, measure ~470 Ω from the J5 gate line
   to +12 V. If the pull-up is open/missing, the gate has NO turn-off path —
   it floats near 1 V on the FETs' Ciss when the opto lets go, FETs linger ON
   for tens of ms, and the coil stays coupled to the supply → would explain
   the entire 24 ms / 41 Hz picture (supply control-loop ringing after the
   10 A load dump, seen through still-conducting FETs).

**Gate scope shot remains decisive.** At turn-off, gate bus (J5 ref. ground):
- Clean ~1 V → ~12 V step in tens of µs (brief Miller plateau) → gate is
  fine, look elsewhere.
- ~0.5 ms RC exponential → C5 is on the gate bus.
- Stuck near 1 V for ms before drifting up → open/missing pull-up R1 (or
  opto/wiring fault).

### Follow-up 2026-06-10: prediction if the gate pull-up (R5) is 470 kΩ

Hypothesis to test by measurement: the 470 Ω gate pull-up was populated as
**470 kΩ** (yellow-violet-yellow vs yellow-violet-brown). Prediction:

- Turn-on, steady current, compass deflection, indicator LED: all unaffected
  (the opto pulls the gate low regardless of pull-up value) — matches symptoms.
- Turn-off: pull-up current only ≈23 µA → τ ≈ 470 kΩ × 15 nF ≈ **7 ms**, plus
  several ms of Miller plateau (~150 nC at 23 µA) → FETs in linear region for
  ~10–25 ms → coil stays coupled to supply bulk caps → clamped flyback +
  41 Hz/24 ms ring. **Quantitative match to SDS00012.**
- Gate scope signature: slow exponential 1 V → 12 V, τ ≈ 7 ms, Miller shelf
  near 7–8 V, settled in ~20–30 ms (vs τ ≈ 0.5 ms if C5 is on the gate bus;
  vs stuck at ~1 V if R5 is open).
- No scope needed: power off, ohms from J5 gate line to +12 V reads 470 Ω vs
  470 k directly.

### Follow-up 2026-06-11: gate bus scoped — GATE DRIVE EXONERATED; SDS00012 now in question

New data (`ppm_data/oscope_index.txt`): R1 measured **470 Ω** (photo confirms
yellow-violet-brown; 470k hypothesis dead). Gate captures:

- `SDS00013.png` (gate, no coil, 2 V/div, 20 µs/div): clean rise 2.12 V →
  12.08 V in **~29 µs**. Textbook-healthy turn-off; C5 is NOT on the gate bus,
  pull-up intact. All gate-drive failure hypotheses eliminated.
- `SDS00014.png` (gate, coil attached, 5 V/div, 50 µs/div): rise starts from
  ~1.8 V, an HF oscillation burst during the linear-region transit (classic
  parasitic oscillation of 8 paralleled FETs on a common gate bus — book
  design has no per-gate resistors; brief, probably tolerable), a coupled
  spike to ~+24 V (Vgs ≈ +12 V, within ±20 V rating), then a decaying
  **~66 kHz ring**, fully settled at 12 V by **~290 µs**.

**Why this is big:** 66 kHz is exactly the coil's natural resonance with
parasitics (4.3 mH ‖ ~1.3 nF → 67 kHz) — the signature of a coil that HAS
been cleanly disconnected. Total turn-off event ≈ 290 µs < 0.45 ms Larmor
period. As seen from the gate, **the quench looks fine.**

**Contradiction:** SDS00012 (coil voltage) showed a 41 Hz ring over 24 ms.
With the gate provably at 12 V within ~30 µs, lingering-on FETs cannot
explain that. A multi-volt 41 Hz signal across the grounded 1.1 Ω/4.3 mH
coil would imply amps of circulating current with no apparent loop.
Candidate reconciliations:
1. The 41 Hz event is the **Meanwell's load-dump recovery** (control-loop
   ring after losing 10 A — tens of Hz over tens of ms is textbook SMPS
   behavior) appearing at the coil node as a measurement artifact (1X probe,
   FET output capacitance/common-mode), with NO real coil current → quench
   is actually fine and the no-FID cause is elsewhere (amp oscillation,
   coil orientation, detection method).
2. One FET bank **avalanches** (~150–170 V; series banks don't share voltage
   equally) — clamps the flyback below the designed 270 V but still quenches
   10 A in ~250 µs → physics OK, FET stress only.
3. FETs genuinely leaky/damaged → real slow current. (Argues against: DMM
   showed open in the flyback direction; 66 kHz ring says clean break.)

**Gate low level ~2 V (vs book's ~1 V): NOT a problem.** Vgs ≈ −10 V = fully
enhanced; coil current unaffected. Level is set by the 4N35 sinking the
~21 mA pull-up current with only ~21 mA LED drive — min CTR ≈ 100 %, so it
sits at the saturation edge with Vce ≈ 1–2 V. Harmless; could drop R2
(100 → 47–68 Ω) for margin but it is not the bug.

**Decisive next measurements (current, not voltage):**
1. **Shunt capture** (0.05 Ω in the coil ground leg): one shot at
   ~100 µs/div for the quench shape, one at ~5 ms/div to check whether ANY
   41 Hz current exists. Current gone in ≲0.5 ms and staying gone =
   polarization/quench fully exonerated.
2. Re-capture coil voltage at **10X probe, ~100 µs/div, single-shot** to
   read the true flyback peak: ~270 V = per design; flat-topped ~150–170 V =
   one bank avalanching.
3. If quench exonerated → return to the amp **input-short test** and
   **polarizing-coil tilt to local magnetic inclination**, and confirm
   detection is the with/without-sample FFT comparison.

### Planned 2026-06-12: shunt capture + external-signal tests of coil/amp

Shunt resistors ordered. Plan: shunt current capture (two timebases, per
above), then external-signal exploration of the detector coils + amplifier.

**Recipes for the external-signal tests:**

1. **Don't inject a sig-gen directly into the amp.** Gain ≈ 3.8 M → the
   ±10 V limiter clips at ~2.6 µV input. A generator's minimum (~10 mV) is
   ~4000× too much. Either build a heavy divider (e.g. 10 kΩ : 1 Ω ≈
   10,000:1, mounted AT the amp input, fed with 10–100 mV), or better:
2. **Couple inductively — the book's own method (p. 60–61 cancellation
   test):** sensor coils in their normal place inside the polarizing coil;
   drive the POLARIZING coil from the sig-gen at ~2 kHz (a few hundred mV is
   plenty). Expected: amp output GREATLY reduced vs driving a single coil,
   because the opposed series coils cancel. Large output instead = coils
   adding → one coil's connections reversed. This tests coils, wiring,
   cancellation, and amp in one shot.
3. **Input-short test (the old decisive test #1):** coils disconnected, amp
   input shorted, run normal acquisition + FFT. Output still tuned/tracking
   DIP caps = amp self-oscillation (fix per §5.5 layout: input/output
   separation, ground plane, shield wall). Quiet = amp fine.
4. **Tank tuning check:** with a weak inductively-coupled tone, sweep
   1.5–2.5 kHz and confirm the response peaks where f = 1/(2π√LC) predicts
   for the selected DIP caps; verifies the cap bank does what the labels say.
5. **Fake FID end-to-end test:** gate the sig-gen to a short decaying burst
   at the expected Larmor frequency (~2.2 kHz, ~1–2 s), couple it weakly
   (small loop a meter away from the sensor coils), and run the FULL
   acquisition + Butterworth + FFT pipeline. If the pipeline can't find a
   known synthetic "FID", fix detection before chasing physics.
6. Sig-gen ground can defeat the differential/cancellation scheme — prefer
   battery-powered or transformer/loop coupling; keep the generator's ground
   clip off the amp input.

### Follow-up 2026-06-12: QUENCH EXONERATED — SDS00016 + clamp meter

New data: clamp meter on the coil lead reads **8.6 A** during the pulse
(design ~9.6 A; 12 V/8.6 A ≈ 1.4 Ω loop = coil 1.1 + FETs 0.15 + wiring —
normal; field ≈ 67 G vs 75 G design, ~10% low, harmless).

`SDS00016.png` — turn-off across the coil, 10X probe with scope channel set
1X at 10 V/div (so actual = display × 10), 50 µs/div:
- Baseline ~+11 V (coil terminal during the 8.6 A on-state).
- Turn-off: snaps to **−312 V, flat-topped for ~80 µs** = both series FET
  banks avalanche-clamping at ~156 V each — this IS the book's designed
  energy dump (their "~270 V").
- Cross-check: quench time = L·I/V = 4.3 mH × 8.6 A / 312 V ≈ **120 µs** —
  matches the waveform. Well under the 0.45 ms Larmor period.
- Afterward: small ~50–60 kHz coil-resonance ring decaying in ~150 µs, then
  FLAT. No 41 Hz, no 24 ms tail.

**Conclusions:**
- The quench is per-design; the adiabatic-turn-off theory is DEAD.
- SDS00012's 41 Hz/24 ms ring was an artifact (Meanwell load-dump recovery
  viewed with a 1X probe at slow timebase), as suspected on 6/11.
- Signal GENERATION is now verified end to end (current + quench). The
  shunt capture is now optional (one 5 ms/div shot would formally confirm
  zero post-quench current, but the case is effectively settled).
- Remaining suspects for "no FID", in test order: (1) amp self-oscillation
  → input-short test; (2) sensor-coil cancellation wiring → p.60-61
  sig-gen test; (3) acquisition/processing → fake-FID pipeline test;
  (4) **polarizing-coil tilt** — axis must be ~perpendicular to Earth's
  field (local magnetic inclination from NOAA/IGRF); wrong tilt gives this
  exact symptom with perfect electronics.

### Follow-up 2026-06-13: CANCELLATION + FULL DETECTION CHAIN VERIFIED

Two external-signal tests run (the recipes planned 2026-06-12), plus two
design calculations that follow from the results.

**Test A — sensor-coil cancellation (spatial null).** Drove a homemade test
coil (sig-gen through a 1 kΩ series load) and moved it relative to the two
sensor coils. `ppm_data/SDS00017.png`: yellow = 60 mV drive, magenta = amp
output at **2436 Hz** (hardware freq counter top-right reads 2.43621 kHz;
ignore the `1/ΔX = 694 Hz` cursor — those cursors span several cycles).
Result: a signal appears **only when the test coil is inside ONE sensor coil**;
it nulls when the coil is between them or on top of both. That is exactly the
series-opposition (gradiometer) signature — a source coupling equally to both
coils cancels. **Cancellation wiring is correct.** ✓
- Minor note: the magenta amp output is clipped/flattened on the bottom =
  output-stage DC-offset saturation at this (large) drive level. Irrelevant
  for µV proton signals (deep in the linear region), but a saturated amp
  recovers slowly — keep `DELAY` long enough to clear quench-transient
  saturation, but see the T2* caveat below for why it shouldn't be *too* long.

**Test B — full pipeline via injection + shorted control.** Ran the real
`PPM.py` acquisition+FFT pipeline on sig-gen tones near the proton frequency
(`Software/RPiPythonCode/data/SIGGEN*_2026_06_13_*`) and on a detached/shorted
input (`SHORT_2026_06_13_13_07_35`):
- SIGGEN 2436 Hz & 2438 Hz at 100 mV and 500 mV → clean single FFT peak,
  **58–60 dB SNR**, noise floor ~0 on that scale. The chain converts
  2436.23 Hz → **B = 57.219 µT**, matching the local field (57198 nT, Larmor
  ≈ 2435 Hz). So the injection sits *right at the real proton frequency* and
  the chain reports the right field — acquisition, FFT, interpolation,
  peak-pick and B-calc are all verified at the exact regime that matters.
- SHORT run → "No peaks found above threshold" (processing is NOT fabricating
  signals — good negative control). Noise floor ~1e-6 PSD (~45 dB headroom).
  **But** conducted-interference spurs at ~2620 / 2900 / 3110 Hz appear with
  the input shorted (switching/digital harmonics into the amp, not coil
  pickup). All above 2435 Hz so they won't be confused with a proton peak,
  but worth filtering; 2620 Hz is only ~185 Hz out.

**What is now crossed off the suspect list (from the 6/12 list):**
- ~~Sensor-coil cancellation~~ → working (Test A spatial null).
- ~~Acquisition/processing chain~~ → working (Test B injection + shorted control).
- ~~Amp gross self-oscillation~~ → not oscillating (shorted run is just
  noise + conducted spurs, no runaway tank peak).
- (Quench/polarization already exonerated 6/12.)

**Remaining suspect is now strongly isolated to PROTON-SIGNAL
GENERATION/COUPLING at the sensor** — is enough precessing magnetization
produced, and is its EMF above the µV-scale noise floor.

#### Design calc 1 — tuning capacitor to resonate the sensor tank at 2435 Hz

Sensor inductance L ≈ 2 × 3.5 mH = **7.0 mH** (two coils series; spatially
separated so mutual coupling ≈ 0, self-inductances add). Target f₀ = 2435 Hz.

    C = 1 / [(2πf₀)² L] = 1 / [(2π·2435)² · 0.007] ≈ 0.61 µF

(Book's own example — same 7 mH at 2247 Hz — gives 0.72 µF, a sane DIP-bank
value, so this checks out.) Sensitivity (C tracks L directly): 6.5 mH→0.66 µF,
7.0→0.61, 7.5→0.57, 8.0→0.53 µF.

Tank properties: Q = ω₀L/R = (2π·2435·0.007)/5.9 ≈ **18** (unloaded; amp/
transformer load pulls it down). Gives ~**18× (~25 dB) voltage gain** on the
proton EMF *before* the amp, and a **−3 dB bandwidth ≈ 135 Hz** — wide enough
to be forgiving on tuning (±5% on C stays in band), narrow enough to start
rejecting the 2620/2900/3110 Hz spurs. Build notes: **measure L first** with
an LCR meter (the 3.5 mH/coil is nominal); use **polypropylene film** caps
(low loss/stable, won't spoil Q); 0.47+0.15 µF = 0.62 µF or 0.56 µF + trim;
load the existing 12-position DIP bank with values bracketing 0.61 µF and
sweep to peak. Caveat: resonance helps if the floor is amp/interference-set
(which the SHORT test suggests); if coil Johnson noise dominated, it would
lift signal and noise together (SNR flat) but still add interference rejection.

#### Design calc 2 — expected proton FID EMF for this coil + a water sample

Curie-law magnetization in the polarizing field:

    M₀ = N_p γ² ℏ² B_p / (4 k_B T)

with N_p = 6.69e28 m⁻³ (2 H per H₂O molecule), γ = 2.675e8 rad/s/T,
B_p = 0.0075 T (≈75 G; ~67 G at the measured 8.6 A), T = 293 K
→ **M₀ ≈ 2.5e-5 A/m** (an equivalent source field μ₀M₀ ≈ 31 pT — the
classic tiny proton signal, right order of magnitude).

Coil geometry (book gives 552 turns / 3.5 mH but no dimensions; reverse-
engineered via Wheeler's multilayer formula): **r ≈ 2.0 cm, l ≈ 10 cm,
~4 layers** fits 3.5 mH → A = πr² = 1.26e-3 m², sample volume in one coil
≈ 126 mL. Peak FID EMF by reciprocity (full M₀ goes transverse after a
perpendicular quench):

    ε_pk = ω₀ μ₀ N_c A M₀
         = (15300)(1.257e-6)(552)(1.26e-3)(2.5e-5)
         ≈ 0.33 µV peak  (≈ 0.23 µV RMS)

Noise comparison: coil Johnson noise √(4k_BT·5.9Ω) = 0.31 nV/√Hz; system
input-referred ~2 nV/√Hz; in a 1.5 s record (≈0.67 Hz bin) noise ≈ 1.6 nV.
→ **SNR_raw ≈ 230/1.6 ≈ 140 (~43 dB) untuned**, and ~25 dB more with the tank.
Scaling for adjusting to real numbers: ε_pk ∝ B_p · N_c · r² · f₀ (double the
radius → 4× signal; the 67→75 G uncertainty is only ±12%).

**Implication — the signal should be ~40 dB over the floor even untuned**, so
the gap is upstream of detection. Two high-value, cheap experiments:
1. **Shorten `DELAY`.** The runs used `DELAY 500` (500 ms before sampling).
   In Earth's field T2* (set by field inhomogeneity over the sample) is often
   only ~100–300 ms; at T2*≈200 ms, waiting 500 ms leaves only ~8% of the FID
   (e^−2.5). **Try DELAY 100–150 ms** — just enough for the amp to recover
   from the quench transient. Free, high-leverage test.
2. **Perpendicularity** — ε ∝ sin θ of the polarizing axis vs Earth's field;
   confirm the platform tilt against the local inclination (68°35′).

**Next-up:** estimate T2* from a field-gradient assumption, and/or sanity-check
the polarizing-coil tilt against the 68°35′ inclination; then re-run with a
shorter DELAY and a tuned tank.

---

### Follow-up 2026-06-13 (evening): FIRST SAMPLE RUNS — NO SIGNAL, FRONT-END OSCILLATION FOUND

First real attempts at detection (still **untuned** — no tank cap yet). Runs in
`Software/RPiPythonCode/data/`: `sample_*` (distilled water), `2xsample_*`
(two bottles), `nosample_*`, `Kerosine_*`, `delayreduced200ms_*`,
`2xsampleampgain*`. All look like noise. Numerical analysis of `run_00.dat`
(N=24000, sample_rate ≈ 16.2 kHz, 1.48 s window) gives:

| Run            | rms total | rms @~7.7 kHz | rms in-band 2.3–3.3 kHz | env decay end/start |
|----------------|-----------|---------------|--------------------------|---------------------|
| Distilled water| 19.9      | 17.8          | 2.20                     | 1.06                |
| 2× water       | 20.0      | 17.9          | 2.10                     | 0.97                |
| No sample      | 20.0      | 17.7          | 2.24                     | 1.06                |
| Kerosene       | 20.2      | 18.7          | 1.30                     | 0.98                |
| Coil SHORTED   | 21.4      | 19.2          | 1.17                     | 1.00                |

**Three independent proofs there is no proton signal:**
1. **Water ≈ no-sample in every band** (2.20 vs 2.24). The sample changes nothing.
2. **No envelope decay** (end/start ≈ 1.0). A real FID *must* decay over a 1.48 s
   window (T2* ~0.5–2 s → expect ≈0.3–0.5). Flat envelope = steady interference.
3. **Same total RMS with the coil detached and terminals shorted** (21.4) as with
   a sample (20). The dominant noise is **not coming through the coil** — it is
   generated downstream of it.

**ROOT CAUSE FOUND — chronic front-end oscillation.** The single biggest feature
in *every* run, including coil-shorted, is a coherent tone at **~7.6–7.8 kHz,
~18–19 counts RMS — ~90 % of total noise power.** Present with the input shorted
⇒ the amplifier is self-oscillating (or a switching/clock artifact is injecting),
**not pickup.** This confirms the long-standing "amp oscillation" suspect.
- Apparent frequency drifts run-to-run (7639 / 7565 / 7765 Hz) and sits just
  below Nyquist (8112 Hz @ 16.2 kHz) — likely an oscillation slightly *above*
  Nyquist aliasing down. **There is no anti-alias filter**, so anything 8–16 kHz
  folds straight into the proton band.
- Raw ADC sits on a large DC offset (~−13 800 counts) using only **~90 of 65 536
  counts** of swing — most of the dynamic range is wasted.

**Why it buries the proton signal:** expected EMF ~0.33 µV needs the full ~3.8 M
gain; an amp oscillating at 7.7 kHz is by definition unstable, and the
oscillation + DC offset eat the headroom and desensitize it.

**Prioritized fixes (in order):**
1. **Add the tuning cap / build the LC tank (~0.61 µF) — biggest single win.**
   Resonance does two jobs at once: boosts the proton EMF by **Q ≈ 18×** *and*
   gives a narrow bandpass that rejects the 7.7 kHz **before the amp.**
2. **Kill the oscillation — but note these runs used a CHEAP AliExpress amp
   module, NOT the book's amp.** So the ~7.7 kHz ring is the AliExpress board's
   problem, not the INA217 design's. **Plan (2026-06-13): restore the original
   book amp** (two INA217 stages ~1958× each → audio-transformer ~2.3 kHz
   bandpass → OP177G ±10 V limiter, ±12 V lantern batteries) and re-run. If the
   book amp *also* rings: tighten supply decoupling at each INA217's pins
   (0.1 µF + 10 µF), check transformer loading / lead dress, suspect the OP177G
   limiter stage. Either way, re-do the shorted-input + envelope-decay checks on
   the restored amp to confirm a clean baseline before trusting any sample run.
3. **Add an anti-alias low-pass (~3–4 kHz)** ahead of the ADC — essential
   regardless; you are sampling at 16 kHz with nothing filtering 8–16 kHz.
4. **Re-center the DC bias** to mid-scale so the ADC range is actually used.

Note: `2xsampleampgain*` (raised amp gain) and `delayreduced200ms_*` (DELAY
500→200 ms) made no difference — consistent with the gap being the front-end
oscillation + no tank, not gain or DELAY.

---

### Sample volume / filling factor (2026-06-13)

The FID EMF scales ~**linearly with the polarised sample volume inside the
sensing coil** — the *filling factor* η (fraction of the coil's sensitive bore
occupied by polarised water):

    ε_pk ∝ ω₀ · M₀ · V_sample-in-coil ≈ ω₀ · M₀ · V_coil · η

So small bottles that only partly fill the bore leave signal on the table. Going
from (say) η≈0.25 to η≈1 by filling the bore is a **~3–5× (~10–14 dB) signal
gain** — directly raising signal vs the noise floor. The earlier ~0.33 µV EMF
estimate assumed a particular fill; under-filled bottles give *less* than that.

**Plan:** seal distilled water in a **flexible bag that conforms to and fills one
sensing coil's bore** (beats a cylindrical bottle — no corner air gaps).

Rules / caveats:
- **⚠ GRADIOMETER: fill ONE coil only.** The sensor is series-opposition; a
  sample spanning both coils partly **cancels** (confirmed: signal only when in
  one coil). Keep the reference coil empty for common-mode rejection.
- **Polarising field must cover the whole enlarged sample**, uniformly — any
  part outside the polarising coil isn't polarised and contributes nothing.
- **T2\* vs homogeneity:** a bigger sample spans more field gradient → faster
  dephasing → shorter T2\*/broader line. Fill the *homogeneous* region; don't
  oversize beyond the coil bore.
- **No air bubbles** (dead volume) — seal the bag completely full.
- **Non-magnetic everything** — no metal clips/ties/ferromagnetic contaminants;
  they distort local field and wreck T2\*. Distilled (ideally degassed) water.

Complementary to the amp restore + SW1 tank tuning: those raise gain/Q, this
raises the source signal. All three stack.

---

## Sensor coil characterization & tank tuning (2026-06-19)

Measured the coil resonance directly with the **ring-down method** (see
`measure-inductance-with-scope.md`): drove the sensor coils with a 100 Hz
square wave, **98.8 nF film cap** temporarily across the termini (this cap is a
*test fixture only* — NOT the SW1 bank), scoped the damped LC ring on the tank.
Captures: `ppm_data/SDS00018.png`, `ppm_data/SDS00019.png`.

Ring period from on-screen cursors → resonant frequency → coil inductance
(L = 1 / ((2πf)²·C), C = 98.8 nF):

| Capture | ring period | f_res | derived L |
|---------|-------------|-------|-----------|
| SDS00018 | 142 µs | 7.04 kHz | 5.17 mH |
| SDS00019 | 148 µs | 6.76 kHz | 5.62 mH |
| **avg** | — | **~6.9 kHz** | **L ≈ 5.4 mH (±5%)** |

**Measured L ≈ 5.4 mH for the tank as tested** — note this is higher than the
book's nominal 3.5 mH/coil; use the *measured* value for tuning. The ring dies
in ~4–5 cycles → low loaded Q (~5), so resonance is broad (BW ≈ f/Q ≈ 500 Hz);
the scope's input loading inflates the damping, so realized Q at signal feeding
the amp may differ — re-measure once wired to the amp.

### Tuning the SW1 bank to the Larmor frequency

Larmor freq here = 0.042577 Hz/nT × 57198 nT = **2435 Hz** (matches the
`SIGGEN2436HZ` test runs). To resonate L ≈ 5.4 mH at 2435 Hz needs
**C ≈ 790 nF** (range 760–810 nF across the L uncertainty band).

SW1 bank caps are all in **parallel** (each DIP switch gates one cap between the
signal node and common); total C = sum of ON switches:

| Sw | Cap | nF |  | Sw | Cap | nF |
|----|-----|----|--|----|-----|----|
| 1 | C1 | 560 |  | 7 | C7 | 22 |
| 2 | C2 | 390 |  | 8 | C8 | 10 |
| 3 | C3 | 220 |  | 9 | C9 | 5.6 |
| 4 | C4 | 100 |  | 10 | C10 | 3.9 |
| 5 | C5 | 56 |  | 11 | C11 | 2.2 |
| 6 | C6 | 39 |  | 12 | C12 | 1 |

**→ Set switches 1 + 3 + 8 ON (C1 0.56 + C3 0.22 + C8 0.01 = 790 nF →
resonance ≈ 2440 Hz.)** Three switches, lands on the Larmor frequency.

**Fine-trim** with the small caps while watching the actual precession signal:
+12 (1 nF), +11 (2.2), +10 (3.9) lower f slightly; swap C8→C9 (5.6) raises it.
Confirm by repeating the ring-down with the bank set to 1+3+8 — target ring
period ≈ 410 µs (1/2440 Hz).

---

### Follow-up 2026-06-21: BOOK AMP CONFIRMED — 7.7 kHz OSCILLATION ELIMINATED

End-to-end runs with the **restored book amp** (INA217 ×2 → audio-transformer
bandpass → OP177G limiter), a signal generator driving **2440 Hz** into the
sensor coil, three cap-bank settings, plus a **grounded-input** baseline. Runs
in `Software/RPiPythonCode/data/`: `SIGNAL2440CAP1-3-8_*`,
`SIGNAL2440CAP1-3-8-11_*`, `SIGNAL2440CAP1-3-8-10-11_*`, `GROUNDED_*`
(N=24000, fs≈16224, 1.48 s, 3 runs each, df≈0.68 Hz).

**1. The chronic 7.7 kHz oscillation is GONE.** It was ~90 % of noise power on
the AliExpress module, present even shorted. On the book amp, with input
grounded, the 7–8 kHz band holds **0.02 %** of power. Restoring the book amp
fixed it, exactly as planned in the 2026-06-13 entry.

| Power in band, input grounded/shorted | Old AliExpress amp | New book amp |
|---|---|---|
| 7.5–8.0 kHz | ~90 % | **0.01 %** |
| 7.0–8.0 kHz | dominant | **0.02 %** |

**2. The ~7320 Hz peak in the SIGNAL runs is harmless.** It is exactly
3 × 2440 = 7320 Hz — the **3rd harmonic** of the injected tone (~−45 dB, mild
distortion of a deliberately strong drive). It **disappears in the grounded
run** (7–8 kHz collapses to broadband noise, peaks wandering 7145/7162/7318 Hz),
proving it is not an oscillation.

**3. Pipeline + calibration validated.** All three SIGNAL runs recover the tone
at 2439.7–2440.1 Hz (<1 bin error) with per-run SNR 52–55 dB; computed field
57.301–57.310 µT vs the expected 2440/42.5774 = **57.307 µT** — γ_p constant in
`PPMCalc.py` is correct to ~5 sig figs. Cap-bank setting barely moved SNR
(52–55 dB across all three) because the injected tone swamps the tank — tuning
only matters for the tiny real proton signal. The grounded run correctly
reported **"No peaks found above threshold"** (good null test).

**4. New dominant baseline noise = a 200–500 Hz cluster (NOT mains).** Grounded
per-band power: 0–200 Hz 11 %, **200–500 Hz 75 %**, 500–2000 Hz 12 %, proton
band 2.3–3.3 kHz only **0.95 %**, 3.3–8.1 kHz 0.7 %. ~98 % is below 2 kHz.
Checked against exact mains harmonics: **no power at 50/100/150/300/350 Hz or
60/120 Hz.** The energy is a dense cluster centred ~200–260 Hz (strongest lines
~237 Hz and ~201 Hz with closely-spaced ~2 Hz satellites) — the signature of a
**mechanical/microphonic resonance** (transformer lamination buzz or coil
vibration), not power-line hum. It is large in absolute counts (grounded total
RMS ~27 k vs ~18 k for signal runs) so it eats ADC headroom, but it is well
outside the proton band and rejectable by the transformer + digital bandpass.
**Next noise target:** chase the 200–260 Hz microphonic source (damp/clamp the
transformer and coil, check lead dress and any vibration coupling).

---

### Follow-up 2026-06-23: SHUNT + HALL-SENSOR CAPTURES — TURN-OFF CONFIRMED FAST FROM TWO NEW VANTAGE POINTS

The long-planned current-shunt capture (planned 6/10, 6/12) was finally taken,
plus a capture of the field as the Hall sensor actually sees it. These confirm,
from two *independent* vantage points, what the coil-terminal captures
(SDS00011–16) already implied: the polarizing field collapses non-adiabatically.

- `SDS00022.png` — **voltage across a ~0.1 Ω shunt** (10× 1 Ω 2 W) in the coil
  leg, i.e. **coil current**; AC-coupled, 20 µs/div, 10× probe. Flat baseline
  (steady polarizing current), then at turn-off a burst ringing at
  **11.74 kHz** (cursors = one cycle, 85.2 µs), decaying over ~2–3 cycles.
- `SDS00023.png` — **field at the UGN3503UA Hall sensor**, 20 µs/div, 10× probe.
  Periodic ripple during polarization, large excursion at turn-off ringing at
  **11.90 kHz** (one cycle = 84 µs), settling within a couple hundred µs.

**Verdict — fast enough.** Larmor period at 2435 Hz is **T ≈ 411 µs**. The
dominant field collapse is the first sharp edge (a few µs, ~100× shorter than
T) → solidly non-adiabatic. The residual ring at **~12 kHz is ~5× the Larmor
frequency**, so the protons cannot track it; it averages out rather than
re-tipping or re-polarizing the magnetization. Both shunt (current) and Hall
(field) agree on the same ~12 kHz ring and the same fast initial edge.

**LC ring identified:** L ≈ 5.4 mH with f ≈ 11.7 kHz ⇒ C ≈ 34 nF — consistent
with a ~33 nF snubber across the coil (+ FET Coss).

**Bonus — polarizing field strength from the Hall step.** The UGN3503UA is
1.3 mV/G, so the turn-off step on `SDS00023` gives the field that collapsed:
ΔY = 122 mV ÷ 1.3 mV/G ≈ **94 G ≈ 9.4 mT** inside the coil. The step ≈ B_pol
because the field drops from B_pol to ~Earth (~0.57 G, negligible). This is
comfortably above the book's design target of **≈75 G (7.5 mT)** at coil
centre — independent confirmation (beyond the 600 mm compass deflection) that
the polarizing field is on-spec in *magnitude*, not just present.
*Caveats:* AC coupling reads the step fine but not the absolute level; the
12 kHz ring makes cursor placement on the edge uncertain (dominant error);
result assumes the channel's 10× factor was applied (else it'd be a nonsensical
~940 G). Call it **~90 G, ±a bit.** For a clean number, DC-couple the Hall
output and subtract two static levels: B_pol = (V_on − V_quiescent[≈2.5 V]) /
1.3 mV/G — good to a few % and lets you map field *uniformity* by moving the
sensor inside the coil.

**Side note (not a turn-off fault):** that ~12 kHz ring is real field energy at
the sensor for ~200 µs after turn-off. Harmless to the precession physics, but
if it couples into the INA217 front-end it adds to the dead-time before the FID
is usable. If ever worth killing faster, tune an R–C snubber/clamp to damp it —
trading a slightly slower (still fast enough) edge for a shorter tail.

> Index note: `oscope_index.txt` had an off-by-one (labelled these SDS00023/4);
> corrected so SDS00022 = shunt, SDS00023 = UGN3503UA.

---

### Follow-up 2026-06-24: FIRST TUNED SAMPLE vs NO-SAMPLE RUNS — STILL NO FID; DOMINANT LINE IS THE TANK (true Larmor uncertain on basalt — see same-day addendum below, which walks back the "mistuned, retune to 2435" framing)

First sample/no-sample comparison with the **full chain in place** (book amp +
SW1 tank tuned + real polarise-sample cycles, no signal injection). Runs in
`Software/RPiPythonCode/data/`, all `ONTIM 6000 / SAMPT 1500 / SAMRA 16000 /
COOLD 10000`, differing only in DELAY and analysis band:

| Run | Sample | DELAY | Band | n |
|---|---|---|---|---|
| `SAMPLE_…11_02_05` | yes | 500 ms | 2300–3300 | 3 |
| `SAMPLED150_…11_04_07` | yes | 150 ms | 2300–3300 | 3 |
| `SAMPLED150_…11_06_10` | yes | 150 ms | 2300–3300 | 6 |
| `SAMPLE_WIDE_…11_09_40` | yes | 150 ms | wide | 6 |
| `NO_SAMPLE_WIDE_…11_13_44` | **no** | 150 ms | wide | 6 |

**No proton signal — three independent proofs (same logic as 6/13 evening, now
with the good amp + tank):**
1. **No-sample ≈ sample.** Reprocessed through the PPMCalc pipeline, the
   no-sample averaged spectrum peaks at **2373 Hz / 18.5 dB**, the sample at
   **2382 Hz / 18.5 dB** — same line, same strength. Removing the water removes
   nothing.
2. **Wrong frequency.** Every run peaks **2373–2387 Hz**, consistently ~50–60 Hz
   *below* the 2435 Hz Larmor target. Not a field-model error (that's ~2.4 %).
3. **No envelope decay.** Filtered RMS start/end ratio ≈ 0.95–1.0 in every run
   (zero-phase filtered, so not a causal-filter transient). A real FID must
   decay over the 1.48 s window; flat = steady line.

**The line IS the pickup tank, and it's mistuned.** Inserting the sample shifts
the resonance **2373 → 2382 Hz (~9 Hz up)** — the water dielectrically/inductively
loads the sensor coil, which only a *coil-resonance* line would do (external
interference wouldn't move). So the dominant feature is the LC tank ringing on
ambient/microphonic noise — and it sits at ~2380 Hz, **~55 Hz below** the 2435 Hz
Larmor frequency despite the 6/19 ring-down + 6/21 injection saying 1+3+8 ≈
2440 Hz. A tank centred at 2380 is doubly bad: it (a) manufactures the steady
2380 line and (b) **attenuates a real 2435 Hz proton signal on its resonance
skirt** (worse the higher Q). Likely loaded-Q pull and/or component drift vs the
unloaded ring-down; the live noise-excited resonance is the number that matters.

**DELAY and wide band changed nothing.** 500→150 ms DELAY left the peak at
~2383–2387 Hz (a shorter DELAY should *boost* a decaying signal; it didn't —
consistent with no FID). Widening the band to 2000–4000 Hz revealed no hidden
peak at 2435 Hz, only more steady lines (2650/2750/3050 Hz family).

**Post-processing attempts to dig out a buried FID (none succeeded — confirming
nothing is there in *this* data):**
- *Spectral background subtraction* (no-sample as background): confounded by the
  ~9 Hz sample-induced shift — the resonance doesn't line up, so the residual is
  the shifted line, not a proton peak.
- *Tail-fit resonance peel* (new tool, below): removes ~45 % of the 2380 line
  (its coherent part; the noise-excited narrowband pedestal remains), and **no
  peak emerges at 2435 Hz**; residual-head start/end ratio for sample (1.12) ≈
  no-sample (1.17).

**New analysis tools added to the repo (committed, branch
`add-run-comparison-tools`):**
- `Software/RPiPythonCode/compare_runs.py` — overlays two run sets (averaged
  spectrum + RMS envelope) to test for a real, decaying, sample-dependent signal.
- `Software/RPiPythonCode/suppress_resonance.py` — peels the steady tank line by
  fitting a constant-amplitude sinusoid on the (proton-free) record tail and
  subtracting it across the whole record, exposing any decaying head underneath.
  Exact only for a *coherent* line; suppresses (doesn't erase) a noise-excited
  one. Its real use comes *after* retuning, when line and signal coincide at
  2435 Hz and a notch would kill both.

**Highest-value next step is hardware, not software — retune the tank onto
2435 Hz** so it *amplifies* the protons instead of attenuating them (reduce total
C slightly: f ∝ 1/√C, so ~2380→2435 Hz needs C down ~4–5 %, e.g. trim the small
SW1 caps; re-verify with a ring-down *while loaded by the amp*, not unloaded).
Then re-run sample vs no-sample and use `suppress_resonance.py` to separate the
co-located line from any FID by its decay. Also still open: chase the 200–260 Hz
microphonic (6/21) that drives the resonance, and confirm polarising-coil tilt
vs the 68°35′ inclination. If a retuned, lower-noise tank *still* shows no
sample-dependent decaying head, the gap is source coupling (filling factor /
T2\*), not detection.

#### Addendum 2026-06-24 (same session) — two corrections after thinking it through

Prompted by two good questions from the user; both refine the entry above.

**(1) "How long does the ringing last? Is it weaker with a longer DELAY?"**
Measured in **raw ADC counts** (DC-removed only — *not* PPMCalc's per-record
range normalisation, which would erase absolute-amplitude differences between
runs). In-band (2300–3300 Hz) RMS:

| Run | DELAY | mean in-band RMS (counts) | per-run spread |
|---|---|---|---|
| SAMPLE | 500 ms | 1645 | 1621–1676 |
| SAMPLED150 | 150 ms | 1688 | 1669–1709 |
| SAMPLED150 ×6 | 150 ms | 1678 | 1621–1755 |

The 500 ms run is only ~2.6 % below the 150 ms run — **less than the ±4 %
run-to-run scatter** — so it is **not** meaningfully weaker. Within each record,
first-150 ms vs last-150 ms ratio ≈ 1.02 (DELAY 500) and 0.97 (DELAY 150) =
flat. A decaying component (FID or long ring-down) with τ of a few hundred ms
would show a clear drop when sampling starts 350 ms later, and head > tail;
neither happens → the in-band energy is a **steady, continuously re-driven
resonance**, not a ring-down. The *quench-excited* tank ring-down decays with
τ = Q/(πf) ≈ 0.7–2.4 ms (Q≈5–18 at ~2400 Hz) — gone within ~10 ms, long before
sampling starts at either delay (consistent with the 6/23 captures settling in
~150–200 µs). So the only "ringing" still present at 150–2000 ms is the steady
noise-driven line.

**(2) "2435 Hz is only the *likely* signal location — the field changes daily and
I'm on a basalt volcanic peninsula."** Correct, and it walks back two over-claims
in the entry above:
- **2435 Hz is the IGRF *model* value (57198 nT) and does not include the local
  crustal anomaly.** On basalt/volcanic terrain, static anomalies of ±hundreds-
  to-thousands of nT are normal; diurnal (Sq) variation adds a few nT / few Hz,
  more in a storm. So the true local Larmor could plausibly sit anywhere
  ~2300–2500 Hz. The observed 2380 Hz line = **55.74 µT**, only ~1450 nT below
  the model — entirely consistent with a basalt anomaly. (There is also a
  ~2450 Hz line = the **49th harmonic of 50 Hz mains**, the one the code warns
  about — so "the peak" is at least two interferers, not one clean feature.)
- **Therefore the "tank is mistuned ~55 Hz low → retune to 2435 Hz" advice was
  premature.** If the field really is ~55.8 µT, then 2380 Hz *is* Larmor and the
  tank may already be on target — retuning to 2435 would move *away* from the
  signal. And the tank is low-Q (~5, BW ≈ 500 Hz), so it already spans
  ~2200–2650 Hz; exact tuning isn't critical for first detection.
- **The "wrong frequency" item in the three-proofs list is the weak one** and
  should not be leaned on. The two field-independent proofs — no-sample matches
  sample, and no envelope decay — are what actually rule out a proton signal
  here, and they hold regardless of the basalt offset.

**Revised next step:** don't chase a number. **Search wide (~2200–2600 Hz) and
let the real Larmor reveal itself as the one peak that both appears only with the
sample and decays**, wherever it lands. Pinning the local field to better than
~±1000 nT needs an independent reference (or a working FID to report it) — the
model value isn't trustworthy on basalt.

#### Follow-up 2026-06-24 (later) — Arduino boot-handshake bug found & fixed

Noticed in the logs that the controller did **not acknowledge the settings for
the first run** of each session: `Sending command: 'ONTIM 6000'` →
`Received response: ''` (empty) for the first 4–5 commands, with the boot banner
`'Proton Precession Magnetometer - Coil Controller'` appearing mid-stream as a
bogus reply to `COOLD`. Cause: **opening the serial port toggles DTR and resets
the Arduino**, which then boots ~1–2 s before it listens; the host was firing the
config commands into a still-booting board. Only run 1 is affected (one port-open
per session); runs 2+ ack normally (`OK ONTIM: 6000` …).

**Data-quality implication:** `run_00` of each 2026-06-24 multi-run session
probably executed with the Arduino's **power-on default timing, not the logged
values** — in particular the SAMPLED150 / WIDE sessions' `run_00` may have used
the firmware default `DELAY`, not 150 ms. Treat `run_00` of those sessions as
suspect (drop it, or re-run). Doesn't change the no-FID conclusion (runs 2+ are
valid and tell the same story), but worth knowing.

**Fix (committed):** `PPM.PPMRun.__init__` now waits for the boot banner
(`READY_BANNER` = "Coil Controller", up to `READY_TIMEOUT_S` = 5 s) before
sending anything, via a new `_wait_for_ready()`; flushes the input buffer once
the banner is seen so the first real command gets a clean ack. Timeout is
non-fatal (boards that don't auto-reset just proceed). The log now shows a
`Controller ready: '…'` line at the start of each session. Tests added.

---

## Quick reference — key specs from the book
- Amplifier gain ≈ 3.8 M (two INA217 stages, ~1958 each; audio transformer
  bandpass ~2.3 kHz; OP177G limiter clamps ±10 V). Powered by lantern
  batteries (±12 V).
- Sensor coils: 22 AWG, 552 turns, L ≈ 3.5 mH each, ~5.9 Ω incl. cable; two
  wound opposite & in series for common-mode noise cancellation.
- Earth's-field precession frequency ≈ 1.5–2.4 kHz (example: ~2247 Hz,
  Longmont CO).
- DAQ: IOtech ADAC/5501MF, 12-bit, ≥10 ksps; acquire 0.5–3.0 s.
- Processing (Ch. 7): drop first ~2000 points, 6th-order Butterworth BPF,
  FFT, then high-res hrft to locate the peak to ~0.1 Hz.
- PC control program: `adl.c` (Appendix A). Microcontroller: `mag4.asm` for
  AT90S2313 (Appendix B).
- Book web page / calculators: http://www.exstrom.com/magnum.html and the
  Digital Signal Processing page http://www.exstrom.com/journal/sigproc/
