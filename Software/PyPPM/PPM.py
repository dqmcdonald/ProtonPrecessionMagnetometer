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

BAUD_RATE = 57600  # Serial Communication rate

ON_TIME_COMMAND = "ONTIM"
ON_TIME_DEFAULT = 6000	    # Coil polarised for six seconds

# Maximum sample rate from hardware appears to be about 
# 16000 samples/s. Therefore request that as a nominal sample rate. But this
# is more about indicating the number of samples. The number of samples
# is calculated from the sample time in seconds * the sample rate.
# The maximum number of samples is 32K.
SAMPLE_TIME_COMMAND = "SAMPT"
SAMPLE_TIME_DEFAULT = 1000  # Sample for milliseconds

SAMPLE_RATE_COMMAND = "SAMRA"
SAMPLE_RATE_DEFAULT = 16000 # samples/s. 

DELAY_COMMAND = "DELAY"
DELAY_DEFAULT = 100 # Time between coil off and sampling begins

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
        self._actual_sample_rate = SAMPLE_RATE_DEFAULT
        
    def getSignalData(self):
        return self._signal_data
    
    def getSampleRate(self):
        return self._sample_rate

    def getActualSampleRate(self):
        # The measured sample rate
        return self._actual_sample_rate
    
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
        self._actual_sample_rate = int(resp);
        self.log("Actual Sample Rate:  '{}' samples/s".format(
                self._actual_sample_rate))

        resp = self._ser.readline()
        resp = resp.decode('utf-8').strip()
        num_samples = int(resp);
        self.log("Number of samples: '{}'".format(num_samples))

        
        self._signal_data = np.zeros(num_samples)

        with open(DATA_FILE_NAME, mode='w', encoding= "utf-8") as f:         
            f.write("{}\n".format(num_samples));
            f.write("{}\n".format(self._actual_sample_rate));
        
            for i in range(num_samples):
                resp = self._ser.readline()
                resp = resp.decode('utf-8').strip()
                self._signal_data[i] = int(resp)
                f.write("{}\n".format(int(resp)))
            
        self.log("Recieved '{}' samples".format(num_samples))

        
        
            
        
            

