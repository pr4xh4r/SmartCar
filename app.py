#!/usr/bin/env python3
"""SmartCar — Main Flask + SocketIO Application."""

import time
import threading
from flask import Flask, render_template, Response, request
from flask_socketio import SocketIO, emit

import config
from motor import MotorController
from camera import CameraStream
from line_follower import LineFollower
from traffic_detector import TrafficLightDetector
from smart_park import SmartParker

try:
    import RPi.GPIO as GPIO
except ImportError:
    from unittest.mock import MagicMock
    GPIO = MagicMock()

# ── Init ──
app = Flask(__name__)
app.config["SECRET_KEY"] = "smartcar2026"
socketio = SocketIO(app, cors_allowed_origins="*")


# Allow cross-origin requests
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


motor = MotorController()
camera = CameraStream()
line_follower = LineFollower()
traffic_detector = TrafficLightDetector()
smart_parker = SmartParker()

current_mode = config.MODE_MANUAL
mode_lock = threading.Lock()
auto_running = False
auto_thread = None

VALID_MODES = {config.MODE_MANUAL, config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC,
               config.MODE_AUTOPILOT, config.MODE_SMART_PARK}
VALID_CMDS = {"forward", "backward", "left", "right", "stop"}

# ── LED & Buzzer Setup ──
GPIO.setup(config.LED, GPIO.OUT)
GPIO.output(config.LED, GPIO.LOW)
GPIO.setup(config.BUZZER, GPIO.OUT)
GPIO.output(config.BUZZER, GPIO.LOW)

led_enabled = True
led_running = True


def led_blink_loop():
    """LED blink thread — parking: 1s on/off with buzzer, else: fast blink."""
    while led_running:
        if not led_enabled:
            GPIO.output(config.LED, GPIO.LOW)
            GPIO.output(config.BUZZER, GPIO.LOW)
            time.sleep(0.2)
            continue

        with mode_lock:
            mode = current_mode

        if mode == config.MODE_SMART_PARK:
            # Parking mode: LED + buzzer 1 sec on, 1 sec off
            GPIO.output(config.LED, GPIO.HIGH)
            GPIO.output(config.BUZZER, GPIO.HIGH)
            time.sleep(1.0)
            GPIO.output(config.LED, GPIO.LOW)
            GPIO.output(config.BUZZER, GPIO.LOW)
            time.sleep(1.0)
        else:
            # Normal: LED blinks fast (0.3s on, 0.3s off)
            GPIO.output(config.LED, GPIO.HIGH)
            time.sleep(0.3)
            GPIO.output(config.LED, GPIO.LOW)
            time.sleep(0.3)


# Start LED blink thread
threading.Thread(target=led_blink_loop, daemon=True).start()


def buzzer_beep(times=1, duration=0.15):
    """Non-blocking buzzer beeps."""
    def _beep():
        for i in range(times):
            GPIO.output(config.BUZZER, GPIO.HIGH)
            time.sleep(duration)
            GPIO.output(config.BUZZER, GPIO.LOW)
            if i < times - 1:
                time.sleep(0.1)
    threading.Thread(target=_beep, daemon=True).start()


# ── MJPEG Stream ──
def generate_frames():
    while True:
        try:
            jpeg = camera.get_jpeg()
            if jpeg:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                time.sleep(0.1)
            else:
                time.sleep(0.1)
        except Exception as e:
            print(f"[ERROR] Frame generation: {e}")
            time.sleep(0.1)


# ── Autonomous Loop ──
def auto_loop():
    global auto_running
    while auto_running:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        with mode_lock:
            mode = current_mode

        try:
            if mode == config.MODE_LINE_FOLLOW:
                left, right, _ = line_follower.process(frame)
                if left is not None and right is not None:
                    motor.differential_drive(left, right)
                else:
                    motor.stop()
                socketio.emit("status", {
                    "mode": mode,
                    "line_detected": line_follower.line_detected,
                })

            elif mode == config.MODE_TRAFFIC:
                color, conf, _ = traffic_detector.process(frame)
                if color == "red":
                    motor.stop()
                    buzzer_beep(1)
                elif color == "green":
                    motor.forward()
                    buzzer_beep(2, 0.08)
                elif color == "yellow":
                    motor.set_speed(config.DEFAULT_SPEED // 2)
                    motor.forward()
                    motor.set_speed(config.DEFAULT_SPEED)
                else:
                    motor.stop()
                socketio.emit("status", {
                    "mode": mode,
                    "traffic_color": color,
                    "confidence": round(conf, 2),
                })

            elif mode == config.MODE_AUTOPILOT:
                color, conf, _ = traffic_detector.process(frame)
                if color == "red":
                    motor.stop()
                    buzzer_beep(1)
                else:
                    left, right, _ = line_follower.process(frame)
                    if left is not None and right is not None:
                        motor.differential_drive(left, right)
                    else:
                        motor.stop()
                    if color == "green":
                        buzzer_beep(2, 0.08)
                socketio.emit("status", {
                    "mode": mode,
                    "traffic_color": color,
                    "line_detected": line_follower.line_detected,
                })

            elif mode == config.MODE_SMART_PARK:
                phase, _ = smart_parker.process(frame, motor)
                socketio.emit("status", {
                    "mode": mode,
                    "park_phase": phase,
                })
                if phase in (SmartParker.PHASE_DONE, SmartParker.PHASE_FAILED):
                    if phase == SmartParker.PHASE_DONE:
                        buzzer_beep(3, 0.1)
                    auto_running = False
                    break

        except Exception as e:
            print(f"[ERROR] Auto loop: {e}")

        time.sleep(0.05)


def start_auto_mode():
    global auto_running, auto_thread
    stop_auto_mode()
    auto_running = True
    auto_thread = threading.Thread(target=auto_loop, daemon=True)
    auto_thread.start()


def stop_auto_mode():
    global auto_running
    auto_running = False
    motor.stop()
    line_follower.reset_pid()


# ── Routes ──
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/test_motor/<direction>")
def test_motor(direction):
    if direction not in VALID_CMDS:
        return "Invalid", 400
    actions = {
        "forward": motor.forward,
        "backward": motor.backward,
        "left": motor.turn_left,
        "right": motor.turn_right,
        "stop": motor.stop,
    }
    actions[direction]()
    return f"Motor: {direction}"


# ── SocketIO Events ──
@socketio.on("connect")
def on_connect():
    emit("status", {"mode": current_mode, "speed": motor.speed, "led": led_enabled})
    print("[INFO] Client connected")


@socketio.on("set_mode")
def on_set_mode(data):
    global current_mode
    mode = data.get("mode", config.MODE_MANUAL)
    if mode not in VALID_MODES:
        return

    with mode_lock:
        current_mode = mode

    if mode == config.MODE_MANUAL:
        stop_auto_mode()
    elif mode == config.MODE_SMART_PARK:
        smart_parker.reset()
        start_auto_mode()
    elif mode in (config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC, config.MODE_AUTOPILOT):
        start_auto_mode()

    emit("status", {"mode": current_mode}, broadcast=True)


@socketio.on("control")
def on_control(data):
    action = data.get("action", "stop")
    if action not in VALID_CMDS:
        return
    print(f"[CONTROL] {action}")
    with mode_lock:
        if current_mode != config.MODE_MANUAL:
            return
    actions = {
        "forward": motor.forward,
        "backward": motor.backward,
        "left": motor.turn_left,
        "right": motor.turn_right,
        "stop": motor.stop,
    }
    actions[action]()


@socketio.on("set_speed")
def on_set_speed(data):
    speed = max(0, min(100, int(data.get("speed", config.DEFAULT_SPEED))))
    motor.set_speed(speed)
    emit("status", {"speed": motor.speed}, broadcast=True)


@socketio.on("led")
def on_led(data):
    global led_enabled
    state = data.get("state", False)
    led_enabled = state
    print(f"[LED] {'ON' if state else 'OFF'}")


@socketio.on("buzzer")
def on_buzzer(data):
    buzzer_beep(times=data.get("times", 1))


# ── Main ──
if __name__ == "__main__":
    camera.start()
    try:
        print(f"[INFO] SmartCar running at http://{config.HOST}:{config.PORT}")
        socketio.run(app, host=config.HOST, port=config.PORT,
                     debug=False, allow_unsafe_werkzeug=True)
    finally:
        led_running = False
        camera.stop()
        motor.cleanup()
