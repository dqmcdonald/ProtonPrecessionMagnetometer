/***
Arduino sketch for Proton Precession Magnetometer Pulse Controller

Arduino receives instructions and sends data via Serial connection from RaspberryPi Zero 2 W 

PPM Coil is energiesed by turning pin 4 low, this makes the voltage on the MOSETS go low via an optocoupler

One coil is turned off there is a brief delay, then the ADC is used sample the signal from the sensor coils.
For speed each sample is stored in the external SPI 1MB SRAM chip
Target sample rate is 20,000/s
When sensing is complete, the arduino will send the data to the RPi over serial where further analysis will be peformed.

There is an RGB LED used to indicate, by color, the current action
A push button can be used to initiate an cycle of energising the coil


Pin Assignments:
D0  - Serial TX (To Rpi)
D1  - Serial RX (To Rpi)
D2  - Attached to pushbutton (activiated by going LOW)
D3  - Not Used
D4  - Activate PPM Coil
D5  - RGB Red
D6  - RGB Blue
D7  - ADC BUSY Pin
D8  - ADC RD (Clock Select)
D9  - RGB Green
D10 - SRAM Clock Select
D11 - SPI MISO (ADC + SRAM)
D12 - SPI MOSI (ADC + SRAM)
D13 - SPI SCK  (ADC + SRAM)

SRAM is 23LC1024
ADC is LTC1855

Libraries Used:
  Bounce2: https://github.com/thomasfredericks/Bounce2
  SRAM_Simple: https://github.com/dndubins/SRAMsimple


Quentin McDonald
October 2024
*/
// Includes
#include <SPI.h>
#include <Bounce2.h>
#include <SRAMsimple.h>



// Pin definitions
#define PUSHBUTTON_PIN 2
#define COIL_PIN 4
#define LED_RED_PIN 5
#define LED_BLUE_PIN 6
#define BUSY_PIN 7
#define ADC_RD_PIN 8
#define LED_GREEN_PIN 9
#define SRAM_CS_PIN 10
#define SPI_MISO_PIN 11
#define SPI_MOSI_PIN 12
#define SPI_CLOCK_PIN 13

#define TEST_INT 42
#define NUM_MEMTESTS 10

#define VREF 20.0  // ADC Voltage ref


#define CSPIN 10  // Default Chip Select Line for Uno (change as needed)
SRAMsimple sram;  //initialize an instance of this class

// INSTANTIATE A Button OBJECT
Bounce2::Button button = Bounce2::Button();

// Buffer for serial comms
const int SERIAL_BUFF_LEN = 32;
char serial_buff[SERIAL_BUFF_LEN];
const long BAUD_RATE = 115200;



// Parameters - these defaults will likley be overridden by commands from the Pi
int coil_activation_time = 6000;  // Time coil will be on (ms)
int sample_delay = 500;           // Wait time before sampling data (ms)
int cool_down_period = 10000;     // Delay before next cycle of activation
int sample_rate = 20000;          // Sample rate (samples/s)
int sample_time = 2000;           // Time sample will be on (ms)


void setup() {
  Serial.begin(BAUD_RATE);
  Serial.println("\n\nProton Precession Magnetometer - Coil Contoller\n");

  //LED: Start with Green
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(LED_BLUE_PIN, OUTPUT);
  setRGBLEDColor(50, 200, 50);

  // Pushbutton:
  button.attach(PUSHBUTTON_PIN, INPUT_PULLUP);  // USE INTERNAL PULL-UP
  // DEBOUNCE INTERVAL IN MILLISECONDS
  button.interval(5);
  // INDICATE THAT THE LOW STATE CORRESPONDS TO PHYSICALLY PRESSING THE BUTTON
  button.setPressedState(LOW);

  // ADC CS Pin
  pinMode(ADC_RD_PIN, OUTPUT);
  digitalWrite(ADC_RD_PIN, HIGH);  // Pull Chip Select High


  // Coil MOSFET Gate pin:
  pinMode(COIL_PIN, OUTPUT);
  digitalWrite(COIL_PIN, HIGH);

  // Setup and test SRAM memory
  SPI.begin();
  SPI.setClockDivider(SPI_CLOCK_DIV2);
  int tempInt = 0;
  uint32_t test_address;
  randomSeed(analogRead(A0));
  for (int i = 0; i < NUM_MEMTESTS; i++) {
    test_address = random(65536);
    sram.WriteInt(test_address, TEST_INT);
    tempInt = sram.ReadInt(test_address);
    if (tempInt == TEST_INT) {
      Serial.print("Memory check passed - read ");
      Serial.print(tempInt);
      Serial.print(" from address ");
      Serial.println(test_address);
    } else {
      Serial.print("Memory check passed - read ");
      Serial.print(tempInt);
      Serial.print(" from address ");
      Serial.println(test_address);
      Serial.print(" Expected: ");
      Serial.println(TEST_INT);
    }
  }
  Serial.println("Memory Check done\n");




  Serial.println("Setup Done");
}

void loop() {


  button.update();

  if (button.pressed()) {
    doMeasurement();
  }

  if (Serial.available()) {
    processCommand();
  }

  
}
void setRGBLEDColor(int r, int g, int b) {
  // Set the RGB LED to the color given by r, g and b in the range 1-255

  analogWrite(LED_RED_PIN, r);
  analogWrite(LED_GREEN_PIN, g);
  analogWrite(LED_BLUE_PIN, b);
}


void processCommand() {
  // Process a command received by Serial
  // Commands are of the form XXXXX NNNNNN where XXXXX is a five character opcode and NNNNNN is an integer
  memset(serial_buff, 0, SERIAL_BUFF_LEN);

  bool done = false;
  int char_cnt = 0;
  int c;
  int op;

  while (not done) {
    c = Serial.read();
    if (c > 0) {
      // Serial.println(c);
      if (c == '\n') {
        done = true;
        //   Serial.println("Line end");
      } else {

        if (char_cnt == SERIAL_BUFF_LEN) {
          done = true;
        } else {
          serial_buff[char_cnt] = c;
          char_cnt++;
        }
      }
    }
  }
  // Serial.println(serial_buff);
  if (strncmp(serial_buff, "EXECU", 5) == 0) {
    // Execute the cycle
    Serial.println("OK EXECU");
    doMeasurement();
  } else if (strncmp(serial_buff, "ONTIM", 5) == 0) {
    // Coil activation time
    op = getOp(serial_buff);
    if (op >= 0) {
      coil_activation_time = op;
      Serial.print("OK ONTIM: ");
      Serial.println(coil_activation_time);
    }
  } else if (strncmp(serial_buff, "SAMPT", 5) == 0) {
    // Sample time
    op = getOp(serial_buff);
    if (op >= 0) {
      sample_time = op;
      Serial.print("OK SAMPT: ");
      Serial.println(sample_time);
    }
  } else if (strncmp(serial_buff, "SAMRA", 5) == 0) {
    // Sample rate
    op = getOp(serial_buff);
    if (op >= 0) {
      sample_rate = op;
      Serial.print("OK SAMRA: ");
      Serial.println(sample_rate);
    }
  } else if (strncmp(serial_buff, "DELAY", 5) == 0) {
    // Sample delay
    op = getOp(serial_buff);
    if (op >= 0) {
      sample_delay = op;
      Serial.print("OK DELAY: ");
      Serial.println(sample_delay);
    }
  } else if (strncmp(serial_buff, "COOLD", 5) == 0) {
    // Cool down period
    op = getOp(serial_buff);
    if (op >= 0) {
      cool_down_period = op;
      Serial.print("OK COOLDOWN: ");
      Serial.println(cool_down_period);
    }
  } else if (strncmp(serial_buff, "READV", 5) == 0) {
    // Command for debugging the ADC
    uint16_t voltage_code = read_voltage();
    float voltage = code_to_voltage(voltage_code, VREF);

    Serial.print("Voltage = : ");
    Serial.println(voltage);
  } else {
    Serial.print("Uknown command: ");
    Serial.println(serial_buff);
  }



  return;
}

int getOp(const char* buff) {
  // Extracts the integer operand from the input string. Returns -1 if it's not present
  if (strlen(buff) > 7) {
    return atoi(&buff[5]);
  } else {
    return -1;
  }
}

void doMeasurement() {
  unsigned long num_samples;

  setRGBLEDColor(200, 50, 30);
  digitalWrite(COIL_PIN, LOW);

  delay(coil_activation_time);

  digitalWrite(COIL_PIN, HIGH);

  // Wait delay time:
  setRGBLEDColor(200, 50, 200);
  delay(sample_delay);

  setRGBLEDColor(200, 200, 50);
  // record signal and send to Raspberry pi
  num_samples = recordSignal();

  // sendData to the RPi
  sendData(num_samples);

  setRGBLEDColor(50, 50, 200);
  delay(cool_down_period);

  setRGBLEDColor(50, 200, 50);
  
  return;
}

unsigned long recordSignal()
// Record a sample at the current rate for the current time.
// Data is stored in SRAM and later transferred to the Raspberry PI by Serial
// Returns the number of data sampled
{

  uint32_t address = 0;
  unsigned long time_remaining;


  // First calculate the period in us for the current sample rate:
  unsigned long period = 1000000 / sample_rate;

  unsigned long num_samples = ((unsigned long)sample_rate * (unsigned long)sample_time) / 1000;

  uint16_t voltage = read_voltage();  // Start ADC reading
  //bool done = false;
  byte temp[2];
  unsigned long start_time = 0;
  unsigned long time_elapsed = 0;


  // Put memory into write mode:
  pinMode(CSPIN, OUTPUT);    // set CS pin to output mode
  digitalWrite(CS, LOW);     // set SPI slave select LOW
  SPI.transfer(WRMR);        // command to write to mode register
  SPI.transfer(Sequential);  // set for sequential mode
  digitalWrite(CSPIN, HIGH);

  // Do a loop for the number of samples
  for (unsigned long isample = 0; isample < num_samples; isample++) {
    start_time = micros();

    voltage = read_voltage();

    // sram.WriteInt(address, voltage);  // Don't use SRAM:
    // Use expanded version direct for speed:
    temp[0] = (byte)(voltage >> 8);       // high byte of integer
    temp[1] = (byte)(voltage);            // low byte of integer
    PORTB = PORTB & B11111011;            // start new command sequence (CS Pin low)
    SPI.transfer(WRITE);                  // send WRITE command
    SPI.transfer((byte)(address >> 16));  // send high byte of address
    SPI.transfer((byte)(address >> 8));   // send middle byte of address
    SPI.transfer((byte)address);          // send low byte of address
    SPI.transfer(temp, 2);                // transfer an array of data => needs array name & size (2 elements)
    PORTB = PORTB | B00000100;            // End with CSPin High

    address += 2;

    // Wait for at least the rest of the sampling period:
    time_elapsed = micros() - start_time;
    time_remaining = period - time_elapsed;
    if (time_remaining > 3)
      delayMicroseconds(time_remaining);
  }

  return num_samples;
}

uint16_t read_voltage(void) {
  // Query the external ADC to get the current voltage value
  uint16_t adc_code;
  uint16_t voltage;

  adc_code = 0x0;  // Differential, ports one and two

  spi_transfer_word(ADC_RD_PIN, adc_code, &voltage);

  return voltage;
}

void sendData(unsigned long num_samples) {
  // Send data via Serial to the RPi
  int voltage;
  Serial.println(num_samples);
  uint32_t address = 0;

  for (unsigned long i = 0; i < num_samples; i++) {
    voltage = sram.ReadInt(address);
    address += 2;
    Serial.println(voltage);
  }
}

// Code below here is taken in part from Linduino: https://github.com/analogdevicesinc/Linduino/tree/master
// Reads and sends a word
// Return 0 if successful, 1 if failed
void spi_transfer_word(uint8_t cs_pin, uint16_t tx, uint16_t* rx) {
  union {
    uint8_t b[2];
    uint16_t w;
  } data_tx;

  union {
    uint8_t b[2];
    uint16_t w;
  } data_rx;

  data_tx.w = tx;

  //digitalWrite(cs_pin, LOW);  //! 1) Pull CS low
  PORTB = PORTB & B11111110;

  data_rx.b[1] = SPI.transfer(data_tx.b[1]);  //! 2) Read MSB and send MSB
  data_rx.b[0] = SPI.transfer(data_tx.b[0]);  //! 3) Read LSB and send LSB

  *rx = data_rx.w;

  //digitalWrite(cs_pin, HIGH);  //! 4) Pull CS high
  PORTB = PORTB | B00000001;
}

// Calculates the LTC1859 input voltage given the data, vref
float code_to_voltage(uint16_t adc_code, float vref) {
  float voltage;
  float sign = 1;


  if ((adc_code & 0x8000) == 0x8000)  //adc code is < 0
  {
    adc_code = (adc_code ^ 0xFFFF) + 1;  //! Convert ADC code from two's complement to binary
    sign = -1;
  }
  voltage = sign * (float)adc_code;
  voltage = voltage / (pow(2, 15) - 1);  //! 2) This calculates the input as a fraction of the reference voltage (dimensionless)


  voltage = voltage * vref;  //! 3) Multiply fraction by Vref to get the actual voltage at the input (in volts)

  return (voltage);
}
