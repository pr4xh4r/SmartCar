import cv2
import numpy as np
import time
import config


class SmartParker:
    """Auto-parking using green marker detection."""

    PHASE_SCANNING = "scanning"
    PHASE_ALIGNING = "aligning"
    PHASE_REVERSING = "reversing"
    PHASE_DONE = "parked"
    PHASE_FAILED = "failed"

    def __init__(self):
        self.phase = self.PHASE_SCANNING
        self.markers = []
        self.debug_frame = None
        self.start_time = 0
        self._reverse_start = 0

    def reset(self):
        self.phase = self.PHASE_SCANNING
        self.markers = []
        self.start_time = time.time()

    def process(self, frame, motor):
        """Run one parking step. Returns (phase, annotated_frame)."""
        h, w = frame.shape[:2]
        annotated = frame.copy()

        # Detect green markers
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv,
                           np.array(config.PARK_MARKER_LOWER),
                           np.array(config.PARK_MARKER_UPPER))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        markers = [c for c in contours if cv2.contourArea(c) > config.PARK_MIN_AREA]

        # Draw detected markers
        for m in markers:
            x, y, mw, mh = cv2.boundingRect(m)
            cv2.rectangle(annotated, (x, y), (x + mw, y + mh), (0, 255, 0), 2)
            cv2.putText(annotated, "MARKER", (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        # Timeout
        if time.time() - self.start_time > 20:
            self.phase = self.PHASE_FAILED
            motor.stop()

        if self.phase == self.PHASE_SCANNING:
            cv2.putText(annotated, "SCANNING FOR SPOT...", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

            if len(markers) >= 2:
                # Sort markers by x-position
                marker_centers = []
                for m in markers:
                    M = cv2.moments(m)
                    if M["m00"] > 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        marker_centers.append((cx, cy))

                if len(marker_centers) >= 2:
                    marker_centers.sort(key=lambda p: p[0])
                    self.markers = marker_centers[:2]
                    self.phase = self.PHASE_ALIGNING
            else:
                # Slowly rotate to scan
                motor.soft_right(left_speed=35, right_speed=20)

        elif self.phase == self.PHASE_ALIGNING:
            cv2.putText(annotated, "ALIGNING...", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)

            if len(self.markers) >= 2:
                mid_x = (self.markers[0][0] + self.markers[1][0]) // 2
                center_x = w // 2
                error = mid_x - center_x

                if abs(error) < 20:
                    motor.stop()
                    self.phase = self.PHASE_REVERSING
                    self._reverse_start = time.time()
                elif error > 0:
                    motor.soft_right(left_speed=35, right_speed=20)
                else:
                    motor.soft_left(left_speed=20, right_speed=35)
            else:
                self.phase = self.PHASE_SCANNING

        elif self.phase == self.PHASE_REVERSING:
            cv2.putText(annotated, "REVERSING IN...", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

            elapsed = time.time() - self._reverse_start
            if elapsed < 2.0:
                motor.backward()
            else:
                motor.stop()
                self.phase = self.PHASE_DONE

        elif self.phase == self.PHASE_DONE:
            cv2.putText(annotated, "PARKED!", (w // 2 - 50, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
            motor.stop()

        elif self.phase == self.PHASE_FAILED:
            cv2.putText(annotated, "PARK FAILED - TIMEOUT", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            motor.stop()

        self.debug_frame = annotated
        return self.phase, annotated
