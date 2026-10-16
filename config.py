# SmartCar Configuration — Pin Definitions & Constants
# Raspberry Pi 3 + L298N + 4 BO Motors + Pi Camera v1.3

# ── L298N Motor Driver Pins ──
# Left motors (2 BO motors wired in parallel → Motor A)
ENA = 25   # PWM speed control for left motors
IN1 = 24   # Left forward
IN2 = 23   # Left backward

# Right motors (2 BO motors wired in parallel → Motor B)
ENB = 12   # PWM speed control for right motors
IN3 = 17   # Right forward
IN4 = 27   # Right backward

# ── Single White LED Plate ──
LED = 5    # GPIO 5 (Pin 29)

# ── Buzzer ──
BUZZER = 19

# ── Motor Defaults ──
DEFAULT_SPEED = 100      # PWM duty cycle (0-100) — full speed for auto modes
TURN_SPEED = 70          # Inner wheel speed during turns
PWM_FREQ = 1000          # PWM frequency in Hz

# ── Camera ──
CAMERA_WIDTH = 256
CAMERA_HEIGHT = 192
CAMERA_FPS = 10

# ── Line Follower PID ──
PID_KP = 0.4
PID_KI = 0.0
PID_KD = 0.2
LINE_THRESHOLD = 60      # Binary threshold for black line

# ── Traffic Light Detection (HSV Ranges) ──
RED_LOWER_1 = (0, 120, 70)
RED_UPPER_1 = (10, 255, 255)
RED_LOWER_2 = (170, 120, 70)
RED_UPPER_2 = (180, 255, 255)
GREEN_LOWER = (36, 100, 100)
GREEN_UPPER = (86, 255, 255)
YELLOW_LOWER = (15, 100, 100)
YELLOW_UPPER = (35, 255, 255)
MIN_TRAFFIC_AREA = 500   # Minimum contour area to count as traffic light

# ── Smart Parking (Green Markers HSV) ──
PARK_MARKER_LOWER = (36, 80, 80)
PARK_MARKER_UPPER = (86, 255, 255)
PARK_MIN_AREA = 300

# ── Modes ──
MODE_MANUAL = "manual"
MODE_LINE_FOLLOW = "line_follow"
MODE_TRAFFIC = "traffic"
MODE_AUTOPILOT = "autopilot"
MODE_SMART_PARK = "smart_park"
MODE_CONVOY = "convoy"

# ── Server ──
HOST = "0.0.0.0"
PORT = 5000
