import serial
import time
import numpy as np

#
# Proton Precession Magnetometer Control Software
# This module contains code that communicates with the Arduino Pro Mini
# that turns on/off the polarising coil and retrieves the signal data. 
# Communication is done by serial
#

DATA_FILE_NAME = "ppm.dat"

BAUD_RATE = 115200  # Communication rate

ON_TIME_COMMAND = "ONTIM"
ON_TIME_DEFAULT = 6000	    # Coil polarised for two seconds

SAMPLE_TIME_COMMAND = "SAMPT"
SAMPLE_TIME_DEFAULT = 2000  # Sample for two seconds

SAMPLE_RATE_COMMAND = "SAMRA"
SAMPLE_RATE_DEFAULT = 2000 # samples/s

DELAY_COMMAND = "DELAY"
DELAY_DEFAULT = 500 # Time between coil off and sampling begins

COOL_DOWN_COMMAND = "COOLD"
COOL_DOWN_DEFAULT = 10000 # Cool down MOSFET for 10 seconds

EXECUTE_COMMAND = "EXECU"

class PPMRun:
    def __init__(self, lg=None):
        self._ser = serial.Serial('/dev/serial0', BAUD_RATE, timeout=1)
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer() 
        self._logger = lg
        self._signal_data = None
        self._sample_rate = SAMPLE_RATE_DEFAULT
        self._sample_time = SAMPLE_TIME_DEFAULT
        
    def getSignalData(self):
        return self._signal_data
    
    def getSampleRate(self):
        return self._sample_rate
    
    def getSampleTime(self):
        return self._sample_time
        
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
       

    def doMeasurement(self):
        # Send command to activate the coil and record the signal
        self.sendCommand(EXECUTE_COMMAND)
        time.sleep(8)
        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        num_samples = int(resp);
        self.log("Number of samples: '{}'".format(num_samples))
        
        self._signal_data = np.zeros(num_samples)
        
        for i in range(num_samples):
            resp = self._ser.readline()
            resp = resp.decode('utf-8').strip()
            self._signal_data[i] = int(resp)
            
        
            
        
            

