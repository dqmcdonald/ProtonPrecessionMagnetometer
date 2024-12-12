import logging
import serial
#
# Proton Precession Magnetometer Control Software
# This module contains code that communicates with the Arduino Pro Mini
# that turns on/off the polarising coil and retrieves the signal data. 
# Communication is done by serial
#

BAUD_RATE = 9600  # Communication rate

ON_TIME_COMMAND = "ONTIM"
ON_TIME_DEFAULT = 6000	    # Coil polarised for two seconds

SAMPLE_TIME_COMMAND = "SAMPT"
SAMPLE_TIME_DEFAULT = 2000  # Sample for two seconds

SAMPLE_RATE_COMMAND = "SAMRA"
SAMPLE_RATE_DEFAULT = 20000 # 20000 samples/s

DELAY_COMMAND = "DELAY"
DELAY_DEFAULT = 500 # Time between coil off and sampling begins

COOL_DOWN_COMMAND = "COOLD"
COOL_DOWN_DEFAULT = 10000 # Cool down MOSFET for 10 seconds

EXECUTE_COMMAND = "EXECU"

class PyPPM:
    def __init__(self, lg=None):
        self._ser = serial.Serial('/dev/serial0', 9600, timeout=1)
        self._ser.reset_input_buffer()
        self._logger = lg
        
        
    def log(self, msg ):
        # Log message "msg" to the current logger (if any)
        if self._logger:
            self._logger.info(msg)
            
    def send( self, text ):
        # Send message via Serial
        self._ser.write("{}\n".format(text).encode('utf-8'))
        self.log("Sending command:   '{}'".format(text))
        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        self.log("Received response: '{}'".format(resp))

    def sendCommand(self, command, value=None):
        # Send command via serial
        if value is not None:
            text = "{} {}".format(command,value)
        else:
            text = command
        self.send(text)
        
       
        

    def sendDefaultValues(self):
        # Send default values to the Arduino coil controller

        self.sendCommand(ON_TIME_COMMAND, ON_TIME_DEFAULT )
        self.sendCommand(SAMPLE_TIME_COMMAND, SAMPLE_TIME_DEFAULT )
        self.sendCommand(SAMPLE_RATE_COMMAND, SAMPLE_RATE_DEFAULT )
        self.sendCommand(DELAY_COMMAND, DELAY_DEFAULT )
        self.sendCommand(COOL_DOWN_COMMAND, COOL_DOWN_DEFAULT )
       






if __name__ == '__main__':

    logger = logging.getLogger("PPM")
    logging.basicConfig(filename='ppm.log', level=logging.INFO,format='%(asctime)s %(message)s',
                        datefmt="%d-%b-%Y %H:%M:%S")
    

    ppm = PyPPM(logger)
    ppm.sendDefaultValues()
    
    ppm.sendCommand("READV");
    ppm.sendCommand("READV");

#    ser.write(str('ONTIM `1000\n').encode('utf-8')) 
#    print(ser.readline())
#    ser.write(str('EXECU\n').encode('utf-8')) 
#    print(ser.readline())
