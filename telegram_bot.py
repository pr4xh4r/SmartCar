#!/usr/bin/env python3
"""SmartCar Telegram Bot — Button-only control."""

import time
import threading
import io
import os
import cv2

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

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

# ── Bot token via env (see .env.example) ──
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ── Telegram WebApp URL (override via .env) ──
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://smartcar2027.netlify.app")

# ── Init hardware ──
motor = MotorController()
camera = CameraStream()
line_follower = LineFollower()
traffic_detector = TrafficLightDetector()
smart_parker = SmartParker()

current_mode = config.MODE_MANUAL
mode_lock = threading.Lock()
auto_running = False
led_enabled = True
led_running = True

GPIO.setup(config.LED, GPIO.OUT)
GPIO.output(config.LED, GPIO.LOW)
GPIO.setup(config.BUZZER, GPIO.OUT)
GPIO.output(config.BUZZER, GPIO.LOW)


def led_blink_loop():
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


# ── Auto mode ──
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
                        motor.differential_drive(left, right)
                    else:
                        motor.stop()
            elif mode == config.MODE_SMART_PARK:
                phase, _ = smart_parker.process(frame, motor)
                if phase in (SmartParker.PHASE_DONE, SmartParker.PHASE_FAILED):
                    if phase == SmartParker.PHASE_DONE:
                        buzzer_beep(3, 0.1)
                    auto_running = False
                    break
        except Exception as e:
            print(f"[ERROR] Auto loop: {e}")
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


# ── Keyboards ──
def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬆ Forward", callback_data="forward"),
        ],
        [
            InlineKeyboardButton("⬅", callback_data="left"),
            InlineKeyboardButton("🛑 STOP", callback_data="stop"),
            InlineKeyboardButton("➡", callback_data="right"),
        ],
        [
            InlineKeyboardButton("⬇ Backward", callback_data="backward"),
        ],
        [
            InlineKeyboardButton("📷 Photo", callback_data="photo"),
            InlineKeyboardButton("📢 Honk", callback_data="honk"),
        ],
        [
            InlineKeyboardButton(f"💡 LED {'ON' if led_enabled else 'OFF'}", callback_data="led"),
            InlineKeyboardButton(f"⚡ {motor.speed}%", callback_data="speed_info"),
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
            InlineKeyboardButton("🌐 Web Control Panel", web_app=WebAppInfo(url=WEBAPP_URL)),
        ],
    ])


def mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            ("✅ " if current_mode == config.MODE_MANUAL else "") + "🕹 Manual",
            callback_data="mode_manual"
        )],
        [InlineKeyboardButton(
            ("✅ " if current_mode == config.MODE_LINE_FOLLOW else "") + "📏 Line Follow",
            callback_data="mode_line_follow"
        )],
        [InlineKeyboardButton(
            ("✅ " if current_mode == config.MODE_TRAFFIC else "") + "🚦 Traffic Light",
            callback_data="mode_traffic"
        )],
        [InlineKeyboardButton(
            ("✅ " if current_mode == config.MODE_AUTOPILOT else "") + "🤖 Auto Pilot",
            callback_data="mode_autopilot"
        )],
        [InlineKeyboardButton(
            ("✅ " if current_mode == config.MODE_SMART_PARK else "") + "🅿 Smart Park",
            callback_data="mode_smart_park"
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="back")],
    ])


# ── /start — only command needed ──
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 *SmartCar*\n\n"
        f"Mode: *{current_mode.replace('_', ' ').upper()}*\n"
        f"Speed: *{motor.speed}%*\n\n"
        "Tap buttons to control your car:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ── All button actions ──
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_mode, led_enabled
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Motor controls ──
    if data in ("forward", "backward", "left", "right", "stop"):
        if data != "stop":
            with mode_lock:
                if current_mode != config.MODE_MANUAL:
                    await query.edit_message_text(
                        f"⚠ Switch to *Manual* mode first!\n"
                        f"Current: *{current_mode.replace('_', ' ').upper()}*",
                        parse_mode="Markdown",
                        reply_markup=main_keyboard()
                    )
                    return

        actions = {
            "forward": motor.forward,
            "backward": motor.backward,
            "left": motor.turn_left,
            "right": motor.turn_right,
            "stop": motor.stop,
        }
        actions[data]()

        if data == "stop":
            stop_auto_mode()

        # Auto-stop after 2s (safety — Telegram has no hold/release)
        if data != "stop":
            def auto_stop():
                time.sleep(2)
                motor.stop()
            threading.Thread(target=auto_stop, daemon=True).start()

        icons = {"forward": "⬆", "backward": "⬇", "left": "⬅", "right": "➡", "stop": "🛑"}
        await query.edit_message_text(
            f"{icons[data]} *{data.upper()}*\n"
            f"Speed: {motor.speed}% | Mode: {current_mode.replace('_', ' ').upper()}",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    # ── Photo ──
    elif data == "photo":
        frame = camera.get_frame()
        if frame is not None:
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            bio = io.BytesIO(jpeg.tobytes())
            bio.name = "smartcar.jpg"
            await query.message.reply_photo(
                photo=InputFile(bio),
                caption=f"📷 Mode: {current_mode} | Speed: {motor.speed}%",
                reply_markup=main_keyboard()
            )
        else:
            await query.edit_message_text(
                "❌ Camera not available",
                reply_markup=main_keyboard()
            )

    # ── Honk ──
    elif data == "honk":
        buzzer_beep(2)
        await query.edit_message_text(
            "📢 *HONK HONK!*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    # ── LED toggle ──
    elif data == "led":
        led_enabled = not led_enabled
        await query.edit_message_text(
            f"💡 LED: *{'ON' if led_enabled else 'OFF'}*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    # ── Speed ──
    elif data == "speed_up":
        motor.set_speed(min(100, motor.speed + 10))
        await query.edit_message_text(
            f"🚀 Speed: *{motor.speed}%*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    elif data == "speed_down":
        motor.set_speed(max(0, motor.speed - 10))
        await query.edit_message_text(
            f"🐢 Speed: *{motor.speed}%*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    elif data == "speed_info":
        await query.edit_message_text(
            f"⚡ Current Speed: *{motor.speed}%*\nUse buttons below to adjust",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    # ── Show modes ──
    elif data == "modes":
        await query.edit_message_text(
            "🔧 *Select Mode:*\n\n"
            f"Current: *{current_mode.replace('_', ' ').upper()}*",
            parse_mode="Markdown",
            reply_markup=mode_keyboard()
        )

    # ── Mode selection ──
    elif data.startswith("mode_"):
        mode = data.replace("mode_", "")
        valid = {config.MODE_MANUAL, config.MODE_LINE_FOLLOW, config.MODE_TRAFFIC,
                 config.MODE_AUTOPILOT, config.MODE_SMART_PARK}
        if mode not in valid:
            return
        with mode_lock:
            current_mode = mode
        if mode == config.MODE_MANUAL:
            stop_auto_mode()
        elif mode == config.MODE_SMART_PARK:
            smart_parker.reset()
            start_auto_mode()
        else:
            start_auto_mode()
        await query.edit_message_text(
            f"✅ Mode: *{mode.replace('_', ' ').upper()}*",
            parse_mode="Markdown",
            reply_markup=mode_keyboard()
        )

    # ── Status ──
    elif data == "status":
        cam_status = "OK" if camera.frame is not None else "OFF"
        await query.edit_message_text(
            f"📊 *SmartCar Status*\n\n"
            f"Mode: `{current_mode.replace('_', ' ').upper()}`\n"
            f"Speed: `{motor.speed}%`\n"
            f"LED: `{'ON' if led_enabled else 'OFF'}`\n"
            f"Camera: `{cam_status}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    # ── Back to main ──
    elif data == "back":
        await query.edit_message_text(
            f"🚗 *SmartCar*\n"
            f"Mode: *{current_mode.replace('_', ' ').upper()}* | Speed: *{motor.speed}%*",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )


# ── Main ──
if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 50)
        print("  SET YOUR BOT TOKEN!")
        print("  1. Open Telegram → @BotFather")
        print("  2. Send /newbot")
        print("  3. Copy the token")
        print("  4. Edit telegram_bot.py line 33")
        print("=" * 50)
        exit(1)

    camera.start()
    print("[INFO] SmartCar Telegram Bot starting...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("[INFO] Bot running! Send /start in Telegram.")

    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        led_running = False
        camera.stop()
        motor.cleanup()
