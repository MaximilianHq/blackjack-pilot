import time
import math

class HiLoCounter:
    def __init__(self, decks=6, cooldown_sec=3.0, coord_dist_thresh=0.06):
        self.decks = decks
        self.cooldown_sec = cooldown_sec
        self.coord_dist_thresh = coord_dist_thresh
        self.reset()

    @staticmethod
    def hilo_value(card):
        if card == "A" or card == 10:
            return -1
        if isinstance(card, int) and 2 <= card <= 6:
            return 1
        if isinstance(card, int) and 7 <= card <= 9:
            return 0
        return 0

    def reset(self):
        self.running_count = 0
        self.cards_seen = 0
        self.active_cards = []
        self.cleared_spots = []
        self.history = []

    def update_spatial(self, detections, now=None):
        if now is None:
            now = time.time()

        valid_dets = []
        for det in detections:
            val = det.get("val")
            if val == "B" or val is None:
                continue
            norm = det.get("bbox_norm")
            if not norm or len(norm) != 4:
                continue
            cx = (norm[0] + norm[2]) / 2.0
            cy = (norm[1] + norm[3]) / 2.0
            valid_dets.append({
                "cx": cx,
                "cy": cy,
                "val": val,
                "conf": det.get("conf", 0.5),
            })

        matched_active = set()
        matched_dets = set()

        for d_idx, det in enumerate(valid_dets):
            best_dist = 999.0
            best_a_idx = -1
            for a_idx, ac in enumerate(self.active_cards):
                if a_idx in matched_active:
                    continue
                dist = math.hypot(det["cx"] - ac["cx"], det["cy"] - ac["cy"])
                if dist < self.coord_dist_thresh and dist < best_dist:
                    best_dist = dist
                    best_a_idx = a_idx

            if best_a_idx >= 0:
                matched_active.add(best_a_idx)
                matched_dets.add(d_idx)
                ac = self.active_cards[best_a_idx]
                ac["last_seen"] = now
                ac["cx"] = 0.8 * ac["cx"] + 0.2 * det["cx"]
                ac["cy"] = 0.8 * ac["cy"] + 0.2 * det["cy"]

        for d_idx, det in enumerate(valid_dets):
            if d_idx in matched_dets:
                continue

            cx, cy, val = det["cx"], det["cy"], det["val"]

            was_cleared_recently = False
            for cs in self.cleared_spots:
                dist = math.hypot(cx - cs["cx"], cy - cs["cy"])
                if dist < self.coord_dist_thresh:
                    if (now - cs["cleared_at"]) < self.cooldown_sec:
                        was_cleared_recently = True
                        break

            if was_cleared_recently:
                continue

            hilo = self.hilo_value(val)
            self.running_count += hilo
            self.cards_seen += 1
            new_card_entry = {
                "cx": cx,
                "cy": cy,
                "val": val,
                "first_seen": now,
                "last_seen": now,
            }
            self.active_cards.append(new_card_entry)
            self.history.append((now, val, hilo, cx, cy))

        remaining_active = []
        for ac in self.active_cards:
            if (now - ac["last_seen"]) > 1.8:
                self.cleared_spots.append({
                    "cx": ac["cx"],
                    "cy": ac["cy"],
                    "cleared_at": now,
                })
            else:
                remaining_active.append(ac)
        self.active_cards = remaining_active

        self.cleared_spots = [
            cs for cs in self.cleared_spots if (now - cs["cleared_at"]) < 20.0
        ]

    @property
    def decks_remaining(self):
        return max(0.5, self.decks - (self.cards_seen / 52.0))

    @property
    def true_count(self):
        return self.running_count / self.decks_remaining

# Test simulation
c = HiLoCounter(decks=6, cooldown_sec=3.0)

# Frame 1: 10 dealt at (0.40, 0.50)
c.update_spatial([{"val": 10, "bbox_norm": [0.35, 0.45, 0.45, 0.55]}], now=100.0)
assert c.cards_seen == 1
assert c.running_count == -1

# Frame 2: Same 10 at (0.40, 0.50) 100ms later -> NOT COUNTED TWICE
c.update_spatial([{"val": 10, "bbox_norm": [0.35, 0.45, 0.45, 0.55]}], now=100.1)
assert c.cards_seen == 1
assert c.running_count == -1

# Frame 3: 5 dealt at (0.60, 0.70) 500ms later -> COUNTED ONCE
c.update_spatial([
    {"val": 10, "bbox_norm": [0.35, 0.45, 0.45, 0.55]},
    {"val": 5, "bbox_norm": [0.55, 0.65, 0.65, 0.75]},
], now=100.6)
assert c.cards_seen == 2
assert c.running_count == 0

# Cards disappear (round sweep) at t=102.0
c.update_spatial([], now=102.0)
# At t=103.0 (> 1.8s since 100.6) -> cards swept into cleared_spots with cleared_at=103.0
c.update_spatial([], now=103.0)
assert len(c.active_cards) == 0
assert len(c.cleared_spots) == 2
assert c.cards_seen == 2

# At t=104.5 (1.5s after sweep, < 3.0s cooldown), ghost flicker at (0.40, 0.50) -> BLOCKED BY COOLDOWN!
c.update_spatial([{"val": 10, "bbox_norm": [0.35, 0.45, 0.45, 0.55]}], now=104.5)
assert c.cards_seen == 2, f"Expected 2 (blocked by cooldown), got {c.cards_seen}"

# At t=107.0 (> 3.0s cooldown since cleared_at=103.0), new round card 6 dealt at (0.40, 0.50) -> COUNTED!
c.update_spatial([{"val": 6, "bbox_norm": [0.35, 0.45, 0.45, 0.55]}], now=107.0)
assert c.cards_seen == 3
assert c.running_count == 1
print("ALL TESTS PASSED PERFECTLY!")

