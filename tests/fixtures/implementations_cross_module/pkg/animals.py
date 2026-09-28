"""Base module for the cross-module implementation fixture."""


class Zebra:
    """Interface-shaped base declared in a different module."""

    def trot(self, pace):
        raise NotImplementedError
