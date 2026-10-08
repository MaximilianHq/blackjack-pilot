# Blackjack Pilot 🃏

Modern AI-powered Blackjack Assistant and YOLO11 training workspace featuring real-time card detection, Hi-Lo card counting, and instant Basic Strategy recommendations.

Supports two display modes:
1. **Desktop App**: Native high-performance PySide6 GUI with live GDI screen capture.
2. **Edge / Chrome Extension**: Live casino HUD overlay rendered directly on top of your browser table stream with in-browser calibration.

---

## 📁 Project Structure

```text
blackjack-pilot/
├── main.py                     # Desktop GUI (PySide6 GUI, live screen capture)
├── server.py                   # Local WebSocket AI Engine for the browser extension
├── blackjack_strategy.py       # Basic Strategy engine (hard, soft, pair splits, Illustrious 18)
├── card_counter.py             # Hi-Lo card counter & True Count estimation
├── round_stats.py              # Statistics, win rate tracking, and round evaluation
├── requirements.txt            # Python dependencies
├── docs/
│   └── basic_strategy.png      # Basic Strategy reference chart
├── models/
│   └── yolo11m_blackjack_v1.pt # Trained YOLO11m model (97.4% mAP50)
├── extension/                  # Edge / Chrome Browser Extension
│   ├── manifest.json           # Manifest V3 extension configuration
│   ├── icons/                  # 16px, 48px, 128px extension icons
│   ├── popup/                  # Extension popup controller & sensitivity settings
│   ├── background/             # Background service worker
│   └── content/                # In-browser HUD overlay & on-screen zone snipper
├── dataset/                    # Dataset directory structure for training
│   ├── data.yaml               # YOLO dataset configuration
│   ├── train/images/ & labels/
│   ├── valid/images/ & labels/
│   └── test/images/ & labels/
└── training/                   # Model training & analysis utilities
    ├── train.py                # Train YOLO11m at 1280p widescreen (GPU optimized)
    ├── test.py                 # Interactive image detection tester
    └── video2image.py          # Automatic frame extractor from gameplay videos
```

---

## 🌐 Edge & Chrome Extension (In-Browser HUD Overlay)

Run the assistant as a transparent HUD floating directly over your live casino table in **Microsoft Edge** or **Google Chrome**.

### 1. Start the Local AI Server
Launch the background engine that executes YOLO on GPU and evaluates hands:
```bash
python server.py
```
*(Runs on `ws://127.0.0.1:8765` with hardware acceleration)*

### 2. Install Extension in Edge / Chrome
1. Open Edge or Chrome and navigate to `edge://extensions` (or `chrome://extensions`).
2. Enable **Developer mode** (toggle in the bottom-left / top-right).
3. Click **Load unpacked** (*Läs in okomprimerat*) and select the `c:\blackjack-pilot\extension` folder.
4. Pin the **Blackjack Pilot** icon to your browser toolbar.

### 3. Using the In-Browser Overlay
1. Navigate to your live casino blackjack game in Edge/Chrome.
2. Click the Blackjack Pilot extension icon:
   - Click **▶ Start Browser Capture** and select the current tab to stream.
   - Click **📹 1. Feed Area** and drag a rectangle over the video table.
   - Click **👑 2. Dealer Zone** and drag a rectangle over the dealer's card placement area.
   - Click **👤 3. Player Zone** and drag a rectangle over your card box.
3. The draggable dark-themed HUD floating on your screen will immediately display:
   - **Optimal Move**: Glowing action badge (HIT, STAND, DOUBLE, SPLIT, SURRENDER).
   - **Hand Cards & Totals**: Evaluated dealer upcard and player hand sum.
   - **Hi-Lo Card Counting**: Running Count, True Count, and estimated Decks Remaining.
   - **Session Statistics**: Win rate %, rounds count, and record.

---

## 🖥️ Desktop Application (Native Mode)

If you prefer a standalone desktop window:

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch Desktop App
```bash
python main.py
```

### 3. Desktop Calibration
1. Click **📹 1. Select Full Video Feed** and drag a box over your game table.
2. Click **👑 2. Select Dealer Zone** and mark the dealer's area.
3. Click **👤 3. Select Player Zone** and mark your box.

---

## 📊 Basic Strategy Chart

The assistant implements standard casino multi-deck basic strategy rules with optional count-based Illustrious 18 deviations:

<p align="center">
  <img src="docs/basic_strategy.png" alt="Basic Strategy Reference Chart" width="600" />
</p>

### Strategy Legend:
- **Hard Totals**: Decisions based on non-Ace totals (or hands where Ace must count as 1 to avoid busting).
- **Soft Totals**: Hands containing an Ace counted as 11 (e.g., A,7 = Soft 18).
- **Pair Splitting**: Options to split identical-rank cards into two independent hands.
- **Surrender**: Forfeit half the bet on high-risk matchups when late surrender is offered.

---

## 🛠️ Training & Model Tools

### Test the Model on Images:
```bash
python training/test.py
```
*(Press Space/Enter for next image, 'q' or ESC to exit)*

### Extract Video Frames for Training:
```bash
python training/video2image.py
```

### Train a New YOLO11 Model:
Place images and annotations in `dataset/train` and `dataset/valid`, then run:
```bash
python training/train.py
```
*(When training finishes, the best weights are automatically copied to `models/yolo11m_blackjack_1280.pt`)*
