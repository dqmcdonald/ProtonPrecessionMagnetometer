# PPM Amplifier v2.0 — Change List / Punch List

Actionable companion to `amp-v2.0-design-review.md`. Work top-to-bottom; the
first two gate everything else. Tick the box when done.

Legend: 🔴 blocker · 🟠 should-fix · 🟡 nice-to-have

---

## 🔴 Must verify / fix before trusting the board

- [x] **Identify U1/U2 — DONE, no action.** Board photos: `ti INA217` in 16-pin
      package. INA217 exists in SOL-16 (DW) — genuine part, correct footprint.
      Pinout verified pin-by-pin vs TI datasheet (2/15=RG, 4=VIN−, 5=VIN+,
      7=V−, 10=REF, 11=VOUT, 13=V+, rest NC) — all match. Gain = 1+10k/5.11 =
      1958/stage → 3.83 M total. Correct.

- [x] **Input bias-return — RESOLVED, no action.** Coil electrical centre is
      grounded at **J2.3**, giving each INA217 input a ~3 Ω DC path to GND
      through half the coil — correct bias return for the bipolar inputs (better
      than discrete Megohm resistors, which would drop volts of offset). Caveat:
      only valid with the coil connected; running with the input open will rail
      (expected). **No design blockers remain on this board.**

---

## 🟠 Should fix

- [ ] **T1 pin 2 — RESOLVED, wiring is correct.** The 42TL016 is 600:600, 1:1,
      center-tapped; pin 2 is the **primary center tap** and is correctly left
      open (primary is driven full-winding end-to-end: pin1=U1 out, pin3=GND).
      Secondary CT (pin5) is correctly grounded, pins 4/6 → U2 diff inputs.
      Only action: add an explicit **no-connect (×) flag on pin 2** to silence
      ERC. (Downgraded from "High" after verifying the part — see review doc.)
- [ ] **Tighten decoupling** C20–C25 (100 nF) hard against each IC's V+/V− pins
      and drop a GND via right at each cap. (EMC DC-001/DC-003 — HF-instability
      path on a high-gain board.)

---

## 🟡 Nice-to-have / housekeeping

- [ ] Confirm the **GND pour is continuous and unbroken directly under U1 and
      the input traces** (2-layer board, no dedicated plane — EMC SU-001).
- [ ] Fix **courtyard overlap C13 ↔ U1** (0.57 mm²) — nudge apart.
- [ ] Fix **U3 datasheet link** — currently points to OP279, should be OP177.
      Reconcile value `OP177G` vs symbol name `OPA177G`.
- [ ] Re-sync **R4 value** — schematic `10.2K 1%` vs PCB `10.2K`.
- [ ] (Pre-fab, not functional) Populate **MPNs** on the BOM so datasheet
      verification and sourcing can run (SS-001 / DS-001).

---

## Bench notes
- Tuning is already on this board: **SW1 selects C1–C12 (0.001–0.56 µF) across
  the coil.** Pick the combination that lands the LC tank at ~2435 Hz
  (max ≈0.61 µF). No external tuning cap needed.
- After fixes, re-run the **shorted-input + envelope-decay baseline** (see
  `magnetometer-debug-notes.md`) before any sample run.

### How to do the shorted-input test correctly
J2 pinout: **pin 1 = VIN−** (U1.4), **pin 2 = VIN+** (U1.5), **pin 3 = GND**
(coil-centre node).

1. **Disconnect the coil.**
2. **Jumper all three J2 pins together: 1 = 2 = 3.** This gives zero differential
   input *and* ties both inputs to GND (keeps the INA217 bias return intact).
3. Power up, scope the output: should sit near **0 V DC** and be **quiet** —
   that is the amplifier's true noise/oscillation floor, the baseline to compare
   every coil measurement against.

**Do NOT** short only pin 2↔pin 3 (grounds VIN+ but leaves VIN− floating → that
input rails) or only pin 1↔pin 2 (zero differential but common mode floats, no
bias return → rails). **Pin 3 (GND) must be in the short.**

Optional, more realistic floor: short pin 1↔pin 2 through a **~6 Ω** resistor
(mimics the coil source resistance) with pin 3 grounded. For a first
"is it quiet / not oscillating?" check, the hard short of all three is simpler.

### How to validate the gain
Two gotchas first: (a) total gain ≈ **3.83 M (132 dB)**, so to get a safe ~2 V
output you need only ~**0.5 µV** in → inject through a **calibrated attenuator**,
never directly; (b) gain is **band-limited and clamped**, so test with a
**2435 Hz sine** and keep the output **below the ±9.8 V zener clamp**
(flat-topped output = clamping, reduce input). Common setup: **SW1 all OFF**
(no tank loading), **no coil**, ×10 probe, AC coupling.

J2 drive: feed **J2.2 (VIN+)** from the attenuator's low node; tie
**J2.1 (VIN−)** and **J2.3** to GND. (The attenuator's bottom resistor also
gives VIN+ its DC bias return.)

**Method A — quick stage-1 check (easiest, highest confidence).** The
transformer splits the chain into two identical ×1958 stages, so one stage
validates the design; trust symmetry for the rest.
1. Divider **÷1000**: 10 kΩ series + **10 Ω** to GND; drive VIN+ from the 10 Ω node.
2. Sig-gen ~**0.5 Vpp** @ 2435 Hz → ~0.5 mVpp at the input.
3. Scope **U1 pin 11** (= T1 primary pad).
4. **Gain₁ = V(U1·11) / V_in** → expect **≈1958 (65.8 dB)**, ~1 Vpp out
   (keep ≤ ~2 Vpp to stay linear).

**Method B — full-chain total gain (the real number).**
1. Divider **÷10 000**: 10 kΩ series + **1 Ω** to GND (the 1 Ω also mimics the
   coil's low source impedance). Inject ratio = 1/10001.
2. Sig-gen ≈ **5 mVpp** @ 2435 Hz → ~0.5 µVpp at the input.
3. Scope **P2 (Signal Out)**.
4. **Total gain = V(P2) × 10001 / V_gen** → expect **≈3.83 M (131.7 dB)**,
   ~2 Vpp clean sine.
   - µV injection is touchy: keep the 1 Ω resistor + leads tiny/short, keep the
     gen cable away from the output end, watch for output not tracking input
     linearly (stray pickup or clamping).

**Bonus (free with the same rig):**
- **Sweep frequency** at fixed input, plot V(P2): should **peak ~2.3–2.4 kHz**,
  −3 dB near ~300 Hz and ~3.4 kHz → validates the transformer bandpass.
- **Raise the input** until the output flat-tops at **±9.8 V** → confirms the
  D1/D2 zener clamp.

| Quantity | Predicted |
|---|---|
| Per stage (U1, U2) | 1958× = 65.8 dB |
| Total @ 2435 Hz | 3.83 M = 131.7 dB |
| Output clamp | ±9.8 V (9.1 V zener + diode) |
