const socket = io();

// ── Elements ──
const connStatus = document.getElementById("connStatus");
const camOverlay = document.getElementById("camOverlay");
const camFeed = document.getElementById("camFeed");
const modeLabel = document.getElementById("modeLabel");
const detectionLabel = document.getElementById("detectionLabel");
const statusBar = document.getElementById("statusBar");
const manualControls = document.getElementById("manualControls");
const speedSlider = document.getElementById("speedSlider");
const speedVal = document.getElementById("speedVal");
const modeBtns = document.querySelectorAll(".mode-btn");
const dpadBtns = document.querySelectorAll(".dpad-btn");
const toggleBtns = document.querySelectorAll(".toggle-btn[data-led]");
const honkBtn = document.getElementById("honkBtn");

let currentMode = "manual";

// ── Connection ──
socket.on("connect", () => {
    connStatus.classList.add("connected");
    camOverlay.classList.add("hidden");
});

socket.on("disconnect", () => {
    connStatus.classList.remove("connected");
    camOverlay.classList.remove("hidden");
    camOverlay.textContent = "DISCONNECTED";
});

// ── Camera feed error recovery ──
camFeed.onerror = () => {
    setTimeout(() => {
        camFeed.src = "/video_feed?" + Date.now();
    }, 1000);
};

// ── Status Updates ──
socket.on("status", (data) => {
    if (data.mode) {
        currentMode = data.mode;
        modeLabel.textContent = data.mode.replace("_", " ").toUpperCase();
        updateControlState();
    }

    if (data.speed !== undefined) {
        speedSlider.value = data.speed;
        speedVal.textContent = data.speed + "%";
    }

    // Detection info
    statusBar.className = "status-bar";
    let det = "";

    if (data.traffic_color && data.traffic_color !== "none") {
        const colors = { red: "#ff3b3b", green: "#00e676", yellow: "#ffc107" };
        det = data.traffic_color.toUpperCase();
        if (data.confidence) det += ` (${Math.round(data.confidence * 100)}%)`;
        detectionLabel.style.color = colors[data.traffic_color] || "#ffc107";
    }

    if (data.line_detected !== undefined) {
        det += det ? " | " : "";
        det += data.line_detected ? "LINE OK" : "NO LINE";
    }

    if (data.park_phase) {
        det = data.park_phase.toUpperCase();
        if (data.park_phase === "parked") {
            statusBar.classList.add("parked");
        } else if (data.park_phase !== "failed") {
            statusBar.classList.add("parking");
        }
    }

    detectionLabel.textContent = det;
});

// ── Mode Buttons ──
modeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
        modeBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        socket.emit("set_mode", { mode: btn.dataset.mode });
    });
});

function updateControlState() {
    if (currentMode === "manual") {
        manualControls.classList.remove("disabled");
    } else {
        manualControls.classList.add("disabled");
    }
}

// ── D-Pad Controls (touch + mouse) ──
dpadBtns.forEach((btn) => {
    const action = btn.dataset.action;

    // Touch events
    btn.addEventListener("touchstart", (e) => {
        e.preventDefault();
        btn.classList.add("pressed");
        socket.emit("control", { action: action });
    });

    btn.addEventListener("touchend", (e) => {
        e.preventDefault();
        btn.classList.remove("pressed");
        if (action !== "stop") {
            socket.emit("control", { action: "stop" });
        }
    });

    // Mouse events (for desktop testing)
    btn.addEventListener("mousedown", () => {
        btn.classList.add("pressed");
        socket.emit("control", { action: action });
    });

    btn.addEventListener("mouseup", () => {
        btn.classList.remove("pressed");
        if (action !== "stop") {
            socket.emit("control", { action: "stop" });
        }
    });

    btn.addEventListener("mouseleave", () => {
        btn.classList.remove("pressed");
    });
});

// ── Keyboard Controls (WASD + Arrow Keys) ──
const keyMap = {
    ArrowUp: "forward", w: "forward", W: "forward",
    ArrowDown: "backward", s: "backward", S: "backward",
    ArrowLeft: "left", a: "left", A: "left",
    ArrowRight: "right", d: "right", D: "right",
    " ": "stop",
};

const keysPressed = new Set();

document.addEventListener("keydown", (e) => {
    const action = keyMap[e.key];
    if (action && !keysPressed.has(e.key)) {
        keysPressed.add(e.key);
        socket.emit("control", { action: action });
    }
});

document.addEventListener("keyup", (e) => {
    if (keyMap[e.key]) {
        keysPressed.delete(e.key);
        if (keysPressed.size === 0) {
            socket.emit("control", { action: "stop" });
        }
    }
});

// ── Speed Slider ──
speedSlider.addEventListener("input", () => {
    speedVal.textContent = speedSlider.value + "%";
    socket.emit("set_speed", { speed: parseInt(speedSlider.value) });
});

// ── LED Toggles ──
toggleBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
        btn.classList.toggle("on");
        socket.emit("led", {
            led: btn.dataset.led,
            state: btn.classList.contains("on"),
        });
    });
});

// ── Honk Button ──
honkBtn.addEventListener("touchstart", (e) => {
    e.preventDefault();
    socket.emit("buzzer", { times: 1 });
});
honkBtn.addEventListener("click", () => {
    socket.emit("buzzer", { times: 1 });
});
