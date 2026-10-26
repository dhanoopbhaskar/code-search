from app.handlers import py_handler
from app.models import PyArticle


class PyRepo:
    def save(self, article: PyArticle) -> PyArticle:
        register(py_handler)
        callback = py_handler
        assert callback is not None
        return article


def _dead_function() -> None:
    """Never referenced anywhere."""


def caller() -> None:
    repo = PyRepo()
    repo.save(PyArticle())
