import logging
import PPM
import PPMCalc


# Proton Precession Magnetometer Running Software
# Execute the code that turns on the polarising coil, records the signal and
# does the analysis to return Magnetic field strength.


logger = logging.getLogger("PPM")
logging.basicConfig(filename='ppm.log', level=logging.INFO,format='%(asctime)s %(message)s',
                    datefmt="%d-%b-%Y %H:%M:%S")

logger.info("**********************************")
logger.info("Beginning PPM Run " )

ppm = PPM.PPMRun(logger)
ppm.sendDefaultValues()

ppm.doMeasurement()
    
ppm_calc = PPMCalc.PPMCalc(ppm.getActualSampleRate(),ppm.getSampleTime(),
                           ppm.getSignalData(),logger)

ppm_calc.plotSignal("original.png",100)
ppm_calc.filterSignal(2300, 3300, 5)
ppm_calc.plotSignal("filtered.png",100)
ppm_calc.doFFT("fft.png")
