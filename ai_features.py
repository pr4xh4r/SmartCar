"""SmartCar AI Features — Lightweight for Pi 3 (1GB RAM).

All processing at 160x120 resolution internally.
Uses only basic OpenCV — no heavy ML models.
Optimized to avoid false positives.
"""

import cv2
import numpy as np
import time
import threading
from collections import deque


# ══════════════════════════════════════════
#  1. COLLISION PREDICTION & AUTO-BRAKE
# ══════════════════════════════════════════
class CollisionPredictor:
    """Detects objects getting closer by tracking contour area growth.
    Uses center ROI only — ignores edges (road sides, sky).
    Requires 4 consecutive growing frames to trigger (avoids false positives).
    """

    def __init__(self):
        self.prev_area = 0
        self.growth_rates = deque(maxlen=6)
        self.risk = "safe"
        self.ttc = 999
        self.danger_count = 0      # consecutive danger frames
        self.CONFIRM_FRAMES = 4    # need 4 frames of danger to trigger

    def process(self, frame):
        small = cv2.resize(frame, (160, 120))
        # Center region only — where obstacles matter most
        roi = small[20:80, 30:130]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 40, 120)

        # Dilate edges to connect nearby contours
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Only consider substantial contours
        contours = [c for c in contours if cv2.contourArea(c) > 80]

        if not contours:
            self.prev_area = 0
            self.danger_count = 0
            self.risk = "safe"
            self.ttc = 999
            return self.risk, self.ttc

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        if self.prev_area > 80:
            growth = (area - self.prev_area) / max(self.prev_area, 1)
            self.growth_rates.append(growth)

        self.prev_area = area

        if len(self.growth_rates) >= 4:
            avg_growth = sum(self.growth_rates) / len(self.growth_rates)
            # Also check if object is already large (close)
            is_close = area > 1500

            if avg_growth > 0.25 and is_close:
                self.danger_count += 1
            elif avg_growth > 0.15:
                self.danger_count = max(0, self.danger_count - 1)
            else:
                self.danger_count = 0

            if self.danger_count >= self.CONFIRM_FRAMES:
                self.risk = "danger"
                self.ttc = max(0.5, 2.0 / max(avg_growth * 10, 0.1))
            elif self.danger_count >= 2:
                self.risk = "warning"
                self.ttc = max(1.5, 4.0 / max(avg_growth * 10, 0.1))
            else:
                self.risk = "safe"
                self.ttc = 999
        else:
            self.risk = "safe"
            self.ttc = 999

        return self.risk, self.ttc


# ══════════════════════════════════════════
#  2. PEDESTRIAN / MOVING OBJECT TRACKER
# ══════════════════════════════════════════
class PedestrianTracker:
    """Tracks moving objects using frame differencing.

    Accuracy improvements:
    - Only detects in upper-center region (where pedestrians appear)
    - Filters by aspect ratio (pedestrians are taller than wide)
    - Requires 3 consecutive detections before alerting (avoids false positives)
    - Tracks centroid to predict direction
    """

    def __init__(self):
        self.prev_gray = None
        self.prev_positions = deque(maxlen=6)
        self.detected = False
        self.direction = "none"
        self.confirm_count = 0       # consecutive detection frames
        self.CONFIRM_FRAMES = 3      # need 3 frames to confirm
        self.no_detect_count = 0     # frames without detection

    def process(self, frame):
        small = cv2.resize(frame, (160, 120))
        # Upper center — where pedestrians appear in front of car
        roi = small[10:80, 20:140]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (7, 7), 0)

        if self.prev_gray is None:
            self.prev_gray = blur
            self.detected = False
            return self.detected, self.direction

        diff = cv2.absdiff(self.prev_gray, blur)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        self.prev_gray = blur

        # Filter: size + aspect ratio (pedestrian = taller than wide)
        pedestrian_contours = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < 300 or area > 6000:
                continue
            x, y, w, h = cv2.boundingRect(c)
            aspect = h / max(w, 1)
            # Pedestrian: height > width (aspect > 1.0)
            # Also accept square-ish (aspect > 0.7) for close-up
            if aspect > 0.7:
                pedestrian_contours.append(c)

        if not pedestrian_contours:
            self.no_detect_count += 1
            # Only clear after 5 frames of no detection (hysteresis)
            if self.no_detect_count > 5:
                self.confirm_count = 0
                self.detected = False
                self.direction = "none"
                self.prev_positions.clear()
            return self.detected, self.direction

        self.no_detect_count = 0
        self.confirm_count += 1

        largest = max(pedestrian_contours, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            self.prev_positions.append((cx, cy, time.time()))

        # Only confirm detection after CONFIRM_FRAMES consecutive detections
        if self.confirm_count >= self.CONFIRM_FRAMES:
            self.detected = True

            # Predict direction from positions
            if len(self.prev_positions) >= 3:
                dx = self.prev_positions[-1][0] - self.prev_positions[0][0]
                dy = self.prev_positions[-1][1] - self.prev_positions[0][1]

                if abs(dx) > abs(dy) and abs(dx) > 8:
                    self.direction = "right" if dx > 0 else "left"
                elif dy > 8:
                    self.direction = "approaching"
                else:
                    self.direction = "stationary"
            else:
                self.direction = "stationary"
        else:
            self.detected = False
            self.direction = "none"

        return self.detected, self.direction


# ══════════════════════════════════════════
#  3. DRIVER BEHAVIOR ANALYSIS
# ══════════════════════════════════════════
class DriverAnalyzer:
    """Tracks driving patterns and calculates a safety score."""

    def __init__(self):
        self.total_commands = 0
        self.sharp_turns = 0
        self.hard_brakes = 0
        self.speed_changes = 0
        self.avg_speed_sum = 0
        self.avg_speed_count = 0
        self.last_action = "stop"
        self.last_speed = 0
        self.last_action_time = time.time()
        self.session_start = time.time()

    def log_action(self, action, speed):
        now = time.time()
        dt = now - self.last_action_time
        self.total_commands += 1

        # Sharp turn: direction change within 0.5 seconds
        if action in ("left", "right") and self.last_action == "forward" and dt < 0.5:
            self.sharp_turns += 1

        # Hard brake: stop from high speed within 0.3 seconds
        if action == "stop" and self.last_action in ("forward", "backward"):
            if self.last_speed > 50 and dt < 0.3:
                self.hard_brakes += 1

        # Sudden speed change
        if abs(speed - self.last_speed) > 25:
            self.speed_changes += 1

        self.avg_speed_sum += speed
        self.avg_speed_count += 1
        self.last_action = action
        self.last_speed = speed
        self.last_action_time = now

    def get_score(self):
        duration = round(time.time() - self.session_start)
        if self.total_commands == 0:
            return {"score": 100, "sharp_turns": 0, "hard_brakes": 0,
                    "avg_speed": 0, "total_commands": 0, "grade": "A+",
                    "duration": duration}

        avg_speed = self.avg_speed_sum / max(self.avg_speed_count, 1)

        score = 100
        score -= self.sharp_turns * 5
        score -= self.hard_brakes * 10
        score -= self.speed_changes * 2
        if avg_speed > 80:
            score -= 10
        score = max(0, min(100, score))

        if score >= 90:
            grade = "A+"
        elif score >= 75:
            grade = "A"
        elif score >= 60:
            grade = "B"
        elif score >= 40:
            grade = "C"
        else:
            grade = "D"

        return {
            "score": round(score),
            "sharp_turns": self.sharp_turns,
            "hard_brakes": self.hard_brakes,
            "avg_speed": round(avg_speed),
            "total_commands": self.total_commands,
            "grade": grade,
            "duration": duration,
        }


# ══════════════════════════════════════════
#  4. ACCIDENT DETECTOR + SOS
# ══════════════════════════════════════════
class AccidentDetector:
    """Detects sudden impacts via frame change spike + motor state.

    Accuracy improvements:
    - Tracks running average of frame changes (baseline)
    - Only triggers when change > 3x baseline AND motor was running
    - Motor must have been running for > 1 second (avoids startup false positives)
    - Captures 5 photos with 2 sec delay
    """

    def __init__(self):
        self.prev_gray = None
        self.was_moving = False
        self.moving_since = 0        # timestamp when motor started
        self.cooldown = 0
        self.accident_detected = False
        self.accident_photos = []
        self.alert_callback = None
        self.change_history = deque(maxlen=20)  # baseline frame changes
        self.baseline = 5.0          # initial baseline

    def set_alert_callback(self, callback):
        self.alert_callback = callback

    def update_motor_state(self, is_moving):
        if is_moving and not self.was_moving:
            self.moving_since = time.time()
        self.was_moving = is_moving

    def check(self, frame, camera):
        self.accident_detected = False

        if self.cooldown > 0:
            self.cooldown -= 1
            return False

        small = cv2.resize(frame, (80, 60))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None:
            self.prev_gray = gray
            return False

        diff = cv2.absdiff(self.prev_gray, gray)
        change = float(np.mean(diff))
        self.prev_gray = gray

        # Update baseline (running average of normal changes)
        self.change_history.append(change)
        if len(self.change_history) >= 10:
            self.baseline = sum(self.change_history) / len(self.change_history)

        # Conditions for accident:
        # 1. Motor was running for at least 1 second
        # 2. Frame change is 3x above baseline
        # 3. Frame change is at least 30 (absolute minimum)
        motor_running_long = (self.was_moving and
                              (time.time() - self.moving_since) > 1.0)
        spike = change > max(self.baseline * 3, 30)

        if motor_running_long and spike:
            self.accident_detected = True
            self.cooldown = 200  # ~10 seconds cooldown

            # Capture 5 photos with 2 sec delay
            self.accident_photos = []
            for i in range(5):
                f = camera.get_frame()
                if f is not None:
                    _, jpeg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    self.accident_photos.append(jpeg.tobytes())
                if i < 4:
                    time.sleep(2)

            if self.alert_callback and self.accident_photos:
                threading.Thread(
                    target=self.alert_callback,
                    args=(self.accident_photos,),
                    daemon=True
                ).start()

            return True

        return False


# ══════════════════════════════════════════
#  5. ROAD CONDITION DETECTOR
# ══════════════════════════════════════════
class RoadAnalyzer:
    """Analyzes road texture using Laplacian variance.
    Uses running average to avoid flickering between states.
    """

    def __init__(self):
        self.condition = "unknown"
        self.variance = 0
        self.speed_factor = 1.0
        self.history = deque(maxlen=10)  # smooth readings

    def process(self, frame):
        small = cv2.resize(frame, (160, 120))
        road = small[90:, 30:130]  # bottom center strip
        gray = cv2.cvtColor(road, cv2.COLOR_BGR2GRAY)

        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        self.variance = laplacian.var()
        self.history.append(self.variance)

        # Use average of recent readings (avoids flickering)
        avg_var = sum(self.history) / len(self.history)

        if avg_var < 100:
            self.condition = "smooth"
            self.speed_factor = 1.0
        elif avg_var < 500:
            self.condition = "normal"
            self.speed_factor = 0.8
        else:
            self.condition = "rough"
            self.speed_factor = 0.5

        return self.condition, self.speed_factor


# ══════════════════════════════════════════
#  6. CONVOY / FOLLOW ME MODE
# ══════════════════════════════════════════
class ConvoyFollower:
    """Follows a colored object. Color selected via Telegram.
    Uses PID-like control for smooth steering.
    Requires minimum area to avoid tracking noise.
    """

    COLORS = {
        "red":    [(0, 120, 70), (10, 255, 255), (170, 120, 70), (180, 255, 255)],
        "blue":   [(100, 120, 70), (130, 255, 255)],
        "green":  [(36, 80, 80), (86, 255, 255)],
        "yellow": [(20, 100, 100), (35, 255, 255)],
        "orange": [(10, 120, 70), (20, 255, 255)],
        "pink":   [(140, 50, 50), (170, 255, 255)],
        "white":  [(0, 0, 200), (180, 30, 255)],
    }

    def __init__(self):
        self.target_color = None
        self.active = False
        self.last_error = 0
        self.integral = 0
        self.lost_count = 0    # frames without target

    def set_color(self, color_name):
        color_name = color_name.lower().strip()
        if color_name in self.COLORS:
            self.target_color = color_name
            self.active = True
            self.lost_count = 0
            self.integral = 0
            self.last_error = 0
            return True
        return False

    def stop(self):
        self.active = False
        self.target_color = None

    def process(self, frame):
        if not self.active or not self.target_color:
            return None, None

        small = cv2.resize(frame, (160, 120))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

        ranges = self.COLORS[self.target_color]
        if len(ranges) == 4:
            mask1 = cv2.inRange(hsv, np.array(ranges[0]), np.array(ranges[1]))
            mask2 = cv2.inRange(hsv, np.array(ranges[2]), np.array(ranges[3]))
            mask = cv2.bitwise_or(mask1, mask2)
        else:
            mask = cv2.inRange(hsv, np.array(ranges[0]), np.array(ranges[1]))

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Higher minimum area to avoid noise
        contours = [c for c in contours if cv2.contourArea(c) > 200]

        if not contours:
            self.lost_count += 1
            if self.lost_count > 15:  # lost for ~1.5 seconds
                return None, None
            # Keep last steering briefly
            return 0, 0  # stop but don't return None

        self.lost_count = 0
        largest = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None, None

        cx = int(M["m10"] / M["m00"])
        area = cv2.contourArea(largest)

        # PD controller for steering
        error = cx - 80  # center is 80
        derivative = error - self.last_error
        correction = error * 0.4 + derivative * 0.15
        self.last_error = error

        # Speed based on distance
        if area > 4000:
            base_speed = 0    # too close, stop
        elif area > 2500:
            base_speed = 25   # close, slow
        elif area > 800:
            base_speed = 45   # medium distance
        else:
            base_speed = 60   # far, speed up

        left_speed = base_speed + correction
        right_speed = base_speed - correction

        left_speed = max(-50, min(75, left_speed))
        right_speed = max(-50, min(75, right_speed))

        return left_speed, right_speed
