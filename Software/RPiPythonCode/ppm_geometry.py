"""
ppm_geometry.py — Coil and sample orientation diagram for the PPM.

Prints a plain-text explanation of why the coil must be perpendicular to
Earth's magnetic field and generates a three-panel PNG diagram showing:

    Panel 1 (Option A): East–West horizontal setup viewed from the East.
        The coil axis points East (out of the page), so the coil face is
        visible as a circle.  B_earth lies in the coil plane.  No tilt needed.

    Panel 2 (Option B): North–South tilted setup viewed from the East.
        The coil axis lies in the North–vertical (meridian) plane, tilted
        (90° − I) above horizontal so the axis is perpendicular to B_earth.
        The coil appears edge-on as a thick line.

    Panel 3 (top view): Both options shown from above with a compass rose.

Physics background
------------------
Earth's field B_earth points toward magnetic North and downward at the
magnetic inclination angle I (dip angle).  At 68°35′ N latitude, I ≈ 68.6°,
meaning the field is nearly vertical.

For maximum precession signal, the polarising field (along the coil axis)
must be as perpendicular to B_earth as possible.  If the polarising field
were parallel to B_earth the proton magnetisation would merely align with
Earth's field after switch-off and no precession would occur.

B_earth lies entirely in the North–vertical plane (it has no East/West
component).  Therefore the East direction is always exactly perpendicular to
B_earth, making the East–West horizontal coil (Option A) the simplest valid
setup — no tilt or compass alignment is required.
"""

import argparse

import numpy as np
import matplotlib
matplotlib.use('Agg')   # non-interactive; no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.transforms as mtf
from matplotlib.patches import Arc


def print_explanation(I_deg):
    """Print a plain-text explanation of the coil orientation geometry.

    Derives all angles from the supplied inclination and explains both valid
    perpendicular orientations.

    Args:
        I_deg: Magnetic inclination in decimal degrees (positive = dipping
               downward in the northern hemisphere).
    """
    tilt_deg = 90 - I_deg   # Option B tilt above horizontal
    deg = int(I_deg)
    mins = round((I_deg - deg) * 60)

    # Resolve B_earth into horizontal and vertical components.
    # Horizontal component = cos(I), vertical = sin(I).
    # At I = 68.6°: bh ≈ 37 %, bv ≈ 93 % — the field is nearly vertical.
    bh = np.cos(np.radians(I_deg))
    bv = np.sin(np.radians(I_deg))

    print()
    print("=" * 60)
    print("  PPM Coil & Sample Geometry")
    print("=" * 60)
    print(f"  Magnetic inclination : {deg}°{mins:02d}′ ({I_deg:.3f}°)")
    print(f"  Horizontal component : {bh*100:.1f}% of total field")
    print(f"  Vertical component   : {bv*100:.1f}% of total field (downward)")
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
    print("  perpendicular to B_earth regardless of inclination.")
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
    print(f"    • Coil axis points roughly North, tilted {tilt_deg:.1f}°")
    print(f"      above horizontal (North end elevated)")
    print(f"    • Tilt = 90° − I = 90° − {I_deg:.1f}° = {tilt_deg:.1f}°")
    print(f"    • Both ends of the coil axis point North/South, not East/West")
    print()
    print("  Both options give equal signal amplitude. Option A is easier")
    print("  to set up and avoids any North-finding step.")
    print()
    print("  Note: orientation affects signal strength only, NOT the")
    print("  measured field value. The Larmor frequency (and therefore")
    print("  the reported field in nT) is independent of coil orientation.")
    print("=" * 60)
    print()


def draw_geometry(inclination_deg, output_path="ppm_geometry.png"):
    """Generate and save the three-panel geometry diagram.

    All geometry is derived analytically from inclination_deg so the diagram
    is correct for any location without manual adjustment.

    Coordinate convention used throughout this function:
        Side-view panels use a 2-D (North, Up) coordinate system, as seen by
        an observer looking East.  In this view:
            x-axis = North (rightward)
            y-axis = Up (upward)
            out-of-page = East

    Args:
        inclination_deg: Magnetic inclination in decimal degrees.
        output_path:     Path for the output PNG file.
    """
    I_deg = inclination_deg
    I = np.radians(I_deg)
    tilt_deg = 90 - I_deg   # Option B coil axis angle above horizontal

    # Unit vectors in the (North, Up) side-view plane.
    # be: B_earth direction — toward North and downward at angle I below horizontal.
    # ca: coil axis for Option B — perpendicular to be, tilted tilt_deg above horizontal.
    be = np.array([ np.cos(I), -np.sin(I)])
    ca = np.array([ np.sin(I),  np.cos(I)])

    # Format degrees + minutes for the title label.
    deg = int(I_deg)
    mins = round((I_deg - deg) * 60)

    fig = plt.figure(figsize=(16, 9))
    fig.patch.set_facecolor('#f5f5f5')

    # ── Panel 1: Option A — E-W horizontal, viewed from East ─────────────────
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

    # Horizontal reference line for visual context.
    ax1.axhline(0, color='#bbbbbb', lw=1, linestyle='--')
    ax1.text(1.3, 0.06, 'horiz.', fontsize=7, color='#999999')

    # B_earth arrow in the (N, Up) plane.
    # At I = 68.6°: be ≈ (0.37, −0.93) — mostly downward, slightly northward.
    blen = 1.35
    ax1.annotate('', xy=(be[0]*blen, be[1]*blen), xytext=(0, 0),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18), zorder=5)
    ax1.text(be[0]*blen*0.5 + 0.14, be[1]*blen*0.5 + 0.06,
             r'$B_{earth}$', fontsize=13, color='#2255cc', fontweight='bold')

    # Arc showing inclination angle measured from horizontal down to B_earth.
    ax1.add_patch(Arc((0, 0), 0.65, 0.65, angle=0,
                      theta1=np.degrees(np.arctan2(be[1], be[0])), theta2=0,
                      color='#2255cc', lw=1.4))
    ax1.text(0.42, -0.18, f'I={I_deg:.0f}°', fontsize=8.5, color='#2255cc')

    # Coil ring: axis = East = out of page, so the ring appears as a circle.
    coil_r = 0.38
    coil_circle = mpatches.Circle((0, 0), coil_r, lw=2.5, edgecolor='#228833',
                                   facecolor='#e8f5e9', alpha=0.85, zorder=4)
    ax1.add_patch(coil_circle)

    # Centre dot + label indicating the axis comes out of the page.
    ax1.plot(0, 0, '.', color='#228833', markersize=10, zorder=6)
    ax1.text(0.08, -0.12, 'Coil axis\n(East, out of page)', fontsize=7.5,
             color='#228833', ha='left')

    # Sample bottle shown end-on (circle) because the bottle lies along the E-W axis.
    bottle_circle = mpatches.Circle((0, 0), 0.16, lw=1.5, edgecolor='#008888',
                                     facecolor='#cceeee', alpha=0.9, zorder=5)
    ax1.add_patch(bottle_circle)
    ax1.text(0.22, 0.28, 'Bottle\n(end-on)', fontsize=7.5, color='#006666')

    # Annotate that B_earth passes through the coil plane rather than through
    # the axis — this is the geometry that allows precession to be detected.
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

    # Compass key for this panel (N = up-right, Up = up, E = out of page).
    for ddx, ddy, lbl in [(0, 0.28, 'N'), (0, -0.28, ''), (0.28, 0, ''), (-0.28, 0, '')]:
        if lbl:
            ax1.annotate('', xy=(1.2+ddx, -1.2+ddy), xytext=(1.2, -1.2),
                         arrowprops=dict(arrowstyle='->', color='#555555', lw=1.2))
            ax1.text(1.2+ddx+0.02, -1.2+ddy+0.02, lbl, fontsize=9,
                     fontweight='bold', color='#555555')
    ax1.text(1.0, -1.2+0.05, '⊙', fontsize=14, color='#555555', ha='center')
    ax1.text(0.66, -1.2-0.04, 'Up', fontsize=8, color='#555555')
    ax1.text(1.36, -1.27, 'E (out)', fontsize=7.5, color='#555555')

    # ── Panel 2: Option B — tilted in the meridian plane, viewed from East ────
    # The coil axis lies in the (North, Up) plane at tilt_deg above horizontal.
    # Viewed from the East, the coil ring is edge-on and appears as a thick line
    # oriented perpendicular to the coil axis (i.e. along the B_earth direction).
    ax2 = fig.add_subplot(132)
    ax2.set_xlim(-0.5, 2.4)
    ax2.set_ylim(-1.8, 1.4)
    ax2.set_aspect('equal')
    ax2.axis('off')
    ax2.set_facecolor('#f5f5f5')
    ax2.set_title('Option B — N–S tilted in meridian plane\n(view from East)',
                  fontsize=10, fontweight='bold', pad=6)

    cx, cy = 0.8, 0.0   # diagram centre point

    ax2.axhline(cy, color='#bbbbbb', lw=1, linestyle='--')
    ax2.text(2.22, cy + 0.05, 'horiz.', fontsize=7, color='#999999')

    # B_earth arrow (same direction as Panel 1).
    ax2.annotate('', xy=(cx + be[0]*blen, cy + be[1]*blen), xytext=(cx, cy),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18), zorder=5)
    ax2.text(cx + be[0]*blen*0.5 + 0.14, cy + be[1]*blen*0.5 + 0.06,
             r'$B_{earth}$', fontsize=13, color='#2255cc', fontweight='bold')
    ax2.add_patch(Arc((cx, cy), 0.65, 0.65, angle=0,
                      theta1=np.degrees(np.arctan2(be[1], be[0])), theta2=0,
                      color='#2255cc', lw=1.4))
    ax2.text(cx + 0.42, cy - 0.18, f'I={I_deg:.0f}°', fontsize=8.5, color='#2255cc')

    # Coil axis: double-headed arrow showing that either end of the axis is
    # equivalent (coil is symmetric about its centre).
    clen = 1.0
    ax2.annotate('', xy=(cx + ca[0]*clen, cy + ca[1]*clen),
                 xytext=(cx - ca[0]*clen, cy - ca[1]*clen),
                 arrowprops=dict(arrowstyle='<->', color='#228833', lw=2.0,
                                 mutation_scale=14), zorder=4)
    ax2.text(cx + ca[0]*clen + 0.04, cy + ca[1]*clen + 0.03,
             'Coil axis', fontsize=9, color='#228833')

    # Arc showing the tilt angle of the coil axis above horizontal.
    ax2.add_patch(Arc((cx, cy), 0.55, 0.55, angle=0, theta1=0, theta2=tilt_deg,
                      color='#228833', lw=1.4))
    ax2.text(cx + 0.32, cy + 0.09, f'{tilt_deg:.1f}°', fontsize=9, color='#228833')

    # Right-angle symbol confirming that the coil axis is perpendicular to B_earth.
    # Drawn as two line segments forming the corner of a square, offset from the
    # intersection point along both vectors.
    ra = 0.11
    p1 = np.array([cx, cy]) + ra * be
    p2 = p1 + ra * ca
    p3 = np.array([cx, cy]) + ra * ca
    ax2.plot([p1[0], p2[0], p3[0]], [p1[1], p2[1], p3[1]], 'k-', lw=1.2, zorder=6)

    # Sample bottle: rectangle rotated to the coil axis angle.
    blen_b, bwid_b = 0.85, 0.17
    bottle = mpatches.FancyBboxPatch((-blen_b/2, -bwid_b/2), blen_b, bwid_b,
                                      boxstyle='round,pad=0.01', lw=1.5,
                                      edgecolor='#008888', facecolor='#cceeee',
                                      alpha=0.9, zorder=3)
    bottle.set_transform(
        mtf.Affine2D().rotate_deg(tilt_deg).translate(cx, cy) + ax2.transData)
    ax2.add_patch(bottle)
    ax2.text(cx + ca[0]*0.72 + 0.07, cy + ca[1]*0.72 - 0.04,
             'Sample\nbottle', fontsize=8.5, color='#006666')

    # Coil viewed edge-on: the ring plane is perpendicular to the coil axis.
    # From the East, this plane is seen almost edge-on, appearing as a short
    # thick line oriented along B_earth (perpendicular to the coil axis).
    cr = 0.16
    ax2.plot([cx + be[0]*cr, cx - be[0]*cr],
             [cy + be[1]*cr, cy - be[1]*cr],
             '-', color='#228833', lw=5, alpha=0.7,
             solid_capstyle='round', zorder=5)
    ax2.text(cx - 0.28, cy - 0.65, 'Coil\n(edge-on)', fontsize=8,
             color='#228833', ha='center')

    # Reference frame arrows (same convention as Panel 1).
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
             f'North end elevated {tilt_deg:.1f}° (= 90° − I).\nCoil axis lies in N–vertical plane.',
             fontsize=9, ha='left', color='#224400',
             bbox=dict(boxstyle='round,pad=0.35', facecolor='#f0fff0',
                       edgecolor='#88bb88', lw=1.2))

    # ── Panel 3: Top view — both options on a compass ─────────────────────────
    # Looking vertically downward, the horizontal extent of each setup is visible.
    # Option A runs East-West (green); Option B runs North-South (orange).
    # The key physical difference — A is level, B is tilted — is not visible from
    # above, so it is noted in the annotation box.
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

    # B_earth projected onto the horizontal plane: only the northward component
    # bh = cos(I) is visible from above.  The vertical component (bv = sin(I))
    # goes into the ground and is shown as a cross symbol.
    bh = np.cos(I)
    ax3.annotate('', xy=(0, bh*1.1), xytext=(0, 0),
                 arrowprops=dict(arrowstyle='->', color='#2255cc', lw=2.5,
                                 mutation_scale=18))
    ax3.text(0.08, bh*0.6, r'$B_h$', fontsize=11, color='#2255cc',
             fontweight='bold')
    # ⊗ = "into the page" symbol representing the downward B_v component.
    ax3.plot(0, 0, 'x', color='#2255cc', markersize=12, mew=2.5)
    ax3.text(0.1, -0.2, r'$B_v$ ↓', fontsize=8.5, color='#2255cc')

    # Option A: E-W bottle (horizontal rectangle at y = +0.45).
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

    # Option B: N-S bottle (vertical rectangle, centred on y = −0.5).
    bB = mpatches.FancyBboxPatch((-bw/2, -1.0), bw, bl,
                                  boxstyle='round,pad=0.01', lw=1.5,
                                  edgecolor='#cc6600', facecolor='#fff3e0',
                                  alpha=0.9, zorder=3)
    ax3.add_patch(bB)
    ax3.text(0.15, -0.5, 'B: N–S\n(tilted)', fontsize=8, color='#7a3b00')
    ax3.annotate('', xy=(0, -0.38), xytext=(0, -1.05),
                 arrowprops=dict(arrowstyle='<->', color='#cc6600', lw=1.5,
                                 mutation_scale=11))

    ax3.text(0, -1.52,
             'In top view, B and A look similar.\n'
             'The difference is the tilt: A is level,\n'
             f'B is tilted {tilt_deg:.1f}° (N end up).',
             fontsize=8.5, ha='center', color='#333333',
             bbox=dict(boxstyle='round,pad=0.35', facecolor='#fffde7',
                       edgecolor='#cccc88', lw=1))

    fig.suptitle(
        f'Proton Precession Magnetometer — Ideal coil & sample geometry\n'
        f'Inclination  I = {deg}°{mins:02d}′',
        fontsize=13, fontweight='bold', y=1.01)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(output_path, dpi=130, bbox_inches='tight', facecolor='#f5f5f5')
    plt.close(fig)
    print(f"Diagram saved to {output_path}")


def main():
    """Parse arguments, print the explanation, and generate the diagram."""
    p = argparse.ArgumentParser(
        description="PPM coil/sample geometry — diagram and plain-text explanation")
    p.add_argument("--inclination", type=float, default=68 + 35/60,
                   metavar="DEG",
                   help="Magnetic inclination in decimal degrees "
                        "(default: 68.583 = 68°35′)")
    p.add_argument("--output", default="ppm_geometry.png", metavar="FILE",
                   help="Output PNG path (default: ppm_geometry.png)")
    args = p.parse_args()

    print_explanation(args.inclination)
    draw_geometry(args.inclination, args.output)


if __name__ == "__main__":
    main()
