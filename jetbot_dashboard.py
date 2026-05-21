# =========================================================
#  JETBOT ADVANCED DASHBOARD - FIXED DETECTION BUILD
# =========================================================
# CHANGES vs original:
#   [x] Replaced brightness-hack with real contour detection
#   [x] Fixed green ROI bounding box drawn on feed
#   [x] Red bounding boxes per detected object inside ROI
#   [x] Morphological cleanup (removes noise on 2GB hardware)
#   [x] Obstacle flag wired into movement logic correctly
#   [x] Detection confidence label on each box
#   [x] Frame-level status overlay (CLEAR / OBSTACLE DETECTED)
#   [x] Pure ASCII - no unicode or emoji (Python 3.6 safe)
#
# RUN:   python3 jetbot_dashboard.py
# OPEN:  http://<JETBOT-IP>:5000
# =========================================================

from flask import Flask, Response, render_template_string, request
from jetbot import Camera, Robot
import cv2
import numpy as np
import threading
import time

# -------------------- INIT --------------------
app    = Flask(__name__)
camera = Camera.instance()
robot  = Robot()

# -------------------- CONFIG --------------------
FRAME_W    = 320
FRAME_H    = 240
MOVE_SPEED = 0.35
MOVE_TIME  = 0.18
MAP_SIZE   = 120

# Detection ROI (fixed green box, bottom-centre of frame)
# Tweak these 4 values to reposition / resize the detection zone.
ROI_X1 = int(FRAME_W * 0.20)   # left   edge
ROI_Y1 = int(FRAME_H * 0.45)   # top    edge
ROI_X2 = int(FRAME_W * 0.80)   # right  edge
ROI_Y2 = int(FRAME_H * 0.92)   # bottom edge

# Contour detection thresholds
MIN_CONTOUR_AREA = 800
MAX_CONTOUR_AREA = (ROI_X2 - ROI_X1) * (ROI_Y2 - ROI_Y1) * 0.85

# Map cell values
FREE     = 0
PATH     = 100
OBSTACLE = 255

# -------------------- STATE --------------------
x         = MAP_SIZE // 2
y         = MAP_SIZE // 2
direction = "UP"
grid      = np.zeros((MAP_SIZE, MAP_SIZE), dtype=np.uint8)
lock      = threading.Lock()

obstacle_detected = False
obstacle_lock     = threading.Lock()

# -------------------- DETECTION CORE --------------------
def detect_objects_in_roi(frame):
    roi  = frame[ROI_Y1:ROI_Y2, ROI_X1:ROI_X2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)

    thresh = cv2.adaptiveThreshold(
        blur, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=15,
        C=4
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    clean  = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    clean  = cv2.dilate(clean, kernel, iterations=2)

    contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes       = []
    is_obstacle = False

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if MIN_CONTOUR_AREA < area < MAX_CONTOUR_AREA:
            rx, ry, rw, rh = cv2.boundingRect(cnt)
            fx = ROI_X1 + rx
            fy = ROI_Y1 + ry
            boxes.append((fx, fy, rw, rh, area))
            is_obstacle = True

    return boxes, is_obstacle


def annotate_frame(frame):
    out = frame.copy()

    boxes, is_obstacle = detect_objects_in_roi(frame)

    with obstacle_lock:
        global obstacle_detected
        obstacle_detected = is_obstacle

    roi_color = (0, 80, 255) if is_obstacle else (0, 220, 80)
    cv2.rectangle(out, (ROI_X1, ROI_Y1), (ROI_X2, ROI_Y2), roi_color, 2)
    cv2.putText(out, "DETECTION ZONE",
                (ROI_X1 + 2, ROI_Y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, roi_color, 1, cv2.LINE_AA)

    roi_area = (ROI_X2 - ROI_X1) * (ROI_Y2 - ROI_Y1)
    for (fx, fy, rw, rh, area) in boxes:
        cv2.rectangle(out, (fx, fy), (fx + rw, fy + rh), (0, 0, 255), 2)
        conf    = min(int((area / roi_area) * 100 * 2.5), 99)
        label   = "OBJ " + str(conf) + "%"
        label_y = fy - 5 if fy > 15 else fy + rh + 15
        cv2.putText(out, label,
                    (fx, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1, cv2.LINE_AA)

    if is_obstacle:
        banner_col  = (0, 0, 200)
        banner_text = "! OBSTACLE (" + str(len(boxes)) + " obj)"
    else:
        banner_col  = (0, 160, 60)
        banner_text = "CLEAR"

    cv2.rectangle(out, (0, 0), (200, 24), banner_col, -1)
    cv2.putText(out, banner_text, (6, 17),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

    return out

# -------------------- CAMERA STREAM --------------------
def gen_camera():
    while True:
        frame = camera.value
        frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        frame = annotate_frame(frame)
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            buffer.tobytes() +
            b'\r\n'
        )

# -------------------- MAP --------------------
def draw_robot_arrow(img, cx, cy, d):
    pts = {
        "UP":    ((cx, cy + 10), (cx, cy - 10)),
        "LEFT":  ((cx + 10, cy), (cx - 10, cy)),
        "RIGHT": ((cx - 10, cy), (cx + 10, cy)),
    }
    if d in pts:
        cv2.arrowedLine(img, pts[d][0], pts[d][1], (0, 255, 255), 2)


def generate_map():
    img  = np.zeros((420, 420, 3), dtype=np.uint8)
    cell = 10

    for i in range(40):
        for j in range(40):
            gx = (x - 20) + j
            gy = (y - 20) + i
            if 0 <= gx < MAP_SIZE and 0 <= gy < MAP_SIZE:
                val   = grid[gy][gx]
                color = (30, 30, 30)
                if val == PATH:
                    color = (255, 120, 0)
                elif val == OBSTACLE:
                    color = (40, 40, 220)
                cv2.rectangle(img,
                              (j * cell, i * cell),
                              ((j + 1) * cell, (i + 1) * cell),
                              color, -1)

    for i in range(0, 421, cell):
        cv2.line(img, (i, 0),  (i, 420), (45, 45, 45), 1)
        cv2.line(img, (0, i),  (420, i), (45, 45, 45), 1)

    rx, ry = 20 * cell, 20 * cell
    cv2.circle(img, (rx, ry), 8, (0, 255, 0), -1)
    draw_robot_arrow(img, rx, ry, direction)
    return img


def gen_map():
    while True:
        img = generate_map()
        ret, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            buffer.tobytes() +
            b'\r\n'
        )

# -------------------- MOVEMENT --------------------
def move_robot(cmd):
    global x, y, direction

    with lock:
        grid[y][x] = PATH

        with obstacle_lock:
            obs = obstacle_detected

        if cmd == "forward":
            direction = "UP"
            if obs:
                grid[max(0, y - 1)][x] = OBSTACLE
                print("[DETECTION] Obstacle blocked forward move")
                return
            else:
                robot.forward(MOVE_SPEED)
                y = max(0, y - 1)

        elif cmd == "left":
            direction = "LEFT"
            robot.left(MOVE_SPEED)
            x = max(0, x - 1)

        elif cmd == "right":
            direction = "RIGHT"
            robot.right(MOVE_SPEED)
            x = min(MAP_SIZE - 1, x + 1)

        elif cmd == "stop":
            robot.stop()
            return

        time.sleep(MOVE_TIME)
        robot.stop()

# -------------------- HTML GUI --------------------
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JetBot AI Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@400;700&display=swap');

        :root {
            --bg:     #090c14;
            --panel:  #101520;
            --border: #1e2d45;
            --accent: #00e5ff;
            --ok:     #00e676;
            --text:   #cdd9ef;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Exo 2', sans-serif;
            min-height: 100vh;
            padding: 20px;
        }

        header { text-align: center; margin-bottom: 24px; }

        header h1 {
            font-family: 'Share Tech Mono', monospace;
            font-size: 1.6rem;
            letter-spacing: 4px;
            color: var(--accent);
            text-shadow: 0 0 18px rgba(0,229,255,0.35);
        }

        header p {
            font-size: 0.75rem;
            color: #4a607a;
            letter-spacing: 2px;
            margin-top: 4px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 18px;
            max-width: 900px;
            margin: 0 auto 24px;
        }

        .panel {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }

        .panel-header {
            padding: 10px 16px;
            border-bottom: 1px solid var(--border);
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.78rem;
            letter-spacing: 2px;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .dot {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: var(--ok);
            box-shadow: 0 0 8px var(--ok);
            animation: pulse 1.8s ease-in-out infinite;
        }

        @keyframes pulse {
            0%,100% { opacity: 1; }
            50%      { opacity: 0.3; }
        }

        .panel img { width: 100%; display: block; }

        .controls {
            max-width: 280px;
            margin: 0 auto 18px;
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }

        .controls h3 {
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.75rem;
            letter-spacing: 2px;
            color: var(--accent);
            text-align: center;
            margin-bottom: 16px;
        }

        .btn-row {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 6px 0;
        }

        button {
            width: 72px; height: 72px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: #151c2e;
            color: white;
            font-size: 14px;
            font-family: 'Share Tech Mono', monospace;
            letter-spacing: 1px;
            cursor: pointer;
            transition: background 0.15s, transform 0.1s;
        }

        button:hover  { background: #1e2d45; }
        button:active { transform: scale(0.93); }

        button[value="stop"] {
            background: #2a1020;
            border-color: #5a1a2a;
        }

        .status-bar {
            max-width: 900px;
            margin: 0 auto;
            text-align: center;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.72rem;
            letter-spacing: 1.5px;
            color: #3a5070;
        }
    </style>
</head>
<body>

<header>
    <h1>JETBOT COMMAND INTERFACE</h1>
    <p>CONTOUR DETECTION - LIVE MAP - OBSTACLE AVOIDANCE</p>
</header>

<div class="grid">
    <div class="panel">
        <div class="panel-header">
            <div class="dot"></div> LIVE FEED + DETECTION
        </div>
        <img src="/video_feed">
    </div>
    <div class="panel">
        <div class="panel-header">
            <div class="dot"></div> OCCUPANCY MAP
        </div>
        <img src="/map_feed">
    </div>
</div>

<div class="controls">
    <h3>MOVEMENT</h3>
    <form action="/move" method="post">
        <div class="btn-row">
            <button name="cmd" value="forward">FWD</button>
        </div>
        <div class="btn-row">
            <button name="cmd" value="left">LFT</button>
            <button name="cmd" value="stop">STP</button>
            <button name="cmd" value="right">RGT</button>
        </div>
    </form>
</div>

<div class="status-bar">
    GREEN BOX = DETECTION ZONE | RED BOXES = DETECTED OBJECTS | BLUE MAP CELLS = OBSTACLES
</div>

</body>
</html>
"""

# -------------------- ROUTES --------------------
@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/video_feed')
def video_feed():
    return Response(gen_camera(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/map_feed')
def map_feed():
    return Response(gen_map(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/move', methods=['POST'])
def move():
    cmd = request.form['cmd']
    threading.Thread(target=move_robot, args=(cmd,)).start()
    return ("", 204)

# -------------------- MAIN --------------------
if __name__ == "__main__":
    try:
        print("JetBot Dashboard starting...")
        print("Open in browser: http://<JETBOT-IP>:5000")
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        robot.stop()
        print("Robot stopped.")
