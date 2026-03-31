# redis-scratch

A Redis server built from scratch in Python. Supports the RESP protocol, multiple data structures, TTLs, pipelining, and comes with an interactive CLI.

## Getting started

Start the server:

```bash
python3 server.py
```

Then in another terminal, open the CLI:

```bash
python3 cli.py
```

Or connect on a different port:

```bash
python3 cli.py -p 6380
```

---

## What works

**Strings**
```
SET name Alice
GET name
INCR counter
APPEND greeting " world"
GETRANGE name 0 2
SET session abc EX 60
```

**Lists**
```
LPUSH tasks "write tests"
RPUSH tasks "deploy"
LRANGE tasks 0 -1
LPOP tasks
LINSERT tasks BEFORE "deploy" "review"
```

**Keys / expiry**
```
EXPIRE name 30
TTL name
PERSIST name
DEL key1 key2
KEYS *
SCAN 0 MATCH user:* COUNT 20
RENAME oldkey newkey
TYPE name
```

**Server**
```
PING
DBSIZE
SELECT 1
FLUSHDB
TIME
```

---

## Pipelining

```python
from client import RedisClient

with RedisClient() as client:
    results = (client.Pipeline()
        .command("SET", "x", "1")
        .command("INCR", "x")
        .command("GET", "x")
        .execute())
    # ["OK", 2, "2"]
```

---

## Project layout

```
server.py          # TCP server, event loop, client connections
protocol.py        # RESP parser + serializer
command_router.py  # maps command names to handler functions
database.py        # keyspace, ValueEntry, TTL logic
client.py          # Python client + pipeline
cli.py             # interactive REPL

datastructures/
  rstring.py       # strings with integer/float ops
  rlist.py         # doubly linked list
  rset.py          # sets
  rhash.py         # hashes
  rsortedset.py    # sorted sets (in progress)
```