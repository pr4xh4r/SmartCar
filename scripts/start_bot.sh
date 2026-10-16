#!/bin/bash
# SmartCar — Telegram Bot Only
# Run: ./scripts/start_bot.sh  (from project root)
cd "$(dirname "$0")/.."

echo "Starting SmartCar Telegram Bot..."
echo "=================================="
echo "  Send /start to your bot"
echo "=================================="

sudo python3 telegram_bot.py
