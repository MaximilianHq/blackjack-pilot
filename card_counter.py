import time
import math


class HiLoCounter:
    """
    Spatial & Temporal Hi-Lo card counter.
    Tracks each card's coordinates to prevent counting the same card twice.
    Enforces a cooldown delay before allowing a new card count at the same coordinates.
    """

    CLEAR_FRAMES = 12  # table empty this many frames -> round over
    DROP_FRAMES = 8  # fewer cards than peak this many frames -> new round

    def __init__(self, decks=6, cooldown_sec=3.0, coord_dist_thresh=0.06):
        self.decks = decks
        self.cooldown_sec = cooldown_sec  # Cooldown delay before counting another card at the same spot
        self.coord_dist_thresh = coord_dist_thresh  # Center distance threshold (~6% of feed width/height)
        self.reset()

    @staticmethod
    def hilo_value(card):
        if card == "A" or card == 10:
            return -1
        if isinstance(card, int) and 2 <= card <= 6:
            return 1
        if isinstance(card, int) and 7 <= card <= 9:
            return 0
        return 0  # 'B' / unknown

    def reset(self):
        self.committed_count = 0
        self.committed_cards = 0
        self.peak_player = []
        self.peak_dealer = []
        self.peak_cards = []
        self._clear_frames = 0
        self._drop_frames = 0

        # Spatial tracking attributes
        self.spatial_running_count = 0
        self.spatial_cards_seen = 0
        self.active_cards = []
        self.cleared_spots = []
        self.history = []

    def update_spatial(self, detections, now=None):
        """
        Deduplicates cards by spatial coordinates and delays so the same card
        is never counted twice at the same coordinates.
        """
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
                # SAME CARD AT SAME COORDINATES:
                # Do NOT count again! Update position and timestamp
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

            # NEW GENUINE CARD COUNTED AT COORDINATES (cx, cy)!
            hilo = self.hilo_value(val)
            self.spatial_running_count += hilo
            self.spatial_cards_seen += 1
            new_card_entry = {
                "cx": cx,
                "cy": cy,
                "val": val,
                "first_seen": now,
                "last_seen": now,
            }
            self.active_cards.append(new_card_entry)
            self.history.append((now, val, hilo, cx, cy))
            print(f"[HiLoCounter] Counted card {val} (HiLo: {hilo:+d}) at ({cx:.2f}, {cy:.2f}) -> RC: {self.spatial_running_count:+d}, Seen: {self.spatial_cards_seen}")

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

    def _commit_table(self):
        for c in self.peak_cards:
            self.committed_count += self.hilo_value(c)
            self.committed_cards += 1
        self.peak_cards = []

    def update_table(self, table_cards):
        """Feed cards detected across the full table area."""
        cards = [c for c in table_cards if c != "B"]
        now = len(cards)

        if now == 0:
            self._clear_frames += 1
            self._drop_frames = 0
            if self._clear_frames >= self.CLEAR_FRAMES and len(self.peak_cards) > 0:
                self._commit_table()
            return

        self._clear_frames = 0

        # New deal detected if card count drops significantly from peak to initial deal
        if len(self.peak_cards) >= 4 and now < len(self.peak_cards) and now <= 3:
            self._drop_frames += 1
            if self._drop_frames >= self.DROP_FRAMES:
                self._commit_table()
                self._drop_frames = 0
                self.peak_cards = list(cards)
            return
        self._drop_frames = 0

        if len(cards) >= len(self.peak_cards):
            self.peak_cards = list(cards)

    def _peak_total(self):
        return len(self.peak_player) + len(self.peak_dealer)

    def _commit_two(self):
        for c in self.peak_player + self.peak_dealer:
            self.committed_count += self.hilo_value(c)
            self.committed_cards += 1
        self.peak_player = []
        self.peak_dealer = []

    def update(self, player_cards, dealer_cards):
        """Fallback: feed cards from player and dealer regions only."""
        p = [c for c in player_cards if c != "B"]
        d = [c for c in dealer_cards if c != "B"]
        now = len(p) + len(d)

        if now == 0:
            self._clear_frames += 1
            self._drop_frames = 0
            if self._clear_frames >= self.CLEAR_FRAMES and self._peak_total() > 0:
                self._commit_two()
            return

        self._clear_frames = 0

        if self._peak_total() >= 4 and now < self._peak_total() and now <= 3:
            self._drop_frames += 1
            if self._drop_frames >= self.DROP_FRAMES:
                self._commit_two()
                self._drop_frames = 0
                self.peak_player = list(p)
                self.peak_dealer = list(d)
            return
        self._drop_frames = 0

        if len(p) >= len(self.peak_player):
            self.peak_player = list(p)
        if len(d) >= len(self.peak_dealer):
            self.peak_dealer = list(d)

    @property
    def current_round_cards(self):
        if self.peak_cards:
            return self.peak_cards
        return self.peak_player + self.peak_dealer

    @property
    def running_count(self):
        if self.spatial_cards_seen > 0 or len(self.active_cards) > 0 or len(self.cleared_spots) > 0:
            return self.spatial_running_count
        return self.committed_count + sum(
            self.hilo_value(c) for c in self.current_round_cards
        )

    @property
    def cards_seen(self):
        if self.spatial_cards_seen > 0 or len(self.active_cards) > 0 or len(self.cleared_spots) > 0:
            return self.spatial_cards_seen
        return self.committed_cards + len(self.current_round_cards)

    @property
    def decks_remaining(self):
        return max(0.5, self.decks - self.cards_seen / 52.0)

    @property
    def true_count(self):
        return self.running_count / self.decks_remaining
