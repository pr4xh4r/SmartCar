#!/bin/bash
# SmartCar — Cloud Mode (control from anywhere via internet)
# Run: ./scripts/start_cloud.sh  (from project root)
cd "$(dirname "$0")/.."

echo "Starting SmartCar (Cloud Mode)..."
echo "=================================="
echo "  Control from: smartcar2027.netlify.app"
echo "=================================="

sudo python3 cloud.py
