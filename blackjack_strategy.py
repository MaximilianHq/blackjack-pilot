from typing import ClassVar


class BlackjackStrategy:
    def __init__(self):
        # Dealer upcards are integers 2-10 or the string 'A'

        # Late Surrender Table (Overrides standard moves)
        self.surrender = {
            16: {
                2: "",
                3: "",
                4: "",
                5: "",
                6: "",
                7: "",
                8: "",
                9: "SUR",
                10: "SUR",
                "A": "SUR",
            },
            15: {
                2: "",
                3: "",
                4: "",
                5: "",
                6: "",
                7: "",
                8: "",
                9: "",
                10: "SUR",
                "A": "",
            },
        }

        # Pair Splitting Table (Used when player has exactly two identical cards)
        self.splits = {
            "A": {
                2: "Y",
                3: "Y",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "Y",
                8: "Y",
                9: "Y",
                10: "Y",
                "A": "Y",
            },
            10: {
                2: "N",
                3: "N",
                4: "N",
                5: "N",
                6: "N",
                7: "N",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            9: {
                2: "Y",
                3: "Y",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "N",
                8: "Y",
                9: "Y",
                10: "N",
                "A": "N",
            },
            8: {
                2: "Y",
                3: "Y",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "Y",
                8: "Y",
                9: "Y",
                10: "Y",
                "A": "Y",
            },
            7: {
                2: "Y",
                3: "Y",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "Y",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            6: {
                2: "Y/N",
                3: "Y",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "N",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            5: {
                2: "N",
                3: "N",
                4: "N",
                5: "N",
                6: "N",
                7: "N",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            4: {
                2: "N",
                3: "N",
                4: "N",
                5: "Y/N",
                6: "Y/N",
                7: "N",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            3: {
                2: "Y/N",
                3: "Y/N",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "Y",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
            2: {
                2: "Y/N",
                3: "Y/N",
                4: "Y",
                5: "Y",
                6: "Y",
                7: "Y",
                8: "N",
                9: "N",
                10: "N",
                "A": "N",
            },
        }

        # Soft Totals Table (Used when hand contains an Ace counted as 11)
        self.soft = {
            20: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "S",
                8: "S",
                9: "S",
                10: "S",
                "A": "S",
            },  # A,9
            19: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "Ds",
                7: "S",
                8: "S",
                9: "S",
                10: "S",
                "A": "S",
            },  # A,8
            18: {
                2: "Ds",
                3: "Ds",
                4: "Ds",
                5: "Ds",
                6: "Ds",
                7: "S",
                8: "S",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,7
            17: {
                2: "H",
                3: "D",
                4: "D",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,6
            16: {
                2: "H",
                3: "H",
                4: "D",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,5
            15: {
                2: "H",
                3: "H",
                4: "D",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,4
            14: {
                2: "H",
                3: "H",
                4: "H",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,3
            13: {
                2: "H",
                3: "H",
                4: "H",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # A,2
        }

        # Hard Totals Table
        self.hard = {
            17: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "S",
                8: "S",
                9: "S",
                10: "S",
                "A": "S",
            },  # 17+
            16: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            15: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            14: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            13: {
                2: "S",
                3: "S",
                4: "S",
                5: "S",
                6: "S",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            12: {
                2: "H",
                3: "H",
                4: "S",
                5: "S",
                6: "S",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            11: {
                2: "D",
                3: "D",
                4: "D",
                5: "D",
                6: "D",
                7: "D",
                8: "D",
                9: "D",
                10: "D",
                "A": "D",
            },
            10: {
                2: "D",
                3: "D",
                4: "D",
                5: "D",
                6: "D",
                7: "D",
                8: "D",
                9: "D",
                10: "H",
                "A": "H",
            },
            9: {
                2: "H",
                3: "D",
                4: "D",
                5: "D",
                6: "D",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },
            8: {
                2: "H",
                3: "H",
                4: "H",
                5: "H",
                6: "H",
                7: "H",
                8: "H",
                9: "H",
                10: "H",
                "A": "H",
            },  # 8 or less
        }

        # Key Legend mapping codes to human-readable instructions
        self.legend = {
            "H": "Hit",
            "S": "Stand",
            "D": "Double if allowed, otherwise hit",
            "Ds": "Double if allowed, otherwise stand",
            "Y": "Split the Pair",
            "Y/N": 'Split if "Double After Split (DAS)" is offered, otherwise do not split',
            "N": "Don't Split the Pair",
            "SUR": "Surrender",
        }

    @staticmethod
    def _norm(card):
        """Normalize a card to 'A' or an int 2-10 (J/Q/K -> 10)."""
        if isinstance(card, str):
            c = card.strip().upper()
            if c == "A":
                return "A"
            if c in ("J", "Q", "K"):
                return 10
            return int(c)
        return int(card)

    def _calculate_total(self, cards):
        total = 0
        aces = 0
        for card in cards:
            card = self._norm(card)
            if card == "A":
                total += 11
                aces += 1
            else:
                total += card

        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        is_soft = aces > 0 and total <= 21
        return total, is_soft

    def evaluate_round(self, player_cards, dealer_cards):
        """
        Follows the real game order. Cards may contain 'B' (face-down).
        returns: (state, message) where state is one of:
        WAITING, BLACKJACK, PUSH, WIN, LOSE, DEALER_TURN, PLAY
        """
        p = [c for c in player_cards if c != "B"]
        d = [c for c in dealer_cards if c != "B"]
        hole_hidden = "B" in dealer_cards or len(d) == 1

        if len(p) < 2 or len(d) < 1:
            return "WAITING", "Waiting for cards..."

        try:
            p_total, _ = self._calculate_total(p)
            d_total, _ = self._calculate_total(d)
        except (ValueError, TypeError):
            return "WAITING", "Unreadable card, waiting..."

        d_natural = len(d) == 2 and d_total == 21

        # 1. Natural blackjack (two cards, 21)
        if len(p) == 2 and p_total == 21:
            if d_natural:
                return "PUSH", "Both have Blackjack - PUSH"
            if hole_hidden and self._norm(d[0]) in (10, "A"):
                return (
                    "BLACKJACK_PENDING",
                    "BLACKJACK! (waiting for dealer's hole card)",
                )
            return "BLACKJACK", "BLACKJACK! You win 3:2"

        # 2. Player bust - dealer irrelevant
        if p_total > 21:
            return "LOSE", f"BUST ({p_total}) - You lose"

        # 3. Player still deciding (under 21, dealer hole card still hidden)
        if p_total < 21 and hole_hidden:
            return "PLAY", None

        # 4. Player stands at 21 (auto-stand) but dealer not revealed yet
        if hole_hidden:
            return "STAND_21", "21 - Stand! Dealer's turn..."

        # 5. Dealer revealed: dealer plays
        if d_total > 21:
            return "WIN", f"Dealer BUST ({d_total}) - You WIN!"
        if d_total < 17:
            # Dealer is playing out their hand, so the player has already stood
            return "DEALER_TURN", f"Dealer has {d_total}, must draw..."

        # 6. Showdown
        if p_total > d_total:
            return "WIN", f"You WIN! {p_total} vs {d_total}"
        if p_total < d_total:
            return "LOSE", f"You lose. {p_total} vs {d_total}"
        return "PUSH", f"PUSH. {p_total} vs {d_total}"

    def get_best_move(self, player_cards, dealer_upcard):
        """
        player_cards: list of detected cards, e.g., ['A', 8] or [10, 10]
        dealer_upcard: single value, e.g., 9 or 'A'
        returns: (move_code, full_instruction)
        """
        if isinstance(dealer_upcard, (list, tuple)):
            dealer_upcard = dealer_upcard[0]
        dealer = self._norm(dealer_upcard)

        player_cards = [self._norm(c) for c in player_cards]
        total, is_soft = self._calculate_total(player_cards)

        # Game-engine states the strategy must not answer
        if total > 21:
            return "BUST", "Bust"
        if total == 21:
            return "S", "Stand (21)"

        move_code = None
        surrender_code = None

        # 1. Check Surrender first (only valid on first two cards usually, applied to 15 and 16)[cite: 1]
        if len(player_cards) == 2 and total in self.surrender:
            surrender_code = self.surrender[total].get(dealer, "")

        # 2. Check Pairs[cite: 1]
        if len(player_cards) == 2 and player_cards[0] == player_cards[1]:
            pair_card = "A" if player_cards[0] == "A" else int(player_cards[0])
            split_move = self.splits.get(pair_card, {}).get(dealer, "N")

            # If the chart says 'N', we bypass returning the split string and fall back to hard/soft totals
            if split_move != "N":
                move_code = split_move

        # 3. Check Soft Totals[cite: 1]
        if not move_code and is_soft:
            lookup_total = min(total, 20)  # Cap at 20 (A,9)
            move_code = self.soft.get(lookup_total, {}).get(dealer, "S")

        # 4. Check Hard Totals[cite: 1]
        if not move_code:
            lookup_total = max(8, min(total, 17))  # Floor at 8, Cap at 17
            move_code = self.hard.get(lookup_total, {}).get(dealer, "S")

        # 5. Format Output
        # Doubling is only possible on the first two cards
        if len(player_cards) > 2:
            if move_code == "D":
                move_code = "H"
            elif move_code == "Ds":
                move_code = "S"
        final_instruction = self.legend.get(move_code, move_code)

        if surrender_code == "SUR":
            return (
                f"SUR + {move_code}",
                f"Surrender if allowed. Otherwise: {final_instruction}",
            )

        return move_code, final_instruction

    # ------------------------------------------------------------------
    # Hi-Lo count based hints
    # ------------------------------------------------------------------
    DEALER_ORDER: ClassVar[list[int | str]] = [2, 3, 4, 5, 6, 7, 8, 9, 10, "A"]

    # (hard total, dealer upcard): (operator, index, action)
    # Active when true count satisfies the operator against the index.
    # Based on the commonly used Hi-Lo "Illustrious 18" / Fab 4 indices.
    HARD_DEVIATIONS: ClassVar[dict[tuple[int, int | str], tuple[str, int, str]]] = {
        (16, 10): (">=", 0, "Stand"),
        (16, 9): (">=", 5, "Stand"),
        (15, 10): (">=", 4, "Stand"),
        (12, 2): (">=", 3, "Stand"),
        (12, 3): (">=", 2, "Stand"),
        (13, 2): ("<", -1, "Hit"),
        (13, 3): ("<", -2, "Hit"),
        (12, 4): ("<", 0, "Hit"),
        (12, 5): ("<", -2, "Hit"),
        (12, 6): ("<", -1, "Hit"),
        (10, 10): (">=", 4, "Double"),
        (10, "A"): (">=", 4, "Double"),
        (9, 2): (">=", 1, "Double"),
        (9, 7): (">=", 3, "Double"),
        (8, 6): (">=", 2, "Double"),
    }
    # (pair card, dealer upcard): (operator, index, action)
    PAIR_DEVIATIONS: ClassVar[dict[tuple[int, int], tuple[str, int, str]]] = {
        (10, 5): (">=", 5, "Split"),
        (10, 6): (">=", 4, "Split"),
    }

    @staticmethod
    def _short_move(code):
        return code.replace("SUR + ", "").strip()

    def get_borderline(self, player_cards, dealer_upcard):
        """
        If the neighbouring dealer upcards (one lower / one higher) give a
        different chart answer for this same hand, the hand sits on an edge of
        the chart. returns a list like [(7, 'H')] (empty if not borderline).
        """
        if isinstance(dealer_upcard, (list, tuple)):
            dealer_upcard = dealer_upcard[0]
        dealer = self._norm(dealer_upcard)
        if dealer not in self.DEALER_ORDER:
            return []
        i = self.DEALER_ORDER.index(dealer)
        here, _ = self.get_best_move(player_cards, dealer)
        diffs = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.DEALER_ORDER):
                other = self.DEALER_ORDER[j]
                code, _ = self.get_best_move(player_cards, other)
                if self._short_move(code) != self._short_move(here):
                    diffs.append((other, self._short_move(code)))
        return diffs

    def get_count_hints(self, player_cards, dealer_upcard, true_count):
        """
        returns a list of (level, text). level: 'alert' (count says deviate),
        'warn' (near an index / borderline hand), 'info'.
        """
        hints = []
        if isinstance(dealer_upcard, (list, tuple)):
            dealer_upcard = dealer_upcard[0]
        dealer = self._norm(dealer_upcard)
        cards = [self._norm(c) for c in player_cards]
        total, is_soft = self._calculate_total(cards)
        if total >= 21:
            return hints

        base_code, _ = self.get_best_move(cards, dealer)
        base = self._short_move(base_code)

        # Insurance
        if dealer == "A" and len(cards) == 2 and true_count >= 3:
            hints.append(("alert", f"Count TC {true_count:+.1f} >= +3: take INSURANCE"))

        # Index deviation
        entry = None
        if len(cards) == 2 and cards[0] == cards[1] and cards[0] != "A":
            entry = self.PAIR_DEVIATIONS.get((cards[0], dealer))
        if entry is None and not is_soft and not base.startswith("Y"):
            entry = self.HARD_DEVIATIONS.get((total, dealer))
            if entry and entry[2] == "Double" and len(cards) != 2:
                entry = None

        if entry:
            op, idx, action = entry
            active = true_count >= idx if op == ">=" else true_count < idx
            close = abs(true_count - idx) <= 1
            idx_txt = f"TC {op} {idx:+d}"
            if active:
                hints.append(
                    (
                        "alert",
                        f"COUNT SAYS: {action} instead (index {idx_txt}, now {true_count:+.1f})",
                    )
                )
            elif close:
                hints.append(
                    (
                        "warn",
                        f"Close to deviation: {action} at {idx_txt} (now {true_count:+.1f})",
                    )
                )

        # Borderline hand (neighbouring dealer upcards disagree with the chart)
        border = self.get_borderline(cards, dealer)
        if border and not any(lvl == "alert" for lvl, _ in hints):
            nb = ", ".join(f"vs {u}: {m}" for u, m in border)
            hints.append(
                (
                    "warn",
                    f"Borderline hand ({nb}). Check count TC {true_count:+.1f} (high = stand/double/split, low = hit)",
                )
            )
        return hints
