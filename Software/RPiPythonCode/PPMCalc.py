import numpy as np
import matplotlib.pyplot as plt
import scipy.signal as sig
from scipy.signal import butter, lfilter

def butter_bandpass(lowcut, highcut, fs, order=5):
    return butter(order, [lowcut, highcut], fs=fs, btype='band')

def butter_bandpass_filter(data, lowcut, highcut, fs, order=5):
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    y = lfilter(b, a, data)
    return y


class PPMCalc:
    
    def __init__(self, sample_rate, sample_time, signal_data, lg=None):
        self._logger = lg
        self._sample_rate = int(sample_rate)
        self._sample_time = sample_time/1000 # Convert from microseconds
        self._signal_data = signal_data
        # Normalise and center around zero:
        self._signal_data = ((self._signal_data-np.min(self._signal_data))/
                ((np.max(self._signal_data)-np.min(self._signal_data))))
          
        self._signal_data = self._signal_data - np.mean(self._signal_data)
        # Create corresponding time axis:
        self._time = np.arange(0, self._sample_time, 1/self._sample_rate)
        
        
    def log(self, msg ):
        # Log message "msg" to the current logger (if any)
        if self._logger:
            self._logger.info(msg)
            
    def plotSignal(self, file_name, max_data = 500):
        plt.figure(figsize=(20, 6), dpi=80)
        plt.plot(self._time[:max_data], self._signal_data[:max_data])
        plt.savefig(file_name)
        
    def filterSignal(self, lower, upper, order=5):
        # create filtered version of the signal data using Butterworth 
        # filter of order with a window defined by "lower" and "upper"
        self._signal_data = butter_bandpass_filter(self._signal_data,
                                                            lower, upper,
                                                            self._sample_rate,
                                                            order)
    def doFFT( self, filename ):
        # Calculate a periodogram
       f, den = sig.periodogram(self._signal_data, 
                                self._sample_rate)
#       plt.semilogy(f,den)
#       plt.plot(f,den)
       plt.bar(f,den)
       plt.ylim([0, 0.1])
       plt.xlim([2600, 3400])
       plt.savefig(filename)

       print( f[0], den[0])
       print( f[1], den[1])

       peaks_filt,_ = sig.find_peaks(den,height=0.02)
       print("Peaks:")
       for p in peaks_filt:
           print( f[p], " Hz",  den[p] )

