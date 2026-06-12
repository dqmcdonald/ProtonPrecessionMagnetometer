/***
 * PPMPulseControllerADC.ino — Arduino controller for Proton Precession Magnetometer
 *
 * Receives configuration commands from a Raspberry Pi over serial and manages
 * the full measurement cycle:
 *
 *   1. POLARISE  Energise the coil (COIL_PIN LOW) for coil_activation_time ms.
 *                The strong DC field aligns proton spins in the water sample
 *                along the coil axis (T1 relaxation, ~3 s for tap water;
 *                default 6 s ≈ 2 × T1 captures most available magnetisation).
 *
 *   2. SETTLE    Switch coil off; wait sample_delay ms for the large inductive
 *                transient to decay so it does not saturate the ADC input.
 *
 *   3. SAMPLE    Read the precession signal from the LTC1855 SPI ADC and store
 *                each 16-bit sample in the 23LC1024 SPI SRAM.  The loop runs
 *                as fast as possible; actual rate is measured via the RTC
 *                32.768 kHz interrupt and reported to the Pi.
 *
 *   4. TRANSMIT  Send the actual sample rate, sample count, and all ADC values
 *                to the Pi over serial.
 *
 *   5. COOL DOWN Wait cool_down_period ms for the MOSFET to cool.  During this
 *                phase serial commands are still processed, so the Pi can send
 *                the next run's configuration without risking a serial-buffer
 *                overflow.  An EXECU received during cool-down is queued and
 *                executed automatically when cool-down completes.
 *
 * Background acquisition (BKGND command):
 *   Runs SAMPLE + TRANSMIT only — the coil is never energised, so the record
 *   contains just amplifier noise and ambient interference (mains harmonics,
 *   etc.).  The Pi subtracts its spectrum from a normal measurement's spectrum
 *   to suppress interference that falls inside the Larmor band.  No settle
 *   delay (there is no coil transient) and no cool-down (the MOSFET never
 *   conducted).  A BKGND received during cool-down is queued like EXECU.
 *
 * Pin assignments:
 *   D0  Serial TX (to Pi)            D1  Serial RX (from Pi)
 *   D2  Push button (LOW = pressed)  D3  RTC 32.768 kHz interrupt
 *   D4  Coil activate (LOW = on)     D5  RGB Red
 *   D6  RGB Blue                     D7  ADC BUSY (not currently used)
 *   D8  ADC CS / RD                  D9  RGB Green
 *   D10 SRAM CS                      D11 SPI MISO
 *   D12 SPI MOSI                     D13 SPI SCK
 *
 * External devices:
 *   ADC:  LTC1855 — 16-bit differential SPI ADC, signed two's complement output
 *   SRAM: 23LC1024 — 128 KB SPI SRAM (65 536 uint16_t samples maximum)
 *   RTC:  32.768 kHz square wave; rising edges counted to measure elapsed time
 *
 * Serial protocol:
 *   Command/control is ASCII, '\n'-terminated:
 *     Commands  "XXXXX NNNN\n" — 5-char opcode, optional integer parameter
 *     Responses "OK XXXXX: N\n" on success; "ERR: ...\n" on error
 *
 *   Measurement data is sent as a single binary frame (little-endian) for
 *   speed and reliability — roughly 3× fewer bytes than the old line-based
 *   ASCII format and no per-sample text parsing on the Pi:
 *     bytes 0-3  : marker 'P','P','M','D'
 *     bytes 4-7  : actual_sample_rate (uint32)
 *     bytes 8-11 : num_samples        (uint32)
 *     then num_samples × int16 samples (signed two's complement)
 *
 * Libraries: Bounce2, SRAMsimple
 * Quentin McDonald, October 2024
 */

#include <SPI.h>
#include <Bounce2.h>
#include <SRAMsimple.h>

// ── Pin definitions ──────────────────────────────────────────────────────────
// const uint8_t is preferred over #define: type-safe and visible in debuggers.

const uint8_t PUSHBUTTON_PIN = 2;
const uint8_t INTERRUPT_PIN  = 3;   // RTC 32.768 kHz square-wave input
const uint8_t COIL_PIN       = 4;   // LOW = coil on (optocoupler/MOSFET active-low)
const uint8_t LED_RED_PIN    = 5;
const uint8_t LED_BLUE_PIN   = 6;
// Pin 7 (ADC BUSY) is wired but not used in firmware
const uint8_t ADC_CS_PIN     = 8;   // LTC1855 chip select (= /RD pin)
const uint8_t LED_GREEN_PIN  = 9;
const uint8_t SRAM_CS_PIN    = 10;  // 23LC1024 chip select
// Pins 11-13 are SPI (MISO/MOSI/SCK), managed by the SPI library

// ── Constants ────────────────────────────────────────────────────────────────

// LTC1855 is a ±10 V differential ADC; full-scale range = 20 V, so VREF = 20.
// Only used by the READV debug command.
const float VREF = 20.0f;

// 23LC1024 capacity: 128 KB = 65 536 × 2-byte (uint16_t) samples.
const unsigned long MAX_SAMPLES = 65536UL;

// Self-test value and iteration count for SRAM startup check.
const int TEST_INT    = 42;
const int NUM_MEMTESTS = 10;

// Serial baud rate — must match PPM.py BAUD_RATE.  250000 divides both the
// 8 MHz and 16 MHz AVR clocks exactly (0% baud error, unlike 57600/115200)
// and cuts the ~48 KB data frame transfer from ~8.3 s to ~1.9 s.
const long BAUD_RATE = 250000;

// Command buffer: longest possible command is "COOLD 10000\n" = 12 chars.
const int SERIAL_BUFF_LEN = 32;

// RTC square-wave frequency for elapsed-time measurement during sampling.
const float RTC_FREQ_HZ = 32768.0f;

// ── State machine ─────────────────────────────────────────────────────────────
// Non-blocking design: the main loop never calls delay() except for the brief
// sample_delay settle period.  This keeps the serial port responsive during the
// long polarise and cool-down phases and prevents buffer overflow on multi-run
// measurements.

enum MeasurementState {
    STATE_IDLE,       // waiting for EXECU command or button press
    STATE_POLARISING, // coil energised; waiting for coil_activation_time to expire
    STATE_COOLING     // MOSFET cool-down after data sent; commands still accepted
};

MeasurementState measurement_state = STATE_IDLE;
unsigned long    state_start_ms    = 0;

// Set true when EXECU arrives during cool-down; the measurement starts
// automatically as soon as cool-down completes.
bool measurement_requested = false;

// Set true (together with measurement_requested) when BKGND arrives during
// cool-down, so the queued run is executed as a background acquisition.
bool background_requested = false;

// ── Globals ───────────────────────────────────────────────────────────────────

// Incremented by timer_isr() on each 32.768 kHz rising edge.
// Must be volatile because it is written in an ISR and read in the main loop.
// unsigned long prevents negative wrap-around (long could go negative after
// ~18 hours of continuous interrupts, though this never occurs in practice).
volatile unsigned long interrupt_counter = 0;

SRAMsimple      sram;
Bounce2::Button button = Bounce2::Button();

char serial_buff[SERIAL_BUFF_LEN];

// Measurement parameters — Pi overrides these before each run via commands.
// Defaults match PPM.py defaults so a freshly powered Arduino behaves sensibly
// even if the Pi does not send configuration.
int coil_activation_time = 6000;   // ms  polarisation time (~2 × T1 for water)
int sample_delay         = 500;    // ms  transient settle time after coil off
int cool_down_period     = 10000;  // ms  MOSFET thermal recovery between runs
int sample_rate          = 16000;  // used only to compute num_samples (see SAMRA note)
int sample_time          = 1500;   // ms  ADC sampling window

// ── Structs ───────────────────────────────────────────────────────────────────

struct SampleData {
    unsigned long num_samples;
    unsigned long actual_sample_rate;
};

// ── Forward declarations ──────────────────────────────────────────────────────

void          processCommand();
void          startMeasurement();
void          runBackgroundMeasurement();
SampleData    recordSignal();
void          sendData(unsigned long num_samples, unsigned long actual_sample_rate);
void          writeUint32LE(uint32_t value);
int16_t       read_voltage();
void          spi_transfer_word(uint8_t cs_pin, uint16_t tx, uint16_t *rx);
float         code_to_voltage(uint16_t adc_code, float vref);
void          setRGBLEDColor(int r, int g, int b);
void          timer_isr();
int           getOp(const char *buff);

// ── setup() ──────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(BAUD_RATE);
    // If a command arrives partially (serial noise, host crash mid-send),
    // readBytesUntil() gives up after 200 ms rather than blocking forever.
    Serial.setTimeout(200);
    Serial.println(F("\n\nProton Precession Magnetometer - Coil Controller\n"));

    // LED: green = ready
    pinMode(LED_RED_PIN,   OUTPUT);
    pinMode(LED_GREEN_PIN, OUTPUT);
    pinMode(LED_BLUE_PIN,  OUTPUT);
    setRGBLEDColor(50, 200, 50);

    // Push button with internal pull-up; LOW = physically pressed
    button.attach(PUSHBUTTON_PIN, INPUT_PULLUP);
    button.interval(5);
    button.setPressedState(LOW);

    // RTC 32.768 kHz input — interrupt attached only during sampling
    pinMode(INTERRUPT_PIN, INPUT_PULLUP);

    // ADC CS: deassert (HIGH) until a conversion is requested
    pinMode(ADC_CS_PIN, OUTPUT);
    digitalWrite(ADC_CS_PIN, HIGH);

    // Coil MOSFET gate: HIGH = coil OFF (active-low via optocoupler)
    pinMode(COIL_PIN, OUTPUT);
    digitalWrite(COIL_PIN, HIGH);

    // SPI bus — ADC (LTC1855) and SRAM (23LC1024) share MISO/MOSI/SCK.
    // SPI_CLOCK_DIV2 = 8 MHz, within the LTC1855's 10 MHz maximum.
    SPI.begin();
    SPI.setClockDivider(SPI_CLOCK_DIV2);

    // SRAM startup self-test: write and read back TEST_INT at random addresses.
    randomSeed(analogRead(A0));
    bool memory_ok = true;
    for (int i = 0; i < NUM_MEMTESTS; i++) {
        uint32_t addr = random(65536);
        sram.WriteInt(addr, TEST_INT);
        int readback = sram.ReadInt(addr);
        if (readback == TEST_INT) {
            Serial.print(F("Memory check passed: read "));
            Serial.print(readback);
            Serial.print(F(" from address "));
            Serial.println(addr);
        } else {
            // BUG FIX: original code printed "passed" in both branches.
            Serial.print(F("Memory check FAILED: read "));
            Serial.print(readback);
            Serial.print(F(" from address "));
            Serial.print(addr);
            Serial.print(F(", expected "));
            Serial.println(TEST_INT);
            memory_ok = false;
        }
    }
    Serial.println(memory_ok ? F("Memory check done — all passed\n")
                              : F("Memory check done — FAILURES DETECTED\n"));
    Serial.println(F("Setup done"));
}

// ── loop() ───────────────────────────────────────────────────────────────────

void loop() {
    button.update();

    // Accept serial commands when idle or cooling.
    // Processing commands during cool-down prevents the 64-byte hardware
    // serial receive buffer overflowing when the Pi sends the next run's
    // configuration immediately after reading the previous run's data.
    if (Serial.available() &&
        (measurement_state == STATE_IDLE || measurement_state == STATE_COOLING)) {
        processCommand();
    }

    switch (measurement_state) {

        case STATE_IDLE:
            if (button.pressed()) {
                startMeasurement();
            }
            break;

        case STATE_POLARISING:
            if (millis() - state_start_ms >= (unsigned long)coil_activation_time) {
                // Proton spins are now aligned along the coil axis.  Switch off
                // the coil; they will precess around Earth's field at the Larmor
                // frequency: f = γ·B/(2π) ≈ 2435 Hz for 57 µT mid-latitude field.
                digitalWrite(COIL_PIN, HIGH);
                setRGBLEDColor(200, 50, 200);  // purple = settling

                // Brief blocking delay for the inductive transient to decay below
                // the ADC input range before sampling begins.
                delay(sample_delay);

                setRGBLEDColor(200, 200, 50);  // yellow = sampling
                SampleData sd = recordSignal();
                sendData(sd.num_samples, sd.actual_sample_rate);

                // Begin non-blocking cool-down; Pi can send next config now.
                setRGBLEDColor(50, 50, 200);   // blue = cooling
                state_start_ms = millis();
                measurement_state = STATE_COOLING;
            }
            break;

        case STATE_COOLING:
            if (millis() - state_start_ms >= (unsigned long)cool_down_period) {
                setRGBLEDColor(50, 200, 50);   // green = ready
                measurement_state = STATE_IDLE;
                // If the Pi sent EXECU/BKGND while we were cooling, start
                // the queued run immediately.
                if (measurement_requested) {
                    measurement_requested = false;
                    if (background_requested) {
                        background_requested = false;
                        runBackgroundMeasurement();
                    } else {
                        startMeasurement();
                    }
                }
            }
            break;
    }
}

// ── startMeasurement() ───────────────────────────────────────────────────────

void startMeasurement() {
    if (measurement_state != STATE_IDLE) {
        Serial.println(F("ERR: busy"));
        return;
    }
    setRGBLEDColor(200, 50, 30);   // red = polarising
    digitalWrite(COIL_PIN, LOW);   // energise coil
    state_start_ms    = millis();
    measurement_state = STATE_POLARISING;
}

// ── runBackgroundMeasurement() ───────────────────────────────────────────────

void runBackgroundMeasurement() {
    // Sample-only acquisition: the coil is never energised, so the record
    // contains amplifier noise and ambient interference only.  Used by the Pi
    // for background spectral subtraction.
    //
    // Skips the polarise and settle phases (no coil current, no transient)
    // and the cool-down phase (the MOSFET never conducted), so the device
    // returns to IDLE as soon as the data has been sent.  Blocks the main
    // loop for the duration of sampling + transmit, exactly as the normal
    // measurement path does.
    if (measurement_state != STATE_IDLE) {
        Serial.println(F("ERR: busy"));
        return;
    }
    setRGBLEDColor(200, 200, 50);  // yellow = sampling
    SampleData sd = recordSignal();
    sendData(sd.num_samples, sd.actual_sample_rate);
    setRGBLEDColor(50, 200, 50);   // green = ready
}

// ── processCommand() ─────────────────────────────────────────────────────────

void processCommand() {
    // Read one newline-terminated command into serial_buff.
    // readBytesUntil() returns 0 on timeout (200 ms, set in setup()) so a
    // partial or missing command never blocks indefinitely.
    memset(serial_buff, 0, SERIAL_BUFF_LEN);
    int len = Serial.readBytesUntil('\n', serial_buff, SERIAL_BUFF_LEN - 1);
    if (len == 0) return;

    // Trim trailing \r to handle Windows-style CRLF line endings.
    if (serial_buff[len - 1] == '\r') len--;
    serial_buff[len] = '\0';

    if (strncmp(serial_buff, "EXECU", 5) == 0) {
        if (measurement_state == STATE_IDLE) {
            Serial.println(F("OK EXECU"));
            startMeasurement();
        } else if (measurement_state == STATE_COOLING) {
            // Queue the request; it will fire when cool-down ends.
            Serial.println(F("OK EXECU"));
            measurement_requested = true;
        } else {
            Serial.println(F("ERR: busy"));
        }

    } else if (strncmp(serial_buff, "BKGND", 5) == 0) {
        if (measurement_state == STATE_IDLE) {
            Serial.println(F("OK BKGND"));
            runBackgroundMeasurement();
        } else if (measurement_state == STATE_COOLING) {
            // Queue the request; it will fire when cool-down ends.
            Serial.println(F("OK BKGND"));
            measurement_requested = true;
            background_requested  = true;
        } else {
            Serial.println(F("ERR: busy"));
        }

    } else if (strncmp(serial_buff, "ONTIM", 5) == 0) {
        int op = getOp(serial_buff);
        if (op > 0) {
            coil_activation_time = op;
            Serial.print(F("OK ONTIM: "));
            Serial.println(coil_activation_time);
        }

    } else if (strncmp(serial_buff, "SAMPT", 5) == 0) {
        int op = getOp(serial_buff);
        if (op > 0) {
            sample_time = op;
            Serial.print(F("OK SAMPT: "));
            Serial.println(sample_time);
        }

    } else if (strncmp(serial_buff, "SAMRA", 5) == 0) {
        // NOTE: this value controls how many samples are collected
        // (num_samples = sample_rate * sample_time / 1000), NOT the actual
        // sample rate.  The loop runs as fast as SPI transactions allow; the
        // true rate is measured via the RTC interrupt and reported back.
        int op = getOp(serial_buff);
        if (op > 0) {
            sample_rate = op;
            Serial.print(F("OK SAMRA: "));
            Serial.println(sample_rate);
        }

    } else if (strncmp(serial_buff, "DELAY", 5) == 0) {
        int op = getOp(serial_buff);
        if (op >= 0) {
            sample_delay = op;
            Serial.print(F("OK DELAY: "));
            Serial.println(sample_delay);
        }

    } else if (strncmp(serial_buff, "COOLD", 5) == 0) {
        int op = getOp(serial_buff);
        if (op >= 0) {
            cool_down_period = op;
            Serial.print(F("OK COOLD: "));
            Serial.println(cool_down_period);
        }

    } else if (strncmp(serial_buff, "READV", 5) == 0) {
        // Debug: read one ADC sample and print as voltage.
        // VREF = 20 V (LTC1855 ±10 V differential range).
        uint16_t raw     = (uint16_t)read_voltage();
        float    voltage = code_to_voltage(raw, VREF);
        Serial.print(F("Voltage: "));
        Serial.println(voltage);

    } else {
        Serial.print(F("Unknown command: "));
        Serial.println(serial_buff);
    }
}

// ── getOp() ──────────────────────────────────────────────────────────────────

int getOp(const char *buff) {
    // Extract the integer operand from "XXXXX NNNN".
    // The operand starts at index 6 (past the 5-char opcode and one space).
    // atoi() handles the conversion; it returns 0 for missing/non-numeric input.
    if ((int)strlen(buff) > 6) {
        return atoi(&buff[6]);
    }
    return -1;
}

// ── recordSignal() ───────────────────────────────────────────────────────────

SampleData recordSignal() {
    // Collect ADC samples into SRAM as fast as the SPI bus allows, then
    // compute the actual sample rate from the elapsed RTC-interrupt count.
    //
    // The LTC1855 outputs signed 16-bit two's complement values.  They are
    // stored as raw bytes (big-endian uint16_t) and the Pi reconstructs the
    // signed value on readback.
    //
    // sample_rate here is only a target used to decide how many samples to
    // collect.  The loop has no timer-based pacing; the actual rate depends on
    // SPI transaction overhead and is typically close to (but not exactly) the
    // requested value.

    unsigned long num_samples =
        ((unsigned long)sample_rate * (unsigned long)sample_time) / 1000UL;

    // Guard against SRAM overflow: 23LC1024 = 128 KB = 65 536 uint16_t samples.
    if (num_samples > MAX_SAMPLES) {
        num_samples = MAX_SAMPLES;
    }

    // Set SRAM to sequential access mode.  Although each sample write uses an
    // individual CS pulse (necessary because ADC reads interleave on the same
    // SPI bus), sequential mode avoids mode-register overhead between transactions.
    digitalWrite(SRAM_CS_PIN, LOW);
    SPI.transfer(WRMR);        // write mode register
    SPI.transfer(Sequential);  // sequential access
    digitalWrite(SRAM_CS_PIN, HIGH);

    // Dummy read to flush any stale conversion result held in the LTC1855
    // output register before the timed sampling loop begins.
    (void)read_voltage();

    // Start counting 32.768 kHz RTC edges for elapsed-time measurement.
    interrupt_counter = 0;
    attachInterrupt(digitalPinToInterrupt(INTERRUPT_PIN), timer_isr, RISING);

    uint32_t address = 0;
    uint8_t  temp[2];

    for (unsigned long i = 0; i < num_samples; i++) {
        int16_t voltage = read_voltage();

        // Store as big-endian bytes.  The sign bit is preserved in the raw
        // bit pattern; the Pi casts back to int16_t when it reads the data.
        temp[0] = (uint8_t)((uint16_t)voltage >> 8);  // high byte
        temp[1] = (uint8_t)voltage;                   // low byte

        // Direct PORTB manipulation rather than digitalWrite() to minimise
        // per-sample overhead in the tight loop.
        // SRAM_CS_PIN = 10 = PB2: clear bit 2 for CS-low, set for CS-high.
        PORTB &= B11111011;                        // CS low
        SPI.transfer(WRITE);                       // WRITE command
        SPI.transfer((uint8_t)(address >> 16));    // address MSB
        SPI.transfer((uint8_t)(address >> 8));     // address mid
        SPI.transfer((uint8_t)address);            // address LSB
        SPI.transfer(temp, 2);                     // two data bytes
        PORTB |= B00000100;                        // CS high

        address += 2;
    }

    detachInterrupt(digitalPinToInterrupt(INTERRUPT_PIN));

    // interrupt_counter = number of 32.768 kHz rising edges during the loop.
    // Dividing by RTC_FREQ_HZ gives elapsed seconds; then rate = n / t.
    float         elapsed_secs    = (float)interrupt_counter / RTC_FREQ_HZ;
    unsigned long actual_rate     = (elapsed_secs > 0.0f)
                                    ? (unsigned long)((float)num_samples / elapsed_secs)
                                    : (unsigned long)sample_rate;  // fallback if RTC silent

    SampleData sd;
    sd.num_samples        = num_samples;
    sd.actual_sample_rate = actual_rate;
    return sd;
}

// ── sendData() ───────────────────────────────────────────────────────────────

void sendData(unsigned long num_samples, unsigned long actual_sample_rate) {
    // Send the measurement as one binary frame (little-endian).  Only the bulk
    // data transfer is binary; command/control responses remain ASCII.
    //
    //   bytes 0-3  : marker 'P','P','M','D'   (lets the Pi resync on the frame)
    //   bytes 4-7  : actual_sample_rate (uint32)
    //   bytes 8-11 : num_samples        (uint32)
    //   then num_samples × int16 samples (signed two's complement)
    Serial.write('P');
    Serial.write('P');
    Serial.write('M');
    Serial.write('D');
    writeUint32LE((uint32_t)actual_sample_rate);
    writeUint32LE((uint32_t)num_samples);

    // Burst-read all samples from SRAM in one sequential transaction.
    // Sequential mode is already configured from recordSignal().  Issuing a
    // single READ command + start address and then clocking out all bytes
    // avoids the per-sample command/address overhead of individual ReadInt()
    // calls (~7 bytes overhead saved per sample).
    digitalWrite(SRAM_CS_PIN, LOW);
    SPI.transfer(READ);   // sequential read command (0x03)
    SPI.transfer(0x00);   // 24-bit start address = 0x000000
    SPI.transfer(0x00);
    SPI.transfer(0x00);

    for (unsigned long i = 0; i < num_samples; i++) {
        uint8_t hi = SPI.transfer(0);   // SRAM holds samples big-endian
        uint8_t lo = SPI.transfer(0);
        // Emit each sample little-endian (low byte first) on the wire.
        Serial.write(lo);
        Serial.write(hi);
    }

    digitalWrite(SRAM_CS_PIN, HIGH);
}

// ── writeUint32LE() ──────────────────────────────────────────────────────────

void writeUint32LE(uint32_t value) {
    // Write a 32-bit value to the serial port, least-significant byte first.
    Serial.write((uint8_t)(value));
    Serial.write((uint8_t)(value >> 8));
    Serial.write((uint8_t)(value >> 16));
    Serial.write((uint8_t)(value >> 24));
}

// ── read_voltage() ───────────────────────────────────────────────────────────

int16_t read_voltage() {
    // Request one differential conversion from the LTC1855 and return the
    // signed 16-bit result.  The LTC1855 output is two's complement:
    // 0x7FFF = +VREF/2, 0x8000 = -VREF/2, 0x0000 = 0 V differential.
    uint16_t raw = 0;
    spi_transfer_word(ADC_CS_PIN, 0x0000, &raw);
    return (int16_t)raw;
}

// ── spi_transfer_word() ──────────────────────────────────────────────────────

void spi_transfer_word(uint8_t cs_pin, uint16_t tx, uint16_t *rx) {
    // Send and receive one 16-bit word MSB-first over SPI.
    // ADC_CS_PIN = 8 = PB0: direct PORTB manipulation avoids the ~4 µs
    // overhead of digitalWrite() which matters in the tight sample loop.
    //
    // Adapted from Linduino (Analog Devices github.com/analogdevicesinc/Linduino).
    // Corrected device reference: LTC1855 (not LTC1859 as in the original).

    union { uint8_t b[2]; uint16_t w; } data_tx, data_rx;
    data_tx.w = tx;

    // ADC_CS_PIN = 8 = PB0: clear bit 0 for CS-low, set for CS-high.
    PORTB &= B11111110;                             // CS low
    data_rx.b[1] = SPI.transfer(data_tx.b[1]);     // MSB first
    data_rx.b[0] = SPI.transfer(data_tx.b[0]);     // LSB second
    PORTB |= B00000001;                             // CS high

    *rx = data_rx.w;
}

// ── setRGBLEDColor() ─────────────────────────────────────────────────────────

void setRGBLEDColor(int r, int g, int b) {
    // Set LED colour using PWM.  Values 0–255: 0 = off, 255 = full brightness.
    // Colour convention used in this sketch:
    //   Green  = idle / ready
    //   Red    = polarising
    //   Purple = settling (transient decay)
    //   Yellow = sampling
    //   Blue   = cooling
    analogWrite(LED_RED_PIN,   r);
    analogWrite(LED_GREEN_PIN, g);
    analogWrite(LED_BLUE_PIN,  b);
}

// ── timer_isr() ──────────────────────────────────────────────────────────────

void timer_isr() {
    // Counts rising edges of the 32.768 kHz RTC output.
    // elapsed_seconds = interrupt_counter / 32768.0
    interrupt_counter++;
}

// ── code_to_voltage() ────────────────────────────────────────────────────────

float code_to_voltage(uint16_t adc_code, float vref) {
    // Convert a raw LTC1855 ADC code to a floating-point voltage.
    // Output encoding is 16-bit two's complement: bit 15 is the sign bit.
    //   0x7FFF → +vref/2   (full-scale positive)
    //   0x8000 → -vref/2   (full-scale negative)
    //   0x0000 →  0 V
    // With VREF = 20 V the usable range is ±10 V.
    //
    // Adapted from Linduino (Analog Devices github.com/analogdevicesinc/Linduino).

    float sign = 1.0f;
    if (adc_code & 0x8000) {
        adc_code = (adc_code ^ 0xFFFF) + 1;  // two's complement → magnitude
        sign = -1.0f;
    }
    // Normalise to ±1 then scale by vref.
    float voltage = sign * (float)adc_code / (float)((1UL << 15) - 1) * vref;
    return voltage;
}
