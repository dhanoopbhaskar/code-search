import datetime
import hashlib
import uuid


class UserProfile:
    # Unique identifier assigned on creation.
    user_id = None
    # Display name shown to other users.
    name = None

    def display_name(self) -> str:
        return self.name

    def describe(self) -> str:
        trigger()
        cache = build()
        return f"UserProfile({self.user_id}, {self.name})"
