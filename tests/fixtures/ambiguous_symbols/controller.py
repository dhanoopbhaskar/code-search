"""Web controllers — duplicated method names alongside the service layer."""

from models import Article, User
from service import ArticleService, AuthService, UserService


class ArticleController:
    def __init__(self) -> None:
        self.articleService = ArticleService()

    def getBySlug(self, slug: str) -> Article:
        return self.articleService.getBySlug(slug)

    def save(self, article: Article) -> None:
        self.articleService.save(article)

    def favoriteArticle(self, article: Article, user: User) -> None:
        self.articleService.favoriteArticle(article, user)


class AuthController:
    def __init__(self) -> None:
        self.authService = AuthService()

    def register(self, username: str, password: str) -> str:
        user = self.authService.register(username, password)
        return user.name


class UserController:
    def __init__(self) -> None:
        self.userService = UserService()

    def getCurrentUser(self, token: str) -> User:
        return self.userService.getCurrentUser(token)
