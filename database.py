"""
database.py — The Core Key-Value Store
=======================================

This is the CENTRAL data structure of Redis. Every command
ultimately reads from or writes to the database.

Structure:
    KeyspaceManager (manages 16 databases)
    └── Database (one key-value store)
        └── ValueEntry (wrapper: value + type + expiry metadata)

INTERVIEW CONCEPTS:
  - Hash table design (the keyspace IS a hash map)
  - Lazy deletion (expired keys cleaned up on access, not eagerly)
  - Type safety per key (a key holds ONE type, operations must match)
  - Glob pattern matching (the KEYS command)
  - Cursor-based iteration (SCAN — iterate without locking)

WHY ValueEntry EXISTS:
A raw dict of {key: value} isn't enough because Redis needs to
track METADATA alongside each value:
  - What TYPE is it? (string, list, hash, set, sorted set)
  - When does it EXPIRE? (TTL)
  - When was it CREATED?

Without this wrapper, you'd need parallel dicts:
    values = {"name": RedisString("Alice")}
    types  = {"name": ValueType.STRING}
    expiry = {"name": 1700000000.0}

That's fragile. ValueEntry bundles it all together — same
encapsulation principle as ClientConnection.
"""

import time
import fnmatch
from enum import Enum
from typing import Optional, Any, Callable


# =============================================================================
# VALUE TYPE ENUM
# =============================================================================
# Every key in Redis has exactly ONE type. You can't do LPUSH on a string
# or GET on a list. The type is set when the key is first created and
# locked in until the key is deleted.
#
# OOP Concept: Enums prevent typos and give you type safety.
# "string" vs "String" vs "STRING" → just use ValueType.STRING.
# =============================================================================

class ValueType(Enum):
    STRING = "string"
    LIST = "list"
    HASH = "hash"
    SET = "set"
    SORTED_SET = "zset"
    STREAM = "stream"


# =============================================================================
# WRONG TYPE ERROR
# =============================================================================

class WrongTypeError(Exception):
    """
    Raised when a command is used against a key holding the wrong type.

    Example:
        SET name "Alice"   → creates a STRING
        LPUSH name "Bob"   → WrongTypeError! name is a STRING, not a LIST
    """
    def __init__(self):
        super().__init__(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )


# =============================================================================
# VALUE ENTRY — wrapper around each stored value
# =============================================================================

class ValueEntry:
    """
    Wraps a stored value with its type and expiry metadata.

    Every key in the database maps to one of these.
    The actual data structure (RedisString, RedisList, etc.)
    lives inside self._value.
    """

    def __init__(self, value: Any, value_type: ValueType):
        self._value = value
        self._type = value_type
        self._created_at: float = time.time()
        self._expires_at: Optional[float] = None  # None = no expiry

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
        """Check if this key has passed its expiry time."""
        if self._expires_at is None:
            return False
        return time.time() > self._expires_at

    @property
    def ttl_remaining(self) -> Optional[float]:
        """
        Seconds until expiry, or None if no expiry is set.
        Returns negative if already expired (but not yet cleaned up).
        """
        if self._expires_at is None:
            return None
        return self._expires_at - time.time()

    def __repr__(self) -> str:
        return f"ValueEntry(type={self._type.value}, expires={self._expires_at})"


# =============================================================================
# DATABASE — one keyspace (Redis has 16 of these by default)
# =============================================================================

class Database:
    """
    A single key-value store. Redis runs 16 of these (SELECT 0-15).

    The keyspace is a dict: str → ValueEntry.
    This IS a hash table — the most fundamental data structure
    in all of Redis and one of the most common interview topics.

    LAZY EXPIRATION:
    When you call GET on an expired key, we delete it and return None.
    We do NOT run a background thread scanning every key. This is a
    deliberate tradeoff:
      - Pro: zero CPU cost for keys nobody is reading
      - Con: expired keys sit in memory until accessed
    Redis combines this with an ACTIVE sweep (in ExpiryEngine)
    that probabilistically samples keys to clean up. You'll build
    that in Phase 4.
    """

    def __init__(self, db_index: int = 0):
        self._data: dict[str, ValueEntry] = {}
        self._db_index = db_index

    def get(self, key: str) -> Optional[ValueEntry]:
        """
        Look up a key. Returns None if missing or expired.

        This is where LAZY EXPIRATION happens. Every read checks
        the TTL and silently deletes expired keys. The caller
        never sees expired data.
        """
        entry = self._data.get(key)

        if entry is None:
            return None

        # ── LAZY EXPIRATION ───────────────────────────────
        # Check BEFORE returning. If expired, pretend it
        # doesn't exist. This is O(1) — just a timestamp check.
        if entry.is_expired():
            del self._data[key]
            return None

        return entry

    def set(self, key: str, value: Any, value_type: ValueType) -> None:
        """
        Create or overwrite a key with a new value.

        Overwrites regardless of old type — SET always wins.
        This is different from get_or_create which checks type.
        """
        self._data[key] = ValueEntry(value, value_type)

    def delete(self, *keys: str) -> int:
        """
        Delete one or more keys. Return count of keys that existed.

        DEL key1 key2 key3 → returns how many were actually present.
        """
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
        return count

    def exists(self, *keys: str) -> int:
        """
        Return count of keys that exist (and are not expired).

        EXISTS key1 key2 key3 → how many of these exist?
        Note: same key listed twice counts twice if it exists.
        """
        count = 0
        for key in keys:
            if self.get(key) is not None:  # get() handles lazy expiry
                count += 1
        return count

    def keys(self, pattern: str = '*') -> list:
        """
        Return all keys matching a glob-style pattern.

        Uses fnmatch which supports: * ? [abc] [a-z]

        WARNING: This scans EVERY key — O(n). In production Redis,
        KEYS is considered dangerous on large databases because it
        blocks the single thread. Use SCAN instead.
        """
        result = []
        # Iterate over a copy of keys since lazy expiry might
        # modify the dict during iteration.
        for key in list(self._data.keys()):
            # get() triggers lazy expiration
            if self.get(key) is not None:
                if fnmatch.fnmatch(key, pattern):
                    result.append(key)
        return result

    def type_of(self, key: str) -> Optional[str]:
        """
        Return the type name of the value at key, or None.

        TYPE key → "string", "list", "hash", "set", "zset", or None
        """
        entry = self.get(key)
        if entry is None:
            return None
        return entry.type.value

    def rename(self, old_key: str, new_key: str) -> bool:
        """
        Atomically rename a key. Returns False if old_key doesn't exist.

        RENAME old new:
          1. Get the entry at old_key
          2. Delete old_key
          3. Store entry at new_key (overwrites if new_key existed)
        """
        entry = self.get(old_key)
        if entry is None:
            return False

        # Remove old, set new. Preserves the ValueEntry (type, expiry, etc.)
        del self._data[old_key]
        self._data[new_key] = entry
        return True

    def get_or_create(self, key: str, value_type: ValueType,
                      factory: Callable) -> ValueEntry:
        """
        Get existing key if types match, or create a new one.

        This is the CORE TYPE SAFETY mechanism. Used by commands like
        LPUSH, SADD, etc. that need a specific type:

            entry = db.get_or_create("mylist", ValueType.LIST, RedisList)
            entry.value.lpush("hello")

        Three cases:
          1. Key exists, correct type → return it
          2. Key exists, WRONG type  → raise WrongTypeError
          3. Key missing             → create with factory(), store, return

        Args:
            key: The key to look up or create.
            value_type: The expected type.
            factory: Callable that creates a new empty data structure.
                     e.g. RedisList, RedisHash, RedisSet
        """
        entry = self.get(key)

        if entry is not None:
            # Key exists — type must match
            if entry.type != value_type:
                raise WrongTypeError()
            return entry

        # Key doesn't exist — create new entry
        new_value = factory()
        entry = ValueEntry(new_value, value_type)
        self._data[key] = entry
        return entry

    def flush(self) -> None:
        """Delete ALL keys. (FLUSHDB)"""
        self._data.clear()

    def dbsize(self) -> int:
        """
        Return number of keys (including not-yet-expired ones).

        For an exact count of non-expired keys you'd need to scan all,
        which is expensive. Redis also returns the approximate count.
        """
        return len(self._data)

    def scan(self, cursor: int, pattern: str = '*',
             count: int = 10) -> tuple:
        """
        Incrementally iterate over the keyspace.

        Unlike KEYS which scans everything at once, SCAN returns a
        small batch and a cursor to continue from. This lets you
        iterate millions of keys without blocking the server.

        Args:
            cursor: Position to resume from. 0 = start.
            pattern: Glob pattern to filter keys.
            count: Hint for how many to return (not a guarantee).

        Returns:
            (next_cursor, [matching_keys])
            next_cursor = 0 means iteration is complete.

        DSA Concept: cursor-based pagination over a hash table.
        Real Redis uses a clever "reverse binary iteration" of hash
        table buckets to handle rehashing. Our simplified version
        uses a sorted key list.
        """
        all_keys = sorted(self._data.keys())
        matched = []

        # Start from cursor position, scan up to count keys
        i = cursor
        scanned = 0

        while i < len(all_keys) and scanned < count:
            key = all_keys[i]
            # Check expiry
            if self.get(key) is not None:
                if fnmatch.fnmatch(key, pattern):
                    matched.append(key)
            i += 1
            scanned += 1

        # Next cursor: 0 if we reached the end, else current position
        next_cursor = 0 if i >= len(all_keys) else i

        return (next_cursor, matched)

    def random_key(self) -> Optional[str]:
        """Return a random key from the database, or None if empty."""
        import random
        keys = list(self._data.keys())
        if not keys:
            return None

        # Try a few times to find a non-expired key
        for _ in range(min(10, len(keys))):
            key = random.choice(keys)
            if self.get(key) is not None:
                return key
        return None

    def __repr__(self) -> str:
        return f"Database(index={self._db_index}, keys={len(self._data)})"


# =============================================================================
# KEYSPACE MANAGER — manages all 16 databases
# =============================================================================

class KeyspaceManager:
    """
    Manages multiple Database instances (Redis supports SELECT 0-15).

    Most users only ever use database 0, but the ability to switch
    is part of the Redis spec. Each client tracks which database
    they've SELECTed in their ClientConnection state.

    This is the object the server holds. Commands access the right
    database through: manager.get_db(client._selected_db)
    """

    def __init__(self, num_databases: int = 16):
        self._databases = [
            Database(db_index=i) for i in range(num_databases)
        ]
        self._num_databases = num_databases

    def get_db(self, index: int) -> Database:
        """
        Return the database at the given index.

        Raises IndexError if out of range (0-15 by default).
        """
        if index < 0 or index >= self._num_databases:
            raise IndexError(
                f"DB index {index} is out of range (0-{self._num_databases - 1})"
            )
        return self._databases[index]

    def flush_all(self) -> None:
        """Flush every database. (FLUSHALL)"""
        for db in self._databases:
            db.flush()

    def get_all_keys_count(self) -> int:
        """Total keys across all databases."""
        return sum(db.dbsize() for db in self._databases)

    def __repr__(self) -> str:
        total = self.get_all_keys_count()
        return f"KeyspaceManager(databases={self._num_databases}, total_keys={total})"