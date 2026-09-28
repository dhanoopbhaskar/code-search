"""Domain models — a model-level method shares its name with controllers."""


class User:
    def __init__(self, name: str) -> None:
        self.name = name


class Article:
    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.favorites = set()

    def favoriteArticle(self, user: User) -> None:
        self.favorites.add(user)
