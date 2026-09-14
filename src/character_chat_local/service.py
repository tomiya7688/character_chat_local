from __future__ import annotations

from .storage import Storage


class ChatService:
    def __init__(self, storage: Storage):
        self.storage = storage
