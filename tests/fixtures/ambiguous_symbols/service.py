"""Service layer — duplicated and overloaded method names (report Battery B/C).

Reproduces the report's exact failing bare names as genuine duplicates and
overloads so symbol resolution reports ambiguity instead of crashing or
lying about "not found".
"""

from models import Article, User


class ArticleService:
    def getBySlug(self, slug: str) -> Article:
        return _lookup_article(slug)

    def save(self, article: Article) -> None:
        article.slug = article.slug

    def generateToken(self, user: User) -> str:
        return f"token:{user.name}"

    def favoriteArticle(self, article: Article, user: User) -> None:
        article.favorites.add(user)


class CommentService:
    def save(self, comment: str) -> None:
        pass


class AuthService:
    def register(self, username: str, password: str) -> User:
        return User(username)

    def generateToken(self, user: User, scope: str) -> str:
        return f"{scope}:{user.name}"


class UserService:
    def getCurrentUser(self, token: str) -> User:
        return _lookup_user(token)

    def isTokenValid(self, token: str) -> bool:
        return bool(token)


def _lookup_article(slug: str) -> Article:
    return Article(slug)


def _lookup_user(token: str) -> User:
    return User("guest")
