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

if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BASE_DIR

if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
if EXE_DIR not in sys.path:
    sys.path.append(EXE_DIR)

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


def box_overlap_ratio(a, b):
    """
    Overlap between two boxes as a fraction of the SMALLER box's area
    (0.0 = no overlap, 1.0 = smaller box completely covered).
    """
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / min(area_a, area_b)


def group_hands(cards, min_overlap=0.10):
    """
    Group cards into hands (connected components). Two cards belong to the
    same hand only if their overlap EXCEEDS min_overlap (fraction of the
    smaller card's area, e.g. 0.10 = 10%). A single card is also a hand.
    Returns a list of {"cards": [...], "bbox_norm": [...]}.
    """
    n = len(cards)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if box_overlap_ratio(cards[i]["bbox_norm"], cards[j]["bbox_norm"]) > min_overlap:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cards[i])

    hands = []
    for members in groups.values():
        members.sort(key=lambda c: c["bbox_norm"][0])
        hands.append(
            {
                "cards": members,
                "bbox_norm": [
                    min(c["bbox_norm"][0] for c in members),
                    min(c["bbox_norm"][1] for c in members),
                    max(c["bbox_norm"][2] for c in members),
                    max(c["bbox_norm"][3] for c in members),
                ],
            }
        )
    hands.sort(key=lambda h: h["bbox_norm"][0])
    return hands


def point_box_distance(px, py, box):
    """Distance from a point to a box (0 if the point is inside)."""
    x1, y1, x2, y2 = box
    dx = max(x1 - px, 0.0, px - x2)
    dy = max(y1 - py, 0.0, py - y2)
    return (dx * dx + dy * dy) ** 0.5


def box_distance(a, b):
    """
    Euclidean distance between two normalized boxes [x1, y1, x2, y2].
    Returns 0.0 if boxes intersect or touch.
    """
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx * dx + dy * dy) ** 0.5


class BlackjackEngine:
    def __init__(self):
        self.strategy = BlackjackStrategy()
        self.counter = HiLoCounter(decks=6)
        self.stats = RoundStats()
        self.tracker = CardTracker(max_missed=3, iou_thresh=0.30)

        # Load trained blackjack model from models/
        model_path = os.path.join(EXE_DIR, "models", "yolo11m_blackjack_v1.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(BASE_DIR, "models", "yolo11m_blackjack_v1.pt")
        if not os.path.exists(model_path):
            for m_dir in [os.path.join(EXE_DIR, "models"), os.path.join(BASE_DIR, "models")]:
                if os.path.exists(m_dir):
                    candidates = [
                        os.path.join(m_dir, f)
                        for f in sorted(os.listdir(m_dir))
                        if f.endswith(".pt")
                    ]
                    if candidates:
                        model_path = candidates[0]
                        break
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"No trained blackjack model found! Searched: {EXE_DIR}/models and {BASE_DIR}/models"
            )

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        print(f"[Engine] Loading YOLO model: {model_path} on {device}...")
        self.model = YOLO(model_path)
        self.device = device

        self.conf_thresh = 0.35
        self.iou_thresh = 0.50

        # Dealer zone: relative (x1, y1, x2, y2). Player: list of points [[x, y], ...] used to pick hands.
        self.dealer_zone = None
        self.player_points = []
        self.hand_overlap_pct = 15.0  # overlap % that must be exceeded to join a hand
        self.hand_zone_pct = 2.0  # Constant 2% detection zone around player spot
        self.hand_zone_radius = 0.02

        # Last card tracking
        self.last_dealer_cards = []
        self.last_player_cards = []

    def set_zones(self, dealer_zone, player_points, zone_size=None):
        self.dealer_zone = dealer_zone
        self.hand_zone_pct = 2.0
        self.hand_zone_radius = 0.02
        if player_points is None:
            self.player_points = []
        elif isinstance(player_points, list):
            if player_points and isinstance(player_points[0], (int, float)):
                # Single point [x, y]
                self.player_points = [player_points]
            else:
                self.player_points = [
                    p for p in player_points if isinstance(p, (list, tuple)) and len(p) == 2
                ]
        else:
            self.player_points = []
        # Sort left to right so hand 1, hand 2, etc. match visual order
        self.player_points.sort(key=lambda p: p[0])
        self.tracker.reset()

    def set_hand_zone_size(self, pct=2.0):
        self.hand_zone_pct = 2.0
        self.hand_zone_radius = 0.02

    @property
    def player_point(self):
        return self.player_points[0] if self.player_points else None

    def set_thresholds(self, conf, iou):
        self.conf_thresh = conf
        self.iou_thresh = iou

    def reset_counter(self):
        self.counter.reset()
        self.tracker.reset()

    def reset_stats(self):
        self.stats.reset()

    def set_hand_overlap(self, pct):
        self.hand_overlap_pct = max(0.0, min(100.0, float(pct)))

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

        dz_is_norm = self.dealer_zone is not None and max(self.dealer_zone) <= 1.0

        all_candidates = []
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
            all_candidates.append(d)

        # 1. Start with cards directly inside or overlapping the dealer zone box
        dealer_cards = []
        other_cards = []

        for d in all_candidates:
            in_dealer = self._in_zone(
                d["bbox_norm"] if dz_is_norm else d["bbox"], self.dealer_zone
            )
            if in_dealer:
                dealer_cards.append(d)
            else:
                other_cards.append(d)

        # 2. Expand dealer hand: include all cards within < 20% distance (0.20) of any card in the dealer hand
        if dealer_cards and self.dealer_zone:
            max_dealer_dist = 0.20
            expanded = True
            while expanded:
                expanded = False
                for d in list(other_cards):
                    min_dist = min(
                        box_distance(d["bbox_norm"], dc["bbox_norm"])
                        for dc in dealer_cards
                    )
                    cy = (d["bbox_norm"][1] + d["bbox_norm"][3]) / 2.0
                    if min_dist < max_dealer_dist and cy < 0.55:
                        dealer_cards.append(d)
                        other_cards.remove(d)
                        expanded = True

        for d in dealer_cards:
            d["category"] = "dealer"
            d["hand_id"] = "dealer"

        for d in other_cards:
            d["category"] = "table"

        dealer_cards.sort(key=lambda x: x["bbox_norm"][0])
        active_detections = dealer_cards + other_cards

        # Hands = groups of touching cards, everywhere except the dealer zone
        hands = group_hands(other_cards, self.hand_overlap_pct / 100.0)

        # Match each player spot ONLY to hands that fall inside its dedicated zone
        # (prevents grabbing nearest neighbor hands across the table when this seat is empty)
        rx = self.hand_zone_radius
        ry = self.hand_zone_radius * 1.2  # slightly taller for vertical card orientation

        matched_player_hands = []
        matched_hand_ids = set()
        spot_to_hand = {}

        for pt_idx, pt in enumerate(self.player_points):
            px, py = pt
            available_hands = [h for h in hands if id(h) not in matched_hand_ids]
            if not available_hands:
                continue

            candidates = []
            for h in available_hands:
                hx1, hy1, hx2, hy2 = h["bbox_norm"]
                # Distance from spot to hand box
                dx = max(hx1 - px, 0.0, px - hx2)
                dy = max(hy1 - py, 0.0, py - hy2)
                norm_dist = ((dx / rx) ** 2 + (dy / ry) ** 2) ** 0.5

                # Also check individual cards in case bounding box is slightly loose
                min_card_dist = norm_dist
                for c in h["cards"]:
                    cx1, cy1, cx2, cy2 = c["bbox_norm"]
                    cdx = max(cx1 - px, 0.0, px - cx2)
                    cdy = max(cy1 - py, 0.0, py - cy2)
                    c_norm = ((cdx / rx) ** 2 + (cdy / ry) ** 2) ** 0.5
                    if c_norm < min_card_dist:
                        min_card_dist = c_norm

                best_dist = min(norm_dist, min_card_dist)
                # Only hands whose box or cards enter this spot's zone are eligible!
                if best_dist <= 1.0:
                    candidates.append((best_dist, h))

            if candidates:
                candidates.sort(key=lambda x: x[0])
                best_hand = candidates[0][1]
                matched_player_hands.append(best_hand)
                matched_hand_ids.add(id(best_hand))
                spot_to_hand[id(best_hand)] = pt_idx + 1

        # Sort player hands left to right (Hand 1, Hand 2, etc.)
        matched_player_hands.sort(key=lambda h: h["bbox_norm"][0])

        hands_out = []
        for h_idx, h in enumerate(hands):
            is_player = id(h) in matched_hand_ids
            hand_idx = spot_to_hand.get(id(h), (matched_player_hands.index(h) + 1) if is_player else None)
            h_id = f"player_{hand_idx}" if is_player else f"table_{h_idx}"
            for c in h["cards"]:
                c["category"] = "player" if is_player else "table"
                c["hand_id"] = h_id
                c["hand_idx"] = hand_idx

            hands_out.append(
                {
                    "bbox_norm": [round(v, 4) for v in h["bbox_norm"]],
                    "cards": [c["val"] for c in h["cards"]],
                    "is_player": is_player,
                    "hand_idx": hand_idx,
                    "hand_id": h_id,
                }
            )

        table_cards = [c for c in other_cards if c["category"] == "table"]

        all_vals = [d["val"] for d in (dealer_cards + [c for h in matched_player_hands for c in h["cards"]] + table_cards)]
        dealer_vals = [d["val"] for d in dealer_cards]

        # Update card counter with spatial coordinate tracking and delay
        try:
            self.counter.update_spatial(active_detections)
        except Exception as exc:
            print(f"[Counter Exception]: {exc}")

        # Formats for dealer
        d_cards_txt, d_sum_txt = format_hand_text(dealer_vals)
        valid_dealer = [c for c in dealer_vals if c != "B"]
        dealer_up = valid_dealer[0] if valid_dealer else 10
        tc = self.counter.true_count

        # Strategy decision for each player hand
        evaluated_player_hands = []
        for p_hand in matched_player_hands:
            idx = spot_to_hand.get(id(p_hand), matched_player_hands.index(p_hand) + 1)
            p_vals = [c["val"] for c in p_hand["cards"]]
            valid_p = [c for c in p_vals if c != "B"]
            p_txt, s_txt = format_hand_text(p_vals)

            opt_move = "WAITING"
            m_code = ""
            m_instr = "Waiting for cards..."
            m_color = "#8b949e"
            c_hint = None

            if len(valid_p) >= 2:
                m_code, m_instr = self.strategy.get_best_move(valid_p, dealer_up)
                opt_move = m_instr.upper()
                hints = self.strategy.get_count_hints(valid_p, dealer_up, tc)
                if hints:
                    c_hint = hints[0][1]

                if "Hit" in m_instr or m_code == "H":
                    m_color = "#3fb950"  # Green
                elif "Stand" in m_instr or m_code == "S":
                    m_color = "#f85149"  # Red
                elif "Double" in m_instr or m_code.startswith("D"):
                    m_color = "#d29922"  # Gold
                elif "Split" in m_instr or m_code.startswith("Y"):
                    m_color = "#bc8cff"  # Purple
                elif "Surrender" in m_instr or m_code.startswith("SUR"):
                    m_color = "#ff7b72"  # Pink/Red
            elif len(valid_p) == 1:
                m_instr = f"Waiting for 2nd card..."
                opt_move = "WAITING"
                m_color = "#58a6ff"

            r_state, _ = self.strategy.evaluate_round(p_vals, dealer_vals)
            if r_state in ("WIN", "LOSE", "PUSH", "BLACKJACK"):
                self.stats.update(r_state)

            evaluated_player_hands.append({
                "hand_idx": idx,
                "cards": p_vals,
                "text": p_txt,
                "sum": s_txt,
                "optimal_move": opt_move,
                "move_code": m_code,
                "instruction": m_instr,
                "move_color": m_color,
                "count_hint": c_hint,
                "round_state": r_state,
                "bbox_norm": [round(v, 4) for v in p_hand["bbox_norm"]],
            })

        # Summary move for main card
        if len(evaluated_player_hands) == 1:
            h0 = evaluated_player_hands[0]
            optimal_move = h0["optimal_move"]
            move_code = h0["move_code"]
            instruction = h0["instruction"]
            move_color = h0["move_color"]
            count_hint = h0["count_hint"]
            player_vals = h0["cards"]
            p_cards_txt = h0["text"]
            p_sum_txt = h0["sum"]
            round_state = h0["round_state"]
        elif len(evaluated_player_hands) > 1:
            optimal_move = " | ".join(f"H{h['hand_idx']}: {h['optimal_move']}" for h in evaluated_player_hands)
            move_code = ",".join(h["move_code"] for h in evaluated_player_hands)
            instruction = " • ".join(f"H{h['hand_idx']}: {h['instruction']}" for h in evaluated_player_hands)
            move_color = evaluated_player_hands[0]["move_color"]
            count_hint = evaluated_player_hands[0]["count_hint"]
            player_vals = [c for h in evaluated_player_hands for c in h["cards"]]
            p_cards_txt = " | ".join(f"H{h['hand_idx']}: {h['text']}" for h in evaluated_player_hands)
            p_sum_txt = " | ".join(f"H{h['hand_idx']}: {h['sum']}" for h in evaluated_player_hands)
            round_state = evaluated_player_hands[0]["round_state"]
        else:
            optimal_move = "WAITING"
            move_code = ""
            instruction = "Select Player Hands in menu" if not self.player_points else "Waiting for cards..."
            move_color = "#8b949e"
            count_hint = None
            player_vals = []
            p_cards_txt = "-"
            p_sum_txt = "Total: -"
            round_state = "WAITING"

        self.last_dealer_cards = dealer_vals
        self.last_player_cards = player_vals

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
            "player_hands": evaluated_player_hands,
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
            "hand_zone_pct": round(self.hand_zone_pct, 1),
            "detections": active_detections,
            "hands": hands_out,
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
                    pz = data.get("player_points")
                    if pz is None:
                        pz = data.get("player_point")
                    if pz is None:
                        pz = data.get("player_zone")
                    zs = data.get("hand_zone_size") or data.get("zone_size")
                    engine.set_zones(dz, pz, zone_size=zs)
                    print(f"[Engine] Zones set: Dealer={dz}, Player Points={pz}, Hand Zone={engine.hand_zone_pct}%")
                    await websocket.send(
                        json.dumps({"type": "zones_ack", "success": True, "hand_zone_pct": engine.hand_zone_pct})
                    )

                elif action == "set_hand_zone_size":
                    pct = float(data.get("pct", data.get("size", 8.0)))
                    engine.set_hand_zone_size(pct)
                    print(f"[Engine] Hand zone size set: {engine.hand_zone_pct}%")
                    await websocket.send(
                        json.dumps({"type": "hand_zone_size_ack", "pct": engine.hand_zone_pct})
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

                elif action == "set_hand_overlap":
                    pct = float(data.get("pct", 15))
                    engine.set_hand_overlap(pct)
                    await websocket.send(
                        json.dumps({"type": "hand_overlap_ack", "pct": engine.hand_overlap_pct})
                    )

                elif action == "set_decks":
                    decks = int(data.get("decks", 6))
                    engine.set_decks(decks)
                    await websocket.send(
                        json.dumps({"type": "decks_ack", "decks": decks})
                    )

    except websockets.exceptions.ConnectionClosed:
        print(f"[WebSocket] Client disconnected: {client_ip}")


def auto_register_windows_protocol():
    """Silently registers blackjack-pilot:// URI scheme in Windows HKCU registry for 1-click browser launch."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.join(EXE_DIR, "start_server.bat")
        key_path = r"Software\Classes\blackjack-pilot"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Blackjack Pilot Protocol")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe_path}"')
    except Exception:
        pass


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
    auto_register_windows_protocol()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Server] Shutdown requested. Exiting.")
