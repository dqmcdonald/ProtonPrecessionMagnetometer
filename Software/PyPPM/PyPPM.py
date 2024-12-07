import serial
#
# Proton Precession Magnetometer Control Software
# This module contains code that communicates with the Arduino Pro Mini
# that turns on/off the polarising coil and retrieves the signal data. 
# Communication is done by serial
#

BAUD_RATE = 9600  # Communication rate

ON_TIME_COMMAND = "ONTIM"
ON_TIME_DEFAULT = 6000



class PyPPM:
    def __init__(self):
        self._ser = serial.Serial('/dev/serial0', 9600, timeout=1)
        self._ser.reset_input_buffer()


    def sendCommand(self, command, value):
        # Send command via serial
       
        

    def sendDefaultValues(self):
        # Send default values to the Arduino coil controller

        self.sendCommand(ON_TIME_COMMAND, ON_TIME_DEFAULT )






if __name__ == '__main__':


    ppm = PyPPM()
    self.sendDefaultValues()

#    ser.write(str('ONTIM `1000\n').encode('utf-8')) 
#    print(ser.readline())
#    ser.write(str('EXECU\n').encode('utf-8')) 
#    print(ser.readline())
