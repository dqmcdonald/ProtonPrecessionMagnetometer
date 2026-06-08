"""
ppm_geometry.py — Coil and sample orientation diagram for the PPM.

Prints a plain-text explanation of why the coil must be perpendicular to
Earth's magnetic field and generates a three-panel PNG diagram showing:

    Panel 1 (Option A): East–West horizontal setup viewed from the East.
        The coil axis points East (out of the page), so the coil face is
        visible as a circle.  B_earth lies in the coil plane.  No tilt needed.

    Panel 2 (Option B): North–South tilted setup viewed from the East.
        The coil axis lies in the North–vertical (meridian) plane, tilted
        (90° − |I|) above horizontal so the axis is perpendicular to B_earth.
        In the Northern Hemisphere the North end is elevated; in the Southern
        Hemisphere the South end is elevated.  The coil appears edge-on.

    Panel 3 (top view): Both options shown from above with a compass rose.

Physics background
------------------
Earth's field B_earth points toward magnetic North and at the magnetic
inclination angle I (dip angle).  Positive I means the field dips INTO the
ground (Northern Hemisphere).  Negative I means the field comes OUT of the
ground (Southern Hemisphere), because field lines emerge near the south
magnetic pole in Antarctica.

For maximum precession signal, the polarising field (along the coil axis)
must be as perpendicular to B_earth as possible.  If the polarising field
were parallel to B_earth the proton magnetisation would merely align with
Earth's field after switch-off and no precession would occur.

B_earth lies entirely in the North–vertical plane (it has no East/West
component).  Therefore the East direction is always exactly perpendicular to
B_earth regardless of inclination or hemisphere, making the East–West
horizontal coil (Option A) the simplest valid setup — no tilt or compass
alignment is required.

Default location: Christchurch, New Zealand (−43.626°, +172.726°).
Magnetic field parameters are computed from geographic coordinates.  For
IGRF-14-accurate values install ppigrf:  pip install ppigrf
Otherwise a centred-dipole approximation is used (inclination accurate to
±2°; total field rough to ±20%).
"""

import argparse
import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')   # non-interactive; no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.transforms as mtf
from matplotlib.patches import Arc


# Default location: Christchurch, New Zealand.
_DEFAULT_LAT = -43.62649
_DEFAULT_LON =  172.72553

# Proton gyromagnetic ratio / 2π in Hz/T.
# f_Larmor = PROTON_GYRO_HZ_PER_T × B_total[T]
PROTON_GYRO_HZ_PER_T = 42.5775e6


# ── Capacitor bank (book Table 5.1) ──────────────────────────────────────────

# DIP switch capacitor values in µF.  Switches close in parallel, so the total
# capacitance is the sum of the selected values.
DIP_SWITCH_CAPS_UF = [
    0.5600,   # switch  1
    0.3900,   # switch  2
    0.2200,   # switch  3
    0.1000,   # switch  4
    0.0560,   # switch  5
    0.0390,   # switch  6
    0.0220,   # switch  7
    0.0100,   # switch  8
    0.00560,  # switch  9
    0.00390,  # switch 10
    0.00220,  # switch 11
    0.00100,  # switch 12
]


def recommend_capacitors(inductance_H, larmor_hz, caps_uF=None):
    """Find the DIP switch combination that tunes the LC circuit to the Larmor frequency.

    The sensor coil (total inductance L) and the selected capacitors (parallel
    combination, total C = ΣC_i) form a series resonant circuit:

        f_resonant = 1 / (2π√(LC))

    Solving for the required capacitance:

        C_target = 1 / (L · (2π · f)²)

    With 12 binary switches there are 2¹²−1 = 4095 non-empty combinations;
    exhaustive search finds the one whose resonant frequency is closest to the
    target Larmor frequency.

    Args:
        inductance_H: Total coil inductance in Henrys (both coils in series).
        larmor_hz:    Target resonant frequency in Hz.
        caps_uF:      Available capacitor values in µF (default: Table 5.1).

    Returns:
        (target_C_uF, switch_list, achieved_C_uF, achieved_f_hz, error_hz)

        target_C_uF:    Ideal capacitance in µF.
        switch_list:    1-based switch numbers to close (list of int).
        achieved_C_uF:  Total capacitance of the best combination in µF.
        achieved_f_hz:  Resonant frequency of that combination in Hz.
        error_hz:       achieved_f_hz − larmor_hz (positive = tuned above target).
    """
    if caps_uF is None:
        caps_uF = DIP_SWITCH_CAPS_UF

    omega = 2.0 * np.pi * larmor_hz
    target_C_uF = 1e6 / (inductance_H * omega**2)   # µF

    n = len(caps_uF)
    best_switches = []
    best_C_uF     = 0.0
    best_err      = float('inf')

    for mask in range(1, 1 << n):
        C = sum(caps_uF[i] for i in range(n) if (mask >> i) & 1)
        err = abs(C - target_C_uF)
        if err < best_err:
            best_err      = err
            best_C_uF     = C
            best_switches = [i + 1 for i in range(n) if (mask >> i) & 1]

    f_achieved = 1.0 / (2.0 * np.pi * np.sqrt(inductance_H * best_C_uF * 1e-6))
    return target_C_uF, best_switches, best_C_uF, f_achieved, f_achieved - larmor_hz


# ── Magnetic field computation ────────────────────────────────────────────────

def compute_field_params(lat_deg, lon_deg, alt_km=0.0):
    """Compute magnetic inclination and total field strength for a location.

    Tries ppigrf (full IGRF-14) first; falls back to a centred-dipole
    approximation if ppigrf is not installed.

        pip install ppigrf      # for IGRF-14 accuracy

    Args:
        lat_deg: Geographic latitude in decimal degrees (negative = South).
        lon_deg: Geographic longitude in decimal degrees (negative = West).
        alt_km:  Altitude above sea level in km (default 0 = sea level).

    Returns:
        (inclination_deg, total_field_nT, method_str)

        inclination_deg: Dip angle in degrees.  Positive = field dips INTO the
                         ground (Northern Hemisphere).  Negative = field comes
                         OUT of the ground (Southern Hemisphere).
        total_field_nT:  Total field magnitude in nanoTesla.
        method_str:      Human-readable label for the method used.
    """
    try:
        import ppigrf
        # ppigrf compares the date against pandas Timestamps internally, so it
        # needs datetime.datetime (not datetime.date) to avoid a TypeError.
        date = datetime.datetime.now()
        # ppigrf.igrf(lon, lat, alt_km, date) → (Be, Bn, Bu) all in nT.
        # Bu is the upward component; inclination sign convention uses positive-down,
        # so Bdown = -Bu.
        Be, Bn, Bu = ppigrf.igrf(lon_deg, lat_deg, alt_km, date)
        # ppigrf may return 1-element numpy arrays; .item() extracts a Python scalar.
        Be, Bn, Bu = np.asarray(Be).item(), np.asarray(Bn).item(), np.asarray(Bu).item()
        Bh   = np.sqrt(Be**2 + Bn**2)
        I_deg = float(np.degrees(np.arctan2(-Bu, Bh)))
        F_nT  = float(np.sqrt(Be**2 + Bn**2 + Bu**2))
        return I_deg, F_nT, "IGRF-14 via ppigrf"
    except ImportError:
        pass

    # ── Centred-dipole fallback ────────────────────────────────────────────────
    # Inclination accuracy: typically ±1–2°.
    # Total-field accuracy: ±20%; install ppigrf for better results.
    #
    # The geomagnetic pole position is derived from the IGRF-14 dipole
    # coefficients g10, g11, h11 for epoch ~2025.
    pole_lat = np.radians(80.65)
    pole_lon = np.radians(287.35)
    lat_r = np.radians(lat_deg)
    lon_r = np.radians(lon_deg)

    # Magnetic latitude of the observer location.
    sin_mlat = float(np.clip(
        np.sin(lat_r) * np.sin(pole_lat)
        + np.cos(lat_r) * np.cos(pole_lat) * np.cos(lon_r - pole_lon),
        -1.0, 1.0))
    cos_mlat = np.sqrt(max(0.0, 1.0 - sin_mlat**2))

    # Dipole inclination: tan(I) = 2·sin(λ_m) / cos(λ_m) = 2·tan(λ_m).
    I_deg = float(np.degrees(np.arctan2(2.0 * sin_mlat, cos_mlat)))

    # Dipole total field: F = B0·√(1 + 3·sin²λ_m)
    # B0 = |g10| ≈ equatorial surface field from IGRF-14.
    B0 = 29_442.0   # nT
    F_nT = B0 * float(np.sqrt(1.0 + 3.0 * sin_mlat**2))

    return I_deg, F_nT, "centred-dipole (±2° incl., ±20% field; pip install ppigrf)"


# ── Text explanation ──────────────────────────────────────────────────────────

def print_explanation(I_deg, total_field_nT=None, lat_deg=None, lon_deg=None,
                       inductance_H=None):
    """Print a plain-text explanation of the coil orientation geometry.

    Derives all angles from the supplied inclination and explains both valid
    perpendicular orientations.  Handles both hemispheres correctly.

    Args:
        I_deg:          Magnetic inclination in decimal degrees (positive = NH).
        total_field_nT: Optional total field in nT for Larmor frequency estimate.
        lat_deg:        Optional geographic latitude for the header.
        lon_deg:        Optional geographic longitude for the header.
    """
    sh            = I_deg < 0                  # Southern Hemisphere?
    abs_I         = abs(I_deg)
    tilt_display  = 90.0 - abs_I              # Option B tilt above horizontal
    elevated_end  = "South" if sh else "North"
    vdir          = "upward" if sh else "downward"

    abs_I_int = int(abs_I)
    mins_val  = round((abs_I - abs_I_int) * 60)
    sign_ch   = '−' if sh else '+'

    bh = abs(np.cos(np.radians(I_deg)))    # horizontal fraction (always positive)
    bv = abs(np.sin(np.radians(I_deg)))    # vertical fraction; direction = vdir

    print()
    print("=" * 60)
    print("  PPM Coil & Sample Geometry")
    print("=" * 60)
    if lat_deg is not None and lon_deg is not None:
        hemi_ns = 'S' if lat_deg < 0 else 'N'
        hemi_ew = 'W' if lon_deg < 0 else 'E'
        print(f"  Location             : {abs(lat_deg):.4f}°{hemi_ns}  "
              f"{abs(lon_deg):.4f}°{hemi_ew}")
    print(f"  Magnetic inclination : {sign_ch}{abs_I_int}°{mins_val:02d}′  ({I_deg:.3f}°)")
    print(f"  Horizontal component : {bh*100:.1f}% of total field (toward magnetic N)")
    print(f"  Vertical component   : {bv*100:.1f}% of total field ({vdir})")
    if total_field_nT is not None:
        larmor = PROTON_GYRO_HZ_PER_T * total_field_nT * 1e-9
        print(f"  Total field          : {total_field_nT:.0f} nT  "
              f"({total_field_nT/1000:.3f} µT)")
        print(f"  Expected Larmor freq : {larmor:.1f} Hz")
    print()
    print("Why the coil axis must be perpendicular to B_earth")
    print("-" * 60)
    print("  The protons are polarised along the coil axis. After the")
    print("  polarising field is switched off, the magnetisation precesses")
    print("  around Earth's field. The precessing component — and therefore")
    print("  the signal — is maximised when the polarising field is as")
    print("  perpendicular to B_earth as possible.")
    print()
    print("  B_earth lies entirely in the North–vertical plane (it has no")
    print("  East/West component), so the East direction is always")
    print("  perpendicular to B_earth regardless of inclination or hemisphere.")
    print()
    print("Two valid orientations")
    print("-" * 60)
    print()
    print("  Option A — East–West horizontal  (recommended, simpler)")
    print("    • Coil axis points East–West, level (no tilt required)")
    print("    • The E–W direction is inherently ⊥ to B_earth at any")
    print("      inclination because B_earth has no East component")
    print("    • Sample bottle lies horizontally, oriented East–West")
    print()
    print(f"  Option B — Tilted in the meridian (N–S vertical) plane")
    print(f"    • Coil axis tilted {tilt_display:.1f}° above horizontal,")
    print(f"      {elevated_end} end elevated")
    print(f"    • Tilt = 90° − |I| = 90° − {abs_I:.1f}° = {tilt_display:.1f}°")
    print(f"    • Both ends of the coil axis point North/South, not East/West")
    print()
    print("  Both options give equal signal amplitude. Option A is easier")
    print("  to set up and avoids any North-finding step.")
    print()
    print("  Note: orientation affects signal strength only, NOT the")
    print("  measured field value. The Larmor frequency (and therefore")
    print("  the reported field in nT) is independent of coil orientation.")

    if inductance_H is not None and total_field_nT is not None:
        larmor = PROTON_GYRO_HZ_PER_T * total_field_nT * 1e-9
        target_C_uF, switches, C_uF, f_hz, err_hz = recommend_capacitors(
            inductance_H, larmor)

        print()
        print("LC circuit capacitor tuning")
        print("-" * 60)
        print(f"  Coil inductance      : {inductance_H * 1000:.2f} mH  (both coils in series)")
        print(f"  Target frequency     : {larmor:.1f} Hz")
        print(f"  Required capacitance : {target_C_uF:.4f} µF")
        print()
        sw_str   = ', '.join(str(s) for s in switches)
        parts    = ' + '.join(f'{DIP_SWITCH_CAPS_UF[s-1]:.4f}' for s in switches)
        print(f"  Best DIP combination : switch{'es' if len(switches) > 1 else ''} {sw_str}")
        print(f"    {parts} = {C_uF:.4f} µF")
        sign = '+' if err_hz >= 0 else ''
        pct  = abs(err_hz) / larmor * 100
        print(f"  Resonant frequency   : {f_hz:.1f} Hz  "
              f"({sign}{err_hz:.1f} Hz, {pct:.3f}% error)")

    print("=" * 60)
    print()


# ── Diagram ───────────────────────────────────────────────────────────────────

def draw_geometry(inclination_deg, output_path="ppm_geometry.png",
                  lat_deg=None, lon_deg=None, total_field_nT=None):
    """Generate and save the three-panel geometry diagram.

    All geometry is derived analytically from inclination_deg so the diagram
    is correct for any location and both hemispheres without manual adjustment.

    Coordinate convention used throughout this function:
        Side-view panels use a 2-D (North, Up) coordinate system, as seen by
        an observer looking East.  In this view:
            x-axis = North (rightward)
            y-axis = Up (upward)
            out-of-page = East

    In the Northern Hemisphere, B_earth points North-and-DOWN (into the ground).
    In the Southern Hemisphere, B_earth points North-and-UP (out of the ground),
    so the be vector has a positive y component and the coil axis (Option B)
    tilts with the South end elevated rather than the North end.

    Args:
        inclination_deg: Magnetic inclination in decimal degrees.
                         Positive = Northern Hemisphere; negative = Southern.
        output_path:     Path for the output PNG file.
        lat_deg:         Optional latitude for suptitle annotation.
        lon_deg:         Optional longitude for suptitle annotation.
        total_field_nT:  Optional total field in nT for Larmor freq annotation.
    """
    I_deg = inclination_deg
    I     = np.radians(I_deg)

    sh            = I_deg < 0               # Southern Hemisphere?
    abs_I         = abs(I_deg)
    tilt_display  = 90.0 - abs_I            # angle above horizontal (always positive)
    # tilt_rot is used for the matplotlib rotate_deg() bottle transform.
    # For NH (I>0): tilt_rot = 90-I aligns bottle with ca = (sin I, cos I) [N-up].
    # For SH (I<0): tilt_rot = 90-I = 90+|I| > 90, which also happens to equal
    # arctan2(cos I, sin I) correctly placing the bottle along ca [S-up].
    tilt_rot      = 90.0 - I_deg
    elevated_end  = "South" if sh else "North"

    # Unit vectors in the (North, Up) side-view plane.
    # be: B_earth direction (NH: North-down; SH: North-up)
    # ca: Option B coil axis — always perpendicular to be in this plane.
    be = np.array([np.cos(I), -np.sin(I)])
    ca = np.array([np.sin(I),  np.cos(I)])

    # Angle of be from the +x (North = horizontal) axis.
    # NH: negative (field below horizontal);  SH: positive (field above horizontal).
    be_angle = float(np.degrees(np.arctan2(be[1], be[0])))

    # Inclination arc: draw a small arc from horizontal to the B_earth direction.
    # matplotlib Arc goes counterclockwise from theta1 to theta2.
    # NH: be_angle < 0  → theta1=be_angle, theta2=0  (sweep through negatives: below horiz.)
    # SH: be_angle > 0  → theta1=0, theta2=be_angle  (sweep through positives: above horiz.)
    if sh:
        arc_theta1, arc_theta2 = 0.0, be_angle
    else:
        arc_theta1, arc_theta2 = be_angle, 0.0

    # Inclination label sits just outside the arc; below horizontal in NH, above in SH.
    i_label_dy = 0.17 if sh else -0.18

    # Signed degrees+minutes for inclination label.
    abs_I_int = int(abs_I)
    mins_val  = round((abs_I - abs_I_int) * 60)
    sign_ch   = '−' if sh else ''

    blen = 1.35    # B_earth arrow half-length
    clen = 1.0     # coil axis half-length

    fig = plt.figure(figsize=(16, 9))
    fig.patch.set_facecolor('#f5f5f5')

    # ── Panel 1: Option A — E-W horizontal, viewed from East ──────────────────
    # Looking from the East along the coil axis, the coil ring appears as a
    # circle (face-on).  B_earth, which lies in the N-Up plane (the coil plane),
    # is visible in full.
    ax1 = fig.add_subplot(131)
    ax1.set_xlim(-1.6, 1.6)
    ax1.set_ylim(-1.8, 1.4)
    ax1.set_aspect('equal')
    ax1.axis('off')
    ax1.set_facecolor('#f5f5f5')
    ax1.set_title('Option A — E–W horizontal\n(view from East, looking West)',
                  fontsize=10, fontweight='bold', pad=6)

    ax1.axhline(0, color='#bbbbbb', lw=1, linestyle='--')
    ax1.text(1.3, 0.06, 'horiz.', fontsize=7, color='#999999')

    # B_earth arrow.
    ax1.annotate('', xy=(be[0]*blen, be[1]*blen), xytext=(0, 0),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18), zorder=5)
    ax1.text(be[0]*blen*0.5 + 0.14, be[1]*blen*0.5 + 0.06,
             r'$B_{earth}$', fontsize=13, color='#2255cc', fontweight='bold')

    # Inclination arc and label.
    ax1.add_patch(Arc((0, 0), 0.65, 0.65, angle=0,
                      theta1=arc_theta1, theta2=arc_theta2,
                      color='#2255cc', lw=1.4))
    ax1.text(0.42, i_label_dy, f'I={sign_ch}{abs_I:.0f}°', fontsize=8.5, color='#2255cc')

    # Coil ring: axis = East = out of page, so the ring appears as a circle.
    coil_r = 0.38
    ax1.add_patch(mpatches.Circle((0, 0), coil_r, lw=2.5, edgecolor='#228833',
                                   facecolor='#e8f5e9', alpha=0.85, zorder=4))
    ax1.plot(0, 0, '.', color='#228833', markersize=10, zorder=6)
    ax1.text(0.08, -0.12, 'Coil axis\n(East, out of page)', fontsize=7.5,
             color='#228833', ha='left')

    # Sample bottle shown end-on.
    ax1.add_patch(mpatches.Circle((0, 0), 0.16, lw=1.5, edgecolor='#008888',
                                   facecolor='#cceeee', alpha=0.9, zorder=5))
    ax1.text(0.22, 0.28, 'Bottle\n(end-on)', fontsize=7.5, color='#006666')

    # Annotation: B_earth lies in the coil plane.
    ax1.annotate('', xy=(be[0]*0.38, be[1]*0.38), xytext=(be[0]*0.5, be[1]*0.5),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=1.2,
                                 mutation_scale=10, alpha=0.5))
    ax1.text(be[0]*0.6 + 0.05, be[1]*0.6 + 0.03,
             r'$B_{earth}$ lies in', fontsize=7.5, color='#2255cc', alpha=0.8)
    ax1.text(be[0]*0.6 + 0.05, be[1]*0.6 - 0.12,
             'the coil plane', fontsize=7.5, color='#2255cc', alpha=0.8)

    ax1.text(0, -1.45, 'No tilt required.\nCoil lies flat, E–W.',
             fontsize=9, ha='center', color='#224400',
             bbox=dict(boxstyle='round,pad=0.35', facecolor='#f0fff0',
                       edgecolor='#88bb88', lw=1.2))

    # Compass key for this panel (N = up, E = out of page).
    ax1.annotate('', xy=(1.2, -1.2+0.28), xytext=(1.2, -1.2),
                 arrowprops=dict(arrowstyle='->', color='#555555', lw=1.2))
    ax1.text(1.22, -1.2+0.30, 'N', fontsize=9, fontweight='bold', color='#555555')
    ax1.text(1.0,  -1.2+0.05, '⊙', fontsize=14, color='#555555', ha='center')
    ax1.text(0.66, -1.2-0.04, 'Up', fontsize=8, color='#555555')
    ax1.text(1.36, -1.27, 'E (out)', fontsize=7.5, color='#555555')

    # ── Panel 2: Option B — tilted in the meridian plane, viewed from East ────
    # The coil axis lies in the (North, Up) plane at tilt_display above horizontal.
    # NH: North end elevated.  SH: South end elevated.
    # Viewed from the East, the coil ring appears edge-on as a short thick line.
    ax2 = fig.add_subplot(132)
    ax2.set_xlim(-0.5, 2.4)
    ax2.set_ylim(-1.8, 1.4)
    ax2.set_aspect('equal')
    ax2.axis('off')
    ax2.set_facecolor('#f5f5f5')
    ax2.set_title('Option B — N–S tilted in meridian plane\n(view from East)',
                  fontsize=10, fontweight='bold', pad=6)

    cx, cy = 0.8, 0.0    # centre of diagram

    ax2.axhline(cy, color='#bbbbbb', lw=1, linestyle='--')
    ax2.text(2.22, cy + 0.05, 'horiz.', fontsize=7, color='#999999')

    # B_earth arrow.
    ax2.annotate('', xy=(cx + be[0]*blen, cy + be[1]*blen), xytext=(cx, cy),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18), zorder=5)
    ax2.text(cx + be[0]*blen*0.5 + 0.14, cy + be[1]*blen*0.5 + 0.06,
             r'$B_{earth}$', fontsize=13, color='#2255cc', fontweight='bold')

    # Inclination arc and label.
    ax2.add_patch(Arc((cx, cy), 0.65, 0.65, angle=0,
                      theta1=arc_theta1, theta2=arc_theta2,
                      color='#2255cc', lw=1.4))
    ax2.text(cx + 0.42, cy + i_label_dy,
             f'I={sign_ch}{abs_I:.0f}°', fontsize=8.5, color='#2255cc')

    # Coil axis: double-headed arrow.
    ax2.annotate('', xy=(cx + ca[0]*clen, cy + ca[1]*clen),
                 xytext=(cx - ca[0]*clen, cy - ca[1]*clen),
                 arrowprops=dict(arrowstyle='<->', color='#228833', lw=2.0,
                                 mutation_scale=14), zorder=4)

    # "Coil axis" label: NH → label near the elevated North end (right of centre);
    # SH → label near the elevated South end (left of centre).
    if sh:
        ax2.text(cx + ca[0]*clen - 0.45, cy + ca[1]*clen + 0.04,
                 'Coil axis', fontsize=9, color='#228833')
    else:
        ax2.text(cx + ca[0]*clen + 0.04, cy + ca[1]*clen + 0.03,
                 'Coil axis', fontsize=9, color='#228833')

    # Coil axis tilt arc: angle above horizontal toward the elevated end.
    # NH: elevated end is North (+x); arc from 0° to tilt_display.
    # SH: elevated end is South (−x); arc from 180°−tilt_display to 180°.
    if sh:
        ax2.add_patch(Arc((cx, cy), 0.55, 0.55, angle=0,
                          theta1=180.0 - tilt_display, theta2=180.0,
                          color='#228833', lw=1.4))
        ax2.text(cx - 0.46, cy + 0.08, f'{tilt_display:.1f}°',
                 fontsize=9, color='#228833')
    else:
        ax2.add_patch(Arc((cx, cy), 0.55, 0.55, angle=0,
                          theta1=0.0, theta2=tilt_display,
                          color='#228833', lw=1.4))
        ax2.text(cx + 0.32, cy + 0.09, f'{tilt_display:.1f}°',
                 fontsize=9, color='#228833')

    # Right-angle symbol confirming coil axis ⊥ B_earth.
    # Computed from the actual vectors, so it is correct for both hemispheres.
    ra = 0.11
    p1 = np.array([cx, cy]) + ra * be
    p2 = p1 + ra * ca
    p3 = np.array([cx, cy]) + ra * ca
    ax2.plot([p1[0], p2[0], p3[0]], [p1[1], p2[1], p3[1]], 'k-', lw=1.2, zorder=6)

    # Sample bottle: rectangle rotated to the coil axis angle.
    # tilt_rot = 90 − I_deg correctly aligns the bottle with ca for both hemispheres.
    blen_b, bwid_b = 0.85, 0.17
    bottle = mpatches.FancyBboxPatch((-blen_b/2, -bwid_b/2), blen_b, bwid_b,
                                      boxstyle='round,pad=0.01', lw=1.5,
                                      edgecolor='#008888', facecolor='#cceeee',
                                      alpha=0.9, zorder=3)
    bottle.set_transform(
        mtf.Affine2D().rotate_deg(tilt_rot).translate(cx, cy) + ax2.transData)
    ax2.add_patch(bottle)
    ax2.text(cx + ca[0]*0.72 + 0.07, cy + ca[1]*0.72 - 0.04,
             'Sample\nbottle', fontsize=8.5, color='#006666')

    # Coil viewed edge-on: the ring plane is perpendicular to the coil axis.
    # From the East, this plane appears as a short thick line along the be direction.
    cr = 0.16
    ax2.plot([cx + be[0]*cr, cx - be[0]*cr],
             [cy + be[1]*cr, cy - be[1]*cr],
             '-', color='#228833', lw=5, alpha=0.7,
             solid_capstyle='round', zorder=5)
    ax2.text(cx - 0.28, cy - 0.65, 'Coil\n(edge-on)', fontsize=8,
             color='#228833', ha='center')

    # Reference frame arrows.
    rx, ry = 2.0, 0.85
    ax2.annotate('', xy=(rx+0.3, ry), xytext=(rx, ry),
                 arrowprops=dict(arrowstyle='->', color='#555555', lw=1.3))
    ax2.text(rx+0.33, ry-0.06, 'N', fontsize=9, fontweight='bold', color='#555555')
    ax2.annotate('', xy=(rx, ry+0.3), xytext=(rx, ry),
                 arrowprops=dict(arrowstyle='->', color='#555555', lw=1.3))
    ax2.text(rx-0.13, ry+0.33, 'Up', fontsize=9, fontweight='bold', color='#555555')
    ax2.text(rx-0.04, ry+0.04, '⊙', fontsize=14, color='#555555',
             ha='center', va='center')
    ax2.text(rx-0.38, ry-0.05, 'E (out)', fontsize=7.5, color='#555555')

    ax2.text(0.05, -1.45,
             f'{elevated_end} end elevated {tilt_display:.1f}° (= 90° − |I|).\n'
             f'Coil axis lies in N–vertical plane.',
             fontsize=9, ha='left', color='#224400',
             bbox=dict(boxstyle='round,pad=0.35', facecolor='#f0fff0',
                       edgecolor='#88bb88', lw=1.2))

    # ── Panel 3: Top view — both options on a compass ─────────────────────────
    # Looking vertically downward.  Option A runs East-West (green);
    # Option B runs North-South (orange).
    ax3 = fig.add_subplot(133)
    ax3.set_xlim(-1.7, 1.7)
    ax3.set_ylim(-1.7, 1.9)
    ax3.set_aspect('equal')
    ax3.axis('off')
    ax3.set_facecolor('#f5f5f5')
    ax3.set_title('Top view (looking down)\nshowing both options',
                  fontsize=10, fontweight='bold', pad=6)

    # Compass rose.
    for dx, dy, lbl in [(0,1.35,'N'),(0,-1.35,'S'),(1.35,0,'E'),(-1.35,0,'W')]:
        ax3.annotate('', xy=(dx, dy), xytext=(0, 0),
                     arrowprops=dict(arrowstyle='->', color='#888888', lw=1.2,
                                     mutation_scale=11))
        ax3.text(dx*1.12-0.06, dy*1.12-0.06, lbl, fontsize=11,
                 fontweight='bold', color='#666666')

    # B_earth projected onto the horizontal plane: the horizontal component Bh
    # always points toward magnetic North, regardless of hemisphere.
    bh = abs(np.cos(I))
    ax3.annotate('', xy=(0, bh*1.1), xytext=(0, 0),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18))
    ax3.text(0.08, bh*0.6, r'$B_h$', fontsize=11, color='#2255cc', fontweight='bold')

    # Vertical field component symbol.
    # When viewed from directly above (top view):
    #   NH: Bv points INTO the ground = INTO the page → ⊗ with ↓
    #   SH: Bv points OUT of the ground = OUT of the page → ⊙ with ↑
    if sh:
        ax3.text(0, 0, '⊙', fontsize=16, color='#2255cc',
                 ha='center', va='center', zorder=5)
        ax3.text(0.13, -0.22, r'$B_v$ ↑', fontsize=8.5, color='#2255cc')
    else:
        ax3.plot(0, 0, 'x', color='#2255cc', markersize=12, mew=2.5)
        ax3.text(0.13, -0.22, r'$B_v$ ↓', fontsize=8.5, color='#2255cc')

    # Option A: E-W bottle.
    bl, bw = 1.1, 0.17
    bA = mpatches.FancyBboxPatch((-bl/2, 0.45-bw/2), bl, bw,
                                  boxstyle='round,pad=0.01', lw=1.5,
                                  edgecolor='#228833', facecolor='#e8f5e9',
                                  alpha=0.9, zorder=3)
    ax3.add_patch(bA)
    ax3.text(0.58, 0.45+0.12, 'A: E–W\n(no tilt)', fontsize=8, color='#1a6620')
    ax3.annotate('', xy=(0.6, 0.45), xytext=(-0.6, 0.45),
                 arrowprops=dict(arrowstyle='<->', color='#228833', lw=1.5,
                                 mutation_scale=11))

    # Option B: N-S bottle.
    bB = mpatches.FancyBboxPatch((-bw/2, -1.0), bw, bl,
                                  boxstyle='round,pad=0.01', lw=1.5,
                                  edgecolor='#cc6600', facecolor='#fff3e0',
                                  alpha=0.9, zorder=3)
    ax3.add_patch(bB)
    ax3.text(0.15, -0.5, 'B: N–S\n(tilted)', fontsize=8, color='#7a3b00')
    ax3.annotate('', xy=(0, -0.38), xytext=(0, -1.05),
                 arrowprops=dict(arrowstyle='<->', color='#cc6600', lw=1.5,
                                 mutation_scale=11))

    end_short = 'S' if sh else 'N'
    ax3.text(0, -1.52,
             f'In top view, B and A look similar.\n'
             f'The difference is the tilt: A is level,\n'
             f'B is tilted {tilt_display:.1f}° ({end_short} end up).',
             fontsize=8.5, ha='center', color='#333333',
             bbox=dict(boxstyle='round,pad=0.35', facecolor='#fffde7',
                       edgecolor='#cccc88', lw=1))

    # ── Suptitle ──────────────────────────────────────────────────────────────
    loc_str = ''
    if lat_deg is not None and lon_deg is not None:
        hemi_ns = 'S' if lat_deg < 0 else 'N'
        hemi_ew = 'W' if lon_deg < 0 else 'E'
        loc_str = (f'  |  {abs(lat_deg):.3f}°{hemi_ns}, '
                   f'{abs(lon_deg):.3f}°{hemi_ew}')
    larmor_str = ''
    if total_field_nT is not None:
        larmor = PROTON_GYRO_HZ_PER_T * total_field_nT * 1e-9
        larmor_str = (f'  |  B ≈ {total_field_nT:.0f} nT'
                      f'  →  f_L ≈ {larmor:.0f} Hz')

    fig.suptitle(
        f'Proton Precession Magnetometer — Ideal coil & sample geometry\n'
        f'I = {sign_ch}{abs_I_int}°{mins_val:02d}′{loc_str}{larmor_str}',
        fontsize=11, fontweight='bold', y=1.01)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(output_path, dpi=130, bbox_inches='tight', facecolor='#f5f5f5')
    plt.close(fig)
    print(f"Diagram saved to {output_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    """Parse arguments, compute field parameters, print explanation, save diagram."""
    p = argparse.ArgumentParser(
        description="PPM coil/sample geometry — hemisphere-aware diagram and explanation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--lat", type=float, default=_DEFAULT_LAT, metavar="DEG",
                   help="Geographic latitude in decimal degrees (negative = South)")
    p.add_argument("--lon", type=float, default=_DEFAULT_LON, metavar="DEG",
                   help="Geographic longitude in decimal degrees (negative = West)")
    p.add_argument("--inclination", type=float, default=None, metavar="DEG",
                   help="Override computed magnetic inclination (decimal degrees; "
                        "negative = Southern Hemisphere)")
    p.add_argument("--field", type=float, default=None, metavar="NT",
                   help="Override computed total field strength (nanoTesla)")
    p.add_argument("--inductance", type=float, default=7.0, metavar="MH",
                   help="Total sensor coil inductance in mH (both coils in series; "
                        "book reference: ≈ 2×3.5 = 7.0 mH)")
    p.add_argument("--output", default="ppm_geometry.png", metavar="FILE",
                   help="Output PNG path")
    args = p.parse_args()

    # Compute field parameters from lat/lon using IGRF-14 (ppigrf) or dipole fallback.
    computed_I, computed_F, method = compute_field_params(args.lat, args.lon)
    print(f"Field computation: {method}")

    I_deg       = args.inclination  if args.inclination is not None else computed_I
    F_nT        = args.field        if args.field       is not None else computed_F
    inductance_H = args.inductance * 1e-3   # mH → H

    print_explanation(I_deg, total_field_nT=F_nT, lat_deg=args.lat, lon_deg=args.lon,
                      inductance_H=inductance_H)
    draw_geometry(I_deg, args.output, lat_deg=args.lat, lon_deg=args.lon,
                  total_field_nT=F_nT)


if __name__ == "__main__":
    main()
