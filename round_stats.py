class RoundStats:
    """
    Win / loss / push tracker. Fed the evaluated round state every frame; a
    result is recorded once per round, only after it has been stable for
    STABLE_FRAMES frames (guards against one-frame misreads), and the tracker
    re-arms when the table goes back to WAITING / PLAY (next round).
    """

    STABLE_FRAMES = 8
    TERMINAL = ("WIN", "LOSE", "PUSH", "BLACKJACK")

    def __init__(self):
        self.reset()

    def reset(self):
        self.wins = 0
        self.losses = 0
        self.pushes = 0
        self.blackjacks = 0
        self._cand = None
        self._n = 0
        self._recorded = False

    def update(self, state):
        if state in self.TERMINAL:
            if state == self._cand:
                self._n += 1
            else:
                self._cand, self._n = state, 1
            if self._n >= self.STABLE_FRAMES and not self._recorded:
                self._record(state)
                self._recorded = True
            return

        self._cand, self._n = None, 0
        if state in ("WAITING", "PLAY"):
            self._recorded = False

    def _record(self, state):
        if state == "WIN":
            self.wins += 1
        elif state == "BLACKJACK":
            self.wins += 1
            self.blackjacks += 1
        elif state == "LOSE":
            self.losses += 1
        elif state == "PUSH":
            self.pushes += 1

    @property
    def rounds(self):
        return self.wins + self.losses + self.pushes

    @property
    def win_pct(self):
        """Win % of decided rounds (pushes excluded)."""
        decided = self.wins + self.losses
        return 100.0 * self.wins / decided if decided else 0.0

    def summary(self):
        return (
            f"Wins: {self.wins}  Losses: {self.losses}  Pushes: {self.pushes}  "
            f"Win%: {self.win_pct:.1f}%  ({self.rounds} rounds)"
        )
