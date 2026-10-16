import cv2
import numpy as np
import config


class TrafficLightDetector:
    """Detects traffic light colors using HSV color segmentation on the top half of the frame."""

    def __init__(self):
        self.current_color = "none"  # "red", "yellow", "green", "none"
        self.confidence = 0
        self.debug_frame = None

    def process(self, frame):
        """Analyze top half of frame for traffic light colors.
        Returns (color, confidence, annotated_frame).
        """
        h, w = frame.shape[:2]
        roi = frame[:h // 2, :]  # top half
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        annotated = frame.copy()

        # Detect each color
        red_area, red_box = self._detect_color(hsv, roi,
            [config.RED_LOWER_1, config.RED_LOWER_2],
            [config.RED_UPPER_1, config.RED_UPPER_2])

        green_area, green_box = self._detect_color(hsv, roi,
            [config.GREEN_LOWER], [config.GREEN_UPPER])

        yellow_area, yellow_box = self._detect_color(hsv, roi,
            [config.YELLOW_LOWER], [config.YELLOW_UPPER])

        # Pick dominant color
        results = {
            "red": (red_area, red_box, (0, 0, 255)),
            "green": (green_area, green_box, (0, 255, 0)),
            "yellow": (yellow_area, yellow_box, (0, 255, 255)),
        }

        best_color = "none"
        best_area = config.MIN_TRAFFIC_AREA
        best_box = None
        draw_color = (255, 255, 255)

        for color_name, (area, box, bgr) in results.items():
            if area > best_area:
                best_area = area
                best_color = color_name
                best_box = box
                draw_color = bgr

        self.current_color = best_color
        self.confidence = min(best_area / 3000.0, 1.0) if best_color != "none" else 0

        # Draw on annotated frame
        if best_box is not None:
            x, y, bw, bh = best_box
            cv2.rectangle(annotated, (x, y), (x + bw, y + bh), draw_color, 2)
            label = f"{best_color.upper()} ({self.confidence:.0%})"
            cv2.putText(annotated, label, (x, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, draw_color, 2)

        # Status bar
        status = f"TRAFFIC: {best_color.upper()}" if best_color != "none" else "TRAFFIC: SCANNING..."
        cv2.putText(annotated, status, (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, draw_color, 2)

        self.debug_frame = annotated
        return best_color, self.confidence, annotated

    def _detect_color(self, hsv, roi, lowers, uppers):
        """Detect a color given multiple HSV ranges. Returns (area, bounding_box)."""
        combined_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in zip(lowers, uppers):
            mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
            combined_mask = cv2.bitwise_or(combined_mask, mask)

        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return 0, None

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        box = cv2.boundingRect(largest)
        return area, box
