"""Implementer module for the cross-module implementation fixture."""

from pkg.animals import Zebra


class PlainsZebra(Zebra):
    """Direct implementer reached across a module boundary."""

    def trot(self, pace):
        return pace
