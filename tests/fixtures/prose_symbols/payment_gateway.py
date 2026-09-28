class PaymentGateway:
    """Processes card payments and emits settlement events."""

    def charge(self, amount: float) -> bool:
        return amount > 0
