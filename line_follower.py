import cv2
import numpy as np
import config


class LineFollower:
    """Black line follower using PID control on the bottom half of the frame."""

    def __init__(self):
        self.kp = config.PID_KP
        self.ki = config.PID_KI
        self.kd = config.PID_KD
        self.last_error = 0
        self.integral = 0
        self.line_detected = False
        self.debug_frame = None

    def reset_pid(self):
        self.last_error = 0
        self.integral = 0

    def process(self, frame):
        """Analyze bottom half of frame, return (left_speed, right_speed, annotated_frame)."""
        h, w = frame.shape[:2]
        roi = frame[h // 2:, :]  # bottom half

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(blur, config.LINE_THRESHOLD, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        annotated = frame.copy()

        if not contours:
            self.line_detected = False
            self.debug_frame = annotated
            return None, None, annotated

        largest = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest)

        if M["m00"] == 0:
            self.line_detected = False
            self.debug_frame = annotated
            return None, None, annotated

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"]) + h // 2  # offset to full frame coords

        self.line_detected = True

        # Error: how far the line center is from frame center
        error = cx - (w // 2)

        # PID calculation
        self.integral += error
        self.integral = max(-1000, min(1000, self.integral))  # anti-windup
        derivative = error - self.last_error
        correction = (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)
        self.last_error = error

        base_speed = config.DEFAULT_SPEED
        left_speed = base_speed + correction
        right_speed = base_speed - correction

        left_speed = max(-100, min(100, left_speed))
        right_speed = max(-100, min(100, right_speed))

        # Draw annotations
        cv2.drawContours(annotated[h // 2:, :], [largest], -1, (0, 255, 0), 2)
        cv2.circle(annotated, (cx, cy), 8, (0, 0, 255), -1)
        cv2.line(annotated, (w // 2, h // 2), (w // 2, h), (255, 0, 0), 1)
        cv2.putText(annotated, f"err:{error}", (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        self.debug_frame = annotated
        return left_speed, right_speed, annotated
