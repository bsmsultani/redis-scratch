# Building Redis From Scratch in Python — Comprehensive Implementation Plan

> **Goal:** Learn OOP, system design, and data structures & algorithms by building a fully functional Redis clone.
> Each module maps to real interview concepts tested at Amazon/FAANG.

---

## Project Structure Overview

```
pyredis/
│
├── server.py              # TCP server, event loop, client management
├── client.py              # CLI client to connect and send commands
├── protocol.py            # RESP (Redis Serialization Protocol) parser
├── command_router.py      # Command dispatcher / registry
├── database.py            # Core key-value store + keyspace management
│
├── datastructures/
│   ├── __init__.py
│   ├── rstring.py         # Redis String type
│   ├── rlist.py           # Redis List type (doubly linked list)
│   ├── rhash.py           # Redis Hash type
│   ├── rset.py            # Redis Set type
│   ├── rsortedset.py      # Redis Sorted Set type (skip list)
│   └── rstream.py         # Redis Stream type (radix tree / log)
│
├── persistence/
│   ├── __init__.py
│   ├── rdb.py             # RDB snapshot persistence
│   └── aof.py             # Append-Only File persistence
│
├── features/
│   ├── __init__.py
│   ├── expiry.py          # TTL / key expiration engine
│   ├── pubsub.py          # Publish / Subscribe system
│   ├── transactions.py    # MULTI/EXEC transaction pipeline
│   └── eviction.py        # Memory eviction policies (LRU, LFU, etc.)
│
├── config.py              # Server configuration management
├── logger.py              # Logging utility
│
└── tests/
    ├── test_protocol.py
    ├── test_datastructures.py
    ├── test_database.py
    ├── test_persistence.py
    ├── test_pubsub.py
    └── test_transactions.py
```

---

## Phase 1: The Foundation — Protocol & Networking

> **Interview concepts:** TCP/IP, client-server model, serialization/deserialization, state machines, buffered I/O.

---

### File: `protocol.py` — RESP Protocol Parser

The Redis Serialization Protocol (RESP) is how clients and servers communicate.
This is your first encounter with **parsing**, **state machines**, and **serialization** — all common interview topics.

**RESP Types to implement:**
- `+` Simple String → `+OK\r\n`
- `-` Error → `-ERR unknown command\r\n`
- `:` Integer → `:1000\r\n`
- `$` Bulk String → `$5\r\nhello\r\n`
- `*` Array → `*2\r\n$3\r\nGET\r\n$4\r\nname\r\n`
- `_` Null → `_\r\n`

```
Class: RESPParser
├── __init__(self)
│   - Initialize an internal byte buffer
│   - Track current parse position
│
├── feed(self, data: bytes) -> None
│   - Append raw bytes from the network into the buffer
│   - Called every time the server reads from a socket
│
├── parse_one(self) -> Optional[RESPObject]
│   - Try to parse one complete RESP message from the buffer
│   - Return None if buffer has incomplete data (handle partial reads!)
│   - Dispatch to the correct sub-parser based on the first byte
│   - MUST handle the case where a message spans multiple TCP packets
│
├── _parse_simple_string(self) -> str
│   - Read until \r\n, return the content
│
├── _parse_error(self) -> RESPError
│   - Read until \r\n, return an error object
│
├── _parse_integer(self) -> int
│   - Read until \r\n, convert to int
│
├── _parse_bulk_string(self) -> Optional[str]
│   - Read the length prefix, then read exactly that many bytes + \r\n
│   - Return None for null bulk strings ($-1\r\n)
│
├── _parse_array(self) -> Optional[list]
│   - Read the count, then recursively parse that many elements
│   - Return None for null arrays (*-1\r\n)
│
└── has_complete_message(self) -> bool
    - Peek at the buffer to check if a full message is available
```

```
Class: RESPSerializer
├── encode_simple_string(value: str) -> bytes
├── encode_error(message: str) -> bytes
├── encode_integer(value: int) -> bytes
├── encode_bulk_string(value: Optional[str]) -> bytes
├── encode_array(items: Optional[list]) -> bytes
└── encode(obj: Any) -> bytes
    - Auto-detect type and serialize accordingly
    - Used by the server to send responses back to the client
```

**DSA Concepts Practiced:**
- Buffer management (circular buffer / byte stream)
- Recursive descent parsing (for nested arrays)
- State machines for protocol parsing

---

### File: `server.py` — TCP Server & Event Loop

The core server that listens for connections, reads commands, and sends responses.
This teaches **concurrency**, **I/O multiplexing**, and the **reactor pattern**.

```
Class: ClientConnection
├── __init__(self, socket, address)
│   - Store the client socket and address
│   - Create a dedicated RESPParser for this client
│   - Initialize client state (authenticated, selected_db, in_transaction, subscriptions)
│
├── read(self) -> list[list]
│   - Read bytes from socket, feed into parser
│   - Return list of all complete parsed commands
│   - Handle ConnectionResetError, incomplete reads
│
├── write(self, response: bytes) -> None
│   - Send RESP-encoded response back to client
│   - Handle partial writes (buffer until writable)
│
├── close(self) -> None
│   - Clean up resources, unsubscribe from pubsub, close socket
│
└── Properties:
    - fileno() -> int    # for select/epoll registration
    - is_alive -> bool
```

```
Class: RedisServer
├── __init__(self, host='127.0.0.1', port=6379, config=None)
│   - Create server socket, set SO_REUSEADDR
│   - Initialize the Database instance
│   - Initialize CommandRouter
│   - Initialize ExpiryEngine, PubSubManager
│   - Create the event loop (select/selectors module)
│   - Dict of fd -> ClientConnection
│
├── start(self) -> None
│   - Bind and listen on the server socket
│   - Enter the main event loop
│   - On each iteration:
│       1. Check for readable/writable sockets (select/poll/epoll)
│       2. Accept new connections
│       3. Read commands from ready clients
│       4. Route each command through CommandRouter
│       5. Send responses
│       6. Run periodic tasks (expiry sweep, persistence save check)
│
├── _accept_connection(self) -> None
│   - Accept new socket, wrap in ClientConnection
│   - Register with the selector for READ events
│
├── _handle_client(self, client: ClientConnection) -> None
│   - Read and parse commands
│   - For each command: route through CommandRouter
│   - Write response back
│   - If client disconnected: clean up
│
├── _run_periodic_tasks(self) -> None
│   - Called every N iterations of the event loop
│   - Trigger lazy expiry sweep
│   - Check if AOF/RDB save needed
│   - Check memory limits and run eviction if needed
│
├── shutdown(self) -> None
│   - Graceful shutdown: save data, close all connections, close server socket
│
└── Properties:
    - uptime -> float
    - connected_clients -> int
```

**DSA/Design Concepts Practiced:**
- I/O multiplexing (select/poll/epoll) — event-driven architecture
- Reactor pattern
- Single-threaded concurrency (how Redis actually works)
- File descriptor management

---

### File: `client.py` — Redis CLI Client

A simple interactive client for testing your server.

```
Class: RedisClient
├── __init__(self, host='127.0.0.1', port=6379)
│   - Connect via TCP socket
│   - Initialize RESPParser for reading responses
│
├── send_command(self, *args) -> Any
│   - Serialize args as a RESP array of bulk strings
│   - Send over socket
│   - Read and parse response
│   - Return the decoded value
│
├── pipeline(self) -> Pipeline
│   - Return a Pipeline object for batching commands
│
└── close(self) -> None

Class: Pipeline
├── __init__(self, client)
│   - Buffer for queued commands
│
├── command(self, *args) -> 'Pipeline'
│   - Queue a command, return self for chaining
│
└── execute(self) -> list
    - Send all queued commands at once (fewer round trips)
    - Read all responses and return as a list
```

---

## Phase 2: The Core — Database & Command Routing

> **Interview concepts:** Hash tables, design patterns (Command, Strategy, Registry), encapsulation, polymorphism.

---

### File: `database.py` — The Keyspace

The central key-value store. Each key maps to a typed value object.
This is where you practice **hash map design**, **type systems**, and **encapsulation**.

```
Enum: ValueType
    STRING, LIST, HASH, SET, SORTED_SET, STREAM

Class: ValueEntry
├── __init__(self, value, value_type: ValueType)
│   - Store the actual data structure instance
│   - Store the type enum
│   - Store creation timestamp
│   - Store optional TTL/expiry timestamp (None = no expiry)
│
├── is_expired(self) -> bool
│   - Compare current time against expiry timestamp
│
└── Properties:
    - type -> ValueType
    - value -> Any (the actual data structure)
    - ttl_remaining -> Optional[float]
```

```
Class: Database
├── __init__(self, db_index=0)
│   - Internal dict: str -> ValueEntry (the keyspace)
│   - db_index for multi-database support (Redis has 16 DBs by default)
│
├── get(self, key: str) -> Optional[ValueEntry]
│   - Look up key in the keyspace
│   - Check expiry LAZILY: if expired, delete it and return None
│   - This is "lazy expiration" — a core Redis design decision
│
├── set(self, key: str, value: Any, value_type: ValueType) -> None
│   - Create a ValueEntry and store it
│   - Overwrite any existing key regardless of old type
│
├── delete(self, *keys: str) -> int
│   - Remove keys from keyspace, return count of keys that existed
│
├── exists(self, *keys: str) -> int
│   - Return count of keys that exist (and are not expired)
│
├── keys(self, pattern: str = '*') -> list[str]
│   - Return all keys matching glob-style pattern
│   - Implement basic glob matching: * ? [abc] [a-z]
│   - DSA: pattern matching / simple regex engine
│
├── type_of(self, key: str) -> Optional[ValueType]
│   - Return the type of the value at key, or None
│
├── rename(self, old_key: str, new_key: str) -> bool
│   - Atomically rename a key
│
├── get_or_create(self, key: str, value_type: ValueType, factory: Callable) -> ValueEntry
│   - If key exists and matches type, return it
│   - If key exists with WRONG type, raise WrongTypeError
│   - If key doesn't exist, create with factory(), store, and return
│   - This enforces Redis's type-safety per key
│
├── flush(self) -> None
│   - Delete all keys (FLUSHDB)
│
├── dbsize(self) -> int
│   - Return number of non-expired keys
│
└── scan(self, cursor: int, pattern: str, count: int) -> tuple[int, list[str]]
    - Incremental iteration over the keyspace (SCAN command)
    - Return (next_cursor, list_of_keys)
    - DSA: cursor-based iteration over hash table buckets
```

```
Class: KeyspaceManager
├── __init__(self, num_databases=16)
│   - Create a list of Database instances (one per DB index)
│
├── get_db(self, index: int) -> Database
│   - Return the database at the given index
│   - Raise error if index out of range
│
├── flush_all(self) -> None
│   - Flush every database
│
└── get_all_keys_count(self) -> int
    - Total keys across all databases
```

**DSA Concepts Practiced:**
- Hash table design and collision handling
- Lazy deletion strategy
- Glob/pattern matching algorithms
- Cursor-based iteration (how to iterate a hash table without holding a lock)

---

### File: `command_router.py` — Command Dispatcher

Routes incoming commands to their handler functions.
This demonstrates the **Command Pattern**, **Registry Pattern**, and **Strategy Pattern**.

```
Dataclass: CommandSpec
├── name: str                  # e.g., "GET", "SET"
├── handler: Callable          # function to execute
├── min_args: int              # minimum number of arguments
├── max_args: int              # maximum number of arguments (-1 for unlimited)
├── flags: set[str]            # e.g., {"readonly", "write", "admin", "pubsub"}
└── description: str           # human-readable description
```

```
Class: CommandRouter
├── __init__(self, database: KeyspaceManager)
│   - Store reference to the database
│   - Internal registry: dict[str, CommandSpec]
│   - Call self._register_all_commands()
│
├── _register_all_commands(self) -> None
│   - Register every supported command with its spec
│   - Group by category:
│       STRING:  GET, SET, MGET, MSET, INCR, DECR, INCRBY, DECRBY,
│                APPEND, STRLEN, SETNX, SETEX, GETRANGE, SETRANGE
│       LIST:    LPUSH, RPUSH, LPOP, RPOP, LLEN, LRANGE, LINDEX, LSET,
│                LINSERT, LREM, LTRIM
│       HASH:    HSET, HGET, HDEL, HEXISTS, HGETALL, HKEYS, HVALS,
│                HLEN, HMSET, HMGET, HINCRBY
│       SET:     SADD, SREM, SMEMBERS, SISMEMBER, SCARD, SUNION,
│                SINTER, SDIFF, SRANDMEMBER, SPOP
│       ZSET:    ZADD, ZREM, ZSCORE, ZRANK, ZRANGE, ZRANGEBYSCORE,
│                ZCARD, ZINCRBY, ZCOUNT, ZREVRANGE, ZREVRANK
│       KEYS:    DEL, EXISTS, KEYS, TYPE, RENAME, EXPIRE, TTL, PERSIST,
│                PEXPIRE, PTTL, SCAN, RANDOMKEY
│       SERVER:  PING, ECHO, SELECT, DBSIZE, FLUSHDB, FLUSHALL,
│                INFO, CONFIG, SAVE, BGSAVE, COMMAND, TIME
│       TX:      MULTI, EXEC, DISCARD, WATCH, UNWATCH
│       PUBSUB:  SUBSCRIBE, UNSUBSCRIBE, PUBLISH, PSUBSCRIBE, PUNSUBSCRIBE
│
├── execute(self, client: ClientConnection, command_parts: list[str]) -> bytes
│   - Parse command name (uppercase the first element)
│   - Look up in registry
│   - Validate argument count
│   - If client is in MULTI mode: queue command (unless EXEC/DISCARD)
│   - Call handler(client, *args)
│   - Return RESP-encoded response
│   - Catch and handle WrongTypeError, SyntaxError, etc.
│
├── register(self, spec: CommandSpec) -> None
│   - Add a command to the registry
│
└── get_all_commands(self) -> list[CommandSpec]
    - Return all registered commands (for the COMMAND command)
```

**Design Patterns Practiced:**
- Command Pattern (each command is an encapsulated action)
- Registry/Plugin Pattern (commands register themselves)
- Strategy Pattern (different handlers for different types)
- Single Responsibility Principle

---

## Phase 3: Data Structures — The Heart of Redis (and Interviews)

> **Interview concepts:** Linked lists, hash maps, balanced trees/skip lists, set operations, amortized complexity.

---

### File: `datastructures/rstring.py` — Redis String

Redis strings are binary-safe and also support integer operations.

```
Class: RedisString
├── __init__(self, value: str = '')
│   - Store the raw string value
│
├── get(self) -> str
│   - Return the stored value
│
├── set(self, value: str) -> None
│   - Overwrite the stored value
│
├── append(self, value: str) -> int
│   - Append to existing string, return new length
│
├── strlen(self) -> int
│   - Return the length
│
├── getrange(self, start: int, end: int) -> str
│   - Return substring (Redis uses inclusive end index)
│   - Handle negative indices (from the end)
│
├── setrange(self, offset: int, value: str) -> int
│   - Overwrite starting at offset, zero-pad if needed
│   - Return new total length
│
├── incr(self) -> int
│   - Parse as integer, increment by 1, store back
│   - Raise error if value is not a valid integer
│
├── decr(self) -> int
│   - Same as incr but decrement
│
├── incrby(self, amount: int) -> int
│   - Increment by given amount
│
└── incrbyfloat(self, amount: float) -> float
    - Increment by float, store with minimum decimal representation
```

**DSA Concepts:** String manipulation, type coercion, numeric parsing.

---

### File: `datastructures/rlist.py` — Redis List

Redis lists are **doubly linked lists**. Implement your own — do NOT use Python's built-in list.
This is one of the most common interview data structures.

```
Class: ListNode
├── __init__(self, value: str)
│   - self.value = value
│   - self.prev = None
│   - self.next = None

Class: DoublyLinkedList
├── __init__(self)
│   - self.head: Optional[ListNode] = None
│   - self.tail: Optional[ListNode] = None
│   - self.length: int = 0
│
├── push_head(self, value: str) -> int         # O(1)
│   - Insert at front, return new length
│
├── push_tail(self, value: str) -> int         # O(1)
│   - Insert at back, return new length
│
├── pop_head(self) -> Optional[str]            # O(1)
│   - Remove and return front element
│
├── pop_tail(self) -> Optional[str]            # O(1)
│   - Remove and return back element
│
├── get_by_index(self, index: int) -> Optional[str]  # O(n)
│   - Support negative indices (-1 = last)
│   - Optimize: start from head or tail depending on index
│
├── set_by_index(self, index: int, value: str) -> bool  # O(n)
│   - Set value at index
│
├── insert_before(self, pivot: str, value: str) -> int  # O(n)
│   - Find pivot, insert before it, return new length (-1 if not found)
│
├── insert_after(self, pivot: str, value: str) -> int   # O(n)
│   - Find pivot, insert after it
│
├── remove(self, count: int, value: str) -> int  # O(n)
│   - Remove `count` occurrences of value
│   - count > 0: remove from head; count < 0: from tail; count == 0: all
│   - Return number actually removed

│
├── trim(self, start: int, stop: int) -> None   # O(n)
│   - Keep only elements in [start, stop] range
│
├── range(self, start: int, stop: int) -> list[str]  # O(n)
│   - Return elements in range (inclusive, supports negative indices)
│
├── __len__(self) -> int                        # O(1)
│   - Return self.length
│
└── __iter__(self) -> Iterator[str]
    - Iterate from head to tail
```

```
Class: RedisList
├── __init__(self)
│   - self._list = DoublyLinkedList()
│
├── lpush(self, *values: str) -> int      # Maps to LPUSH
├── rpush(self, *values: str) -> int      # Maps to RPUSH
├── lpop(self) -> Optional[str]           # Maps to LPOP
├── rpop(self) -> Optional[str]           # Maps to RPOP
├── llen(self) -> int                     # Maps to LLEN
├── lrange(self, start: int, stop: int) -> list[str]
├── lindex(self, index: int) -> Optional[str]
├── lset(self, index: int, value: str) -> bool
├── linsert(self, where: str, pivot: str, value: str) -> int
├── lrem(self, count: int, value: str) -> int
└── ltrim(self, start: int, stop: int) -> None
```

**DSA Concepts:** Doubly linked list, two-pointer traversal, index normalization, iterator pattern.

---

### File: `datastructures/rhash.py` — Redis Hash

A hash within a hash — a nested key-value store.

```
Class: RedisHash
├── __init__(self)
│   - self._data: dict[str, str] = {}   # field -> value
│
├── hset(self, *field_value_pairs) -> int
│   - Set one or more field-value pairs
│   - Return count of NEW fields added (not updated)
│
├── hget(self, field: str) -> Optional[str]
│   - Return value at field or None
│
├── hdel(self, *fields: str) -> int
│   - Delete fields, return count deleted
│
├── hexists(self, field: str) -> bool
│
├── hgetall(self) -> dict[str, str]
│   - Return all field-value pairs
│
├── hkeys(self) -> list[str]
│
├── hvals(self) -> list[str]
│
├── hlen(self) -> int
│
├── hincrby(self, field: str, amount: int) -> int
│   - Increment field's integer value
│
├── hincrbyfloat(self, field: str, amount: float) -> float
│
└── hscan(self, cursor: int, pattern: str, count: int) -> tuple[int, dict]
    - Incremental iteration over hash fields
```

**DSA Concepts:** Hash map operations, amortized O(1) access, scan/cursor design.

---

### File: `datastructures/rset.py` — Redis Set

Unordered collection of unique strings.

```
Class: RedisSet
├── __init__(self)
│   - self._members: set[str] = set()
│
├── sadd(self, *members: str) -> int
│   - Add members, return count of NEW members added
│
├── srem(self, *members: str) -> int
│   - Remove members, return count removed
│
├── sismember(self, member: str) -> bool
│
├── smembers(self) -> set[str]
│   - Return all members (copy)
│
├── scard(self) -> int
│   - Return cardinality (size)
│
├── srandmember(self, count: int = 1) -> list[str]
│   - Return random members WITHOUT removing
│   - Positive count: unique members; Negative count: may repeat
│
├── spop(self, count: int = 1) -> list[str]
│   - Remove and return random members
│
├── @staticmethod
├── sunion(*sets: 'RedisSet') -> set[str]
│   - Return the union of all given sets
│
├── @staticmethod
├── sinter(*sets: 'RedisSet') -> set[str]
│   - Return the intersection
│
├── @staticmethod
└── sdiff(*sets: 'RedisSet') -> set[str]
    - Return the difference (first set minus all others)
```

**DSA Concepts:** Set theory, randomized selection (reservoir sampling), hash-based uniqueness.

---

### File: `datastructures/rsortedset.py` — Redis Sorted Set ⭐ THE BIG ONE

This is the **crown jewel** data structure. Real Redis uses a **skip list + hash map** combo.
Implementing a skip list from scratch is an **extremely valuable interview exercise**.

```
Class: SkipListNode
├── __init__(self, member: str, score: float, level: int)
│   - self.member = member
│   - self.score = score
│   - self.forward: list[Optional[SkipListNode]]  # forward pointers per level
│   - self.span: list[int]  # span (distance) at each level — needed for ZRANK
│   - self.backward: Optional[SkipListNode]  # for reverse traversal

Class: SkipList
├── __init__(self, max_level=32, p=0.25)
│   - self.header = SkipListNode('', float('-inf'), max_level)
│   - self.tail: Optional[SkipListNode] = None
│   - self.level = 1       # current highest level in use
│   - self.length = 0
│   - self.max_level = max_level
│   - self.p = p           # probability for level generation
│
├── _random_level(self) -> int                               # O(1) avg
│   - Generate random level using geometric distribution
│   - Keep flipping coins with probability p until tails or max_level
│
├── insert(self, member: str, score: float) -> SkipListNode  # O(log n) avg
│   - Find correct position (maintain update[] array of predecessors at each level)
│   - Track rank[] array for span calculation
│   - Generate random level for new node
│   - Wire up forward pointers and spans at each level
│   - Update backward pointer
│   - Increment length
│
├── delete(self, member: str, score: float) -> bool          # O(log n) avg
│   - Find the node using update[] array
│   - Remove node, fix forward/backward pointers and spans
│   - Decrement level if top levels are now empty
│
├── find(self, member: str, score: float) -> Optional[SkipListNode]  # O(log n)
│   - Traverse from top level down
│
├── get_rank(self, member: str, score: float) -> Optional[int]  # O(log n)
│   - Return 0-based rank by accumulating spans during search
│
├── get_by_rank(self, rank: int) -> Optional[SkipListNode]    # O(log n)
│   - Find node at given rank by following spans
│
├── get_range_by_rank(self, start: int, stop: int) -> list    # O(log n + m)
│   - Return nodes in rank range [start, stop]
│
├── get_range_by_score(self, min_s: float, max_s: float) -> list  # O(log n + m)
│   - Return nodes with score in [min_s, max_s]
│
├── count_in_range(self, min_s: float, max_s: float) -> int   # O(log n)
│   - Count nodes with score in range without iterating all of them
│
└── __len__(self) -> int
```

```
Class: RedisSortedSet
├── __init__(self)
│   - self._skiplist = SkipList()
│   - self._member_scores: dict[str, float] = {}   # member -> score lookup
│   - NOTE: dual data structure! Skip list for ordering, dict for O(1) score lookup
│
├── zadd(self, *score_member_pairs, nx=False, xx=False, gt=False, lt=False) -> int
│   - Add members with scores
│   - NX: only add new, XX: only update existing
│   - GT: only update if new score > old, LT: only update if new score < old
│   - If updating: delete old entry from skip list, insert new one
│   - Return count of new elements added
│
├── zrem(self, *members: str) -> int
│   - Remove members, return count removed
│
├── zscore(self, member: str) -> Optional[float]      # O(1) via dict
│
├── zrank(self, member: str) -> Optional[int]          # O(log n)
│   - Return 0-based rank (by ascending score)
│
├── zrevrank(self, member: str) -> Optional[int]       # O(log n)
│   - Return 0-based rank from the end
│
├── zrange(self, start: int, stop: int, withscores=False) -> list
│   - Return members in rank range
│
├── zrevrange(self, start: int, stop: int, withscores=False) -> list
│   - Same but descending
│
├── zrangebyscore(self, min_score, max_score, withscores=False, offset=0, count=-1) -> list
│   - Return members within score range with optional LIMIT
│
├── zincrby(self, member: str, increment: float) -> float
│   - Increment member's score, reposition in skip list
│
├── zcard(self) -> int
│
└── zcount(self, min_score, max_score) -> int
    - Count members in score range
```

**DSA Concepts Practiced:**
- Skip list (probabilistic alternative to balanced BSTs) — O(log n) operations
- Dual data structures (skip list + hash map for different access patterns)
- Geometric/probabilistic level generation
- Span calculation for rank queries
- Range queries on ordered data

---

### File: `datastructures/rstream.py` — Redis Stream (Bonus/Advanced)

An append-only log with consumer groups. Great for system design interviews about message queues.

```
Class: StreamEntry
├── __init__(self, entry_id: str, fields: dict[str, str])
│   - self.entry_id = entry_id     # "timestamp-sequence" format
│   - self.fields = fields

Class: ConsumerGroup
├── __init__(self, name: str, start_id: str)
│   - self.name = name
│   - self.last_delivered_id = start_id
│   - self.pending: dict[str, PendingEntry] = {}   # entry_id -> consumer
│   - self.consumers: dict[str, Consumer] = {}

Class: RedisStream
├── __init__(self)
│   - self._entries: list[StreamEntry] = []    # append-only ordered log
│   - self._groups: dict[str, ConsumerGroup] = {}
│   - self._last_id = "0-0"
│
├── xadd(self, fields: dict, entry_id='*') -> str
│   - Auto-generate ID if *, append entry, return ID
│
├── xlen(self) -> int
├── xrange(self, start: str, end: str, count: int) -> list[StreamEntry]
├── xread(self, streams: dict[str, str], count: int, block: int) -> dict
└── xgroup_create(self, name: str, start_id: str) -> None
```

**DSA Concepts:** Append-only logs, binary search by ID, consumer group coordination.

---

## Phase 4: Features — TTL, Pub/Sub, Transactions, Eviction

> **Interview concepts:** Priority queues/heaps, observer pattern, optimistic locking, LRU/LFU caches.

---

### File: `features/expiry.py` — Key Expiration Engine

Redis uses **two strategies** for expiring keys — learn both.

```
Class: ExpiryEngine
├── __init__(self, database: Database)
│   - self._database = database
│   - self._expiry_heap: list[tuple[float, str]] = []   # min-heap of (timestamp, key)
│   - heapq-based priority queue
│
├── set_expiry(self, key: str, ttl_seconds: float) -> None
│   - Calculate absolute expiry time
│   - Store in the ValueEntry AND push to the heap
│   - Handle overwriting previous expiry
│
├── set_expiry_at(self, key: str, timestamp: float) -> None
│   - Set expiry as absolute Unix timestamp
│
├── get_ttl(self, key: str) -> Optional[float]
│   - Return remaining TTL in seconds, None if no expiry, -2 if key doesn't exist
│
├── persist(self, key: str) -> bool
│   - Remove expiry from key (make it permanent)
│
├── check_lazy(self, key: str) -> bool
│   - Called on every key access
│   - If key is expired: delete it, return True
│   - This is the LAZY strategy — expire on access
│
├── sweep_active(self, max_keys: int = 20) -> int
│   - The ACTIVE strategy: pop from heap, check top entries
│   - For each: if expired, delete from database
│   - If not expired (or key changed), skip
│   - Stop after max_keys or when top of heap is in the future
│   - Return count of expired keys cleaned up
│   - Called periodically by the server event loop
│
└── cleanup_stale_entries(self) -> None
    - Remove heap entries for keys that no longer exist
    - Prevents heap memory leak
```

**DSA Concepts Practiced:**
- Min-heap / priority queue
- Lazy vs. active expiration (tradeoff between CPU and memory)
- Amortized cleanup strategies

---

### File: `features/pubsub.py` — Publish/Subscribe System

The classic **Observer Pattern** applied to a message broker.

```
Class: Subscription
├── __init__(self, client: ClientConnection, pattern: Optional[str] = None)
│   - self.client = client
│   - self.pattern = pattern   # None for exact channel subs, glob pattern for pattern subs

Class: PubSubManager
├── __init__(self)
│   - self._channel_subs: dict[str, set[Subscription]]   # channel -> subscribers
│   - self._pattern_subs: list[Subscription]              # glob pattern subscribers
│
├── subscribe(self, client: ClientConnection, *channels: str) -> None
│   - Add client to each channel's subscriber set
│   - Send confirmation message to client for each channel
│
├── unsubscribe(self, client: ClientConnection, *channels: str) -> None
│   - Remove client from channels
│   - If no channels given, unsubscribe from all
│
├── psubscribe(self, client: ClientConnection, *patterns: str) -> None
│   - Add pattern-based subscription
│
├── punsubscribe(self, client: ClientConnection, *patterns: str) -> None
│
├── publish(self, channel: str, message: str) -> int
│   - Send message to all exact channel subscribers
│   - Also check all pattern subscribers (glob match against channel name)
│   - Return total number of clients that received the message
│
├── unsubscribe_all(self, client: ClientConnection) -> None
│   - Remove client from ALL subscriptions (called on disconnect)
│
└── get_subscription_count(self, client: ClientConnection) -> int
    - How many channels/patterns this client is subscribed to
```

**DSA Concepts Practiced:**
- Observer/Pub-Sub pattern
- Hash-based fan-out (channel → subscribers)
- Glob pattern matching for `PSUBSCRIBE`

---

### File: `features/transactions.py` — MULTI/EXEC Transactions

Implements Redis transactions with **optimistic locking** via WATCH.

```
Class: TransactionState
├── __init__(self)
│   - self.in_multi: bool = False
│   - self.command_queue: list[tuple] = []    # queued commands
│   - self.watched_keys: dict[str, Any] = {}  # key -> snapshot of value fingerprint
│   - self.is_dirty: bool = False             # True if any watched key was modified

Class: TransactionManager
├── __init__(self, database: Database)
│   - self._database = database
│   - self._client_states: dict[ClientConnection, TransactionState] = {}
│   - self._key_watchers: dict[str, set[ClientConnection]] = {}  # reverse index
│
├── multi(self, client: ClientConnection) -> None
│   - Enter MULTI mode: create TransactionState, set in_multi = True
│   - Raise error if already in MULTI
│
├── queue_command(self, client: ClientConnection, command: tuple) -> None
│   - Append command to the client's queue
│   - Return "+QUEUED" response
│
├── exec(self, client: ClientConnection, executor: Callable) -> list
│   - If any watched key was modified (is_dirty): return None (abort)
│   - Otherwise: execute all queued commands atomically
│   - Collect all responses into a list
│   - Clear transaction state
│   - Return list of responses
│
├── discard(self, client: ClientConnection) -> None
│   - Clear the queue, exit MULTI mode
│
├── watch(self, client: ClientConnection, *keys: str) -> None
│   - Snapshot the current state/fingerprint of each key
│   - Register in _key_watchers reverse index
│   - Must be called BEFORE MULTI
│
├── unwatch(self, client: ClientConnection) -> None
│   - Clear all watches for this client
│
├── notify_key_modified(self, key: str) -> None
│   - Called by Database on ANY write to a key
│   - Mark all clients watching this key as dirty
│   - This is the "optimistic lock check"
│
└── cleanup(self, client: ClientConnection) -> None
    - Remove all state when client disconnects
```

**DSA Concepts Practiced:**
- Optimistic concurrency control (WATCH/MULTI/EXEC)
- Command queuing (FIFO)
- Snapshot isolation / dirty checking
- Reverse index for efficient notification

---

### File: `features/eviction.py` — Memory Eviction Policies

When memory limit is reached, decide which keys to remove. Classic **cache eviction** interview question.

```
Class: EvictionPolicy (Abstract Base Class)
├── @abstractmethod
├── on_access(self, key: str) -> None
│   - Called every time a key is read or written
│
├── @abstractmethod
├── on_add(self, key: str) -> None
│   - Called when a new key is added
│
├── @abstractmethod
├── on_delete(self, key: str) -> None
│   - Called when a key is removed
│
├── @abstractmethod
└── select_victim(self) -> Optional[str]
    - Choose a key to evict, return None if empty

Class: LRUEviction(EvictionPolicy)               # Least Recently Used
├── __init__(self, sample_size: int = 5)
│   - Implement with OrderedDict or custom doubly-linked-list + dict
│   - Redis uses APPROXIMATION: sample random keys, evict least recent
│
├── on_access(self, key: str) -> None
│   - Move key to the "most recently used" end
│
├── select_victim(self) -> Optional[str]
│   - Option A (exact): pop from the "least recently used" end
│   - Option B (approximate, like real Redis): sample N random keys,
│     evict the one with the oldest access time
│
└── Internals:
    - Implement your own LRU cache structure using a doubly linked list + dict
    - The dict maps key -> node for O(1) lookup
    - The linked list maintains access order for O(1) eviction

Class: LFUEviction(EvictionPolicy)               # Least Frequently Used
├── __init__(self)
│   - self._freq_map: dict[str, int]         # key -> access count
│   - self._freq_buckets: dict[int, set]     # count -> set of keys
│   - self._min_freq: int = 0
│
├── on_access(self, key: str) -> None
│   - Increment frequency counter
│   - Move key from old bucket to new bucket
│   - Update min_freq if old bucket is now empty
│
├── select_victim(self) -> Optional[str]
│   - Pick any key from the lowest frequency bucket
│
└── NOTE: Real Redis uses a logarithmic frequency counter with decay.
    - Consider implementing the probabilistic counter:
      counter += 1 only if random() < 1 / (current_count * factor)
      This prevents counters from saturating.

Class: TTLEviction(EvictionPolicy)               # Volatile-TTL
├── select_victim(self) -> Optional[str]
│   - Among keys WITH an expiry, evict the one closest to expiring

Class: RandomEviction(EvictionPolicy)            # Allkeys-Random
├── select_victim(self) -> Optional[str]
│   - Pick a random key from the keyspace

Class: EvictionManager
├── __init__(self, policy: EvictionPolicy, max_memory_bytes: int)
│   - self._policy = policy
│   - self._max_memory = max_memory_bytes
│
├── check_and_evict(self, database: Database) -> int
│   - Estimate current memory usage
│   - While over limit: select victim, delete from database
│   - Return count of evicted keys
│
└── estimate_memory(self, database: Database) -> int
    - Rough estimation of memory used by all stored data
    - Use sys.getsizeof recursively on values
```

**DSA Concepts Practiced:**
- LRU Cache (the single most common interview question!)
- LFU Cache with O(1) operations
- OrderedDict internals (doubly linked list + hash map)
- Probabilistic counting (Morris counter / logarithmic counter)
- Approximate algorithms (sampling-based eviction)

---

## Phase 5: Persistence — Durability on Disk

> **Interview concepts:** Serialization, write-ahead logs, snapshotting, fork-based copy-on-write.

---

### File: `persistence/rdb.py` — RDB Snapshots

Point-in-time snapshot of the entire database.

```
Class: RDBPersistence
├── __init__(self, filepath: str, database: KeyspaceManager)
│   - self._filepath = filepath
│   - self._database = database
│
├── save(self) -> None
│   - Serialize entire keyspace to a binary/JSON file
│   - Write atomically: write to temp file, then rename (atomic on POSIX)
│   - Include:
│       - Magic header + version
│       - For each database with data:
│           - DB selector byte + db_index
│           - For each key:
│               - Value type byte
│               - Optional expiry timestamp
│               - Key as length-prefixed string
│               - Value (serialized based on type)
│       - EOF marker + checksum
│
├── load(self) -> None
│   - Read file, deserialize, populate the KeyspaceManager
│   - Skip keys that are already expired
│   - Validate checksum
│
├── _serialize_value(self, entry: ValueEntry) -> bytes
│   - Dispatch based on value type to serialize each structure
│
├── _deserialize_value(self, data: bytes, value_type: ValueType) -> Any
│   - Rebuild the data structure from bytes
│
└── should_save(self, changes_since_last: int, seconds_since_last: float) -> bool
    - Implement Redis's save rules: "save after N changes in M seconds"
    - E.g., save if 1000 changes in 60 seconds, or 1 change in 900 seconds
```

---

### File: `persistence/aof.py` — Append-Only File

Write-ahead log of every write command.

```
Class: AOFPersistence
├── __init__(self, filepath: str, sync_policy: str = 'everysec')
│   - self._filepath = filepath
│   - self._file: Optional[IO] = None
│   - self._sync_policy = sync_policy  # 'always', 'everysec', 'no'
│   - self._last_sync = time.time()
│   - self._buffer: list[bytes] = []
│
├── open(self) -> None
│   - Open file in append mode
│
├── log_command(self, command_parts: list[str]) -> None
│   - Serialize command as RESP array
│   - Append to file (and/or buffer)
│   - Sync based on policy:
│       'always': fsync after every command
│       'everysec': fsync if >1 second since last sync
│       'no': let OS handle it
│
├── replay(self, executor: Callable) -> int
│   - Read the AOF file from beginning
│   - Parse each RESP command
│   - Execute through the command executor
│   - Return count of commands replayed
│   - This is how data is restored on server startup
│
├── rewrite(self, database: KeyspaceManager) -> None
│   - AOF Rewrite / Compaction:
│   - Instead of replaying 1 million INCRs, write one SET with final value
│   - Create a new AOF from the current state of the database
│   - Atomically replace old file
│   - This prevents the AOF from growing without bound
│
└── close(self) -> None
    - Flush buffer, fsync, close file
```

**DSA Concepts Practiced:**
- Write-ahead logging (WAL)
- Serialization/deserialization
- File I/O buffering strategies
- Log compaction
- Atomic file operations

---

## Phase 6: Configuration & Utilities

---

### File: `config.py`

```
Class: ServerConfig
├── __init__(self, config_file: Optional[str] = None)
│   - Load defaults, then override from file and/or command line
│
├── Defaults:
│   - bind: '127.0.0.1'
│   - port: 6379
│   - databases: 16
│   - maxmemory: 0 (unlimited)
│   - maxmemory_policy: 'noeviction'
│   - save_rules: [(900, 1), (300, 10), (60, 10000)]
│   - appendonly: False
│   - appendfsync: 'everysec'
│   - loglevel: 'notice'
│   - rdbfilename: 'dump.rdb'
│   - appendfilename: 'appendonly.aof'
│
├── get(self, key: str) -> Any
├── set(self, key: str, value: Any) -> None   # CONFIG SET
└── to_dict(self) -> dict                      # CONFIG GET *
```

---

## Implementation Order (Recommended)

Build in this order to keep things testable at every step:

| Step | Module                        | What You Learn                             | Difficulty |
|------|-------------------------------|--------------------------------------------|------------|
| 1    | `protocol.py`                 | Parsing, serialization, buffers            | ★★☆☆☆      |
| 2    | `datastructures/rstring.py`   | String manipulation, type coercion         | ★☆☆☆☆      |
| 3    | `database.py`                 | Hash tables, type system, encapsulation    | ★★☆☆☆      |
| 4    | `command_router.py`           | Command pattern, registry pattern          | ★★☆☆☆      |
| 5    | `server.py` + `client.py`    | TCP, event loop, I/O multiplexing          | ★★★☆☆      |
| 6    | `datastructures/rlist.py`     | Doubly linked list from scratch            | ★★★☆☆      |
| 7    | `datastructures/rhash.py`     | Nested hash maps                           | ★★☆☆☆      |
| 8    | `datastructures/rset.py`      | Set operations, random sampling            | ★★☆☆☆      |
| 9    | `features/expiry.py`          | Heaps, lazy vs active deletion             | ★★★☆☆      |
| 10   | `datastructures/rsortedset.py`| Skip list — the final boss                 | ★★★★★      |
| 11   | `features/eviction.py`        | LRU/LFU cache design                       | ★★★★☆      |
| 12   | `features/pubsub.py`          | Observer pattern, fan-out                  | ★★★☆☆      |
| 13   | `features/transactions.py`    | Optimistic concurrency, WATCH              | ★★★★☆      |
| 14   | `persistence/rdb.py`          | Serialization, atomic writes               | ★★★☆☆      |
| 15   | `persistence/aof.py`          | WAL, log compaction                        | ★★★☆☆      |
| 16   | `datastructures/rstream.py`   | Append-only logs, consumer groups          | ★★★★☆      |

---

## Testing Strategy

Write tests alongside each module:

```
tests/
├── test_protocol.py          # Round-trip encode/decode, partial reads, edge cases
├── test_rstring.py           # INCR overflow, GETRANGE with negatives, empty strings
├── test_rlist.py             # Push/pop ordering, LREM with count variants, empty list
├── test_rhash.py             # HINCRBY on new field, HGETALL ordering
├── test_rset.py              # Set operations, SRANDMEMBER with negative count
├── test_rsortedset.py        # Score ties, ZRANGEBYSCORE edge cases, rank accuracy
├── test_database.py          # Type errors, lazy expiry, SCAN cursor behavior
├── test_expiry.py            # TTL accuracy, active sweep correctness
├── test_eviction.py          # LRU ordering, LFU frequency tracking
├── test_pubsub.py            # Pattern matching, unsubscribe cleanup
├── test_transactions.py      # WATCH dirty detection, MULTI/EXEC atomicity
├── test_persistence.py       # Save/load round trip, AOF replay correctness
└── test_integration.py       # End-to-end: client sends commands, verifies responses
```

---

## Key Interview Concepts Mapped to Modules

| Interview Topic                     | Where You Practice It                        |
|-------------------------------------|----------------------------------------------|
| Hash Maps                           | `database.py`, `rhash.py`, `rset.py`         |
| Linked Lists                        | `rlist.py`, `eviction.py` (LRU)              |
| Skip Lists / Balanced BSTs          | `rsortedset.py`                              |
| Heaps / Priority Queues             | `expiry.py`                                  |
| LRU Cache Design                    | `eviction.py`                                |
| Design Patterns                     | `command_router.py`, `pubsub.py`             |
| Serialization / Protocol Design     | `protocol.py`, `rdb.py`                      |
| Concurrency / Event Loops           | `server.py`                                  |
| Pub/Sub System Design               | `pubsub.py`                                  |
| Database Transactions               | `transactions.py`                            |
| Write-Ahead Logging                 | `aof.py`                                     |
| Cache Eviction Policies             | `eviction.py`                                |
| System Design: "Design Redis"       | **The entire project**                        |
| System Design: "Design a Key-Value Store" | **The entire project**                  |
| System Design: "Design a Message Queue"   | `rstream.py`, `pubsub.py`              |

---

## Tips for Maximum Learning

1. **Implement data structures from scratch.** Don't use Python's `collections.OrderedDict` for LRU — build a linked list + dict yourself. The whole point is practice.

2. **Write the tests first (TDD).** Before implementing `SkipList.insert()`, write tests for what it should do. This mirrors how FAANG interviews work — clarify behavior before coding.

3. **Analyze complexity.** Comment every method with its Big-O. If you can't determine it, that's a learning opportunity.

4. **Draw it out.** Before coding the skip list or LRU, draw the data structure on paper. Trace through insertions and deletions by hand.

5. **Compare with real Redis.** After implementing a feature, read the actual Redis source (it's in C) to see how they solved the same problem.

6. **Practice explaining your design.** After each module, pretend you're in a system design interview: "I chose a skip list because..."

---

*Good luck! This project covers more DSA and system design than most people encounter in months of LeetCode.*
