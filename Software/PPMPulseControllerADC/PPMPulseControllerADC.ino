/***
Arduino sketch for Proton Precession Magnetometer Pulse Controller

Arduino receives instructions and sends data via Serial connection from RaspberryPi Zero 2 W 

PPM Coil is energiesed by turning pin 4 high, this makes the voltage on the MOSETS go low via an optocoupler

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


Quentin McDonald
October 2024
*/
// Includes
#include <SPI.h>



// Pin definitions
#define PUSHUTTON_PIN     2
#define COIL_PIN          4
#define LED_RED_PIN       5
#define LED_BLUE_PIN      6
#define BUSY_PIN          7
#define ADC_RD_PIN        8
#define LED_GREEN_PIN      9
#define SRAM_CS_PIN      10
#define SPI_MISO_PIN     11
#define SPI_MOSI_PIN     12
#define SPI_CLOCK_PIN    13




void setup() {
  // put your setup code here, to run once:

//LED: Start with Green
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(LED_BLUE_PIN, OUTPUT);
  digitalWrite(LED_RED_PIN, LOW);
  digitalWrite(LED_GREEN_PIN, HIGH);
  digitalWrite(LED_BLUE_PIN, LOW);


}

void loop() {
  // put your main code here, to run repeatedly:

}
