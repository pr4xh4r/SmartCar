import config

try:
    import RPi.GPIO as GPIO
except ImportError:
    from unittest.mock import MagicMock
    GPIO = MagicMock()
    print("[WARN] RPi.GPIO not found — running in simulation mode")


class MotorController:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        all_pins = [config.ENA, config.IN1, config.IN2,
                    config.ENB, config.IN3, config.IN4]
        for pin in all_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)

        self.pwm_left = GPIO.PWM(config.ENA, config.PWM_FREQ)
        self.pwm_right = GPIO.PWM(config.ENB, config.PWM_FREQ)
        self.pwm_left.start(100)
        self.pwm_right.start(100)
        self.speed = 100
        self.manual_mode = False

    def set_speed(self, speed):
        self.speed = max(0, min(100, speed))

    def set_manual(self, is_manual):
        self.manual_mode = is_manual

    def _enable(self):
        """Set ENA/ENB — full power for auto, slider speed for manual."""
        if self.manual_mode:
            self.pwm_left.ChangeDutyCycle(self.speed)
            self.pwm_right.ChangeDutyCycle(self.speed)
        else:
            self.pwm_left.ChangeDutyCycle(100)
            self.pwm_right.ChangeDutyCycle(100)

    def forward(self):
        GPIO.output(config.IN1, GPIO.HIGH)
        GPIO.output(config.IN2, GPIO.LOW)
        GPIO.output(config.IN3, GPIO.HIGH)
        GPIO.output(config.IN4, GPIO.LOW)
        self._enable()

    def backward(self):
        GPIO.output(config.IN1, GPIO.LOW)
        GPIO.output(config.IN2, GPIO.HIGH)
        GPIO.output(config.IN3, GPIO.LOW)
        GPIO.output(config.IN4, GPIO.HIGH)
        self._enable()

    def turn_left(self):
        GPIO.output(config.IN1, GPIO.LOW)
        GPIO.output(config.IN2, GPIO.HIGH)
        GPIO.output(config.IN3, GPIO.HIGH)
        GPIO.output(config.IN4, GPIO.LOW)
        self._enable()

    def turn_right(self):
        GPIO.output(config.IN1, GPIO.HIGH)
        GPIO.output(config.IN2, GPIO.LOW)
        GPIO.output(config.IN3, GPIO.LOW)
        GPIO.output(config.IN4, GPIO.HIGH)
        self._enable()

    def soft_left(self, left_speed=None, right_speed=None):
        GPIO.output(config.IN1, GPIO.HIGH)
        GPIO.output(config.IN2, GPIO.LOW)
        GPIO.output(config.IN3, GPIO.HIGH)
        GPIO.output(config.IN4, GPIO.LOW)
        self._enable()

    def soft_right(self, left_speed=None, right_speed=None):
        GPIO.output(config.IN1, GPIO.HIGH)
        GPIO.output(config.IN2, GPIO.LOW)
        GPIO.output(config.IN3, GPIO.HIGH)
        GPIO.output(config.IN4, GPIO.LOW)
        self._enable()

    def differential_drive(self, left_speed, right_speed):
        """For PID — direction based on sign, always full power."""
        left_dir = left_speed >= 0
        right_dir = right_speed >= 0
        GPIO.output(config.IN1, GPIO.HIGH if left_dir else GPIO.LOW)
        GPIO.output(config.IN2, GPIO.LOW if left_dir else GPIO.HIGH)
        GPIO.output(config.IN3, GPIO.HIGH if right_dir else GPIO.LOW)
        GPIO.output(config.IN4, GPIO.LOW if right_dir else GPIO.HIGH)
        self.pwm_left.ChangeDutyCycle(100)
        self.pwm_right.ChangeDutyCycle(100)

    def stop(self):
        GPIO.output(config.IN1, GPIO.LOW)
        GPIO.output(config.IN2, GPIO.LOW)
        GPIO.output(config.IN3, GPIO.LOW)
        GPIO.output(config.IN4, GPIO.LOW)
        self.pwm_left.ChangeDutyCycle(0)
        self.pwm_right.ChangeDutyCycle(0)

    def cleanup(self):
        self.stop()
        self.pwm_left.stop()
        self.pwm_right.stop()
        GPIO.cleanup()
