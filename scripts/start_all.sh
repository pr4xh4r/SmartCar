#!/bin/bash
# SmartCar — Run Everything (Flask + Telegram Bot)
# NOTE: main.py already runs everything in one process (recommended: ./scripts/start.sh).
# This script is kept for the legacy split setup (app.py + telegram_bot.py).
# Run: ./scripts/start_all.sh  (from project root)

cd "$(dirname "$0")/.."

IP=$(hostname -I | awk '{print $1}')

echo "Starting SmartCar (All Modes)..."
echo "=================================="
echo "  WiFi:     http://${IP}:5000"
echo "  Telegram: Send /start to your bot"
echo "=================================="

# Run Flask server in background
sudo "$PWD/venv/bin/python3" app.py &
FLASK_PID=$!

# Run Telegram bot in foreground
sudo "$PWD/venv/bin/python3" telegram_bot.py

# Cleanup on exit
kill $FLASK_PID 2>/dev/null
