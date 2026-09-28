"""Interface/implementation fixture shapes for Python."""

from abc import ABC, abstractmethod


class Animal(ABC):
    """Interface-shaped base with one method."""

    @abstractmethod
    def speak(self, sound): ...


class Dog(Animal):
    """Direct implementer that declares the method itself."""

    def speak(self, sound):
        return sound


class AbstractPet(Animal):
    """Concrete base that provides the method for its subclasses."""

    def speak(self, sound):
        return sound


class Puppy(AbstractPet):
    """Inherits the method from AbstractPet rather than declaring it."""


class Pet(Animal):
    """Sub-interface that re-declares the method for its implementers."""

    @abstractmethod
    def speak(self, sound): ...


class Cat(Pet):
    """Indirect implementer reached through the Pet sub-interface."""

    def speak(self, sound):
        return sound


class Repository(ABC):
    """Interface with no static implementer."""

    @abstractmethod
    def find(self, key): ...


class Alpha(ABC):
    """First interface of the ambiguous same-name pair."""

    @abstractmethod
    def handle(self): ...


class Beta(ABC):
    """Second interface of the ambiguous same-name pair."""

    @abstractmethod
    def handle(self): ...


class Multi(Alpha, Beta):
    """Class implementing several interfaces at once."""

    def handle(self):
        return 1
