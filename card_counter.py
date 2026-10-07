class HiLoCounter:
    """
    Hi-Lo card counter fed with every live frame.

    When a full-table region is provided, it tracks cards across the entire
    table (all players + dealer).
    Frames repeat the same cards many times, so each round's cards are tracked
    as the "peak" (largest set) seen. The round is committed to the running
    count once the table clears / a new deal appears.
    """

    CLEAR_FRAMES = 12  # table empty this many frames -> round over
    DROP_FRAMES = 8  # fewer cards than peak this many frames -> new round

    def __init__(self, decks=6):
        self.decks = decks
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
        return self.committed_count + sum(
            self.hilo_value(c) for c in self.current_round_cards
        )

    @property
    def cards_seen(self):
        return self.committed_cards + len(self.current_round_cards)

    @property
    def decks_remaining(self):
        return max(0.5, self.decks - self.cards_seen / 52.0)

    @property
    def true_count(self):
        return self.running_count / self.decks_remaining
