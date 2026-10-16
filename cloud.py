#!/usr/bin/env python3
"""SmartCar Cloud Bridge — MQTT relay for internet control."""

import json
import time
import threading
import os
import cv2
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import paho.mqtt.client as mqtt

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

# ── Config (override via .env — see .env.example) ──
BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "smartcar2027")

# Topics
T_CMD = TOPIC_PREFIX + "/cmd"
T_SPEED = TOPIC_PREFIX + "/speed"
T_MODE = TOPIC_PREFIX + "/mode"
T_LED = TOPIC_PREFIX + "/led"
T_BUZZER = TOPIC_PREFIX + "/buzzer"
T_CAM = TOPIC_PREFIX + "/cam"
T_STATUS = TOPIC_PREFIX + "/status"

VALID_MODES = {config.MODE_MANUAL, config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC,
               config.MODE_AUTOPILOT, config.MODE_SMART_PARK}
VALID_CMDS = {"forward", "backward", "left", "right", "stop"}

# ── Init hardware ──
motor = MotorController()
camera = CameraStream()
line_follower = LineFollower()
traffic_detector = TrafficLightDetector()
smart_parker = SmartParker()

current_mode = config.MODE_MANUAL
mode_lock = threading.Lock()
auto_running = False

# LED & Buzzer
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
            GPIO.output(config.LED, GPIO.HIGH)
            GPIO.output(config.BUZZER, GPIO.HIGH)
            time.sleep(1.0)
            GPIO.output(config.LED, GPIO.LOW)
            GPIO.output(config.BUZZER, GPIO.LOW)
            time.sleep(1.0)
        else:
            GPIO.output(config.LED, GPIO.HIGH)
            time.sleep(0.3)
            GPIO.output(config.LED, GPIO.LOW)
            time.sleep(0.3)


threading.Thread(target=led_blink_loop, daemon=True).start()


def buzzer_beep(times=1, duration=0.15):
    def _beep():
        for i in range(times):
            GPIO.output(config.BUZZER, GPIO.HIGH)
            time.sleep(duration)
            GPIO.output(config.BUZZER, GPIO.LOW)
            if i < times - 1:
                time.sleep(0.1)
    threading.Thread(target=_beep, daemon=True).start()


# ── MQTT Callbacks ──
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected to {BROKER} (rc={rc})")
    client.subscribe(T_CMD)
    client.subscribe(T_SPEED)
    client.subscribe(T_MODE)
    client.subscribe(T_LED)
    client.subscribe(T_BUZZER)
    client.publish(T_STATUS, json.dumps({"online": True, "mode": current_mode, "led": led_enabled}))


def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnected (rc={rc}). Reconnecting...")


def on_message(client, userdata, msg):
    global current_mode, auto_running, led_enabled
    topic = msg.topic
    try:
        data = msg.payload.decode()
    except Exception as e:
        print(f"[ERROR] Decode failed: {e}")
        return

    if topic == T_CMD:
        if data not in VALID_CMDS:
            return
        print(f"[CMD] {data}")
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
        actions[data]()

    elif topic == T_SPEED:
        try:
            speed = max(0, min(100, int(data)))
            motor.set_speed(speed)
            print(f"[SPEED] {speed}")
        except ValueError:
            pass

    elif topic == T_MODE:
        if data not in VALID_MODES:
            print(f"[WARN] Invalid mode: {data}")
            return
        with mode_lock:
            current_mode = data
        print(f"[MODE] {current_mode}")
        if data == config.MODE_MANUAL:
            stop_auto_mode()
        elif data == config.MODE_SMART_PARK:
            smart_parker.reset()
            start_auto_mode(client)
        elif data in (config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC, config.MODE_AUTOPILOT):
            start_auto_mode(client)
        client.publish(T_STATUS, json.dumps({"mode": current_mode}))

    elif topic == T_LED:
        try:
            d = json.loads(data)
            led_enabled = d.get("state", False)
            print(f"[LED] {'ON' if led_enabled else 'OFF'}")
        except Exception:
            pass

    elif topic == T_BUZZER:
        buzzer_beep(times=int(data) if data.isdigit() else 1)
        print("[BUZZER] beep")


# ── Auto mode loop ──
def auto_loop(client):
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
                client.publish(T_STATUS, json.dumps({
                    "mode": mode, "line_detected": line_follower.line_detected
                }))

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
                client.publish(T_STATUS, json.dumps({
                    "mode": mode, "traffic_color": color,
                    "confidence": round(conf, 2)
                }))

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
                client.publish(T_STATUS, json.dumps({
                    "mode": mode, "traffic_color": color,
                    "line_detected": line_follower.line_detected
                }))

            elif mode == config.MODE_SMART_PARK:
                phase, _ = smart_parker.process(frame, motor)
                client.publish(T_STATUS, json.dumps({
                    "mode": mode, "park_phase": phase
                }))
                if phase in (SmartParker.PHASE_DONE, SmartParker.PHASE_FAILED):
                    if phase == SmartParker.PHASE_DONE:
                        buzzer_beep(3, 0.1)
                    auto_running = False
                    break

        except Exception as e:
            print(f"[ERROR] Auto loop: {e}")

        time.sleep(0.05)


def start_auto_mode(client):
    global auto_running
    stop_auto_mode()
    auto_running = True
    threading.Thread(target=auto_loop, args=(client,), daemon=True).start()


def stop_auto_mode():
    global auto_running
    auto_running = False
    motor.stop()
    line_follower.reset_pid()


# ── Camera stream over MQTT ──
def camera_stream_loop(client):
    while True:
        frame = camera.get_frame()
        if frame is not None:
            small = cv2.resize(frame, (160, 120))
            _, jpeg = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
            client.publish(T_CAM, jpeg.tobytes(), qos=0)
        time.sleep(0.2)


# ── Main ──
if __name__ == "__main__":
    camera.start()

    client = mqtt.Client(client_id="smartcar_pi_" + str(int(time.time())))
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    print(f"[INFO] Connecting to MQTT broker {BROKER}...")
    client.connect(BROKER, PORT, 60)
    client.loop_start()

    threading.Thread(target=camera_stream_loop, args=(client,), daemon=True).start()

    print("[INFO] SmartCar Cloud Mode — Control from smartcar2027.netlify.app")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        led_running = False
        client.publish(T_STATUS, json.dumps({"online": False}))
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
        camera.stop()
        motor.cleanup()
