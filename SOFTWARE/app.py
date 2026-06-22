"""
app.py — Flask Backend for Vertical Carousel Parking System
============================================================
Handles:
  • User authentication & session management
  • Slot assignment & availability checking
  • Carousel rotation commands sent to ESP32
  • Cost calculation on vehicle exit
  • JSON-file persistence (parking_data.json)

Network topology:
  ESP32 Soft-AP (192.168.4.1)  ←HTTP→  Flask server (192.168.4.x:5000)
  User devices connect to the same ESP32 AP and reach Flask at
  http://<flask-host-ip>:5000
"""

import os
import json
import math
import time
import datetime
import threading
import requests
from flask import Flask, request, jsonify, render_template, session

# ─────────────────────────────── Config ────────────────────────────────────
DATA_FILE        = "parking_data.json"
ESP32_BASE_URL   = "http://192.168.4.1"   # ESP32 AP gateway IP
RATE_PER_5MIN    = 2                       # Rs. 2 per 5 minutes
TOTAL_SLOTS      = 4
SECRET_KEY       = "carousel_parking_esp32_secret"
DATA_LOCK        = threading.Lock()        # thread-safe file I/O

app = Flask(__name__, template_folder="templates")
app.secret_key = SECRET_KEY

# ─────────────────────────────── DB Helpers ─────────────────────────────────

def load_data() -> dict:
    """Load parking database from JSON file."""
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data: dict) -> None:
    """Persist database to JSON file (thread-safe)."""
    with DATA_LOCK:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

# ─────────────────────────────── Carousel Logic ─────────────────────────────

SLOT_ORDER = ["A", "B", "C", "D"]          # physical carousel order

def shortest_path(current: int, target: int) -> tuple[str, int]:
    """
    Calculate the shortest rotation to bring `target` slot to Entry/Exit.

    Slots are indexed 0-3 at 90° intervals.
    Returns (direction: 'CW'|'CCW', steps: int).

    CW  → IN1=HIGH, IN2=LOW
    CCW → IN1=LOW,  IN2=HIGH
    """
    diff = (target - current) % TOTAL_SLOTS
    if diff == 0:
        return ("CW", 0)                    # already at position
    elif diff <= TOTAL_SLOTS // 2:
        return ("CW", diff)                 # shorter clockwise
    else:
        return ("CCW", TOTAL_SLOTS - diff)  # shorter counter-clockwise

def send_rotate(steps: int, direction: str) -> bool:
    """
    Send HTTP command to ESP32 to rotate the carousel.
    Returns True on success.
    """
    if steps == 0:
        return True
    try:
        url = f"{ESP32_BASE_URL}/rotate"
        params = {"steps": steps, "dir": direction}
        resp = requests.get(url, params=params, timeout=30)
        return resp.status_code == 200
    except requests.exceptions.RequestException as e:
        app.logger.error(f"ESP32 communication error: {e}")
        return False

def get_esp32_position() -> int | None:
    """Query ESP32 for its tracked carousel position (0-3)."""
    try:
        resp = requests.get(f"{ESP32_BASE_URL}/status", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("position")
    except Exception:
        pass
    return None

# ─────────────────────────────── Routes ─────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return current slot availability and carousel position."""
    data = load_data()
    slots_summary = {}
    for slot_id, slot in data["slots"].items():
        slots_summary[slot_id] = {
            "status":  slot["status"],
            "user":    slot["user"],
            "vehicle": slot["vehicle_number"]
        }
    occupied = sum(1 for s in data["slots"].values() if s["status"] == "occupied")
    return jsonify({
        "slots":             slots_summary,
        "carousel_position": data["carousel_position"],
        "occupied":          occupied,
        "available":         TOTAL_SLOTS - occupied,
        "parking_full":      occupied >= TOTAL_SLOTS
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    """
    Authenticate user and trigger carousel rotation to the first free slot.
    Body JSON: { "username": str, "password": str, "vehicle_number": str }
    """
    body = request.get_json(force=True)
    username  = body.get("username", "").strip().lower()
    password  = body.get("password", "").strip()
    vehicle_no = body.get("vehicle_number", "").strip().upper()

    data = load_data()

    # ── 1. Authenticate ──────────────────────────────────────────────────────
    user_record = data["users"].get(username)
    if not user_record or user_record["password"] != password:
        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    # ── 2. Check if user is already parked ──────────────────────────────────
    if user_record.get("assigned_slot"):
        slot_id = user_record["assigned_slot"]
        return jsonify({
            "success": False,
            "error":   f"You are already parked in Slot {slot_id}. Please exit first."
        }), 409

    # ── 3. Check parking availability ───────────────────────────────────────
    occupied = sum(1 for s in data["slots"].values() if s["status"] == "occupied")
    if occupied >= TOTAL_SLOTS:
        return jsonify({"success": False, "error": "Parking is FULL. No slots available."}), 503

    # ── 4. Find the nearest free slot (minimise rotation) ───────────────────
    current_pos = data["carousel_position"]
    best_slot   = None
    best_steps  = TOTAL_SLOTS + 1
    best_dir    = "CW"

    for slot_id, slot in data["slots"].items():
        if slot["status"] == "empty":
            direction, steps = shortest_path(current_pos, slot["index"])
            if steps < best_steps:
                best_steps = steps
                best_slot  = slot_id
                best_dir   = direction

    # ── 5. Rotate carousel ──────────────────────────────────────────────────
    success = send_rotate(best_steps, best_dir)
    if not success:
        return jsonify({"success": False, "error": "ESP32 communication failed. Check hardware."}), 502

    # ── 6. Update database ──────────────────────────────────────────────────
    target_index          = data["slots"][best_slot]["index"]
    new_position          = target_index                       # slot now at entry
    entry_time            = datetime.datetime.now().isoformat()

    data["slots"][best_slot]["status"]         = "occupied"
    data["slots"][best_slot]["user"]           = username
    data["slots"][best_slot]["entry_time"]     = entry_time
    data["slots"][best_slot]["vehicle_number"] = vehicle_no
    data["users"][username]["assigned_slot"]   = best_slot
    data["carousel_position"]                  = new_position
    save_data(data)

    session["username"] = username

    return jsonify({
        "success":        True,
        "message":        f"Welcome, {user_record['name']}! Drive into Slot {best_slot}.",
        "slot":           best_slot,
        "entry_time":     entry_time,
        "vehicle_number": vehicle_no,
        "steps_rotated":  best_steps,
        "direction":      best_dir
    })


@app.route("/api/exit", methods=["POST"])
def api_exit():
    """
    Exit flow: rotate carousel to user's slot, compute cost, free the slot.
    Body JSON: { "username": str, "password": str }
    """
    body = request.get_json(force=True)
    username = body.get("username", "").strip().lower()
    password = body.get("password", "").strip()

    data = load_data()

    # ── 1. Authenticate ──────────────────────────────────────────────────────
    user_record = data["users"].get(username)
    if not user_record or user_record["password"] != password:
        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    # ── 2. Verify slot assignment ────────────────────────────────────────────
    slot_id = user_record.get("assigned_slot")
    if not slot_id:
        return jsonify({"success": False, "error": "You have no active parking session."}), 404

    slot = data["slots"][slot_id]

    # ── 3. Calculate cost ────────────────────────────────────────────────────
    entry_time  = datetime.datetime.fromisoformat(slot["entry_time"])
    exit_time   = datetime.datetime.now()
    duration    = exit_time - entry_time
    total_secs  = int(duration.total_seconds())
    total_mins  = max(total_secs / 60, 0)
    # Bill for every commenced 5-minute block
    billable_blocks = math.ceil(total_mins / 5) if total_mins > 0 else 1
    cost        = billable_blocks * RATE_PER_5MIN

    hours, remainder = divmod(total_secs, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

    # ── 4. Rotate carousel to user's slot ───────────────────────────────────
    current_pos = data["carousel_position"]
    target_pos  = slot["index"]
    direction, steps = shortest_path(current_pos, target_pos)

    success = send_rotate(steps, direction)
    if not success:
        return jsonify({"success": False, "error": "ESP32 communication failed. Check hardware."}), 502

    # ── 5. Log transaction ───────────────────────────────────────────────────
    tx = {
        "username":       username,
        "slot":           slot_id,
        "vehicle_number": slot["vehicle_number"],
        "entry_time":     slot["entry_time"],
        "exit_time":      exit_time.isoformat(),
        "duration":       duration_str,
        "cost_rs":        cost
    }
    data["transaction_log"].append(tx)

    # ── 6. Free the slot ─────────────────────────────────────────────────────
    data["slots"][slot_id]["status"]         = "empty"
    data["slots"][slot_id]["user"]           = None
    data["slots"][slot_id]["entry_time"]     = None
    data["slots"][slot_id]["vehicle_number"] = None
    data["users"][username]["assigned_slot"] = None
    data["carousel_position"]               = target_pos
    save_data(data)

    session.pop("username", None)

    return jsonify({
        "success":        True,
        "message":        f"Goodbye, {user_record['name']}! Please collect your vehicle from Slot {slot_id}.",
        "slot":           slot_id,
        "vehicle_number": tx["vehicle_number"],
        "entry_time":     tx["entry_time"],
        "exit_time":      tx["exit_time"],
        "duration":       duration_str,
        "cost_rs":        cost,
        "steps_rotated":  steps,
        "direction":      direction
    })


@app.route("/api/esp32/health", methods=["GET"])
def esp32_health():
    """Proxy health check to ESP32 and return its status."""
    try:
        resp = requests.get(f"{ESP32_BASE_URL}/status", timeout=5)
        return jsonify({"online": True, "esp32": resp.json()})
    except Exception as e:
        return jsonify({"online": False, "error": str(e)}), 503


@app.route("/api/reset_position", methods=["POST"])
def reset_position():
    """
    Admin endpoint: manually sync carousel position in DB without moving motor.
    Body JSON: { "position": 0|1|2|3 }
    """
    body = request.get_json(force=True)
    pos  = body.get("position")
    if pos not in [0, 1, 2, 3]:
        return jsonify({"success": False, "error": "position must be 0-3"}), 400
    data = load_data()
    data["carousel_position"] = pos
    save_data(data)
    return jsonify({"success": True, "carousel_position": pos})


# ─────────────────────────────── Entry Point ────────────────────────────────

if __name__ == "__main__":
    # Run on all interfaces so devices on the ESP32 AP can reach us
    app.run(host="0.0.0.0", port=5000, debug=True)
