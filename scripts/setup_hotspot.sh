#!/bin/bash
# SmartCar — WiFi Hotspot Setup
# Makes your Pi create its own WiFi network
# Run: chmod +x setup_hotspot.sh && sudo ./setup_hotspot.sh

SSID="SmartCar-WiFi"
PASSWORD="smartcar123"
IP="192.168.4.1"

echo "================================"
echo "  SmartCar Hotspot Setup"
echo "  SSID: $SSID"
echo "  Pass: $PASSWORD"
echo "  IP:   $IP"
echo "================================"

# Install required packages
echo "[1/4] Installing hostapd and dnsmasq..."
sudo apt-get update
sudo apt-get install -y hostapd dnsmasq

# Stop services while configuring
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

# Configure static IP for wlan0
echo "[2/4] Setting static IP..."
if ! grep -q "SmartCar Hotspot" /etc/dhcpcd.conf 2>/dev/null; then
    sudo bash -c "cat >> /etc/dhcpcd.conf" <<EOF

# SmartCar Hotspot
interface wlan0
    static ip_address=${IP}/24
    nohook wpa_supplicant
EOF
fi

# Configure hostapd (WiFi access point)
echo "[3/4] Configuring WiFi hotspot..."
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

# Point hostapd to config
sudo sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# Configure dnsmasq (DHCP server for connected phones)
echo "[4/4] Configuring DHCP..."
sudo tee /etc/dnsmasq.d/smartcar.conf > /dev/null <<EOF
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=local
address=/smartcar.local/${IP}
EOF

# Enable and start services
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

echo ""
echo "================================"
echo "  Hotspot configured!"
echo ""
echo "  Reboot to activate:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "    1. Connect phone to: $SSID"
echo "    2. Password: $PASSWORD"
echo "    3. Open: http://${IP}:5000"
echo ""
echo "  Or use: http://smartcar.local:5000"
echo "================================"
