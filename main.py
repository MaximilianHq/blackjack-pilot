"""
Blackjack Live Assistant v2
High-performance PySide6 GUI with dark modern theme, non-stretching aspect-ratio previews,
smooth clean sliders, Hi-Lo counting, basic strategy, and support for:
1. Master video feed capture of the entire table (single and multi-monitor support)
2. User-selected sub-zones for Dealer and Player cards
3. Newly trained Roboflow/Mixed model (v2 - Medium) by default
"""

import os
import sys
import time

import cv2
import numpy as np
import torch
from mss import mss

# Fix Windows DPI scaling so mss and PySide6 coordinates match precisely
try:
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
except ImportError:
    pass

from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# Import strategy, card counter, and statistics tracker
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)


from blackjack_strategy import BlackjackStrategy
from card_counter import HiLoCounter
from round_stats import RoundStats


def map_card_value(raw_label):
    """Converts model labels (e.g. 10, A, K, Q, J, 2-9, or 10H) to Blackjack values."""
    lbl = str(raw_label).upper().strip()
    if lbl in ["BACK", "FACEDOWN", "HIDDEN", "B", "CARD"]:
        return "B"
    # Remove suit suffix if present (e.g. 10C -> 10, AH -> A)
    for s in ["S", "H", "D", "C"]:
        if lbl.endswith(s) and len(lbl) > 1:
            lbl = lbl[:-1]
    if lbl == "A":
        return "A"
    elif lbl in ["K", "Q", "J", "10"]:
        return 10
    else:
        try:
            return int(lbl)
        except ValueError:
            return "B"


def calculate_hand_value(cards):
    """Calculates hand total and whether the hand is soft (contains an active Ace counted as 11)."""
    valid = [c for c in cards if c != "B"]
    if not valid:
        return 0, False
    total = 0
    aces = 0
    for c in valid:
        if c == "A":
            total += 11
            aces += 1
        elif isinstance(c, int):
            total += c
        else:
            try:
                total += int(c)
            except (TypeError, ValueError):
                pass
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    is_soft = aces > 0 and total <= 21
    return total, is_soft


def format_hand_text(cards):
    """Formats list of cards and evaluated total into readable display strings."""
    if not cards:
        return "-", "No cards"
    valid = [c for c in cards if c != "B"]
    has_hidden = "B" in cards
    cards_str = ", ".join(str(c) for c in cards)
    if not valid:
        return f"[{cards_str}]", "Hidden card"

    total, is_soft = calculate_hand_value(cards)
    if total > 21:
        sum_str = f"Bust ({total})"
    elif total == 21 and len(valid) == 2 and not has_hidden:
        sum_str = "Blackjack! (21)"
    elif is_soft:
        sum_str = f"Soft {total} ({total - 10}/{total})"
    else:
        sum_str = f"{total}"

    if has_hidden:
        sum_str += " + hidden"

    return f"[{cards_str}]", sum_str


class ModelEngine:
    """Manages YOLO model loading and inference."""

    def __init__(self):
        self.models = {}
        self.active_model_name = ""
        self.active_model = None

        # Model paths - pre-trained 1280p YOLO11 model in models/
        self.model_paths = {
            "YOLO11m Blackjack 1280p (Default)": os.path.join(
                BASE_DIR, "models", "yolo11m_blackjack_1280.pt"
            ),
        }
        # Automatically detect additional .pt models in models/
        models_dir = os.path.join(BASE_DIR, "models")
        if os.path.exists(models_dir):
            for f in sorted(os.listdir(models_dir)):
                if f.endswith(".pt") and f != "yolo11m_blackjack_1280.pt":
                    label = f"Model ({f})"
                    self.model_paths[label] = os.path.join(models_dir, f)

    def load_model(self, name):
        from ultralytics import YOLO

        if name in self.models:
            self.active_model = self.models[name]
            self.active_model_name = name
            return True, f"Active: {name}"

        path = self.model_paths.get(name, "")
        if os.path.exists(path):
            try:
                print(f"[ModelEngine] Loading {name} from {path}...")
                m = YOLO(path)
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
                print(f"[ModelEngine] Device selected: {device}")
                self.models[name] = m
                self.active_model = m
                self.active_model_name = name
                dev_name = (
                    torch.cuda.get_device_name(0)
                    if torch.cuda.is_available()
                    else "CPU"
                )
                return True, f"Active ({dev_name})"
            except (
                FileNotFoundError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                print(f"[ModelEngine] Error loading {name}: {exc}")
                return False, f"Error: {exc}"
        else:
            print(f"[ModelEngine] File missing: {path}")
            return False, "Model file missing"


class CaptureWorker(QThread):
    """
    Background worker thread that grabs screen frames of the master video feed,
    executes YOLO inference once per frame, and categorizes cards located in the
    dealer zone, player zone, and table area.
    """

    frame_ready = Signal(dict)

    def __init__(self, model_engine):
        super().__init__()
        self.model_engine = model_engine
        self.running = True

        self.feed_bbox = None  # {'top': int, 'left': int, 'width': int, 'height': int}
        self.dealer_zone = None  # (dx1, dy1, dx2, dy2) in feed coordinates
        self.player_zone = None  # (px1, py1, px2, py2) in feed coordinates

        self.conf_thresh = 0.35
        self.iou_thresh = 0.5

    def set_feed_bbox(self, bbox):
        self.feed_bbox = bbox

    def set_dealer_zone(self, zone):
        self.dealer_zone = zone

    def set_player_zone(self, zone):
        self.player_zone = zone

    def clear_zones(self):
        self.dealer_zone = None
        self.player_zone = None

    def set_thresholds(self, conf, iou):
        self.conf_thresh = conf
        self.iou_thresh = iou

    def stop(self):
        self.running = False
        self.wait(1000)

    def _in_zone(self, box, zone):
        """Checks if a card's bounding box belongs to the designated zone."""
        if not zone:
            return False
        zx1, zy1, zx2, zy2 = zone
        x1, y1, x2, y2 = box
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        # 1. Check if center point lies inside zone
        if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
            return True

        # 2. Check area overlap fraction (at least 30% of card inside zone)
        ox1 = max(x1, zx1)
        oy1 = max(y1, zy1)
        ox2 = min(x2, zx2)
        oy2 = min(y2, zy2)
        if ox2 > ox1 and oy2 > oy1:
            overlap = (ox2 - ox1) * (oy2 - oy1)
            card_area = (x2 - x1) * (y2 - y1)
            if card_area > 0 and (overlap / card_area) >= 0.30:
                return True
        return False

    def _draw_zone_overlay(self, img, zone, color_bgr, label):
        """Draws a semi-transparent colored overlay and boundary line around a zone."""
        zx1, zy1, zx2, zy2 = zone
        h, w = img.shape[:2]
        zx1 = max(0, min(w - 1, int(zx1)))
        zy1 = max(0, min(h - 1, int(zy1)))
        zx2 = max(0, min(w - 1, int(zx2)))
        zy2 = max(0, min(h - 1, int(zy2)))
        if zx2 <= zx1 or zy2 <= zy1:
            return

        # Semi-transparent background
        sub = img[zy1:zy2, zx1:zx2]
        colored = np.full_like(sub, color_bgr, dtype=np.uint8)
        img[zy1:zy2, zx1:zx2] = cv2.addWeighted(colored, 0.12, sub, 0.88, 0)

        # Border rectangle
        cv2.rectangle(img, (zx1, zy1), (zx2, zy2), color_bgr, 2)

        # Header tag
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        by1 = max(0, zy1 - th - 8)
        by2 = max(th + 8, zy1)
        cv2.rectangle(img, (zx1, by1), (zx1 + tw + 12, by2), color_bgr, -1)
        cv2.putText(
            img,
            label,
            (zx1 + 6, by2 - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )

    def _draw_card_box(self, img, box, label, color_bgr):
        """Draws a bounding box and label tag around a detected card."""
        x1, y1, x2, y2 = box
        cv2.rectangle(img, (x1, y1), (x2, y2), color_bgr, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        by1 = max(0, y1 - th - 6)
        by2 = max(th + 6, y1)
        cv2.rectangle(img, (x1, by1), (x1 + tw + 8, by2), color_bgr, -1)
        cv2.putText(
            img,
            label,
            (x1 + 4, by2 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    def process_frame(self, img_bgr):
        annotated = img_bgr.copy()

        # 1. Render active zones if defined
        if self.dealer_zone:
            self._draw_zone_overlay(
                annotated, self.dealer_zone, (0, 185, 255), "DEALER ZONE"
            )
        if self.player_zone:
            self._draw_zone_overlay(
                annotated, self.player_zone, (255, 170, 0), "PLAYER ZONE"
            )

        raw_detections = []
        if self.model_engine.active_model is not None:
            is_1280 = "1280" in str(self.model_engine.active_model_name)
            run_imgsz = 1280 if is_1280 else 640
            res = self.model_engine.active_model(
                img_bgr,
                imgsz=run_imgsz,
                conf=self.conf_thresh,
                iou=self.iou_thresh,
                verbose=False,
            )[0]
            for box in res.boxes:
                c = float(box.conf[0])
                if c < self.conf_thresh:
                    continue
                cls_id = int(box.cls[0])
                raw_lbl = self.model_engine.active_model.names[cls_id]
                val = map_card_value(raw_lbl)
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                raw_detections.append(
                    {
                        "bbox": (x1, y1, x2, y2),
                        "cx": (x1 + x2) // 2,
                        "cy": (y1 + y2) // 2,
                        "conf": c,
                        "label": raw_lbl,
                        "val": val,
                    }
                )

        # 2. Categorize detected cards into Dealer, Player, and Table
        dealer_cards = []
        player_cards = []
        table_cards = []

        for d in raw_detections:
            box = d["bbox"]
            lbl = d["label"]
            conf = d["conf"]

            in_dealer = self._in_zone(box, self.dealer_zone)
            in_player = self._in_zone(box, self.player_zone)

            if in_dealer:
                dealer_cards.append(d)
                self._draw_card_box(
                    annotated, box, f"DEALER: {lbl} ({conf:.0%})", (0, 185, 255)
                )
            elif in_player:
                player_cards.append(d)
                self._draw_card_box(
                    annotated, box, f"PLAYER: {lbl} ({conf:.0%})", (255, 170, 0)
                )
            else:
                table_cards.append(d)
                # Render other table cards with clean green outline
                self._draw_card_box(
                    annotated, box, f"{lbl} ({conf:.0%})", (0, 230, 115)
                )

        # Sort cards left to right across table
        dealer_cards.sort(key=lambda x: x["bbox"][0])
        player_cards.sort(key=lambda x: x["bbox"][0])

        all_vals = [d["val"] for d in (dealer_cards + player_cards + table_cards)]
        dealer_vals = [d["val"] for d in dealer_cards]
        player_vals = [d["val"] for d in player_cards]

        return {
            "image": annotated,
            "dealer_cards": dealer_vals,
            "player_cards": player_vals,
            "all_cards": all_vals,
        }

    def run(self):
        with mss() as sct:
            while self.running:
                if (
                    self.feed_bbox
                    and self.feed_bbox.get("width", 0) > 40
                    and self.feed_bbox.get("height", 0) > 40
                ):
                    img_bgr = None
                    # First try mss (fast direct GDI capture)
                    try:
                        sct_img = sct.grab(self.feed_bbox)
                        img_bgr = np.array(sct_img)[:, :, :3]
                    except (OSError, TypeError, ValueError):
                        # Multi-monitor setup with negative coordinates fallback to Qt screen grab
                        try:
                            screen = QApplication.primaryScreen()
                            pix = screen.grabWindow(
                                0,
                                self.feed_bbox["left"],
                                self.feed_bbox["top"],
                                self.feed_bbox["width"],
                                self.feed_bbox["height"],
                            )
                            qimg = pix.toImage().convertToFormat(QImage.Format_BGR888)
                            arr = np.frombuffer(
                                qimg.constBits(), dtype=np.uint8
                            ).reshape((qimg.height(), qimg.width(), 3))
                            img_bgr = arr
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            pass

                    if img_bgr is not None:
                        try:
                            result = self.process_frame(img_bgr)
                            self.frame_ready.emit(result)
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            pass
                time.sleep(0.04)  # ~25 FPS max


class AspectRatioLabel(QLabel):
    """A QLabel that maintains correct aspect ratio without image distortion."""

    def __init__(self, placeholder="[ No Video Feed Selected ]"):
        super().__init__()
        self.placeholder = placeholder
        self.setText(placeholder)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            background-color: #121316;
            color: #72767d;
            font-size: 14px;
            font-weight: 500;
            border: 2px dashed #2f3136;
            border-radius: 8px;
        """)
        self.current_pixmap = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 280)

    def set_image(self, img_bgr):
        h, w, ch = img_bgr.shape
        bytes_per_line = ch * w
        q_img = QImage(img_bgr.data, w, h, bytes_per_line, QImage.Format_BGR888)
        self.current_pixmap = QPixmap.fromImage(q_img)
        self.update_pixmap()

    def update_pixmap(self):
        if self.current_pixmap and not self.current_pixmap.isNull():
            scaled = self.current_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            super().setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_pixmap()


class ScreenSnipper(QWidget):
    """
    Fullscreen overlay tool to select video feed or sub-zones.
    Spans all connected monitors and handles multi-monitor virtual coordinates accurately.
    """

    snippet_selected = Signal(dict, str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setMouseTracking(True)

        self.start_global = None
        self.current_global = None
        self.is_dragging = False
        self.target_type = "feed"
        self.instruction_text = ""

    def start(self, target_type="feed", instruction=""):
        self.target_type = target_type
        self.instruction_text = instruction
        self.start_global = None
        self.current_global = None
        self.is_dragging = False

        # Span all screens across the virtual desktop surface (including negative coordinates)
        geo = QRect()
        for screen in QApplication.screens():
            geo = geo.united(screen.geometry())
        self.setGeometry(geo)
        self.show()
        self.activateWindow()
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_global = event.globalPosition().toPoint()
            self.current_global = self.start_global
            self.is_dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self.current_global = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            end_global = event.globalPosition().toPoint()
            self.close()

            if self.start_global is not None:
                x1 = min(self.start_global.x(), end_global.x())
                y1 = min(self.start_global.y(), end_global.y())
                w = abs(end_global.x() - self.start_global.x())
                h = abs(end_global.y() - self.start_global.y())

                if w > 20 and h > 20:
                    bbox = {
                        "top": y1,
                        "left": x1,
                        "width": w,
                        "height": h,
                    }
                    print(
                        f"[ScreenSnipper] Global selection for {self.target_type}: {bbox}"
                    )
                    self.snippet_selected.emit(bbox, self.target_type)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.is_dragging = False
            self.close()
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. Semi-transparent dark overlay across entire desktop
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        # 2. When dragging a rectangle, cut out clear selection region
        if self.is_dragging and self.start_global and self.current_global:
            p1 = self.mapFromGlobal(self.start_global)
            p2 = self.mapFromGlobal(self.current_global)
            sel_rect = QRect(p1, p2).normalized()

            # Render selected cut-out 100% transparent so screen shows sharply underneath
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(sel_rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Border color according to target type
            if self.target_type == "feed":
                color = QColor(56, 139, 253)  # Blue for master feed
            elif self.target_type == "dealer":
                color = QColor(210, 153, 34)  # Gold for dealer zone
            else:
                color = QColor(56, 189, 248)  # Cyan for player zone

            pen = QPen(color, 3)
            painter.setPen(pen)
            painter.drawRect(sel_rect)

            # Dimensions indicator
            dim_text = f"{sel_rect.width()} x {sel_rect.height()}"
            painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(sel_rect.left() + 6, max(24, sel_rect.top() - 8), dim_text)

        # 3. Floating instruction banner
        banner_text = (
            self.instruction_text
            or "Drag a rectangle with the mouse (Press ESC to cancel)"
        )
        painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(banner_text) + 40
        th = 42

        # Center banner on the monitor containing cursor
        cursor_pos = QCursor.pos()
        target_screen = (
            QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        )
        screen_center = target_screen.geometry().center()
        local_center = self.mapFromGlobal(screen_center)

        bx = max(10, local_center.x() - tw // 2)
        by = target_screen.geometry().top() + 30
        local_by = self.mapFromGlobal(QPoint(0, by)).y()

        # Banner background
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(22, 27, 34, 235))
        painter.drawRoundedRect(bx, local_by, tw, th, 8, 8)

        # Banner border
        painter.setPen(QPen(QColor(88, 166, 255), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(bx, local_by, tw, th, 8, 8)

        # Banner text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRect(bx, local_by, tw, th), Qt.AlignCenter, banner_text)


class ModernBlackjackApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blackjack Pilot - Live Pro Assistant v2")
        self.resize(1260, 860)
        self.setMinimumSize(1020, 720)

        # Logic and engines
        self.strategy = BlackjackStrategy()
        self.counter = HiLoCounter(decks=6)
        self.stats = RoundStats()
        self.model_engine = ModelEngine()

        # Coordinates
        self.feed_bbox = None
        self.dealer_zone = None
        self.player_zone = None

        # Worker thread
        self.worker = CaptureWorker(self.model_engine)
        self.worker.frame_ready.connect(self.on_frame_ready)

        # Recent detected cards
        self.last_dealer_cards = []
        self.last_player_cards = []

        # Snipper overlay
        self.snipper = ScreenSnipper()
        self.snipper.snippet_selected.connect(self.on_snippet_selected)

        self.setup_theme()
        self.setup_ui()

        # Initialize models and start capture thread
        self.init_models()
        self.worker.start()

    def setup_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d1117;
            }
            QWidget {
                color: #e6edf3;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #30363d;
                border-radius: 8px;
                margin-top: 18px;
                padding-top: 14px;
                background-color: #161b22;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 10px;
                background-color: #21262d;
                color: #58a6ff;
                border: 1px solid #30363d;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #161b22;
            }
            QPushButton#btnFeed {
                background-color: #1f6feb;
                border-color: #388bfd;
                color: #ffffff;
            }
            QPushButton#btnFeed:hover {
                background-color: #388bfd;
            }
            QPushButton#btnDealerZone {
                background-color: #9a6700;
                border-color: #d29922;
                color: #ffffff;
            }
            QPushButton#btnDealerZone:hover {
                background-color: #bb8009;
            }
            QPushButton#btnPlayerZone {
                background-color: #0969da;
                border-color: #218bff;
                color: #ffffff;
            }
            QPushButton#btnPlayerZone:hover {
                background-color: #218bff;
            }
            QComboBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 12px;
                color: #c9d1d9;
                font-weight: 500;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #161b22;
                border: 1px solid #30363d;
                selection-background-color: #1f6feb;
                color: #c9d1d9;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #21262d;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #58a6ff;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #58a6ff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #58a6ff;
                border-color: #ffffff;
            }
            QSpinBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 5px;
                color: #ffffff;
            }
        """)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # ========================================================
        # LEFT PANEL: Master Video Feed + Table Zones + Hand Cards
        # ========================================================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Video feed group
        feed_group = QGroupBox("Live Video Feed & Table Zones")
        fg_layout = QVBoxLayout(feed_group)
        fg_layout.setSpacing(8)

        # 1. Action buttons for Master Feed and Zones
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        self.btn_select_feed = QPushButton("📹 1. Select Full Video Feed")
        self.btn_select_feed.setObjectName("btnFeed")
        self.btn_select_feed.clicked.connect(lambda: self.start_selection("feed"))
        ctrl_bar.addWidget(self.btn_select_feed)

        self.btn_select_dealer = QPushButton("👑 2. Select Dealer Zone")
        self.btn_select_dealer.setObjectName("btnDealerZone")
        self.btn_select_dealer.clicked.connect(lambda: self.start_selection("dealer"))
        ctrl_bar.addWidget(self.btn_select_dealer)

        self.btn_select_player = QPushButton("👤 3. Select Player Zone")
        self.btn_select_player.setObjectName("btnPlayerZone")
        self.btn_select_player.clicked.connect(lambda: self.start_selection("player"))
        ctrl_bar.addWidget(self.btn_select_player)

        self.btn_reset_zones = QPushButton("↺ Clear Zones")
        self.btn_reset_zones.clicked.connect(self.reset_zones)
        ctrl_bar.addWidget(self.btn_reset_zones)

        ctrl_bar.addStretch()
        fg_layout.addLayout(ctrl_bar)

        # 2. Status indicators for active regions
        status_bar = QHBoxLayout()
        status_bar.setSpacing(16)

        self.lbl_feed_status = QLabel("Feed: Not selected")
        self.lbl_feed_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        status_bar.addWidget(self.lbl_feed_status)

        self.lbl_dealer_status = QLabel("Dealer Zone: Not selected")
        self.lbl_dealer_status.setStyleSheet(
            "color: #d29922; font-size: 11px; font-weight: 500;"
        )
        status_bar.addWidget(self.lbl_dealer_status)

        self.lbl_player_status = QLabel("Player Zone: Not selected")
        self.lbl_player_status.setStyleSheet(
            "color: #58a6ff; font-size: 11px; font-weight: 500;"
        )
        status_bar.addWidget(self.lbl_player_status)

        status_bar.addStretch()
        fg_layout.addLayout(status_bar)

        # 3. Master Video Feed Aspect-Ratio Viewer
        self.preview_master = AspectRatioLabel(
            "[ No Video Feed Selected - Click '1. Select Full Video Feed' ]"
        )
        fg_layout.addWidget(self.preview_master)

        left_layout.addWidget(feed_group, 4)

        # 4. Hand status cards beneath video feed
        hands_layout = QHBoxLayout()
        hands_layout.setSpacing(12)

        # Dealer Hand Card
        dealer_frame = QFrame()
        dealer_frame.setStyleSheet("""
            QFrame {
                background-color: #1c1917;
                border: 2px solid #d29922;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        df_layout = QVBoxLayout(dealer_frame)
        df_layout.setSpacing(4)
        lbl_d_header = QLabel("👑 DEALER HAND")
        lbl_d_header.setStyleSheet("color: #e3b341; font-weight: 700; font-size: 12px;")
        df_layout.addWidget(lbl_d_header)

        self.lbl_dealer_cards = QLabel("Cards: -")
        self.lbl_dealer_cards.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: 700;"
        )
        df_layout.addWidget(self.lbl_dealer_cards)

        self.lbl_dealer_sum = QLabel("Total: -")
        self.lbl_dealer_sum.setStyleSheet(
            "color: #d29922; font-size: 13px; font-weight: 600;"
        )
        df_layout.addWidget(self.lbl_dealer_sum)
        hands_layout.addWidget(dealer_frame)

        # Player Hand Card
        player_frame = QFrame()
        player_frame.setStyleSheet("""
            QFrame {
                background-color: #0c192c;
                border: 2px solid #388bfd;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        pf_layout = QVBoxLayout(player_frame)
        pf_layout.setSpacing(4)
        lbl_p_header = QLabel("👤 YOUR HAND (PLAYER)")
        lbl_p_header.setStyleSheet("color: #58a6ff; font-weight: 700; font-size: 12px;")
        pf_layout.addWidget(lbl_p_header)

        self.lbl_player_cards = QLabel("Cards: -")
        self.lbl_player_cards.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: 700;"
        )
        pf_layout.addWidget(self.lbl_player_cards)

        self.lbl_player_sum = QLabel("Total: -")
        self.lbl_player_sum.setStyleSheet(
            "color: #58a6ff; font-size: 13px; font-weight: 600;"
        )
        pf_layout.addWidget(self.lbl_player_sum)
        hands_layout.addWidget(player_frame)

        left_layout.addLayout(hands_layout, 1)
        main_layout.addWidget(left_panel, 3)

        # ========================================================
        # RIGHT PANEL: AI Controls, Optimal Strategy & Statistics
        # ========================================================
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 1. AI Model Selection
        model_group = QGroupBox("AI Model Selection")
        mg_layout = QVBoxLayout(model_group)
        self.combo_model = QComboBox()
        for name in self.model_engine.model_paths:
            self.combo_model.addItem(name)
        self.combo_model.currentTextChanged.connect(self.on_model_changed)
        mg_layout.addWidget(self.combo_model)

        self.lbl_model_status = QLabel("Status: Initializing...")
        self.lbl_model_status.setStyleSheet("color: #3fb950; font-size: 12px;")
        mg_layout.addWidget(self.lbl_model_status)
        right_layout.addWidget(model_group)

        # 2. Detection Sensitivity Controls
        sens_group = QGroupBox("Detection Sensitivity")
        sg_layout = QGridLayout(sens_group)
        sg_layout.setHorizontalSpacing(10)
        sg_layout.setVerticalSpacing(8)

        # Confidence Slider
        sg_layout.addWidget(QLabel("Confidence:"), 0, 0)
        self.slider_conf = QSlider(Qt.Horizontal)
        self.slider_conf.setRange(10, 90)
        self.slider_conf.setValue(35)
        self.slider_conf.valueChanged.connect(self.on_threshold_changed)
        sg_layout.addWidget(self.slider_conf, 0, 1)
        self.lbl_conf_val = QLabel("35%")
        self.lbl_conf_val.setFixedWidth(36)
        self.lbl_conf_val.setStyleSheet("font-weight: 600; color: #58a6ff;")
        sg_layout.addWidget(self.lbl_conf_val, 0, 2)

        # NMS / Overlap Slider
        sg_layout.addWidget(QLabel("Overlap (IoU):"), 1, 0)
        self.slider_iou = QSlider(Qt.Horizontal)
        self.slider_iou.setRange(20, 80)
        self.slider_iou.setValue(50)
        self.slider_iou.valueChanged.connect(self.on_threshold_changed)
        sg_layout.addWidget(self.slider_iou, 1, 1)
        self.lbl_iou_val = QLabel("50%")
        self.lbl_iou_val.setFixedWidth(36)
        self.lbl_iou_val.setStyleSheet("font-weight: 600; color: #58a6ff;")
        sg_layout.addWidget(self.lbl_iou_val, 1, 2)

        right_layout.addWidget(sens_group)

        # 3. Optimal Move (Basic Strategy)
        strat_group = QGroupBox("Optimal Move (Basic Strategy)")
        str_layout = QVBoxLayout(strat_group)
        self.lbl_optimal_move = QLabel("Waiting for cards...")
        self.lbl_optimal_move.setAlignment(Qt.AlignCenter)
        self.lbl_optimal_move.setStyleSheet("""
            background-color: #161b22;
            border: 2px solid #388bfd;
            border-radius: 8px;
            color: #58a6ff;
            font-size: 20px;
            font-weight: 800;
            padding: 14px;
        """)
        str_layout.addWidget(self.lbl_optimal_move)
        right_layout.addWidget(strat_group)

        # 4. Hi-Lo Card Counter
        count_group = QGroupBox("Hi-Lo Card Counter")
        cg_layout = QVBoxLayout(count_group)

        self.lbl_hilo_readout = QLabel("Running Count: +0   |   True Count: +0.0")
        self.lbl_hilo_readout.setAlignment(Qt.AlignCenter)
        self.lbl_hilo_readout.setStyleSheet("""
            background-color: #121820;
            color: #3fb950;
            font-size: 15px;
            font-weight: 700;
            padding: 8px;
            border-radius: 6px;
        """)
        cg_layout.addWidget(self.lbl_hilo_readout)

        c_ctrl = QHBoxLayout()
        c_ctrl.addWidget(QLabel("Decks remaining:"))
        self.spin_decks = QSpinBox()
        self.spin_decks.setRange(1, 8)
        self.spin_decks.setValue(6)
        self.spin_decks.valueChanged.connect(self.on_decks_changed)
        c_ctrl.addWidget(self.spin_decks)

        btn_reset_count = QPushButton("Reset Counter")
        btn_reset_count.clicked.connect(self.reset_count)
        c_ctrl.addWidget(btn_reset_count)
        cg_layout.addLayout(c_ctrl)

        right_layout.addWidget(count_group)

        # 5. Round & Session Statistics
        stats_group = QGroupBox("Session Statistics")
        st_layout = QVBoxLayout(stats_group)
        self.lbl_stats_summary = QLabel(self.stats.summary())
        self.lbl_stats_summary.setStyleSheet(
            "font-size: 13px; color: #8b949e; padding: 4px;"
        )
        st_layout.addWidget(self.lbl_stats_summary)

        btn_reset_stats = QPushButton("Reset Statistics")
        btn_reset_stats.clicked.connect(self.reset_stats)
        st_layout.addWidget(btn_reset_stats)

        right_layout.addWidget(stats_group)
        right_layout.addStretch()

        main_layout.addWidget(right_panel, 2)

    def init_models(self):
        """Loads default trained model."""
        names = list(self.model_engine.model_paths.keys())
        loaded = False
        for n in names:
            if os.path.exists(self.model_engine.model_paths[n]):
                self.combo_model.setCurrentText(n)
                success, msg = self.model_engine.load_model(n)
                if success:
                    self.lbl_model_status.setText(msg)
                    self.lbl_model_status.setStyleSheet(
                        "color: #3fb950; font-weight: 600;"
                    )
                    loaded = True
                    break
        if not loaded:
            self.lbl_model_status.setText("No model file found!")
            self.lbl_model_status.setStyleSheet("color: #f85149; font-weight: 600;")

    def on_model_changed(self, name):
        success, msg = self.model_engine.load_model(name)
        if success:
            self.lbl_model_status.setText(msg)
            self.lbl_model_status.setStyleSheet("color: #3fb950; font-weight: 600;")
        else:
            self.lbl_model_status.setText(f"Error: {msg}")
            self.lbl_model_status.setStyleSheet("color: #f85149; font-weight: 600;")

    def on_threshold_changed(self):
        conf = self.slider_conf.value() / 100.0
        iou = self.slider_iou.value() / 100.0
        self.lbl_conf_val.setText(f"{self.slider_conf.value()}%")
        self.lbl_iou_val.setText(f"{self.slider_iou.value()}%")
        self.worker.set_thresholds(conf, iou)

    def start_selection(self, target_type):
        if target_type in ["dealer", "player"] and self.feed_bbox is None:
            QMessageBox.information(
                self,
                "Select Video Feed First",
                "Please select the full video feed first (Step 1) so zones can be positioned inside the feed.",
            )
            return

        prompts = {
            "feed": "Step 1: Drag a rectangle around the ENTIRE video feed / table (Press ESC to cancel)",
            "dealer": "Step 2: Drag a rectangle around the DEALER card area (Press ESC to cancel)",
            "player": "Step 3: Drag a rectangle around the PLAYER (your) card area (Press ESC to cancel)",
        }
        self.snipper.start(target_type, prompts.get(target_type, ""))

    def on_snippet_selected(self, bbox, target_type):
        print(f"[Selection] Received {target_type}: {bbox}")
        if target_type == "feed":
            self.feed_bbox = bbox
            self.worker.set_feed_bbox(bbox)
            self.lbl_feed_status.setText(
                f"Feed: {bbox['width']}x{bbox['height']} at ({bbox['left']}, {bbox['top']})"
            )
            self.lbl_feed_status.setStyleSheet(
                "color: #3fb950; font-size: 11px; font-weight: 600;"
            )
            # Clear old sub-zones whenever a new master feed is chosen
            self.reset_zones()
        elif target_type == "dealer":
            if self.feed_bbox:
                # Compute coordinates relative to master feed
                dx1 = max(0, bbox["left"] - self.feed_bbox["left"])
                dy1 = max(0, bbox["top"] - self.feed_bbox["top"])
                dx2 = min(self.feed_bbox["width"], dx1 + bbox["width"])
                dy2 = min(self.feed_bbox["height"], dy1 + bbox["height"])
                if dx2 > dx1 + 10 and dy2 > dy1 + 10:
                    self.dealer_zone = (dx1, dy1, dx2, dy2)
                    self.worker.set_dealer_zone(self.dealer_zone)
                    self.lbl_dealer_status.setText(
                        f"Dealer Zone: Active ({dx2 - dx1}x{dy2 - dy1})"
                    )
                    self.lbl_dealer_status.setStyleSheet(
                        "color: #3fb950; font-size: 11px; font-weight: 600;"
                    )
        elif target_type == "player":
            if self.feed_bbox:
                # Compute coordinates relative to master feed
                px1 = max(0, bbox["left"] - self.feed_bbox["left"])
                py1 = max(0, bbox["top"] - self.feed_bbox["top"])
                px2 = min(self.feed_bbox["width"], px1 + bbox["width"])
                py2 = min(self.feed_bbox["height"], py1 + bbox["height"])
                if px2 > px1 + 10 and py2 > py1 + 10:
                    self.player_zone = (px1, py1, px2, py2)
                    self.worker.set_player_zone(self.player_zone)
                    self.lbl_player_status.setText(
                        f"Player Zone: Active ({px2 - px1}x{py2 - py1})"
                    )
                    self.lbl_player_status.setStyleSheet(
                        "color: #3fb950; font-size: 11px; font-weight: 600;"
                    )

    def reset_zones(self):
        self.dealer_zone = None
        self.player_zone = None
        self.worker.clear_zones()
        self.lbl_dealer_status.setText("Dealer Zone: Not selected")
        self.lbl_dealer_status.setStyleSheet(
            "color: #d29922; font-size: 11px; font-weight: 500;"
        )
        self.lbl_player_status.setText("Player Zone: Not selected")
        self.lbl_player_status.setStyleSheet(
            "color: #58a6ff; font-size: 11px; font-weight: 500;"
        )

    @Slot(dict)
    def on_frame_ready(self, result):
        # 1. Update master video feed preview
        annotated_img = result.get("image")
        if annotated_img is not None:
            self.preview_master.set_image(annotated_img)

        # 2. Update player & dealer hands
        dealer_cards = result.get("dealer_cards", [])
        player_cards = result.get("player_cards", [])
        all_cards = result.get("all_cards", [])

        self.last_dealer_cards = dealer_cards
        self.last_player_cards = player_cards

        # Format display text and evaluated sums
        d_cards_txt, d_sum_txt = format_hand_text(dealer_cards)
        p_cards_txt, p_sum_txt = format_hand_text(player_cards)

        self.lbl_dealer_cards.setText(f"Cards: {d_cards_txt}")
        self.lbl_dealer_sum.setText(f"Total: {d_sum_txt}")

        self.lbl_player_cards.setText(f"Cards: {p_cards_txt}")
        self.lbl_player_sum.setText(f"Total: {p_sum_txt}")

        # 3. Update Hi-Lo card counter with all detected table cards
        try:
            self.counter.update_table(all_cards)
            self.update_counter_ui()
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            print(f"[Counter Error]: {exc}")

        # 4. Update basic strategy recommendation and round evaluation
        try:
            self.update_game_decision()
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            print(f"[Strategy Error]: {exc}")

    def update_game_decision(self):
        valid_dealer = [c for c in self.last_dealer_cards if c != "B"]
        valid_player = [c for c in self.last_player_cards if c != "B"]

        # Evaluate round status (Blackjack, Push, Bust, Win/Lose, etc.)
        round_state, _ = self.strategy.evaluate_round(
            self.last_player_cards, self.last_dealer_cards
        )
        if round_state in ("WIN", "LOSE", "PUSH", "BLACKJACK"):
            self.stats.update(round_state)
            self.lbl_stats_summary.setText(self.stats.summary())

        if not valid_player:
            self.lbl_optimal_move.setText("Waiting for cards...")
            self.lbl_optimal_move.setStyleSheet("""
                background-color: #161b22;
                border: 2px solid #30363d;
                border-radius: 8px;
                color: #8b949e;
                font-size: 18px;
                font-weight: 700;
                padding: 12px;
            """)
            return

        if len(valid_player) < 2:
            p_first = valid_player[0] if valid_player else "-"
            self.lbl_optimal_move.setText(
                f"Player: [{p_first}]\n(Waiting for 2nd card...)"
            )
            self.lbl_optimal_move.setStyleSheet("""
                background-color: #161b22;
                border: 2px solid #58a6ff;
                border-radius: 8px;
                color: #58a6ff;
                font-size: 18px;
                font-weight: 700;
                padding: 12px;
            """)
            return

        dealer_up = valid_dealer[0] if valid_dealer else 10
        move_code, instruction = self.strategy.get_best_move(valid_player, dealer_up)

        # Check Illustrious 18 count-based deviations
        tc = self.counter.true_count
        hints = self.strategy.get_count_hints(valid_player, dealer_up, tc)

        # Recommendation badge coloring
        color = "#58a6ff"
        if "Hit" in instruction or move_code == "H":
            color = "#3fb950"  # Green
        elif "Stand" in instruction or move_code == "S":
            color = "#f85149"  # Red
        elif "Double" in instruction or move_code.startswith("D"):
            color = "#d29922"  # Gold
        elif "Split" in instruction or move_code.startswith("Y"):
            color = "#bc8cff"  # Purple
        elif "Surrender" in instruction or move_code.startswith("SUR"):
            color = "#ff7b72"  # Pink/Red

        display_text = instruction.upper()
        if not valid_dealer:
            display_text += "\n(Note: Dealer card not visible, assuming 10)"
        if hints:
            display_text += f"\n⚡ {hints[0][1]}"

        self.lbl_optimal_move.setText(display_text)
        self.lbl_optimal_move.setStyleSheet(f"""
            background-color: #161b22;
            border: 2px solid {color};
            border-radius: 8px;
            color: {color};
            font-size: 20px;
            font-weight: 800;
            padding: 12px;
        """)

    def on_decks_changed(self, val):
        self.counter.decks = val
        self.update_counter_ui()

    def reset_count(self):
        self.counter.reset()
        self.update_counter_ui()

    def update_counter_ui(self):
        rc = self.counter.running_count
        tc = self.counter.true_count
        seen = self.counter.cards_seen
        sign_rc = f"+{rc}" if rc >= 0 else f"{rc}"
        sign_tc = f"+{tc:.1f}" if tc >= 0 else f"{tc:.1f}"
        self.lbl_hilo_readout.setText(
            f"Running Count: {sign_rc}   |   True Count: {sign_tc}   (Table cards seen: {seen})"
        )

    def reset_stats(self):
        self.stats.reset()
        self.lbl_stats_summary.setText(self.stats.summary())

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = ModernBlackjackApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
