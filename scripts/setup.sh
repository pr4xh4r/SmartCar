#!/bin/bash
# SmartCar — Raspberry Pi Setup Script
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo "================================"
echo "  SmartCar Setup — Raspberry Pi"
echo "================================"

# System dependencies
echo "[1/4] Installing system packages..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-opencv \
    python3-picamera libatlas-base-dev

# Python venv
echo "[2/4] Creating virtual environment..."
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Python packages
echo "[3/4] Installing Python packages..."
pip install flask flask-socketio simple-websocket numpy opencv-python-headless paho-mqtt python-telegram-bot python-dotenv

# Enable camera
echo "[4/4] Checking camera..."
if ! raspistill -t 1000 -o /tmp/test_cam.jpg 2>/dev/null; then
    echo "[WARN] Camera not detected. Make sure it's connected and enabled."
    echo "       Run: sudo raspi-config -> Interface Options -> Camera -> Enable"
else
    echo "[OK] Camera working (raspistill)"
    rm -f /tmp/test_cam.jpg
fi

echo ""
echo "================================"
echo "  Setup complete!"
echo "  To run: source venv/bin/activate && python main.py"
echo "  Then open http://<pi-ip>:5000 on your phone"
echo "================================"
