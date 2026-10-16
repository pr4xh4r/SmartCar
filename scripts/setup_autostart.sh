#!/bin/bash
# SmartCar — Setup auto-start on boot
# Run: chmod +x setup_autostart.sh && sudo ./setup_autostart.sh

echo "Setting up SmartCar auto-start on boot..."

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

sudo tee /etc/systemd/system/smartcar.service > /dev/null <<EOF
[Unit]
Description=SmartCar
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable smartcar.service

echo ""
echo "Done! SmartCar will auto-start on boot."
echo ""
echo "Commands:"
echo "  sudo systemctl start smartcar    — start now"
echo "  sudo systemctl stop smartcar     — stop"
echo "  sudo systemctl restart smartcar  — restart"
echo "  sudo systemctl status smartcar   — check status"
echo "  sudo systemctl disable smartcar  — disable auto-start"
echo "  sudo journalctl -u smartcar -f   — view live logs"
