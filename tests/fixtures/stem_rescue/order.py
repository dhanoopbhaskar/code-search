class OrderService:
    """Tracks customer orders; shares the ``order`` name but defines no
    ``Order`` symbol, so it must never be injected by the stem rescue."""

    def __init__(self) -> None:
        self._items: list[str] = []

    def add(self, item: str) -> None:
        self._items.append(item)
