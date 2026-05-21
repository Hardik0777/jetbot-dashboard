# JetBot AI Dashboard

A real-time web dashboard for the NVIDIA JetBot — featuring live camera feed with contour-based obstacle detection, an occupancy map, and browser-based movement controls.

![Dashboard Preview](docs/preview.png)

---

## Features

- **Live Camera Feed** — Streams MJPEG video at 320×240 directly in the browser
- **Contour-Based Detection** — Adaptive thresholding + morphological cleanup to detect obstacles without relying on brightness hacks
- **Green Detection Zone** — Configurable ROI box overlaid on the feed; turns red when an obstacle is detected
- **Red Bounding Boxes** — Per-object boxes with a confidence percentage label
- **Status Banner** — Frame-level `CLEAR` / `! OBSTACLE` overlay on the video
- **Occupancy Map** — 120×120 grid showing path history (orange) and obstacle cells (blue), centered on the robot
- **Browser Controls** — FWD / LFT / RGT / STP buttons via HTTP POST; obstacle flag blocks forward movement automatically
- **Pure ASCII / Python 3.6 safe** — Runs on JetBot's default 2 GB Jetson Nano image

---

## Hardware Requirements

| Component | Detail |
|-----------|--------|
| Platform  | NVIDIA Jetson Nano (2 GB or 4 GB) |
| Robot     | Waveshare JetBot Kit (or compatible) |
| Camera    | CSI or USB camera supported by `jetbot.Camera` |

---

## Software Requirements

- JetPack 4.x with JetBot Docker image **or** bare-metal JetBot environment
- Python 3.6+

### Python Dependencies

```
flask
jetbot
opencv-python
numpy
```

Install on the Jetson:

```bash
pip3 install flask opencv-python numpy
# jetbot is pre-installed in the official JetBot image
```

---

## Quick Start

1. **Clone the repo onto your JetBot:**
   ```bash
   git clone https://github.com/<your-username>/jetbot-dashboard.git
   cd jetbot-dashboard
   ```

2. **Run the dashboard:**
   ```bash
   python3 jetbot_dashboard.py
   ```

3. **Open in your browser** (same Wi-Fi network):
   ```
   http://<JETBOT-IP>:5000
   ```
   Replace `<JETBOT-IP>` with your JetBot's IP address (find it via `ifconfig` or your router).

---

## Configuration

All tuneable values are at the top of `jetbot_dashboard.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FRAME_W / FRAME_H` | `320 / 240` | Resize resolution for processing & streaming |
| `MOVE_SPEED` | `0.35` | Motor speed (0.0 – 1.0) |
| `MOVE_TIME` | `0.18 s` | Duration of each movement pulse |
| `MAP_SIZE` | `120` | Occupancy grid side length (cells) |
| `ROI_X1/Y1/X2/Y2` | 20–80 % of frame | Detection zone boundaries |
| `MIN_CONTOUR_AREA` | `800 px²` | Minimum blob size to register as an object |
| `MAX_CONTOUR_AREA` | `85 % of ROI` | Maximum blob size (ignores full-frame fills) |

### Tuning the Detection Zone

```python
# Example: shrink the ROI to the bottom third of the frame
ROI_X1 = int(FRAME_W * 0.10)
ROI_Y1 = int(FRAME_H * 0.65)
ROI_X2 = int(FRAME_W * 0.90)
ROI_Y2 = int(FRAME_H * 0.95)
```

---

## Project Structure

```
jetbot-dashboard/
├── jetbot_dashboard.py   # Main application
├── README.md
├── requirements.txt
├── .gitignore
└── docs/
    └── preview.png       # (optional screenshot)
```

---

## How Detection Works

1. **ROI crop** — Only the configured rectangle is analysed each frame.
2. **Grayscale + Gaussian blur** — Reduces sensor noise before thresholding.
3. **Adaptive threshold** (`ADAPTIVE_THRESH_GAUSSIAN_C`, inverted) — Handles variable lighting conditions.
4. **Morphological open + dilate** — Removes small noise blobs; enlarges real objects.
5. **Contour filtering** — Contours outside `MIN_CONTOUR_AREA` … `MAX_CONTOUR_AREA` are discarded.
6. **Obstacle flag** — Set to `True` if any valid contour remains; resets every frame.
7. **Movement gate** — `forward` command is silently blocked when the flag is set; the map cell ahead is marked as an obstacle.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/video_feed` | GET | MJPEG camera stream |
| `/map_feed` | GET | MJPEG occupancy map stream |
| `/move` | POST | Send movement command (`cmd`: `forward` / `left` / `right` / `stop`) |

---

## Known Limitations

- **No reverse** — Back movement is not implemented; add it by extending `move_robot()`.
- **Single-threaded detection** — Detection runs inline with the camera generator; heavy scenes may drop FPS.
- **No persistence** — The occupancy map resets on every restart.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
