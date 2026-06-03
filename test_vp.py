import time
from detector import VideoProcessor

def f(x):
    pass

p = VideoProcessor('Vehicles Driving Through Flooding A93 Road Perthshire Scotland.mp4', on_frame=f, on_error=print)
p.start()
time.sleep(10)
print("Finished 10 seconds")
