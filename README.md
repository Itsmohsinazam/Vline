# 🚘 VLINE
## Vehicle Licence Interpretation and Number Extraction

A fully local Python dashboard that detects and logs vehicle number plates
from a **live camera** or **recorded video** using the
[Plate Recognizer](https://platerecognizer.com) deep-learning API.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 📷 Live Camera | Stream from any USB / built-in webcam |
| 🎬 Video File  | Process MP4, AVI, MOV, MKV, WMV files |
| 🚗 Plate Detection | OCR + bounding boxes on every frame |
| 🏍️ Vehicle Classification | Car · Truck · Bus · Motorcycle · Van · Pickup |
| 💾 SQLite Database | Every detection saved with timestamp |
| 📋 Detection Log | Searchable, sortable history table |
| 📤 CSV Export | Export all records with one click |
| ⚙️ Settings | API key, frame-skip, region filter, local SDK |
| 🖼️ Snapshots | Auto-saved JPEG for each unique plate detected |

---

## 🛠️ Installation

### 1. Prerequisites

- **Python 3.9+** (download from https://python.org)
- **pip** (comes with Python)

### 2. Install dependencies

```bash
cd vline
pip install -r requirements.txt
```

### 3. Get a Plate Recognizer API key

1. Go to https://platerecognizer.com and create a **free account**
2. Copy your **API Token** from the dashboard
3. Paste it in VLINE → Settings → API Key

> **Free tier**: 2,500 lookups/month – more than enough for testing.

---

## 🚀 Running VLINE

```bash
python main.py
```

The dashboard opens full-screen. Three tabs:

### 📷 Live Detection
- Choose **Live Camera** (index 0 = default webcam) or **Video File**
- Click **▶ Start Detection**
- Plates and vehicle types appear on the video feed with bounding boxes
- Each new unique plate is logged and saved to the database

### 📋 Detection Log
- Full history of all detections with search/filter
- Click column headers to sort
- Right-click → delete individual rows
- **Export CSV** saves everything to a spreadsheet

### ⚙️ Settings
- **API Key** – your Plate Recognizer token
- **Frame Skip** – analyse every N-th frame (default 10); higher = fewer API calls
- **Region Filter** – e.g. `pk` for Pakistan, `us` for USA, `gb` for UK
- **Local SDK** – if running the Plate Recognizer Docker container locally

---

## 🐳 Optional: Run Plate Recognizer locally (no internet required)

If you have the Plate Recognizer SDK Docker image:

```bash
docker run -t -p 8080:8080 -e LICENSE_KEY=YOUR_KEY platerecognizer/alpr
```

Then in VLINE Settings:
- ✅ Enable **Use Local SDK**
- URL: `http://localhost:8080/v1/plate-reader/`

---

## 📁 Project Structure

```
vline/
├── main.py          ← Launch this
├── dashboard.py     ← Full Tkinter UI
├── detector.py      ← Plate Recognizer API + OpenCV video engine
├── database.py      ← SQLite storage layer
├── config.py        ← All settings and constants
├── requirements.txt
├── vline_data.db    ← Created on first run (SQLite)
├── vline_config.json← Saved settings
└── snapshots/       ← Auto-saved plate images
```

---

## 🗄️ Database Schema

**detections** table:

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Auto-increment PK |
| plate | TEXT | Detected plate number |
| vehicle_type | TEXT | Car / Truck / Bus / Motorcycle / Van / Pickup |
| confidence | REAL | Vehicle type confidence (0–1) |
| plate_score | REAL | Plate OCR confidence (0–1) |
| source | TEXT | `camera` or `video` |
| snapshot_path | TEXT | Path to saved JPEG |
| region | TEXT | Country/region code |
| timestamp | TEXT | Full datetime |
| date | TEXT | YYYY-MM-DD |
| time | TEXT | HH:MM:SS |

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Camera not opening | Try Camera Index 1 or 2 in the sidebar |
| API errors | Check your API key in Settings; ensure internet connection |
| Slow detection | Increase Frame Skip slider |
| Black screen | Ensure OpenCV can access your webcam (run `python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"`) |

---

*VLINE is powered by the [Plate Recognizer](https://platerecognizer.com) ALPR engine.*
