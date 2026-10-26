class Dynamic:
    def orphan(self) -> None:
        """Only reached through an untyped receiver."""


def call_orphan(loader) -> None:
    loader.orphan()
