import threading
import time
import io
import numpy as np
import cv2
import config

try:
    import picamera
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    print("[WARN] picamera not found — falling back to OpenCV (for desktop testing)")


class CameraStream:
    """Threaded camera capture using legacy picamera (raspistill stack)."""

    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.camera = None
        # Create a "no camera" placeholder frame
        placeholder = np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), dtype=np.uint8)
        cv2.putText(placeholder, "NO CAMERA", (60, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        self.placeholder = placeholder

    def start(self):
        if PICAMERA_AVAILABLE:
            return self._start_picamera()
        else:
            return self._start_opencv()

    # ── Legacy PiCamera (raspistill / raspivid stack) ──
    def _start_picamera(self):
        try:
            self.camera = picamera.PiCamera()
            self.camera.resolution = (256, 192)
            self.camera.framerate = 10
            self.camera.rotation = 0
            time.sleep(2)
            self.running = True
            self.thread = threading.Thread(target=self._picamera_loop, daemon=True)
            self.thread.start()
            print("[INFO] Camera started (legacy picamera / raspistill)")
            return True
        except Exception as e:
            print(f"[ERROR] PiCamera init failed: {e}")
            with self.lock:
                self.frame = self.placeholder
            return False

    def _picamera_loop(self):
        """Capture individual JPEG frames — avoids PiRGBArray buffer bugs."""
        while self.running:
            stream = io.BytesIO()
            try:
                self.camera.capture(stream, format="jpeg", use_video_port=True)
                stream.seek(0)
                data = np.frombuffer(stream.read(), dtype=np.uint8)
                frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if frame is not None:
                    with self.lock:
                        self.frame = frame
            except Exception as e:
                print(f"[WARN] Camera capture error: {e}")
                time.sleep(0.5)
            finally:
                stream.close()

    # ── OpenCV fallback (desktop / USB cam testing) ──
    def _start_opencv(self):
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS)
        if not self.cap.isOpened():
            print("[ERROR] Cannot open camera")
            with self.lock:
                self.frame = self.placeholder
            return False
        self.running = True
        self.thread = threading.Thread(target=self._opencv_loop, daemon=True)
        self.thread.start()
        print("[INFO] Camera started (OpenCV fallback)")
        return True

    def _opencv_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.01)

    # ── Common methods ──
    def get_frame(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            return self.placeholder.copy()

    def get_jpeg(self):
        frame = self.get_frame()
        _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        return jpeg.tobytes()

    def stop(self):
        self.running = False
        if PICAMERA_AVAILABLE and self.camera:
            try:
                self.camera.close()
            except Exception:
                pass
        elif hasattr(self, 'cap') and self.cap:
            self.cap.release()
        print("[INFO] Camera stopped")
