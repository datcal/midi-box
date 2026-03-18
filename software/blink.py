import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)   # use BCM numbering (GPIO 17, not pin 11)
GPIO.setup(17, GPIO.OUT)

try:
    while True:
        GPIO.output(17, GPIO.HIGH)  # LED on
        time.sleep(0.1)
        GPIO.output(17, GPIO.LOW)   # LED off
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()  # always reset pins on exit