#!/usr/bin/env python3
"""SmartCar — All-in-one: Flask + Telegram Bot + MQTT + AI Features."""

import time
import threading
import io
import json
import asyncio
import os
import cv2
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, Response, request
from flask_socketio import SocketIO, emit

import config
from motor import MotorController
from camera import CameraStream
from line_follower import LineFollower
from traffic_detector import TrafficLightDetector
from smart_park import SmartParker
from ai_features import (
    CollisionPredictor, PedestrianTracker, DriverAnalyzer,
    AccidentDetector, RoadAnalyzer, ConvoyFollower
)
from session_log import SessionLogger

try:
    import RPi.GPIO as GPIO
except ImportError:
    from unittest.mock import MagicMock
    GPIO = MagicMock()

try:
    from telegram import (
        Update, InlineKeyboardButton, InlineKeyboardMarkup,
        InputFile, WebAppInfo
    )
    from telegram.ext import (
        ApplicationBuilder, CommandHandler, CallbackQueryHandler,
        ContextTypes
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[WARN] python-telegram-bot not installed — bot disabled")

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("[WARN] paho-mqtt not installed — cloud disabled")

# ══════════════════════════════════════════
#  CONFIG (override via .env — see .env.example)
# ══════════════════════════════════════════
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://smartcar2027.netlify.app")
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "smartcar2027")

# ══════════════════════════════════════════
#  SHARED HARDWARE + AI
# ══════════════════════════════════════════
motor = MotorController()
camera = CameraStream()
line_follower = LineFollower()
traffic_detector = TrafficLightDetector()
smart_parker = SmartParker()

# AI modules
collision = CollisionPredictor()
pedestrian = PedestrianTracker()
driver_analyzer = DriverAnalyzer()
accident_detector = AccidentDetector()
road_analyzer = RoadAnalyzer()
convoy = ConvoyFollower()
slog = SessionLogger()

current_mode = config.MODE_MANUAL
mode_lock = threading.Lock()
auto_running = False
led_enabled = True
led_running = True
ai_frame_counter = 0  # process AI every 3rd frame to save CPU

VALID_MODES = {config.MODE_MANUAL, config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC,
               config.MODE_AUTOPILOT, config.MODE_SMART_PARK, config.MODE_CONVOY}
VALID_CMDS = {"forward", "backward", "left", "right", "stop"}

# Telegram alert — store chat_id and bot reference
tg_alert_chat_id = None
tg_bot_ref = None
tg_loop_ref = None

GPIO.setup(config.LED, GPIO.OUT)
GPIO.output(config.LED, GPIO.LOW)
GPIO.setup(config.BUZZER, GPIO.OUT)
GPIO.output(config.BUZZER, GPIO.LOW)


# ══════════════════════════════════════════
#  SHARED FUNCTIONS
# ══════════════════════════════════════════
def led_blink_loop():
    while led_running:
        if not led_enabled:
            GPIO.output(config.LED, GPIO.LOW)
            time.sleep(0.2)
            continue
        with mode_lock:
            mode = current_mode
        if mode == config.MODE_SMART_PARK:
            # Parking: LED + buzzer blink 1s on/off
            GPIO.output(config.LED, GPIO.HIGH)
            GPIO.output(config.BUZZER, GPIO.HIGH)
            time.sleep(1.0)
            GPIO.output(config.LED, GPIO.LOW)
            GPIO.output(config.BUZZER, GPIO.LOW)
            time.sleep(1.0)
        else:
            # Normal: LED stays ON steady
            GPIO.output(config.LED, GPIO.HIGH)
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


def accident_alarm():
    """Rapid LED flash + long buzzer for accident."""
    for _ in range(10):
        GPIO.output(config.LED, GPIO.HIGH)
        GPIO.output(config.BUZZER, GPIO.HIGH)
        time.sleep(0.1)
        GPIO.output(config.LED, GPIO.LOW)
        GPIO.output(config.BUZZER, GPIO.LOW)
        time.sleep(0.1)


def do_motor_action(action):
    actions = {
        "forward": motor.forward,
        "backward": motor.backward,
        "left": motor.turn_left,
        "right": motor.turn_right,
        "stop": motor.stop,
    }
    func = actions.get(action, motor.stop)
    func()
    driver_analyzer.log_action(action, motor.speed)
    accident_detector.update_motor_state(action != "stop")
    slog.log("MOTOR", f"{action.upper()} (speed: {motor.speed}%)")


def set_mode(mode):
    global current_mode
    if mode not in VALID_MODES:
        return
    with mode_lock:
        current_mode = mode
    slog.log("MODE", f"Changed to {mode.replace('_', ' ').upper()}")
    if mode == config.MODE_MANUAL:
        motor.set_manual(True)
        stop_auto_mode()
        convoy.stop()
        return
    # All auto modes run at 100% speed — max power
    motor.set_manual(False)
    motor.set_speed(100)
    if mode == config.MODE_SMART_PARK:
        smart_parker.reset()
        start_auto_mode()
    elif mode == config.MODE_CONVOY:
        start_auto_mode()
    else:
        start_auto_mode()


# ── Accident Telegram Alert ──
def send_accident_alert(photos):
    """Called by AccidentDetector when accident detected."""
    slog.log("ACCIDENT", "DETECTED! Sending SOS alert + 5 photos")
    motor.stop()
    threading.Thread(target=accident_alarm, daemon=True).start()

    # Send via Telegram if available
    if tg_bot_ref and tg_alert_chat_id and tg_loop_ref:
        async def _send():
            try:
                await tg_bot_ref.send_message(
                    chat_id=tg_alert_chat_id,
                    text="🚨 *ACCIDENT DETECTED!*\n\n"
                         "Car has been stopped.\n"
                         "Sending 5 photos from the scene...",
                    parse_mode="Markdown"
                )
                for i, photo_bytes in enumerate(photos):
                    bio = io.BytesIO(photo_bytes)
                    bio.name = f"accident_{i+1}.jpg"
                    await tg_bot_ref.send_photo(
                        chat_id=tg_alert_chat_id,
                        photo=InputFile(bio),
                        caption=f"🚨 Accident photo {i+1}/5"
                    )
                await tg_bot_ref.send_message(
                    chat_id=tg_alert_chat_id,
                    text="🛑 All photos sent. Car is stopped.\n"
                         "Send /start to resume control.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[ACCIDENT] Telegram send failed: {e}")

        asyncio.run_coroutine_threadsafe(_send(), tg_loop_ref)


accident_detector.set_alert_callback(send_accident_alert)


# ── Send instant Telegram message (non-blocking) ──
def tg_instant_msg(text):
    if tg_bot_ref and tg_alert_chat_id and tg_loop_ref:
        async def _send():
            try:
                await tg_bot_ref.send_message(
                    chat_id=tg_alert_chat_id, text=text, parse_mode="Markdown")
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(_send(), tg_loop_ref)


collision_alerted = False
pedestrian_alerted = False


# ── AI Processing (runs every 3rd frame to save CPU) ──
def process_ai(frame):
    global ai_frame_counter, collision_alerted, pedestrian_alerted
    ai_frame_counter += 1
    if ai_frame_counter % 3 != 0:
        return

    # Collision prediction — auto brake in ALL modes
    risk, ttc = collision.process(frame)
    if risk == "danger":
        motor.stop()
        buzzer_beep(3, 0.1)
        slog.log("AI", f"COLLISION WARNING! TTC={ttc:.1f}s — AUTO BRAKE")
        if not collision_alerted:
            collision_alerted = True
            # Send alert + 2 photos with 2 sec delay
            def send_collision_photos():
                tg_instant_msg(f"🔴 *COLLISION WARNING!*\nTime to impact: *{ttc:.1f}s*\nCar auto-braked!\nSending 2 photos...")
                for i in range(2):
                    f = camera.get_frame()
                    if f is not None and tg_bot_ref and tg_alert_chat_id and tg_loop_ref:
                        _, jpeg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        async def _send_photo(photo_bytes, num):
                            try:
                                bio = io.BytesIO(photo_bytes)
                                bio.name = f"collision_{num}.jpg"
                                await tg_bot_ref.send_photo(
                                    chat_id=tg_alert_chat_id,
                                    photo=InputFile(bio),
                                    caption=f"🔴 Collision photo {num}/2")
                            except Exception:
                                pass
                        asyncio.run_coroutine_threadsafe(
                            _send_photo(jpeg.tobytes(), i+1), tg_loop_ref)
                    if i < 1:
                        time.sleep(2)
            threading.Thread(target=send_collision_photos, daemon=True).start()
    elif risk == "safe":
        collision_alerted = False

    # Pedestrian tracking — auto stop in ALL modes
    pedestrian.process(frame)
    if pedestrian.detected and pedestrian.direction == "approaching":
        motor.stop()
        buzzer_beep(2, 0.1)
        slog.log("AI", "PEDESTRIAN approaching — AUTO STOP")
        if not pedestrian_alerted:
            pedestrian_alerted = True
            tg_instant_msg("🚶 *PEDESTRIAN DETECTED!*\nMoving toward car — auto-stopped!")
    elif not pedestrian.detected:
        pedestrian_alerted = False

    # Road condition
    prev_road = road_analyzer.condition
    road_analyzer.process(frame)
    if road_analyzer.condition != prev_road:
        slog.log("AI", f"Road: {road_analyzer.condition} (speed factor: {int(road_analyzer.speed_factor*100)}%)")

    # Accident detection
    accident_detector.check(frame, camera)


# ── Auto mode loop ──
def auto_loop():
    global auto_running
    while auto_running:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        with mode_lock:
            mode = current_mode

        # Run AI safety checks in all auto modes
        process_ai(frame)

        try:
            if mode == config.MODE_LINE_FOLLOW:
                left, right, _ = line_follower.process(frame)
                if left is not None and right is not None:
                    # Apply road speed factor
                    sf = road_analyzer.speed_factor
                    motor.differential_drive(left * sf, right * sf)
                else:
                    motor.stop()

            elif mode == config.MODE_TRAFFIC:
                color, conf, _ = traffic_detector.process(frame)
                if color == "red":
                    motor.stop(); buzzer_beep(1)
                elif color == "green":
                    motor.forward(); buzzer_beep(2, 0.08)
                else:
                    motor.stop()

            elif mode == config.MODE_AUTOPILOT:
                color, conf, _ = traffic_detector.process(frame)
                if color == "red":
                    motor.stop(); buzzer_beep(1)
                else:
                    left, right, _ = line_follower.process(frame)
                    if left is not None and right is not None:
                        sf = road_analyzer.speed_factor
                        motor.differential_drive(left * sf, right * sf)
                    else:
                        motor.stop()

            elif mode == config.MODE_SMART_PARK:
                phase, _ = smart_parker.process(frame, motor)
                if phase in (SmartParker.PHASE_DONE, SmartParker.PHASE_FAILED):
                    if phase == SmartParker.PHASE_DONE:
                        buzzer_beep(3, 0.1)
                    auto_running = False
                    break

            elif mode == config.MODE_CONVOY:
                left, right = convoy.process(frame)
                if left is not None and right is not None:
                    motor.differential_drive(left, right)
                else:
                    motor.stop()

        except Exception as e:
            print(f"[ERROR] Auto: {e}")
        time.sleep(0.05)


def start_auto_mode():
    global auto_running
    stop_auto_mode()
    auto_running = True
    threading.Thread(target=auto_loop, daemon=True).start()


def stop_auto_mode():
    global auto_running
    auto_running = False
    motor.stop()
    line_follower.reset_pid()


# ── Manual mode AI loop (runs collision + pedestrian checks while driving manually) ──
def manual_ai_loop():
    while True:
        with mode_lock:
            mode = current_mode
        if mode == config.MODE_MANUAL:
            frame = camera.get_frame()
            if frame is not None:
                process_ai(frame)
        time.sleep(0.15)  # ~7 FPS for AI in manual mode


threading.Thread(target=manual_ai_loop, daemon=True).start()


# ══════════════════════════════════════════
#  FLASK WEB APP
# ══════════════════════════════════════════
app = Flask(__name__)
app.config["SECRET_KEY"] = "smartcar2026"
socketio = SocketIO(app, cors_allowed_origins="*")


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


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
        except Exception:
            time.sleep(0.1)


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
    do_motor_action(direction)
    return f"Motor: {direction}"


@app.route("/ai_status")
def ai_status():
    return json.dumps({
        "collision": {"risk": collision.risk, "ttc": round(collision.ttc, 1)},
        "pedestrian": {"detected": pedestrian.detected, "direction": pedestrian.direction},
        "road": {"condition": road_analyzer.condition, "speed_factor": road_analyzer.speed_factor},
        "driver": driver_analyzer.get_score(),
    })


@socketio.on("connect")
def on_connect():
    emit("status", {"mode": current_mode, "speed": motor.speed, "led": led_enabled})
    print("[FLASK] Client connected")


@socketio.on("set_mode")
def on_set_mode(data):
    set_mode(data.get("mode", config.MODE_MANUAL))
    emit("status", {"mode": current_mode}, broadcast=True)


@socketio.on("control")
def on_control(data):
    action = data.get("action", "stop")
    if action not in VALID_CMDS:
        return
    with mode_lock:
        if current_mode != config.MODE_MANUAL and action != "stop":
            return
    do_motor_action(action)


@socketio.on("set_speed")
def on_set_speed(data):
    speed = max(0, min(100, int(data.get("speed", config.DEFAULT_SPEED))))
    motor.set_speed(speed)
    emit("status", {"speed": motor.speed}, broadcast=True)


@socketio.on("led")
def on_led(data):
    global led_enabled
    led_enabled = data.get("state", False)


@socketio.on("buzzer")
def on_buzzer(data):
    buzzer_beep(times=data.get("times", 1))


# ══════════════════════════════════════════
#  TELEGRAM BOT
# ══════════════════════════════════════════
if TELEGRAM_AVAILABLE and BOT_TOKEN and BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":

    def tg_main_kb():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬆ Forward", callback_data="forward")],
            [
                InlineKeyboardButton("⬅", callback_data="left"),
                InlineKeyboardButton("🛑 STOP", callback_data="stop"),
                InlineKeyboardButton("➡", callback_data="right"),
            ],
            [InlineKeyboardButton("⬇ Backward", callback_data="backward")],
            [
                InlineKeyboardButton("📷 Photo", callback_data="photo"),
                InlineKeyboardButton("📢 Honk", callback_data="honk"),
            ],
            [
                InlineKeyboardButton(f"💡 LED {'ON' if led_enabled else 'OFF'}", callback_data="led"),
                InlineKeyboardButton(f"⚡ {motor.speed}%", callback_data="noop"),
            ],
            [
                InlineKeyboardButton("🐢 Speed -", callback_data="speed_down"),
                InlineKeyboardButton("🚀 Speed +", callback_data="speed_up"),
            ],
            [
                InlineKeyboardButton("🔧 Modes", callback_data="modes"),
                InlineKeyboardButton("📊 Status", callback_data="status"),
            ],
            [
                InlineKeyboardButton("🧠 AI Status", callback_data="ai_status"),
                InlineKeyboardButton("🏆 Driver Score", callback_data="driver_score"),
            ],
            [
                InlineKeyboardButton("📍 Location", callback_data="location"),
                InlineKeyboardButton("📋 Session Log", callback_data="session_log"),
            ],
            [InlineKeyboardButton("🌐 Web Panel", web_app=WebAppInfo(url=WEBAPP_URL))],
        ])

    def tg_mode_kb():
        modes = [
            (config.MODE_MANUAL, "🕹 Manual"),
            (config.MODE_LINE_FOLLOW, "📏 Line Follow"),
            (config.MODE_TRAFFIC, "🚦 Traffic"),
            (config.MODE_AUTOPILOT, "🤖 Auto Pilot"),
            (config.MODE_SMART_PARK, "🅿 Smart Park"),
            (config.MODE_CONVOY, "🚗 Follow Me"),
        ]
        buttons = []
        for m, label in modes:
            check = "✅ " if current_mode == m else ""
            buttons.append([InlineKeyboardButton(check + label, callback_data="mode_" + m)])
        buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
        return InlineKeyboardMarkup(buttons)

    def tg_convoy_kb():
        colors = ["red", "blue", "green", "yellow", "orange", "pink", "white"]
        buttons = []
        row = []
        for c in colors:
            row.append(InlineKeyboardButton(c.title(), callback_data="convoy_" + c))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
        return InlineKeyboardMarkup(buttons)

    async def tg_reply(query, text, kb):
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        global tg_alert_chat_id
        tg_alert_chat_id = update.effective_chat.id
        await update.message.reply_text(
            f"🚗 *SmartCar*\n"
            f"Mode: *{current_mode.replace('_', ' ').upper()}* | Speed: *{motor.speed}%*\n\n"
            "Tap buttons to control:",
            parse_mode="Markdown",
            reply_markup=tg_main_kb()
        )

    async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        global led_enabled, tg_alert_chat_id
        query = update.callback_query
        await query.answer()
        data = query.data
        tg_alert_chat_id = query.message.chat_id

        if data == "noop":
            return

        # Motor
        if data in VALID_CMDS:
            if data != "stop":
                with mode_lock:
                    if current_mode != config.MODE_MANUAL:
                        await tg_reply(query,
                            f"⚠ Switch to *Manual* first!\nCurrent: *{current_mode.replace('_',' ').upper()}*",
                            tg_main_kb())
                        return
            do_motor_action(data)
            if data == "stop":
                stop_auto_mode()
            if data != "stop":
                def auto_stop():
                    time.sleep(2)
                    motor.stop()
                threading.Thread(target=auto_stop, daemon=True).start()
            icons = {"forward":"⬆","backward":"⬇","left":"⬅","right":"➡","stop":"🛑"}
            await tg_reply(query,
                f"{icons[data]} *{data.upper()}*\nSpeed: {motor.speed}%",
                tg_main_kb())

        elif data == "photo":
            frame = camera.get_frame()
            if frame is not None:
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                bio = io.BytesIO(jpeg.tobytes())
                bio.name = "smartcar.jpg"
                await query.message.reply_photo(
                    photo=InputFile(bio),
                    caption=f"📷 Mode: {current_mode} | Speed: {motor.speed}%"
                )
            else:
                await tg_reply(query, "❌ Camera not available", tg_main_kb())

        elif data == "honk":
            buzzer_beep(2)
            await tg_reply(query, "📢 *HONK HONK!*", tg_main_kb())

        elif data == "led":
            led_enabled = not led_enabled
            await tg_reply(query, f"💡 LED: *{'ON' if led_enabled else 'OFF'}*", tg_main_kb())

        elif data == "speed_up":
            motor.set_speed(min(100, motor.speed + 10))
            await tg_reply(query, f"🚀 Speed: *{motor.speed}%*", tg_main_kb())

        elif data == "speed_down":
            motor.set_speed(max(0, motor.speed - 10))
            await tg_reply(query, f"🐢 Speed: *{motor.speed}%*", tg_main_kb())

        elif data == "modes":
            await tg_reply(query,
                f"🔧 *Select Mode:*\nCurrent: *{current_mode.replace('_',' ').upper()}*",
                tg_mode_kb())

        elif data.startswith("mode_"):
            mode = data.replace("mode_", "")
            if mode == config.MODE_CONVOY:
                await tg_reply(query,
                    "🚗 *Follow Me Mode*\nSelect the color of the object to follow:",
                    tg_convoy_kb())
                return
            set_mode(mode)
            await tg_reply(query,
                f"✅ Mode: *{mode.replace('_',' ').upper()}*",
                tg_mode_kb())

        elif data.startswith("convoy_"):
            color = data.replace("convoy_", "")
            if convoy.set_color(color):
                set_mode(config.MODE_CONVOY)
                await tg_reply(query,
                    f"🚗 Following *{color.upper()}* object!\nCar will track and follow it.",
                    tg_main_kb())
            else:
                await tg_reply(query, f"❌ Unknown color: {color}", tg_convoy_kb())

        elif data == "ai_status":
            risk_icons = {"safe": "🟢", "warning": "🟡", "danger": "🔴"}
            road_icons = {"smooth": "🟢", "normal": "🟡", "rough": "🔴", "unknown": "⚪"}
            # Send as new message for instant reply
            await query.message.reply_text(
                f"🧠 *AI Status*\n\n"
                f"Collision: {risk_icons.get(collision.risk, '⚪')} `{collision.risk}` (TTC: {collision.ttc:.1f}s)\n"
                f"Pedestrian: `{'DETECTED ' + pedestrian.direction if pedestrian.detected else 'clear'}`\n"
                f"Road: {road_icons.get(road_analyzer.condition, '⚪')} `{road_analyzer.condition}` ({int(road_analyzer.speed_factor*100)}% speed)\n"
                f"Convoy: `{'following ' + (convoy.target_color or 'none') if convoy.active else 'off'}`",
                parse_mode="Markdown",
                reply_markup=tg_main_kb())

        elif data == "driver_score":
            s = driver_analyzer.get_score()
            # Send as new message for instant reply
            await query.message.reply_text(
                f"🏆 *Driver Score: {s['score']}/100 ({s['grade']})*\n\n"
                f"Total commands: `{s['total_commands']}`\n"
                f"Sharp turns: `{s['sharp_turns']}`\n"
                f"Hard brakes: `{s['hard_brakes']}`\n"
                f"Avg speed: `{s['avg_speed']}%`\n"
                f"Session: `{s['duration']}s`",
                parse_mode="Markdown",
                reply_markup=tg_main_kb())

        elif data == "status":
            cam = "OK" if camera.frame is not None else "OFF"
            await tg_reply(query,
                f"📊 *Status*\nMode: `{current_mode}`\nSpeed: `{motor.speed}%`\n"
                f"LED: `{'ON' if led_enabled else 'OFF'}`\nCamera: `{cam}`",
                tg_main_kb())

        elif data == "location":
            await query.answer()
            # Get Pi network info
            try:
                import subprocess
                ip = subprocess.check_output(["hostname", "-I"]).decode().strip().split()[0]
            except Exception:
                ip = "unknown"
            try:
                import subprocess
                ssid = subprocess.check_output(
                    ["iwgetid", "-r"], stderr=subprocess.DEVNULL).decode().strip()
            except Exception:
                ssid = "unknown"

            # Try IP geolocation (free, no key needed)
            lat, lon, city, region, country = None, None, "", "", ""
            try:
                import urllib.request
                resp = urllib.request.urlopen("http://ip-api.com/json/", timeout=3)
                geo = json.loads(resp.read().decode())
                if geo.get("status") == "success":
                    lat = geo.get("lat")
                    lon = geo.get("lon")
                    city = geo.get("city", "")
                    region = geo.get("regionName", "")
                    country = geo.get("country", "")
            except Exception:
                pass

            # Send location pin if coordinates available
            if lat and lon:
                await query.message.reply_location(latitude=lat, longitude=lon)

            location_text = f"📍 *Car Location*\n\n"
            location_text += f"IP: `{ip}`\n"
            location_text += f"WiFi: `{ssid}`\n"
            if city:
                location_text += f"City: `{city}, {region}`\n"
                location_text += f"Country: `{country}`\n"
                location_text += f"Coords: `{lat}, {lon}`\n"
            else:
                location_text += "GPS: `No internet for geolocation`\n"

            await query.message.reply_text(
                location_text, parse_mode="Markdown", reply_markup=tg_main_kb())

        elif data == "session_log":
            s = slog.get_summary()
            await query.message.reply_text(
                f"📋 *Session Log*\n\n"
                f"Duration: `{s['duration']}`\n"
                f"Total events: `{s['total_events']}`\n"
                f"Motor commands: `{s['motor_events']}`\n"
                f"AI detections: `{s['ai_events']}`\n"
                f"Mode changes: `{s['mode_events']}`\n"
                f"Log file: `{s['log_file']}`",
                parse_mode="Markdown",
                reply_markup=tg_main_kb())

        elif data == "back":
            await tg_reply(query,
                f"🚗 *SmartCar*\nMode: *{current_mode.replace('_',' ').upper()}* | Speed: *{motor.speed}%*",
                tg_main_kb())

    def run_telegram_bot():
        global tg_bot_ref, tg_loop_ref
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tg_loop_ref = loop

        tg_app = ApplicationBuilder().token(BOT_TOKEN).build()
        tg_app.add_handler(CommandHandler("start", cmd_start))
        tg_app.add_handler(CallbackQueryHandler(button_handler))

        async def start_bot():
            global tg_bot_ref
            await tg_app.initialize()
            tg_bot_ref = tg_app.bot
            await tg_app.updater.start_polling(drop_pending_updates=True)
            await tg_app.start()
            print("[BOT] Telegram bot running — send /start")
            while True:
                await asyncio.sleep(1)

        loop.run_until_complete(start_bot())

    threading.Thread(target=run_telegram_bot, daemon=True).start()
else:
    if TELEGRAM_AVAILABLE:
        print("[WARN] Bot token not set — Telegram bot disabled")


# ══════════════════════════════════════════
#  MQTT CLOUD
# ══════════════════════════════════════════
if MQTT_AVAILABLE:
    T_CMD = TOPIC_PREFIX + "/cmd"
    T_SPEED = TOPIC_PREFIX + "/speed"
    T_MODE = TOPIC_PREFIX + "/mode"
    T_LED = TOPIC_PREFIX + "/led"
    T_BUZZER = TOPIC_PREFIX + "/buzzer"
    T_CAM = TOPIC_PREFIX + "/cam"
    T_STATUS = TOPIC_PREFIX + "/status"

    def mqtt_on_connect(client, userdata, flags, rc, properties=None):
        print(f"[MQTT] Connected to {MQTT_BROKER}")
        client.subscribe(T_CMD)
        client.subscribe(T_SPEED)
        client.subscribe(T_MODE)
        client.subscribe(T_LED)
        client.subscribe(T_BUZZER)
        client.publish(T_STATUS, json.dumps({"online": True, "mode": current_mode}))

    def mqtt_on_message(client, userdata, msg):
        global led_enabled
        topic = msg.topic
        try:
            data = msg.payload.decode()
        except Exception:
            return

        if topic == T_CMD:
            if data not in VALID_CMDS:
                return
            with mode_lock:
                if current_mode != config.MODE_MANUAL and data != "stop":
                    return
            do_motor_action(data)
        elif topic == T_SPEED:
            try:
                motor.set_speed(max(0, min(100, int(data))))
            except ValueError:
                pass
        elif topic == T_MODE:
            set_mode(data)
        elif topic == T_LED:
            try:
                d = json.loads(data)
                led_enabled = d.get("state", False)
            except Exception:
                pass
        elif topic == T_BUZZER:
            buzzer_beep(times=int(data) if data.isdigit() else 1)

    def mqtt_cam_loop(client):
        while True:
            frame = camera.get_frame()
            if frame is not None:
                small = cv2.resize(frame, (160, 120))
                _, jpeg = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
                client.publish(T_CAM, jpeg.tobytes(), qos=0)
            time.sleep(0.2)

    def run_mqtt():
        try:
            mc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="smartcar_pi_" + str(int(time.time())))
            mc.on_connect = mqtt_on_connect
            mc.on_message = mqtt_on_message
            mc.connect(MQTT_BROKER, MQTT_PORT, 60)
            mc.loop_start()
            threading.Thread(target=mqtt_cam_loop, args=(mc,), daemon=True).start()
            print("[MQTT] Cloud relay running")
        except Exception as e:
            print(f"[MQTT] Cloud unavailable: {e}")

    threading.Thread(target=run_mqtt, daemon=True).start()


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════
if __name__ == "__main__":
    slog.log("SYSTEM", "SmartCar starting...")
    camera.start()
    slog.log("SYSTEM", "Camera started")
    IP = "0.0.0.0"
    try:
        import subprocess
        IP_DISPLAY = subprocess.check_output(["hostname", "-I"]).decode().strip().split()[0]
    except Exception:
        IP_DISPLAY = "localhost"

    print("=" * 50)
    print(f"  SmartCar Running!")
    print(f"  WiFi:     http://{IP_DISPLAY}:5000")
    print(f"  Cloud:    {WEBAPP_URL}")
    print(f"  Telegram: Send /start to bot")
    print(f"  AI:       Collision + Pedestrian + Road + Accident")
    print("=" * 50)

    try:
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        socketio.run(app, host=IP, port=config.PORT,
                     debug=False, allow_unsafe_werkzeug=True)
    finally:
        led_running = False
        camera.stop()
        motor.cleanup()
