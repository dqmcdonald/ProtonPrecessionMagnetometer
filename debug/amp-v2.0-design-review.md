# PPM Amplifier v2.0 — KiCad Design Review (2026-06-13)

Reviewed: `Hardware/PPM Amplifier v2.0` (`.kicad_sch` + `.kicad_pcb`).
Tools run: schematic analyzer, PCB analyzer (`--full`), cross-domain, EMC
pre-compliance, ngspice. 45 components, 53 nets, 130×60 mm, 2-layer, all-SMD.

**Verification basis: CONSISTENCY ONLY.** No MPNs on the BOM (0/27) and no
`datasheets/` directory (analyzer DS-001 + SS-001 errors). Every pin-level claim
below is read from the *custom* `DQM:` library symbols and the netlist — it is
**not** verified against manufacturer datasheets. The two custom analog ICs
(U1/U2) are the weakest point and need datasheet confirmation (see Blocker 1).

---

## Verdict

The architecture is sound and the layout is genuinely good for a high-gain
analog board (clean left-to-right flow, transformer breaking the DC chain,
full decoupling, output limiter). After verifying the parts from the board
photos and confirming the coil wiring, **both original blockers are cleared**:
the in-amps and transformer are correct and genuine, and the input bias-return
is provided by the grounded coil centre tap (J2.3). **No design blockers
remain.** If this board still gives no signal, the cause is upstream of the amp
(proton-signal generation/coupling, or the tank simply not tuned via SW1), not
in the amplifier design. Remaining items below are layout/robustness
improvements, not blockers.

---

## Blockers — verify before trusting the board

### 1. U1/U2 in-amp — VERIFIED CORRECT (resolved from board photos + datasheet)
Board photos show the chips marked `ti INA217 3BAVQKT` in a 16-pin package.
The INA217 **is** offered in a **SOL-16 (wide SO-16, "DW") package**
(INA217AIDW) — not just DIP-8 — so these are **genuine INA217** and the
16-pin `SOIC-16W` footprint is correct.

Pinout verified pin-by-pin against the TI INA217 datasheet SOL-16 diagram:

| Board pin | Wired to | Datasheet (SOL-16) | Match |
|---|---|---|---|
| 2 & 15 | R1/R2 = 5.11 Ω | RG1, RG2 | ✓ |
| 4 | J2.1 / cap bank | V_IN− | ✓ |
| 5 | J2.2 / SW1 | V_IN+ | ✓ |
| 7 | −12 V | V− | ✓ |
| 10 | GND | REF | ✓ |
| 11 | T1 primary | V_OUT | ✓ |
| 13 | +12 V | V+ | ✓ |
| 1,3,6,8,9,12,14,16 | NC | NC | ✓ |

Every pin matches. Gain = 1 + 10 kΩ/R_G = 1 + 10000/5.11 = **1958/stage →
3.83 M total**, matching the 3.8 M design figure. In-amp stages are correctly
specified, footprinted, wired, and genuine. **No action.**

### 2. Input DC bias-return — RESOLVED (grounded coil centre tap)
Earlier flagged as a blocker because the U1 inputs (pins 4/5) connect only to the
coil + DC-blocking tuning caps, with no resistor to ground. **User confirmed the
coil's electrical centre is tied to GND at J2.3** (the gradiometer mid-point).
That gives each input a **~3 Ω DC path to ground through its half of the coil** —
a fully defined common mode and a proper bias-current return for the INA217's
bipolar (µA) inputs. **No action.**

Note: this is the *correct* solution and better than discrete resistors — a
megohm-to-ground would drop µA×MΩ ≈ volts of offset on a bipolar-input part;
the ~3 Ω coil path drops only microvolts. Caveat (operational, not a flaw): the
bias return exists only when the coil is connected. Powering the board with the
input **open** (no coil) will rail — expected; a shorted-input test is fine.

---

## High — should fix

### 3. T1 wiring — VERIFIED CORRECT (downgraded from a flag)
Resolved after looking up the part. The **42TL016 is 600 Ω : 600 Ω, 1:1,
center-tapped** (±3 dB 300 Hz–3.4 kHz, 75 mW). Standard 6-pin layout:
primary 1-2-3 with **pin 2 = center tap**; secondary 4-5-6 with **pin 5 =
center tap** (matches the symbol — pin 2 is named "PM" = primary mid).

Your wiring: pin 1 ← U1 output, pin 3 → GND, **pin 2 (primary CT) open**;
pin 5 (secondary CT) → GND, pins 4/6 → U2's two inputs. This is **correct**:
the primary is driven full-winding end-to-end (1→3) for the full 1:1 ratio with
the CT unused, and the grounded secondary CT converts to a balanced ±
differential drive into U2. A floating *center tap* is the intended state, not
a fault.

What the transformer buys the design: (1) 1:1 interstage coupling; (2) **DC
block** — U1's offset (×~2000) can't cross it, so the 3.8 M gain chain doesn't
rail; (3) single-ended→balanced conversion for U2's in-amp inputs (good CMRR);
(4) the **band-defining bandpass** (~300 Hz–3.4 kHz) bracketing the 2435 Hz
Larmor line, rejecting sub-300 Hz drift/hum and >3.4 kHz junk (incl. the
near-Nyquist oscillation class seen on the other amp).

**Only action:** add an explicit no-connect (×) flag on pin 2 to silence ERC.
**Bench note:** a 600 Ω secondary into a high-Z in-amp input is lightly damped
and may peak/ring around the band. Usually desirable (sharpens the 2.4 kHz
bandpass); if it rings on a scope, add a ~10–100 kΩ damping resistor across the
secondary (pins 4–6).

### 4. Decoupling placement (EMC DC-001/DC-003)
The schematic decoupling is correct (10 µF + 100 nF per rail on all three ICs).
But the layout places several 100 nF caps (C20–C25) **far from the IC pins and
far from a stitching via**. On a 3.8 M-gain board, a long decoupling return loop
is a classic HF-instability path — the same oscillation class you just measured
on the AliExpress amp. **Action:** pull C20–C25 hard against each IC's V+/V−
pins and drop a ground via immediately at each cap.

---

## Medium — good practice

- **Ground plane — RESOLVED.** User confirmed (PCB image) the GND pour is
  **continuous across the whole board** (both layers, filled, unbroken under
  U1/U2/T1/U3 and the input traces), brought out to the system at a single
  through-hole `J8 "1 GND"`. The single external tie is good practice for a µV
  front-end (star ground — one entry point avoids ground loops with the rest of
  the instrument). One thing to keep healthy: the *inter-layer* stitching
  between the top and bottom pours — the analyzer found 6 GND vias; make sure a
  few of them sit **right at each IC's ground pin and beside each decoupling
  cap** (see item 4) so return currents have a short local path between layers,
  not just the one external tie. Not a slot/continuity problem — a
  via-distribution nicety.
- **Courtyard overlap C13 ↔ U1 (PM-001, 0.57 mm²).** Nudge them apart.
- **U3 datasheet/name mismatch.** Value `OP177G` (ADI precision op-amp), symbol
  `DQM:OPA177G` (TI naming), but the attached datasheet URL points to the
  **OP279** (a different, rail-to-rail part). Cosmetic, but fix the link so the
  next reviewer isn't misled.
- **R4 value mismatch** schematic `10.2K 1%` vs PCB `10.2K` (XV-002). Harmless;
  re-sync.

---

## What's good (keep it)

- **Layout topology is well suited to high gain:** strict left→right flow —
  J2 in (x≈48) → cap bank/SW1 → U1 → T1 → U2 → U3 → P2 out (x≈167), ~**119 mm
  input-to-output separation.** Gross output→input feedback coupling is
  unlikely. Nicely done.
- **Transformer between the two ×~1958 stages breaks the DC gain chain** — U1's
  offset (×~2000) can't cascade into U2. The 3.8 M gain exists only in the
  transformer's AC passband (~2.3 kHz). This is the right way to build it.
- **Full per-rail decoupling** (10 µF bulk + 100 nF HF) on all three ICs.
- **Output limiter:** U3 (OP177) is a unity-gain inverter with anti-series
  9.1 V zeners (D1/D2) clamping the output to ≈±9.8 V — protects the ADC.
  ngspice confirms gain = −1.0 (0 dB).
- **The tuning cap bank is on this board.** C1–C12 (0.001–0.56 µF) are switched
  by SW1 *across the coil/inputs* — i.e. your LC-tank tuning cap is here and
  selectable. Max ≈0.61 µF matches the Larmor-tuning calc. (So "do the tuning"
  = pick the right SW1 combination, not add external parts.)

---

## Not performed / limits

- **Datasheet verification:** not done — no MPNs, no `datasheets/`, no DigiKey
  creds. All pin/gain claims are consistency-only. **Blocker 1 is unresolved
  until you supply the U1/U2 part number.**
- **Thermal:** N/A — all three ICs dissipate <0.1 W; not thermally limited.
- **Lifecycle/obsolescence:** not done — needs MPNs + network.
- **Gerbers:** none present in the project.
- **SPICE:** only U3 was auto-simulatable (transformer-coupled in-amp stages
  can't be simulated from detected subcircuits). It passed.

---

## Top 3 actions, in order
1. Read the U1/U2 chip top-mark and confirm the **actual part + pinout** (Blocker 1).
2. Add **input bias-return resistors** to GND, unless the coil already grounds
   the common mode (Blocker 2).
3. Tighten **C20–C25 decoupling** to the IC pins with a via at each (High 4).
