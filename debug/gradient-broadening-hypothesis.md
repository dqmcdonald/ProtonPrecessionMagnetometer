# Why has there *never* been a signal? — binary-failure analysis & the gradient-broadening hypothesis (2026-07-12)

After the 07-12 "site1" runs (larger sample bottle filling one sensor coil,
rig moved ~20 m from the building) still showed nothing — comb-notch Larmor
gap empty, envelope flat, sample ≈ no-sample — the question changed from
*"why is the signal weak?"* to *"why has nothing with FID shape ever
appeared, at any point, in any data set?"* This note works that question
through the physics budget and the verification record, and lands on one
surviving hypothesis with a concrete, mostly-free test plan.

> **STATUS 2026-07-16 — ✅ HYPOTHESIS VINDICATED. Test 3 (off-site,
> non-basalt) produced the FIRST CONFIRMED PROTON FID.** The rig, **unchanged**
> from its basalt configuration, was driven ~10 km off the volcanic peninsula
> to the Groynes (braided-river sediment/gravel flats) and showed a clean
> decaying proton line: **2431.4 Hz, SNR 26–32 dB/run, T2\* ≈ 1.0 s**, present
> ONLY with the water sample, killed by a ferrous toolbox set beside the coils,
> and off the 50 Hz mains comb (2431 = 48.6 × 50). **B = 57.11 µT, matching the
> regional observatory to ~0.1%.** This lands squarely on the §4 Test 3 fork —
> *"signal appears off-site → gradient broadening confirmed."* The 2-month total
> null was **environmental**: basalt static-field gradients crushed T2\* below
> the ~40 ms amplifier-blind window at home; on sediment T2\* returns to ~1 s and
> the FID sits in plain sight, exactly as §3 predicted. Full data + analysis:
> `Software/RPiPythonCode/data/groynes/` and the 2026-07-16 section of
> `magnetometer-debug-notes.md`.
>
> **What this settles and what remains.** The *instrument* is now proven
> end-to-end — the design works. The open problem is no longer "is there a
> signal" but "make it work AT HOME on basalt," which is a **gradient-mitigation**
> task, not rig debugging. Both home-enabling levers attack the same "FID dies
> inside the ~40 ms blind window" bottleneck from opposite ends:
> **(a) smaller sample** — lengthen the gradient-limited T2\* so more FID survives
> the dead time (free, passive; costs signal amplitude — see the tradeoff
> analysis in the 2026-07-16 debug-notes section); **(b) Test 2b input clamp** —
> shorten the dead time so a full-size, short-T2\* sample is observable (hardware,
> keeps signal). See the ranked next-steps list in `magnetometer-debug-notes.md`.
>
> ---
> *Superseded status (2026-07-14, kept for the reasoning trail): hypothesis
> UNTESTED but CORNERED — `delay = 5` showed the blind window is set by
> amplifier overload recovery (~40 ms), not firmware `DELAY`; that bounded T2\*
> to either ≲ 40 ms (hidden) or nonexistent, promoting Test 3 to the decisive
> fork. Test 3 has now resolved it in favour of the hypothesis. Details in §4.*

---

## 1. The physics budget says detection should be EASY — so the failure is binary

From Design calc 2 (2026-06-13, `magnetometer-debug-notes.md`): water proton
magnetization at the measured ~8 A polarizing current gives **ε_pk ≈ 0.3 µV**
at the sensor coil, → **SNR ≈ 40+ dB single-shot untuned**, more with the
tuned tank (measured Q ≈ 5). Every scaling input in that calc is now
*measured*, not assumed: 8 A restored (07-04), quench non-adiabatic (07-03),
tank tuned to 2435 Hz (06-21), filling factor maximized (07-12 big bottle).

**Cross-check against the book's own result:** Fig 7.6 (FFT of filtered
data, Longmont CO) shows the proton peak at ~1650 counts over a ~100-count
floor — only **16× ≈ 24 dB**. The book's signal is *not* extraordinarily
strong; it is exactly what a working rig at this design point produces, and
it is *within the SNR range this rig already logs for mains harmonics*.

**Implication:** we are not 3 dB of averaging away from a detection. A
signal predicted at 25–40 dB that shows **0 dB, always,** means some element
is zeroing it categorically — a binary failure, not a marginal one.

## 2. Binary failures already excluded by the verification record

| Candidate binary failure | Excluded by | Date |
|---|---|---|
| Polarize pulse not firing | LED red over on-time + compass deflect + clamp 8 A | 07-03/04 |
| Adiabatic (slow) quench | Shunt: full collapse ≤ 66 µs vs 411 µs Larmor period | 06-12, 07-03/04 |
| Sensor coil miswired / gradiometer backwards | Sig-gen test-coil: signal ONLY inside one coil, **null when centred** — that null is the signature of correct series-opposition; a same-sense miswire would *add* for a centred source | 06-13 |
| Sensor coil open / wrong L / tank off-frequency | Ring-down: 412–416 µs period = 2.40–2.43 kHz, L ≈ 5.5 mH consistent | 06-19/21 |
| Receive chain dead (coil→amp→ADC→software) | 2436–2440 Hz injection through sensor coil: 52–60 dB, B calibration correct to 0.1% | 06-13, 06-21 |
| Pipeline fabricating/losing peaks | Grounded & shorted runs: clean "No peaks found" | 06-13, 06-21 |
| Polarizing-axis geometry null | Impossible for a horizontal EW axis: field (dip 68.6°) ⊥ East axis regardless of declination (cos∠ = cos I·sin D ≤ ~0.13 for any plausible D → ≥ 82° from parallel). NS is only cos-factor worse (×0.93), yet equally empty — orientation can modulate, not null | 06-25→07-12 data |
| Mains masking a buried line | Comb-notch: Larmor gap (2412–2438 Hz) is *empty* after notching, sample ≈ reference | 07-01, 07-12 |
| Filling factor | Big bottle fills the coil volume | 07-12 |

Nothing on this list can be the killer. What's left must be something the
tests so far are structurally blind to.

## 3. The surviving suspect: T2* crushed by local static-field gradients

### The loophole in every decay test run to date

All acquisitions use `DELAY ≥ 25 ms` between quench and first sample, and
the decay discriminators (quarter-ratio in `comb_notch.py`; even the 07-12
fine 15 ms-window test) only see **t > 25 ms**. If T2* ≈ 10 ms:

- at t = 25 ms the FID amplitude is already e^(−2.5) ≈ **8%** of ~0.3 µV ≈ 25 nV;
- its energy is spread over Δf = 1/(π·T2*) ≈ **30+ Hz** — wider than the
  25 Hz Larmor gap itself;

→ invisible to every test at any averaging depth. **A short-T2* FID has
never been excluded — it has never been *observable* with these settings.**

### Why short T2* is plausible at THIS site and not the book's

T2* in Earth's field is set by ΔB across the sample: Δf = 0.0426 Hz/nT · ΔB,
T2* ≈ 1/(π·Δf).

| ΔB across 10 cm sample | Linewidth | T2* |
|---|---|---|
| 30 nT | 1.3 Hz | 0.25 s (book-like) |
| 300 nT | 13 Hz | 24 ms (marginal at DELAY 25) |
| 500 nT | 21 Hz | **15 ms (dead before sampling)** |

- **Geology:** the book's rig ran in Longmont CO — flat sedimentary plains,
  typical gradients ~10 nT/m. This site is a **basalt volcanic peninsula**
  with documented anomalies of ±1000s nT over metres (06-24 addendum) —
  gradients of 3–5 µT/m near inhomogeneous flows are entirely plausible,
  giving 300–500 nT across the sample.
- **Rig-local ferrous sources:** a single steel screw at 10 cm produces
  µT-scale ΔB; platform brackets, the SLA battery, and a steel bottle cap
  are all candidates.
- Book Fig 7.6's peak is ~1–2 bins (~0.5–1 Hz) wide → their T2* ≳ 0.5 s.
  The authors could afford to *drop the first 0.2 s* of every record (Ch. 7)
  and still see it. On basalt that luxury may not exist.
- **Irony:** the 07-12 larger bottle *worsens* gradient broadening — more
  protons, but spanning more ΔB. (If gradients dominate, a *smaller* sample
  has a longer T2*.)

This directly formalizes the "could the local environment be broadening the
signal?" question raised 2026-07-12 — the answer is: it's the one mechanism
left standing, and it's testable for free.

## 4. Test plan (ranked)

### Test 1 — Static gradient survey at the sensor position (free, ~30 min, decisive)

Phone magnetometer (Physics Toolbox or similar) taped to a **wooden** stick;
rig, battery, and anything ferrous moved a few metres away. Map total field
|B| on a grid over ±15 cm around where the sample sits (e.g. 5×5 horizontal
+ two heights), phone in fixed orientation, average a few seconds per point.
Separately wave it near the platform hardware and the bottle cap.

**Decision thresholds:**
- ΔB > ~300 nT across the sample volume → **gradient broadening is the
  killer**; fix is site/hardware (Tests 2–3), not electronics.
- ΔB < ~100–200 nT → gradients exonerated; go to Test 4.

Caveat: phone resolution/noise ~0.1–0.6 µT — average readings, keep
orientation fixed; it resolves the >300 nT threshold but not much below it.

### Test 2 — Minimum-DELAY run (one config change) — ✅ RUN 2026-07-14; RESULT BELOW

Firmware accepts any `DELAY` value (no lower bound in
`PPMPulseControllerADC.ino`; it's a plain `delay(sample_delay)`). Quench
ring is done in ~0.3 ms and the tank rings down with τ = Q/(πf) ≈ 0.7 ms, so
**`delay = 5`** is safe. Run sample + matched no-sample, then inspect the
first ~30 ms of the comb-notched gap-band envelope at ~2 ms resolution.
A fast-decaying early bump present only with sample = the broadened FID
caught directly. (Watch for amp/transformer recovery artifacts in the
no-sample control — they'll be common to both if benign.)

#### ⚠ RESULT 2026-07-14 — the parenthetical caveat above turned out to be the whole story

Ran `delay = 5` (`data/delay/SAMPLE_5MS_2026_07_14_16_39_12`, 12 signal +
6 background). The coil-pulsed runs do show a big decaying in-band excess the
coil-off backgrounds lack — head(5–35 ms)/tail(1–2 s) envelope ratio
**6.26 ± 0.43** across all 12 runs vs **1.02** for backgrounds. **It is not an
FID:**

| observation | value | reading |
|---|---|---|
| peak count, 5–10 ms after quench | 31276 = **95% of full scale** (RMS 20565 vs steady 2060) | front end is **railed** |
| envelope decay constant | **τ ≈ 38 ms** | tank would be 0.65 ms; water T2\* is 1–2.5 s → neither |
| strongest early bin | **2349 Hz** | 47 × 50 mains, already proven pinned to mains (06-28 retune test) |
| Larmor gap (2405–2445) excess | only 1.9× over background | nothing there |

It is the pulse-induced ring parking on a mains harmonic, seen through a
saturated amplifier — a *steady* line only appears to "decay" because the
clipped gain is recovering.

**This test cannot answer the question in its current form, and Test 2's premise
was wrong.** The blind window is not set by the firmware `DELAY` at all — it is
set by **amplifier overload recovery**. The first genuinely usable sample is
~15–25 ms and the front end is not settled until **~40 ms**, essentially where
`delay = 25` already was. Shortening `DELAY` moves the *sampling* window earlier
but the *amplifier* is still saturated there, so nothing is gained.

**Consequence for the hypothesis: it is neither confirmed nor refuted — it is
still untestable.** If T2\* really is 10–15 ms, the FID is born and dies entirely
inside the interval where the front end is blind. The hypothesis' central
loophole ("no decay test has ever been able to see a short-T2\* FID") therefore
*stands*, but the fix is not a shorter delay — see Test 2b.

#### Dead-time budget: ours vs the book — and the T2\* bound it implies

The book has **no input protection either**; its answer to the overload is
simply to wait it out — `DELAY = 100 ms`, then discard the first 2000 points at
16384 Hz (= 122 ms), so **~222 ms of dead time** before it starts looking. That
is affordable *at Longmont*: at T2\* = 1–2.5 s it costs only ~9–20% of the FID.
The architecture therefore **quietly assumes a long T2\***. Against a 10–15 ms
T2\*, 222 ms of dead time leaves e^(−222/12) ≈ 10⁻⁸ of the signal — not degraded,
annihilated. **So a working book rig tells us nothing about whether this design
*could* work at a short-T2\* site: at the book's site the question never arises.**

**Our dead time is ~40 ms of amplifier recovery — about 5× better than the
book's 222 ms.** We are looking considerably *earlier* than a known-working
instrument, not later. That inverts the usual reading of a null result:

> If a normal, long-T2\* proton signal existed at this site, we would see it
> **more easily than the book does**, not less. We don't.

Combining that with the 07-14 envelope data bounds T2\* directly:

- **T2\* between ~50 ms and 2 s — EXCLUDED.** An FID in that range would leave a
  decaying excess in the 55–205 ms window; there is none (1.14× then 1.03× over
  background, and even that is the amplifier's own recovery tail).
- **T2\* ≲ 40 ms — still completely invisible**, because the front end is blind
  exactly there.

There is no comfortable middle left: **either T2\* is short enough to hide inside
the 40 ms blind window (the hypothesis, now cornered into almost exactly the
10–15 ms it predicted), or there is no signal at all.** Both remaining branches
are settled by Test 3, which needs no hardware change — see there.

### Test 2b — Stop the front end saturating (NEW; the home-enabling hardware fix)

Nothing downstream can see a short-T2\* FID until the amplifier survives the
quench without clipping. Fix: a clamp at the **INA217 inputs** (U1, the first
stage). The existing ±9.1 V zener limiter sits at the *output* of the chain
(OP177G): it protects the ADC but does nothing for the in-amp being slammed.
Target: recovery in milliseconds, not tens of them, so that a 10–15 ms FID is
actually observable. Re-run Test 2 afterwards.

**What the clamp does — and does not — do.** It is *not* meant to keep U1
linear through the transient (no passive diode can: U1's gain is 1958, so it
saturates at only ~5 mV differential — see amp-v2.0-design-review.md item 1 —
and a silicon clamp holds ±0.6 V, still ~120× into overload). Its job is to
**limit overdrive depth**, since overload-recovery time scales with how hard
the input was driven: clamping a ~30 V kick to ~0.6 V cuts overdrive from
~6000× to ~120× (~50×), which is the lever that should pull the 40 ms recovery
down toward a few ms.

**Where the diodes go — each input to GROUND (recommended for this topology).**
The sensor coil lands on J2 with its electrical **centre grounded at J2.3**
(the gradiometer mid-point; amp-v2.0-design-review.md item 2), so the two coil
ends drive **U1 pin 4 (V_IN−)** and **pin 5 (V_IN+)** push-pull about ground.
Put an **anti-parallel diode pair from each input node to GND** (4 diodes, or
two dual packages) — this bounds each pin to ±one diode drop and, because the
centre tap already references ground, clamps both the differential and the
common-mode excursion.

```
 J2.1 ─[½ coil]─┬─ Rs(opt) ─┬──────── U1 pin 4 (V_IN−)
 J2.3 ─ GND     │           ⊥ D1a▼ D1b▲ → GND
 J2.2 ─[½ coil]─┴─ Rs(opt) ─┬──────── U1 pin 5 (V_IN+)
                            ⊥ D2a▼ D2b▲ → GND
```

Alternatives: *across the coil* (pin 4↔pin 5) is a simpler 2-diode differential
clamp — fine here since the grounded CT largely pins the common mode — but it
leaves common-mode unbounded, so to-ground is preferred. *Clamping to the ±12 V
rails* is the textbook in-amp method but clamps at ±12.6 V, far too loose for a
part that saturates at 5 mV — not useful here.

**Diode spec.** The usual worry (clamp leakage injecting offset into a µV path)
is a **non-issue here**: the source impedance is only ~3 Ω through half the
coil, so even 25 nA of leakage is ~75 nV of offset and the shot noise is
~0.01 pV/√Hz. So the choice is driven by **clamp tightness and surge survival**,
not leakage.

| Parameter | Want | Note |
|---|---|---|
| Type | fast **silicon** switching diode | 0.6 V clamp; Schottky (0.3 V) clamps marginally tighter and its µA leakage is tolerable at 3 Ω, but U1 saturates either way so the gain is small |
| trr | < ~50 ns | catch the fast quench edge |
| Surge IFSM | ≥ ~1–2 A non-repetitive | survive the kick |
| Capacitance | < ~5 pF | irrelevant at 2.4 kHz / low-Z |

Concrete parts: **1N4148 / 1N4148W** (cheap, trr ~4 ns, ~2 A surge, <1 nA typ
leakage — two per input to GND); or **BAV199** (SOT-23 dual low-leakage, tidy
per-input pair); **BAS416** if belt-and-braces ultra-low leakage is wanted (not
needed at 3 Ω). Avoid Schottky only if the front end later moves to a high-Z
input.

**Series resistor Rs (optional).** The coil's ~5.4 mH already limits di/dt into
the clamp, so a bare 1N4148 will likely survive. To guarantee it, add
**10–22 Ω** per input between coil and clamp node (clamp on the IC side of Rs).
Noise cost is small — 2× 13 Ω raises front-end noise ~1.3 → ~1.45 nV/√Hz
(~12 %). Keep ≤ ~22 Ω; 100 Ω would double the noise.

**Before cutting copper:** scope U1 pin 4/5 to GND (10× probe) during a quench
to measure the *actual* transient amplitude and duration — that confirms the
surge rating and whether Rs is needed. **Expect partial success:** the ±0.6 V
clamp reduces recovery depth but does not restore linearity, so if the scope
still shows recovery too long after clamping, escalate to **active input
blanking** — a small FET that shorts/disconnects the U1 inputs during the
polarize+quench window and releases just before sampling. That is the definitive
fix (keeps U1 out of overload entirely) but a bigger change; try the passive
clamp first. (U1 also has weak internal input-protection diodes; the external
clamp offloads them regardless.)

**Control still owed on Test 2 either way:** `BKGND` never energises the coil,
so it cannot reproduce a pulse-induced transient, and the 07-14 session had no
coil-pulsed no-sample run. Run one at `delay = 5` (same settings, bottle
removed). If the early excess is unchanged without the sample, it is 100%
amp/mains, as the numbers above imply.

### Test 3 — One session on non-basalt ground — ✅ **RUN 2026-07-16: SIGNAL APPEARED — hypothesis confirmed**

> **RESULT (Groynes, sediment/gravel flats, ~10 km off-basalt, rig unchanged):**
> first confirmed proton FID — 2431.4 Hz, SNR 26–32 dB/run, **T2\* ≈ 1.0 s**,
> sample-dependent, off the mains comb, killed by a nearby ferrous mass, B =
> 57.11 µT (observatory-matched to 0.1%). This is the "signal appears off-site"
> branch below → **gradient broadening confirmed**. See the top-of-file STATUS
> block and the 2026-07-16 debug-notes section for the full five-proof writeup
> and next steps. The rest of this section is the pre-run rationale.


A beach / alluvial flat kills the basalt gradient AND the mains comb in one
trip (rig is already fully battery-portable). If Test 1 shows big gradients,
this is the confirming experiment: a clean site should produce a
book-quality narrow line if broadening is the whole story.

**Promoted 2026-07-14** (planned for ~2026-07-16). Given the T2\* bound above,
this is now the experiment that settles the question, and it needs **no hardware
change at all**. At a low-gradient site T2\* should return to 1–2.5 s, and such
an FID is only ~2–4% decayed by the time our amplifier clears at 40 ms — it would
sit there in plain sight with the rig exactly as it stands today.

- **Signal appears off-site** → gradient broadening **confirmed**. The basalt
  site then needs Test 2b (input clamp) to be usable at all, and we know exactly
  why.
- **Nothing appears off-site either** → the hypothesis is **dead**, and the fault
  is something the verification record has not caught.

Use **`delay = 25`**, not 5: the 5 ms buys nothing while the amplifier is blind
for ~40 ms regardless, and 25 keeps the capture directly comparable with every
historical run. Take a coil-pulsed no-sample control at the same site.

### Test 4 — Only if the survey is clean: re-verify the budget's inputs

If gradients are exonerated, some budget assumption is broken. Measure
(a) the polarizing field actually present *at the sample* — phone
magnetometer at reduced current (~0.5 A so the sensor isn't saturated),
scale linearly to 8 A; expect ~60–70 G equivalent at centre; and
(b) absolute receive sensitivity — a calibrated µV-level injection
(divider + test coil per the 06-13 setup) to put a hard number on the
smallest detectable coil EMF.

## 5. Tilt sweep: demoted

The planned tilt sweep can't explain or fix a *total* null: geometry gives
the horizontal-EW polarizing axis ≥ 82° from the field for any plausible
declination error, and orientation errors only cost cos-factors (NS, which
is geometrically 21° worse, is just as empty). Run the gradient survey
first; revisit tilt only as an optimization *after* a first detection.

---

*Session data behind this note: `Software/RPiPythonCode/data/site1/`
(SAMPLE/NOSAMPLE × EW/NS, 2026-07-12), comb-notch plots
`comb_notch_spectrum_EW.png` / `_NS.png` in the same dir. Prior EMF budget:
"Design calc 2" in `magnetometer-debug-notes.md` (2026-06-13).*
