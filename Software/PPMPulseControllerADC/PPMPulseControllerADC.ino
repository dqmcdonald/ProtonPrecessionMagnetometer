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


#define CSPIN 10  // Default Chip Select Line for Uno (change as needed)
SRAMsimple sram;  //initialize an instance of this class

// INSTANTIATE A Button OBJECT
Bounce2::Button button = Bounce2::Button();

// Buffer for serial comms
const int SERIAL_BUFF_LEN = 32;
char serial_buff[SERIAL_BUFF_LEN];


// Flag to indicate if a measurement should be taken
bool do_measurement = false;

// Parameters
int coil_activation_time = 6000;  // Time coil will be on (ms)
int sample_delay = 500;           // Wait time before sampling data (ms)
int cool_down_period = 10000;     // Delay before next cycle of activation
int sample_rate = 20000;          // Sample rate (samples/s)
int sample_time = 2000;           // Time sample will be on (ms)


void setup() {
  Serial.begin(9600);
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



  // Coil MOSFET Gate pin:
  pinMode(COIL_PIN, OUTPUT);
  digitalWrite(COIL_PIN, HIGH);

  // Setup and test SRAM memory
  SPI.begin();
  int tempInt = 0;
  uint32_t test_address;
  randomSeed(analogRead(A0));
  for( int i=0; i< NUM_MEMTESTS; i++) {
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
    do_measurement = true;
  }

  if (Serial.available()) {
    processCommand();
  }

  if (do_measurement) {
    doMeasurement();
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
    do_measurement = true;
    Serial.println("OK EXECU");
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

  setRGBLEDColor(200, 50, 30);
  digitalWrite(COIL_PIN, LOW);

  delay(coil_activation_time);

  digitalWrite(COIL_PIN, HIGH);

  // Wait delay time:
  setRGBLEDColor(200, 50, 200);
  delay(sample_delay);

  setRGBLEDColor(200, 200, 50);
  // record signal and send to Raspberry pi
  recordSignal();

  setRGBLEDColor(50, 50, 200);
  delay(cool_down_period);

  setRGBLEDColor(50, 200, 50);
  do_measurement = false;
  return;
}

void recordSignal()
// Record a sample at the current rate for the current time.
// Data is stored in SRAM and later transferred to the Raspberry PI by Serial
{





  return;
}
