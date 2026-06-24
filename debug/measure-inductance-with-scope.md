# Measuring Sensor-Coil Inductance with an Oscilloscope

Goal: measure the sensor coil's inductance (L ≈ 7 mH expected: two ~3.5 mH
coils in series) using a scope + signal generator, independent of the LC meter.
The scope measures *frequency* far more accurately than a cheap LC meter
measures inductance (the Siglent even has a hardware frequency counter), so the
resonance method below sidesteps the LC meter entirely and gives the number we
actually care about for tuning the tank.

---

## Method 1 (recommended): LC ring-down

Hang a known capacitor across the coil to form a tank, "kick" it with a square
wave, and read the ringing frequency. L falls straight out of the resonance
formula.

```
  SigGen ──[ R_s 4.7k ]──┬──────────┬──── scope CH1 (x10 probe)
  square wave            │          │
   ~100 Hz, few Vpp     ═══ C      ███ L   (sensor coil ≈ 7 mH)
                         0.1 µF      ███
   SigGen GND ───────────┴──────────┴──── scope GND
```

- **C**: a film cap (polypropylene/polyester) you trust — measure it first or
  use its nominal. 0.1 µF puts the ring at ~6 kHz (plenty of cycles to read).
- **R_s ≈ 4.7 kΩ**: isolates the generator's 50 Ω so it doesn't damp the tank.
  Value isn't critical.
- **Drive**: square wave, ~100 Hz, a few volts. Each edge is a step that excites
  the tank; it rings and decays before the next edge.

**Read it:** AC-couple the scope, trigger on the ring, measure one ringing
period T (or let the hardware counter / an FFT give f0 directly). Then:

    L = 1 / [ (2π f0)² · C ]

**What to expect** if L really is 7 mH and C = 0.1 µF: **f0 ≈ 6.0 kHz**.
Quick gut check: 7 mH × 0.1 µF → 6.0 kHz; read 5 kHz → L ≈ 10 mH; 7 kHz → ≈ 5 mH.

**Bonus — Q for free:** count how many cycles it takes for the ring envelope to
decay to ~37% of its initial amplitude; **Q ≈ π × (that cycle count)**. At 6 kHz
expect ~14 cycles (Q rises with frequency, so this won't equal the Q≈18 at
2435 Hz — that's fine).

**Double bonus:** swap in the candidate **tuning cap (~0.56–0.62 µF)** and the
ring should land at **~2435 Hz** — confirming L, the cap value, and the tuning
calc all at once.

---

## Method 2 (no cap, cross-check): RL time-constant

Independent number with no capacitor:

```
  SigGen ──[ R 100Ω 1% ]──┬──── scope CH1 (across coil)
  square wave 1 kHz       ███
   ~5 Vpp                 ███ L (coil)
                          │
  GND ────────────────────┴────
```

Probe **across the coil**: at each edge the voltage jumps up, then decays
exponentially to ~0 with τ = L / (R + R_coil + 50 Ω). Measure τ (the 37% point
of the decay), then:

    L = τ · (R + R_coil + 50)

With R = 100 Ω and R_coil ≈ 5.9 Ω, expect **τ ≈ 45 µs** for 7 mH. Use ~20 µs/div.
Less precise than resonance (time-constant reads are softer, and you need
R_total accurately) — treat it as the sanity cross-check. If both methods agree,
the LC meter was fine; if they agree with each other but not the meter, trust
these.

---

## Accuracy notes

- Resonance accuracy is limited by **cap tolerance**: L ∝ 1/C, so ±5% cap →
  ±5% L. Use a film cap and, if possible, measure it (capacitance ranges on
  cheap LC meters are usually more trustworthy than the inductance ranges).
  Measuring 2–3 caps and averaging tightens it.
- Use a **x10 probe** so probe capacitance (~100 pF) doesn't perturb a 0.1 µF
  tank — negligible here, but good habit.
- Measure with the coil in its **final wiring** (both sensor coils in series, as
  used) so you get the real 7 mH the tank will see, not one coil.

---

Reference values:
- Sensor coils: 22 AWG, 552 turns, ~3.5 mH each, ~5.9 Ω incl. cable; two in
  series-opposition → L ≈ 7 mH total.
- Target tuning: f0 = 2435 Hz (local field 57198 nT, Larmor ≈ 2435 Hz)
  → C ≈ 0.61 µF, Q ≈ 18, BW ≈ 135 Hz.
