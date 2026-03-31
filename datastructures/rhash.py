from typing import Optional, Dict, List, Tuple
import re

class RedisHash:
    def __init__(self):
        self._data: Dict[str, str] = {}

    def hset(self, *field_value_pairs) -> int:
        """Set field-value pairs, return count of new fields."""
        if len(field_value_pairs) % 2 != 0:
            raise ValueError("Field-value pairs must come in pairs")
        added = 0
        for i in range(0, len(field_value_pairs), 2):
            field, value = field_value_pairs[i], field_value_pairs[i + 1]
            if field not in self._data:
                added += 1
            self._data[field] = value
        return added

    def hget(self, field: str) -> Optional[str]:
        return self._data.get(field)

    def hdel(self, *fields: str) -> int:
        deleted = 0
        for field in fields:
            if field in self._data:
                del self._data[field]
                deleted += 1
        return deleted

    def hexists(self, field: str) -> bool:
        return field in self._data

    def hgetall(self) -> Dict[str, str]:
        return dict(self._data)

    def hkeys(self) -> List[str]:
        return list(self._data.keys())

    def hvals(self) -> List[str]:
        return list(self._data.values())

    def hlen(self) -> int:
        return len(self._data)

    def hincrby(self, field: str, amount: int) -> int:
        """Increment field by integer amount."""
        current = int(self._data.get(field, "0"))
        current += amount
        self._data[field] = str(current)
        return current

    def hincrbyfloat(self, field: str, amount: float) -> float:
        """Increment field by float amount."""
        current = float(self._data.get(field, "0"))
        current += amount
        self._data[field] = str(current)
        return current

    def hscan(self, cursor: int = 0, pattern: str = "*", count: int = 10) -> Tuple[int, Dict[str, str]]:
        keys = list(self._data.keys())
        # convert glob pattern to regex
        regex = re.compile("^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$")
        result: Dict[str, str] = {}
        scanned = 0
        i = cursor
        while scanned < count and i < len(keys):
            key = keys[i]
            if regex.match(key):
                result[key] = self._data[key]
                scanned += 1
            i += 1
        next_cursor = i if i < len(keys) else 0
        return next_cursor, result