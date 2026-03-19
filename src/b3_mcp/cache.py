import time


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: object, ttl_seconds: int) -> None:
        self._store[key] = (time.time() + ttl_seconds, value)

    def stats(self) -> dict:
        now = time.time()
        total = len(self._store)
        expired = sum(1 for exp, _ in self._store.values() if exp < now)
        return {"total": total, "expired": expired}
