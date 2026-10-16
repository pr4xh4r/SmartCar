# SmartCar 🚗

Raspberry Pi 3 robot car with line following, traffic-light detection,
smart parking, collision avoidance, Telegram control, and cloud (MQTT) remote driving.

## Features

- **6 driving modes:** Manual, Line Follow (PID), Traffic Light, Autopilot (line + traffic), Smart Park, Follow-Me (color tracking)
- **AI safety:** collision prediction + auto-brake, pedestrian auto-stop, road-condition speed adapt, accident SOS with photos, driver score
- **3 control surfaces:** local web panel (Flask + SocketIO), Telegram bot with buttons + photos, cloud web panel (MQTT → Netlify)
- **Hardware feedback:** LED status blink, buzzer beeps/honk, accident alarm

## Hardware

- Raspberry Pi 3 + Pi Camera v1.3 (legacy `picamera` / raspistill stack)
- L298N driver + 4× BO motors (left pair → Motor A, right pair → Motor B)
- White LED plate (GPIO 5), buzzer (GPIO 19)
- Pins & tuning live in `config.py`

## Project structure

```
SmartCar/
├── main.py              # All-in-one: Flask + Telegram + MQTT + AI (RECOMMENDED)
├── app.py               # Standalone: local Flask web panel only
├── telegram_bot.py      # Standalone: Telegram button control only
├── cloud.py             # Standalone: MQTT cloud bridge only
├── config.py            # GPIO pins, PID, HSV ranges, modes, server
├── motor.py             # L298N controller (simulates off-Pi)
├── camera.py            # PiCamera / OpenCV thread + MJPEG
├── line_follower.py     # PID black-line follower
├── traffic_detector.py  # HSV traffic-light detector
├── smart_park.py        # Green-marker auto parking
├── ai_features.py       # Collision, pedestrian, driver, accident, road, convoy
├── session_log.py       # Timestamped run logs → logs/
├── templates/index.html # Local Flask UI (uses /video_feed + SocketIO)
├── static/              # Local UI css/js (socket.io vendored for offline hotspot)
├── frontend/            # Cloud web panel (MQTT, deploy to Netlify)
├── scripts/             # setup + start helpers for the Pi
│   ├── setup.sh         # apt + venv + pip install
│   ├── setup_hotspot.sh # Pi as WiFi AP (SmartCar-WiFi)
│   ├── setup_autostart.sh # systemd auto-start on boot
│   ├── start.sh         # run main.py (recommended)
│   ├── start_all.sh     # legacy: app.py + telegram_bot.py
│   ├── start_bot.sh     # legacy: telegram_bot.py only
│   └── start_cloud.sh   # legacy: cloud.py only
└── docs/
    └── images/          # sample camera captures
```

> `main.py` re-implements what `app.py` / `telegram_bot.py` / `cloud.py` do
> separately, all sharing the same `motor/camera/*` modules.
> The standalone files are kept for debugging single subsystems;
> for normal driving just run `main.py`.

## Quick start (Raspberry Pi)

```bash
# 1. Setup
chmod +x scripts/setup.sh && ./scripts/setup.sh
source venv/bin/activate

# 2. Secrets — copy example and fill in your bot token
cp .env.example .env
# edit TELEGRAM_BOT_TOKEN inside .env

# 3. Run (all-in-one: web + Telegram + MQTT + AI)
./scripts/start.sh
# or: sudo python3 main.py
```

Then open `http://<pi-ip>:5000` on your phone (same WiFi),
or send `/start` to your Telegram bot,
or open the cloud panel (needs `cloud` path running / MQTT online).

### Desktop testing

Code runs without Pi hardware — `RPi.GPIO` and `picamera` fall back
to mocks/OpenCV webcam. Install with:

```bash
pip install -r requirements.txt   # Pi-only lines are commented out
python main.py
```

## Driving modes

| Mode | What it does |
|---|---|
| `manual` | D-pad / WASD / Telegram buttons |
| `line_follow` | PID follows black line, stops if lost |
| `traffic` | Red = stop, green = go, yellow = half speed |
| `autopilot` | Line follow + obey traffic lights |
| `smart_park` | Finds 2 green markers, aligns, reverses in |
| `convoy` | Follows Telegram-selected color blob |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/setup.sh` | System packages + venv + pip |
| `scripts/setup_hotspot.sh` | Pi creates `SmartCar-WiFi` AP |
| `scripts/setup_autostart.sh` | systemd `smartcar.service` on boot |
| `scripts/start.sh` | **Recommended** — runs `main.py` |

## Docs

- Sample frames: `docs/images/`

## Security

- Bot token and MQTT settings come from `.env` (see `.env.example`).
  Never commit `.env`. If you previously pushed a token, revoke it via @BotFather.
- The cloud demo uses the public `broker.emqx.io` broker with a shared
  topic prefix — fine for a class demo, not for anything sensitive.
  Set your own `MQTT_TOPIC_PREFIX` in `.env`.
