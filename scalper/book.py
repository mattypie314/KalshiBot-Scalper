"""Order book helpers for Kalshi binary books (yes bids + no bids only)."""

from __future__ import annotations

from dataclasses import dataclass


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class Book:
    yes_bids: list[BookLevel]
    no_bids: list[BookLevel]

    @property
    def yes_bid(self) -> float:
        return self.yes_bids[0].price if self.yes_bids else 0.0

    @property
    def yes_bid_size(self) -> float:
        return self.yes_bids[0].size if self.yes_bids else 0.0

    @property
    def no_bid(self) -> float:
        return self.no_bids[0].price if self.no_bids else 0.0

    @property
    def no_bid_size(self) -> float:
        return self.no_bids[0].size if self.no_bids else 0.0

    @property
    def yes_ask(self) -> float:
        # A no-bid at p is a yes-ask at 1-p.
        return round(1.0 - self.no_bid, 4) if self.no_bids else 1.0

    @property
    def yes_ask_size(self) -> float:
        return self.no_bid_size

    @property
    def spread(self) -> float:
        if not self.yes_bids or not self.no_bids:
            return 1.0
        return max(self.yes_ask - self.yes_bid, 0.0)

    def depth_yes_bid(self, levels: int = 3) -> float:
        return sum(l.size for l in self.yes_bids[:levels])

    def depth_yes_ask(self, levels: int = 3) -> float:
        return sum(l.size for l in self.no_bids[:levels])

    def size_at_or_better_yes_ask(self, limit: float) -> float:
        """Contracts available to buy YES at <= limit (no bids at >= 1-limit)."""
        need = 1.0 - limit
        tot = 0.0
        for lvl in self.no_bids:
            if lvl.price + 1e-9 >= need:
                tot += lvl.size
            else:
                break
        return tot

    def size_at_or_better_yes_bid(self, limit: float) -> float:
        """Contracts available to sell YES at >= limit (yes bids at >= limit)."""
        tot = 0.0
        for lvl in self.yes_bids:
            if lvl.price + 1e-9 >= limit:
                tot += lvl.size
            else:
                break
        return tot


def parse_book(orderbook_fp: dict | None) -> Book:
    raw = orderbook_fp or {}
    yes = [_lvl(p, s) for p, s in reversed(sorted(((_f(a), _f(b)) for a, b in raw.get("yes_dollars") or []), key=lambda x: x[0]))]
    no = [_lvl(p, s) for p, s in reversed(sorted(((_f(a), _f(b)) for a, b in raw.get("no_dollars") or []), key=lambda x: x[0]))]
    return Book(yes_bids=yes, no_bids=no)


def _lvl(price: float, size: float) -> BookLevel:
    return BookLevel(price=price, size=size)


def top_from_market(m: dict) -> Book:
    """Synthesize a one-level book from market snapshot fields when the full book is missing."""
    yb = _f(m.get("yes_bid_dollars"))
    ya = _f(m.get("yes_ask_dollars"))
    ybs = _f(m.get("yes_bid_size_fp"))
    yas = _f(m.get("yes_ask_size_fp"))
    nb = _f(m.get("no_bid_dollars")) or (round(1.0 - ya, 4) if ya else 0.0)
    nbs = yas
    yes = [BookLevel(yb, ybs)] if yb > 0 else []
    no = [BookLevel(nb, nbs)] if nb > 0 else []
    return Book(yes_bids=yes, no_bids=no)
