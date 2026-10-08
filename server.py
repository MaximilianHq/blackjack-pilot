"""
Blackjack Pilot - Local WebSocket AI Engine Server
Provides real-time YOLO11 card detection, Hi-Lo counting, and Basic Strategy
recommendations for the Edge/Chrome extension overlay via WebSocket.
"""

import asyncio
import base64
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
import websockets
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from blackjack_strategy import BlackjackStrategy
from card_counter import HiLoCounter
from main import calculate_hand_value, format_hand_text, map_card_value
from round_stats import RoundStats

HOST = "0.0.0.0"
PORT = 8765


def bbox_iou(b1, b2):
    """Calculates Intersection over Union between two normalized boxes [x1, y1, x2, y2]."""
    x1 = max(b1[0], b2[0])
    y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2])
    y2 = min(b1[3], b2[3])
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter = inter_w * inter_h
    a1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
    a2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0.0 else 0.0


class TrackedCard:
    """Represents a card tracked over consecutive frames with EMA smoothing."""

    def __init__(self, card_id, bbox, bbox_norm, label, val, conf):
        self.id = card_id
        self.bbox = list(bbox)
        self.bbox_norm = list(bbox_norm)
        self.label = label
        self.val = val
        self.conf = conf
        self.hits = 1
        self.missed = 0
        # Confirmed if confidence is high or seen over multiple frames
        self.confirmed = conf >= 0.50

    def update(self, bbox, bbox_norm, label, val, conf, alpha=0.35):
        # Exponential smoothing on bounding boxes to stop jitter
        self.bbox = [
            int(round((1.0 - alpha) * o + alpha * n)) for o, n in zip(self.bbox, bbox)
        ]
        self.bbox_norm = [
            round((1.0 - alpha) * o + alpha * n, 4)
            for o, n in zip(self.bbox_norm, bbox_norm)
        ]
        if conf >= self.conf * 0.9:
            self.label = label
            self.val = val
        self.conf = max(self.conf * 0.9, conf)
        self.hits += 1
        self.missed = 0
        if self.hits >= 2:
            self.confirmed = True


class CardTracker:
    """
    Temporal card tracker that filters out single-frame detection drops,
    stabilizes bounding box positions, and prevents card flickering.
    """

    def __init__(self, max_missed=3, iou_thresh=0.30):
        self.cards = []
        self.next_id = 1
        self.max_missed = max_missed
        self.iou_thresh = iou_thresh
        self.empty_frames = 0

    def reset(self):
        self.cards.clear()
        self.empty_frames = 0

    def update(self, raw_detections):
        if not raw_detections:
            self.empty_frames += 1
            if self.empty_frames >= 3:
                self.cards.clear()
                return []
            for card in self.cards:
                card.missed += 1
            self.cards = [c for c in self.cards if c.missed <= self.max_missed]
            return [c for c in self.cards if c.confirmed]

        self.empty_frames = 0
        matched_indices = set()

        # Match new detections with existing tracked cards
        for card in self.cards:
            best_iou = 0.0
            best_idx = -1
            for idx, det in enumerate(raw_detections):
                if idx in matched_indices:
                    continue
                iou = bbox_iou(card.bbox_norm, det["bbox_norm"])
                if iou > best_iou:
                    best_iou = iou
                    best_idx = idx

            if best_iou >= self.iou_thresh and best_idx >= 0:
                det = raw_detections[best_idx]
                card.update(
                    det["bbox"],
                    det["bbox_norm"],
                    det["label"],
                    det["val"],
                    det["conf"],
                )
                matched_indices.add(best_idx)
            else:
                card.missed += 1

        # Add unmatched new detections as candidates
        for idx, det in enumerate(raw_detections):
            if idx not in matched_indices:
                new_card = TrackedCard(
                    self.next_id,
                    det["bbox"],
                    det["bbox_norm"],
                    det["label"],
                    det["val"],
                    det["conf"],
                )
                self.next_id += 1
                self.cards.append(new_card)

        self.cards = [c for c in self.cards if c.missed <= self.max_missed]
        return [c for c in self.cards if c.confirmed]


class BlackjackEngine:
    def __init__(self):
        self.strategy = BlackjackStrategy()
        self.counter = HiLoCounter(decks=6)
        self.stats = RoundStats()
        self.tracker = CardTracker(max_missed=3, iou_thresh=0.30)

        # Load trained blackjack model from models/
        model_path = os.path.join(BASE_DIR, "models", "yolo11m_blackjack_v1.pt")
        if not os.path.exists(model_path):
            # Look for any custom trained .pt file in models/
            models_dir = os.path.join(BASE_DIR, "models")
            candidates = [
                os.path.join(models_dir, f)
                for f in sorted(os.listdir(models_dir))
                if f.endswith(".pt")
            ]
            if candidates:
                model_path = candidates[0]
            else:
                raise FileNotFoundError(
                    f"No trained blackjack model found in {models_dir}!"
                )

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        print(f"[Engine] Loading YOLO model: {model_path} on {device}...")
        self.model = YOLO(model_path)
        self.device = device

        self.conf_thresh = 0.35
        self.iou_thresh = 0.50

        # Sub-zone relative coordinates: (x1, y1, x2, y2) in 0..1 normalized or absolute px
        self.dealer_zone = None
        self.player_zone = None

        # Last card tracking
        self.last_dealer_cards = []
        self.last_player_cards = []

    def set_zones(self, dealer_zone, player_zone):
        self.dealer_zone = dealer_zone
        self.player_zone = player_zone
        self.tracker.reset()

    def set_thresholds(self, conf, iou):
        self.conf_thresh = conf
        self.iou_thresh = iou

    def reset_counter(self):
        self.counter.reset()
        self.tracker.reset()

    def reset_stats(self):
        self.stats.reset()

    def set_decks(self, decks):
        self.counter.decks = decks

    def _in_zone(self, box, zone):
        if not zone:
            return False
        zx1, zy1, zx2, zy2 = zone
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
            return True

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

    def process_image(self, img_bgr):
        h, w = img_bgr.shape[:2]
        is_1280 = max(h, w) >= 900
        run_imgsz = 1280 if is_1280 else 640

        res = self.model(
            img_bgr,
            imgsz=run_imgsz,
            conf=self.conf_thresh,
            iou=self.iou_thresh,
            verbose=False,
            device=self.device,
        )[0]

        raw_detections = []
        for box in res.boxes:
            c = float(box.conf[0])
            if c < self.conf_thresh:
                continue
            cls_id = int(box.cls[0])
            raw_lbl = self.model.names[cls_id]
            val = map_card_value(raw_lbl)
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            nx1 = round(x1 / w, 4)
            ny1 = round(y1 / h, 4)
            nx2 = round(x2 / w, 4)
            ny2 = round(y2 / h, 4)

            raw_detections.append(
                {
                    "bbox": [x1, y1, x2, y2],
                    "bbox_norm": [nx1, ny1, nx2, ny2],
                    "conf": round(c, 2),
                    "label": raw_lbl,
                    "val": val,
                }
            )

        # Sort raw detections by confidence descending so highest confidence card wins
        raw_detections.sort(key=lambda d: d["conf"], reverse=True)

        # Suppress duplicate cards that are stacked directly on top of each other
        filtered_detections = []
        for det in raw_detections:
            nx1, ny1, nx2, ny2 = det["bbox_norm"]
            cx = (nx1 + nx2) / 2.0
            cy = (ny1 + ny2) / 2.0
            card_w = max(0.01, nx2 - nx1)
            card_h = max(0.01, ny2 - ny1)

            too_close = False
            for kept in filtered_detections:
                knx1, kny1, knx2, kny2 = kept["bbox_norm"]
                kcx = (knx1 + knx2) / 2.0
                kcy = (kny1 + kny2) / 2.0
                k_w = max(0.01, knx2 - knx1)
                k_h = max(0.01, kny2 - kny1)

                avg_w = (card_w + k_w) / 2.0
                avg_h = (card_h + k_h) / 2.0

                # Relative center distance as a fraction of card dimensions
                dist_x = abs(cx - kcx) / avg_w
                dist_y = abs(cy - kcy) / avg_h

                # If centers are closer than 40% of a card's width and height, or IoU > 0.40, they are duplicate predictions
                iou = bbox_iou(det["bbox_norm"], kept["bbox_norm"])
                if (dist_x < 0.40 and dist_y < 0.40) or iou > 0.40:
                    too_close = True
                    break

            if not too_close:
                filtered_detections.append(det)

        # Temporal tracker filters out flickering and stabilizes boxes
        tracked_cards = self.tracker.update(filtered_detections)

        active_detections = []
        dealer_cards = []
        player_cards = []
        table_cards = []

        # Determine if configured zones are normalized (0.0 to 1.0) or absolute px
        dz_is_norm = self.dealer_zone is not None and max(self.dealer_zone) <= 1.0
        pz_is_norm = self.player_zone is not None and max(self.player_zone) <= 1.0

        for card in tracked_cards:
            box_px = card.bbox
            box_norm = card.bbox_norm

            d = {
                "id": card.id,
                "bbox": box_px,
                "bbox_norm": box_norm,
                "conf": round(card.conf, 2),
                "label": card.label,
                "val": card.val,
                "missed": card.missed,
            }

            in_dealer = self._in_zone(
                box_norm if dz_is_norm else box_px, self.dealer_zone
            )
            in_player = self._in_zone(
                box_norm if pz_is_norm else box_px, self.player_zone
            )

            if in_dealer:
                d["category"] = "dealer"
                dealer_cards.append(d)
            elif in_player:
                d["category"] = "player"
                player_cards.append(d)
            else:
                d["category"] = "table"
                table_cards.append(d)

            active_detections.append(d)

        # Sort left to right
        dealer_cards.sort(key=lambda x: x["bbox_norm"][0])
        player_cards.sort(key=lambda x: x["bbox_norm"][0])

        all_vals = [d["val"] for d in (dealer_cards + player_cards + table_cards)]
        dealer_vals = [d["val"] for d in dealer_cards]
        player_vals = [d["val"] for d in player_cards]

        self.last_dealer_cards = dealer_vals
        self.last_player_cards = player_vals

        # Update card counter with spatial coordinate tracking and delay
        try:
            self.counter.update_spatial(active_detections)
        except Exception as exc:
            print(f"[Counter Exception]: {exc}")

        # Formats
        d_cards_txt, d_sum_txt = format_hand_text(dealer_vals)
        p_cards_txt, p_sum_txt = format_hand_text(player_vals)

        # Strategy decision
        valid_dealer = [c for c in dealer_vals if c != "B"]
        valid_player = [c for c in player_vals if c != "B"]

        round_state, _ = self.strategy.evaluate_round(player_vals, dealer_vals)
        if round_state in ("WIN", "LOSE", "PUSH", "BLACKJACK"):
            self.stats.update(round_state)

        optimal_move = "WAITING"
        move_code = ""
        instruction = "Waiting for cards..."
        move_color = "#8b949e"
        count_hint = None

        if valid_player and len(valid_player) >= 2:
            dealer_up = valid_dealer[0] if valid_dealer else 10
            move_code, instruction = self.strategy.get_best_move(
                valid_player, dealer_up
            )
            optimal_move = instruction.upper()

            tc = self.counter.true_count
            hints = self.strategy.get_count_hints(valid_player, dealer_up, tc)
            if hints:
                count_hint = hints[0][1]

            if "Hit" in instruction or move_code == "H":
                move_color = "#3fb950"  # Green
            elif "Stand" in instruction or move_code == "S":
                move_color = "#f85149"  # Red
            elif "Double" in instruction or move_code.startswith("D"):
                move_color = "#d29922"  # Gold
            elif "Split" in instruction or move_code.startswith("Y"):
                move_color = "#bc8cff"  # Purple
            elif "Surrender" in instruction or move_code.startswith("SUR"):
                move_color = "#ff7b72"  # Pink/Red
        elif valid_player and len(valid_player) == 1:
            instruction = f"Player [{valid_player[0]}] - Waiting for 2nd card..."
            optimal_move = "WAITING"
            move_color = "#58a6ff"

        rc = self.counter.running_count
        tc = self.counter.true_count
        sign_rc = f"+{rc}" if rc >= 0 else f"{rc}"
        sign_tc = f"+{tc:.1f}" if tc >= 0 else f"{tc:.1f}"

        return {
            "type": "result",
            "dealer_cards": dealer_vals,
            "dealer_text": d_cards_txt,
            "dealer_sum": d_sum_txt,
            "player_cards": player_vals,
            "player_text": p_cards_txt,
            "player_sum": p_sum_txt,
            "all_cards": all_vals,
            "running_count": sign_rc,
            "true_count": sign_tc,
            "cards_seen": self.counter.cards_seen,
            "decks_remaining": round(self.counter.decks_remaining, 1),
            "optimal_move": optimal_move,
            "move_code": move_code,
            "instruction": instruction,
            "move_color": move_color,
            "count_hint": count_hint,
            "round_state": round_state,
            "stats_summary": self.stats.summary(),
            "wins": self.stats.wins,
            "losses": self.stats.losses,
            "pushes": self.stats.pushes,
            "win_pct": round(self.stats.win_pct, 1),
            "detections": active_detections,
            "width": w,
            "height": h,
        }


engine = None


async def handler(websocket):
    global engine
    client_ip = websocket.remote_address
    print(f"[WebSocket] Client connected: {client_ip}")

    # Send initial state
    await websocket.send(
        json.dumps(
            {
                "type": "status",
                "connected": True,
                "device": engine.device,
                "stats_summary": engine.stats.summary(),
            }
        )
    )

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Binary frame (JPEG / PNG image)
                arr = np.frombuffer(message, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    t0 = time.time()
                    result = engine.process_image(img)
                    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
                    await websocket.send(json.dumps(result))
            else:
                # JSON command
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                action = data.get("action")
                msg_type = data.get("type")
                if action == "frame" or msg_type == "frame":
                    img_data = data.get("image", "")
                    if "," in img_data:
                        img_data = img_data.split(",", 1)[1]
                    try:
                        raw_bytes = base64.b64decode(img_data)
                        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if img is not None:
                            t0 = time.time()
                            result = engine.process_image(img)
                            result["latency_ms"] = round((time.time() - t0) * 1000, 1)
                            await websocket.send(json.dumps(result))
                    except websockets.exceptions.ConnectionClosed:
                        break
                    except Exception as exc:
                        print(f"[Frame Decode Error]: {exc}")
                elif action == "ping":
                    await websocket.send(json.dumps({"type": "pong", "time": time.time()}))
                elif action == "set_zones":
                    dz = data.get("dealer_zone")
                    pz = data.get("player_zone")
                    engine.set_zones(dz, pz)
                    print(f"[Engine] Zones set: Dealer={dz}, Player={pz}")
                    await websocket.send(
                        json.dumps({"type": "zones_ack", "success": True})
                    )

                elif action == "set_thresholds":
                    conf = float(data.get("conf", 0.35))
                    iou = float(data.get("iou", 0.50))
                    engine.set_thresholds(conf, iou)
                    await websocket.send(
                        json.dumps({"type": "thresholds_ack", "conf": conf, "iou": iou})
                    )

                elif action == "reset_counter":
                    engine.reset_counter()
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "counter_reset",
                                "running_count": "+0",
                                "true_count": "+0.0",
                                "cards_seen": 0,
                            }
                        )
                    )

                elif action == "reset_stats":
                    engine.reset_stats()
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "stats_reset",
                                "stats_summary": engine.stats.summary(),
                            }
                        )
                    )

                elif action == "set_decks":
                    decks = int(data.get("decks", 6))
                    engine.set_decks(decks)
                    await websocket.send(
                        json.dumps({"type": "decks_ack", "decks": decks})
                    )

    except websockets.exceptions.ConnectionClosed:
        print(f"[WebSocket] Client disconnected: {client_ip}")


async def main():
    global engine
    engine = BlackjackEngine()
    print(f"\n=======================================================")
    print(f"  Blackjack Pilot - Local WebSocket Server")
    print(f"  Listening on: ws://{HOST}:{PORT}")
    print(f"  Ready to connect with Edge/Chrome Extension!")
    print(f"=======================================================\n")

    async with websockets.serve(handler, HOST, PORT, max_size=10 * 1024 * 1024):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Server] Shutdown requested. Exiting.")
