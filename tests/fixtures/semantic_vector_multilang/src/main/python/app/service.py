class OrderService:
    class Inner:
        def persist(self) -> str:
            return "stored"

    def save(self, order: str) -> str:
        return order


def free_helper(value: int) -> int:
    return value + 1
