import time
import fnmatch
from enum import Enum
from typing import Optional, Any, Callable


class ValueType(Enum):
    STRING = "string"
    LIST = "list"
    HASH = "hash"
    SET = "set"
    SORTED_SET = "zset"
    STREAM = "stream"


class WrongTypeError(Exception):
    def __init__(self):
        super().__init__(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )


class ValueEntry:
    # wraps a value with its type + expiry info
    def __init__(self, value: Any, value_type: ValueType):
        self._value = value
        self._type = value_type
        self._created_at: float = time.time()
        self._expires_at: Optional[float] = None

    @property
    def value(self) -> Any:
        return self._value

    @property
    def type(self) -> ValueType:
        return self._type

    @property
    def created_at(self) -> float:
        return self._created_at

    @property
    def expires_at(self) -> Optional[float]:
        return self._expires_at

    @expires_at.setter
    def expires_at(self, timestamp: Optional[float]) -> None:
        self._expires_at = timestamp

    def is_expired(self) -> bool:
        if self._expires_at is None:
            return False
        return time.time() > self._expires_at

    @property
    def ttl_remaining(self) -> Optional[float]:
        if self._expires_at is None:
            return None
        return self._expires_at - time.time()

    def __repr__(self) -> str:
        return f"ValueEntry(type={self._type.value}, expires={self._expires_at})"


class Database:
    # one keyspace — redis has 16 of these
    def __init__(self, db_index: int = 0):
        self._data: dict[str, ValueEntry] = {}
        self._db_index = db_index

    def get(self, key: str) -> Optional[ValueEntry]:
        entry = self._data.get(key)
        if entry is None:
            return None
        # lazy expiry — check on read, delete if stale
        if entry.is_expired():
            del self._data[key]
            return None
        return entry

    def set(self, key: str, value: Any, value_type: ValueType) -> None:
        self._data[key] = ValueEntry(value, value_type)

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
        return count

    def exists(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if self.get(key) is not None:
                count += 1
        return count

    def keys(self, pattern: str = '*') -> list:
        result = []
        # iterate over a copy since lazy expiry can mutate the dict
        for key in list(self._data.keys()):
            if self.get(key) is not None:
                if fnmatch.fnmatch(key, pattern):
                    result.append(key)
        return result

    def type_of(self, key: str) -> Optional[str]:
        entry = self.get(key)
        if entry is None:
            return None
        return entry.type.value

    def rename(self, old_key: str, new_key: str) -> bool:
        entry = self.get(old_key)
        if entry is None:
            return False
        del self._data[old_key]
        self._data[new_key] = entry
        return True

    def get_or_create(self, key: str, value_type: ValueType,
                      factory: Callable) -> ValueEntry:
        # get existing key or create a new one with the right type
        entry = self.get(key)
        if entry is not None:
            if entry.type != value_type:
                raise WrongTypeError()
            return entry
        new_value = factory()
        entry = ValueEntry(new_value, value_type)
        self._data[key] = entry
        return entry

    def flush(self) -> None:
        self._data.clear()

    def dbsize(self) -> int:
        return len(self._data)

    def scan(self, cursor: int, pattern: str = '*', count: int = 10) -> tuple:
        all_keys = sorted(self._data.keys())
        matched = []

        i = cursor
        scanned = 0

        while i < len(all_keys) and scanned < count:
            key = all_keys[i]
            if self.get(key) is not None:
                if fnmatch.fnmatch(key, pattern):
                    matched.append(key)
            i += 1
            scanned += 1

        next_cursor = 0 if i >= len(all_keys) else i
        return (next_cursor, matched)

    def random_key(self) -> Optional[str]:
        import random
        keys = list(self._data.keys())
        if not keys:
            return None
        for _ in range(min(10, len(keys))):
            key = random.choice(keys)
            if self.get(key) is not None:
                return key
        return None

    def __repr__(self) -> str:
        return f"Database(index={self._db_index}, keys={len(self._data)})"


class KeyspaceManager:
    # holds all 16 databases
    def __init__(self, num_databases: int = 16):
        self._databases = [
            Database(db_index=i) for i in range(num_databases)
        ]
        self._num_databases = num_databases

    def get_db(self, index: int) -> Database:
        if index < 0 or index >= self._num_databases:
            raise IndexError(
                f"DB index {index} is out of range (0-{self._num_databases - 1})"
            )
        return self._databases[index]

    def flush_all(self) -> None:
        for db in self._databases:
            db.flush()

    def get_all_keys_count(self) -> int:
        return sum(db.dbsize() for db in self._databases)

    def __repr__(self) -> str:
        total = self.get_all_keys_count()
        return f"KeyspaceManager(databases={self._num_databases}, total_keys={total})"
