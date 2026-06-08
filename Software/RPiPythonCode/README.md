# Proton Precession Magnetometer — Raspberry Pi Software

Python software for controlling and analysing a Proton Precession Magnetometer (PPM).
The system polarises a water sample with an electromagnet, then measures the Larmor
precession frequency of the protons as they relax back into alignment with Earth's
field.  The Larmor frequency is directly proportional to the total magnetic field
strength:

```
B (µT) = f (Hz) / 42.5775
```

---

## Hardware

| Component | Detail |
|-----------|--------|
| Controller | Raspberry Pi (any model with a UART) |
| Microcontroller | Arduino Pro Mini |
| Serial connection | `/dev/serial0`, 57600 baud |
| Coil | Solenoid wound around a water-filled sample bottle |

The Arduino controls the polarising coil (MOSFET switched) and samples the precession
signal via an ADC.  The Raspberry Pi sends configuration commands and retrieves the
raw sample data over serial.

### Coil and sample orientation

For maximum signal the coil axis must be **perpendicular to Earth's field**.
Earth's field lies entirely in the North–vertical plane, so there are two
equally valid setups:

- **Option A (recommended):** Orient the coil axis **East–West**, level.
  No tilt required — East is always perpendicular to Earth's field.
- **Option B:** Orient the coil axis in the North–South vertical plane,
  tilted `(90° − inclination)` above horizontal with the North end elevated.
  At 68°35′ inclination this is 21.4° above horizontal.

Run `ppm_geometry.py` for a diagram and full explanation tailored to your location.

---

## Installation

```bash
pip install pyserial numpy matplotlib scipy
```

All dependencies run on Raspberry Pi OS without additional system packages.

---

## Running a measurement

```bash
python ppmrun.py [options]
```

Each run creates a timestamped directory under `data/` containing the raw data
files, plots, and a log.

### Common examples

```bash
# Single run with default settings
python ppmrun.py

# Tag the run for easy identification
python ppmrun.py --tag outdoor_test

# Average 5 runs (improves SNR by √5)
python ppmrun.py --runs 5 --tag hillside

# Adjust hardware timing (e.g. longer polarisation)
python ppmrun.py --on-time 8000 --sample-time 2000

# Narrow the bandpass filter around the expected Larmor frequency
python ppmrun.py --low-freq 2200 --high-freq 2700

# Re-analyse an existing data file without any hardware
python ppmrun.py --input data/ppm1.dat --tag reanalysis

# Collect data without generating plots
python ppmrun.py --no-plots
```

### All options

| Option | Default | Description |
|--------|---------|-------------|
| `--input FILE` | — | Re-analyse an existing `.dat` file; no hardware required |
| `--tag TAG` | `PPM` | Prefix for the output directory name |
| `--runs N` | `1` | Number of measurement cycles to average |
| `--on-time MS` | `6000` | Coil polarisation duration (ms) |
| `--sample-time MS` | `1500` | Sampling duration after coil off (ms) |
| `--sample-rate HZ` | `16000` | Requested ADC sample rate (Hz) |
| `--delay MS` | `500` | Delay between coil-off and sampling start (ms) |
| `--cool-down MS` | `10000` | MOSFET cool-down time between runs (ms) |
| `--low-freq HZ` | `2300` | Bandpass filter lower cutoff (Hz) |
| `--high-freq HZ` | `3300` | Bandpass filter upper cutoff (Hz) |
| `--fft-threshold MAG` | `0.0005` | Minimum periodogram magnitude for peak detection |
| `--no-plots` | off | Skip generating PNG graphs |
| `--output-dir DIR` | `data/` | Base directory for output |

### Output files

Each run produces a directory `data/<TAG>_YYYY_MM_DD_HH_MM_SS/` containing:

| File | Description |
|------|-------------|
| `run_00.dat`, `run_01.dat`, … | Raw ADC data for each measurement cycle |
| `original_00.png`, … | Three-panel plot of the raw signal (start / middle / end) |
| `filtered_00.png`, … | Same plot after bandpass filtering |
| `fft_averaged.png` | FFT periodogram averaged across all runs |
| `ppm.log` | Timestamped log of the session |

### Interpreting results

The strongest FFT peak is reported together with the implied field strength:

```
Strongest peak: 2435.3 Hz  →  B = 57.20 µT
Other candidates: 2448.1 Hz (mag=0.0008), 2421.7 Hz (mag=0.0006)
```

Expected Larmor frequency for your location (inclination 68°35′, ~57 200 nT):
**≈ 2435 Hz**.  If the reported peak is substantially higher or lower the signal
may be dominated by interference rather than genuine proton precession — check
hardware connections and coil orientation.

---

## Multi-run averaging

The `--runs N` flag collects N complete measurement cycles and averages their
FFT periodograms before peak detection.  Averaging in the frequency domain
does not require the signals to be phase-aligned; SNR improves by approximately
√N.  Each cycle includes the full polarisation + cool-down sequence, so N = 5
takes roughly `N × (ON_TIME + DELAY + SAMPLE_TIME + COOL_DOWN)` seconds
(≈ 90 s with default timings).

---

## Data file format

`.dat` files use a plain-text format:

```
<num_samples>
<actual_sample_rate_hz>
<sample_0>
<sample_1>
…
```

All values are integers.  Files can be re-analysed at any time with `--input`.

---

## Serial protocol

Command and control is ASCII.  Each command is a 5-character token with an
optional integer parameter, terminated by `\n` (e.g. `ONTIM 6000`), and the
Arduino replies with an acknowledgement line.

Measurement data, however, is returned as a single little-endian **binary**
frame.  This is roughly 3× more compact than a line-based ASCII format and
avoids per-sample text parsing for the tens of thousands of samples in a run:

```
bytes 0-3   marker  b'PPMD'
bytes 4-7   actual_sample_rate  (uint32)
bytes 8-11  num_samples         (uint32)
then        num_samples × int16 samples (signed two's complement)
```

The on-disk `.dat` files remain plain text (see above); only the
over-the-wire transfer is binary.

---

## Geometry diagram

```bash
python ppm_geometry.py                          # uses built-in inclination 68°35′
python ppm_geometry.py --inclination 51.5       # London, for example
python ppm_geometry.py --output my_diagram.png
```

Prints a text explanation of the coil orientation and saves a two-option diagram
showing the East–West horizontal setup (Option A) and the tilted meridian-plane
setup (Option B).

---

## Module reference

### `PPM.py`

Hardware interface.  Communicates with the Arduino over serial.

```python
ppm = PPM.PPMRun(logger)
ppm.configure(on_time=6000, sample_time=1500, sample_rate=16000,
              delay=500, cool_down=10000)
ppm.sendConfiguredValues()
ppm.doMeasurement(output_path="data/my_run/run_00.dat")

sample_rate = ppm.getActualSampleRate()   # Hz, as measured by Arduino
signal      = ppm.getSignalData()         # numpy array of ADC counts
```

### `PPMCalc.py`

Signal processing.  Works entirely on in-memory data; no hardware dependency.

```python
# Load from a saved file
sample_rate, num_samples, data = PPMCalc.load_from_file("data/ppm1.dat")

calc = PPMCalc.PPMCalc(sample_rate, sample_time_ms, data)

calc.plotSignal("raw.png")                # three-panel start/middle/end plot
calc.filterSignal(2300, 3300)             # Butterworth bandpass filter in-place
calc.plotSignal("filtered.png")
calc.plotAmplitudeEnvelope("envelope.png")  # RMS amplitude vs time

peaks = calc.doFFT("fft.png",             # returns [(freq_hz, magnitude), …]
                   low_freq=2300,         # sorted by magnitude descending
                   high_freq=3300,
                   threshold=0.0005)
```

### `ppmrun.py`

Main entry point.  Orchestrates hardware collection, analysis, and reporting.
Importable functions:

| Function | Description |
|----------|-------------|
| `build_parser()` | Returns the `argparse.ArgumentParser` |
| `setup_run_dir(base_dir, tag)` | Creates and returns a timestamped run directory |
| `load_input_file(filepath)` | Loads a `.dat` file for re-analysis |
| `analyse(runs_data, args, run_dir)` | Filters, averages FFTs, returns peaks |
| `report_peaks(peaks, logger)` | Prints peak frequencies and field strength |

---

## Tests

```bash
python -m unittest discover -v
```

56 tests covering signal processing, file I/O, hardware communication (serial
port mocked, including the binary data frame), CLI argument parsing, and the
analysis pipeline.  The test suite runs without hardware and without `pyserial`
installed.
