"""Test file — reproduces the test-vs-production edge case (FR-005).

Names here mirror production duplicates so the candidate list must surface
both the test-file match and the production matches, distinguished by
``file_path``.
"""


class TestViews:
    def getBySlug(self, slug: str) -> None:
        pass

    def save(self, article: object) -> None:
        pass
