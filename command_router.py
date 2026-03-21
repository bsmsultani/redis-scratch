"""
command_router.py — Command Dispatcher & Registry
===================================================

This is the GLUE between the network layer and the data layer.
When the server receives ["SET", "name", "Alice"], the router:
  1. Looks up "SET" in the registry
  2. Validates argument count
  3. Calls the correct handler function
  4. Returns the RESP-encoded response

DESIGN PATTERNS:
  - Command Pattern: each command is an encapsulated action with a handler
  - Registry Pattern: commands register themselves in a dict for O(1) lookup
  - Single Responsibility: router only dispatches, handlers do the work

WHY NOT A GIANT IF/ELIF CHAIN?
You could write:
    if cmd == "GET": ...
    elif cmd == "SET": ...
    elif cmd == "LPUSH": ...
    (50 more elif blocks)

Problems:
  - One massive function that grows forever
  - Can't add commands without editing the dispatcher
  - Hard to test individual commands in isolation

The registry pattern solves all three. Each command is a separate
function registered in a dict. Adding a new command = writing a
function + one register() call.
"""

from dataclasses import dataclass
from typing import Callable, Optional
from protocol import RESPSerializer, RESPError
from database import KeyspaceManager, Database, ValueType, WrongTypeError
from datastructures.rstring import RedisString


# =============================================================================
# COMMAND SPEC — metadata about one command
# =============================================================================

@dataclass
class CommandSpec:
    """
    Everything the router needs to know about a command.

    Using @dataclass saves us from writing __init__ with 5 parameters.
    It auto-generates __init__, __repr__, and __eq__.

    OOP Concept: @dataclass is a code generation tool. It's the
    Pythonic way to create simple "data holder" classes without
    boilerplate.
    """
    name: str               # e.g. "GET", "SET"
    handler: Callable       # the function to call
    min_args: int           # minimum arguments (excluding command name)
    max_args: int           # maximum arguments (-1 = unlimited)
    flags: set              # e.g. {"readonly", "write", "admin"}
    description: str = ""   # human-readable help text


# =============================================================================
# COMMAND ROUTER
# =============================================================================

class CommandRouter:
    """
    Routes parsed commands to their handler functions.

    The registry is a dict: command_name (str) → CommandSpec.
    Lookup is O(1). Adding new commands is one line each.
    """

    def __init__(self, keyspace: KeyspaceManager):
        self._keyspace = keyspace
        self._registry: dict[str, CommandSpec] = {}
        self._register_all_commands()

    # =================================================================
    # PUBLIC API
    # =================================================================

    def execute(self, client, command_parts: list) -> bytes:
        """
        Execute a parsed command and return the RESP-encoded response.

        Args:
            client: The ClientConnection that sent this command.
            command_parts: e.g. ["SET", "name", "Alice"]

        Returns:
            RESP-encoded bytes ready to send back over the wire.
        """
        if not command_parts:
            return RESPSerializer.encode_error("ERR empty command")

        # Command name is always the first element, uppercased.
        name = command_parts[0].upper() if isinstance(command_parts[0], str) else ""
        args = command_parts[1:]

        # ── LOOK UP IN REGISTRY ───────────────────────────
        spec = self._registry.get(name)
        if spec is None:
            return RESPSerializer.encode_error(
                f"ERR unknown command '{name}'"
            )

        # ── VALIDATE ARGUMENT COUNT ───────────────────────
        if len(args) < spec.min_args:
            return RESPSerializer.encode_error(
                f"ERR wrong number of arguments for '{name}' command"
            )
        if spec.max_args != -1 and len(args) > spec.max_args:
            return RESPSerializer.encode_error(
                f"ERR wrong number of arguments for '{name}' command"
            )

        # ── GET THE RIGHT DATABASE ────────────────────────
        # Each client might have SELECTed a different database.
        db = self._keyspace.get_db(client._selected_db)

        # ── EXECUTE THE HANDLER ───────────────────────────
        try:
            return spec.handler(client, db, args)
        except WrongTypeError as e:
            return RESPSerializer.encode_error(str(e))
        except ValueError as e:
            return RESPSerializer.encode_error(f"ERR {e}")
        except Exception as e:
            return RESPSerializer.encode_error(f"ERR {e}")

    def register(self, spec: CommandSpec) -> None:
        """Add a command to the registry."""
        self._registry[spec.name.upper()] = spec

    def get_all_commands(self) -> list:
        """Return all registered command specs."""
        return list(self._registry.values())

    # =================================================================
    # COMMAND REGISTRATION
    # =================================================================

    def _register_all_commands(self) -> None:
        """Register every supported command."""

        # ── SERVER / CONNECTION COMMANDS ───────────────────
        self._register_server_commands()

        # ── STRING COMMANDS ───────────────────────────────
        self._register_string_commands()

        # Uncomment as you build each data structure:
        # self._register_list_commands()
        # self._register_hash_commands()
        # self._register_set_commands()
        # self._register_sorted_set_commands()

        # ── KEY COMMANDS ──────────────────────────────────
        self._register_key_commands()

    # =================================================================
    # SERVER COMMANDS — PING, ECHO, SELECT, DBSIZE, etc.
    # =================================================================

    def _register_server_commands(self) -> None:

        def cmd_ping(client, db, args) -> bytes:
            if args:
                return RESPSerializer.encode_bulk_string(args[0])
            return RESPSerializer.encode_simple_string("PONG")

        def cmd_echo(client, db, args) -> bytes:
            return RESPSerializer.encode_bulk_string(args[0])

        def cmd_select(client, db, args) -> bytes:
            try:
                index = int(args[0])
                # Validate the index is in range by trying to get it.
                self._keyspace.get_db(index)
                client._selected_db = index
                return RESPSerializer.encode_simple_string("OK")
            except (ValueError, IndexError):
                return RESPSerializer.encode_error("ERR DB index is out of range")

        def cmd_dbsize(client, db, args) -> bytes:
            return RESPSerializer.encode_integer(db.dbsize())

        def cmd_flushdb(client, db, args) -> bytes:
            db.flush()
            return RESPSerializer.encode_simple_string("OK")

        def cmd_flushall(client, db, args) -> bytes:
            self._keyspace.flush_all()
            return RESPSerializer.encode_simple_string("OK")

        def cmd_quit(client, db, args) -> bytes:
            client._alive = False
            return RESPSerializer.encode_simple_string("OK")

        def cmd_command(client, db, args) -> bytes:
            # Simplified: return count of registered commands.
            count = len(self._registry)
            return RESPSerializer.encode_integer(count)

        def cmd_time(client, db, args) -> bytes:
            import time
            now = time.time()
            seconds = str(int(now))
            microseconds = str(int((now % 1) * 1_000_000))
            return RESPSerializer.encode_array([seconds, microseconds])

        self.register(CommandSpec("PING", cmd_ping, 0, 1, {"fast"}))
        self.register(CommandSpec("ECHO", cmd_echo, 1, 1, {"fast"}))
        self.register(CommandSpec("SELECT", cmd_select, 1, 1, {"fast"}))
        self.register(CommandSpec("DBSIZE", cmd_dbsize, 0, 0, {"readonly", "fast"}))
        self.register(CommandSpec("FLUSHDB", cmd_flushdb, 0, 0, {"write"}))
        self.register(CommandSpec("FLUSHALL", cmd_flushall, 0, 0, {"write"}))
        self.register(CommandSpec("QUIT", cmd_quit, 0, 0, {"fast"}))
        self.register(CommandSpec("COMMAND", cmd_command, 0, -1, {"readonly"}))
        self.register(CommandSpec("TIME", cmd_time, 0, 0, {"readonly", "fast"}))

    # =================================================================
    # STRING COMMANDS — GET, SET, INCR, DECR, APPEND, etc.
    # =================================================================

    def _register_string_commands(self) -> None:

        def cmd_get(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_bulk_string(None)
            if entry.type != ValueType.STRING:
                raise WrongTypeError()
            return RESPSerializer.encode_bulk_string(entry.value.get())

        def cmd_set(client, db, args) -> bytes:
            key = args[0]
            value = args[1]

            # Parse optional flags: EX, PX, NX, XX
            ex = None   # seconds TTL
            px = None   # milliseconds TTL
            nx = False  # only set if NOT exists
            xx = False  # only set if DOES exist

            i = 2
            while i < len(args):
                flag = args[i].upper()
                if flag == "EX" and i + 1 < len(args):
                    ex = int(args[i + 1])
                    i += 2
                elif flag == "PX" and i + 1 < len(args):
                    px = int(args[i + 1])
                    i += 2
                elif flag == "NX":
                    nx = True
                    i += 1
                elif flag == "XX":
                    xx = True
                    i += 1
                else:
                    return RESPSerializer.encode_error("ERR syntax error")

            # NX: only set if key does NOT exist
            if nx and db.get(key) is not None:
                return RESPSerializer.encode_bulk_string(None)

            # XX: only set if key DOES exist
            if xx and db.get(key) is None:
                return RESPSerializer.encode_bulk_string(None)

            rstring = RedisString(value)
            db.set(key, rstring, ValueType.STRING)

            # Apply TTL if requested
            if ex is not None:
                entry = db.get(key)
                import time
                entry.expires_at = time.time() + ex
            elif px is not None:
                entry = db.get(key)
                import time
                entry.expires_at = time.time() + (px / 1000.0)

            return RESPSerializer.encode_simple_string("OK")

        def cmd_setnx(client, db, args) -> bytes:
            key = args[0]
            if db.get(key) is not None:
                return RESPSerializer.encode_integer(0)
            db.set(key, RedisString(args[1]), ValueType.STRING)
            return RESPSerializer.encode_integer(1)

        def cmd_setex(client, db, args) -> bytes:
            import time
            key = args[0]
            seconds = int(args[1])
            value = args[2]
            rstring = RedisString(value)
            db.set(key, rstring, ValueType.STRING)
            entry = db.get(key)
            entry.expires_at = time.time() + seconds
            return RESPSerializer.encode_simple_string("OK")

        def cmd_mget(client, db, args) -> bytes:
            results = []
            for key in args:
                entry = db.get(key)
                if entry is None or entry.type != ValueType.STRING:
                    results.append(None)
                else:
                    results.append(entry.value.get())
            return RESPSerializer.encode_array(results)

        def cmd_mset(client, db, args) -> bytes:
            if len(args) % 2 != 0:
                return RESPSerializer.encode_error(
                    "ERR wrong number of arguments for 'mset' command"
                )
            for i in range(0, len(args), 2):
                db.set(args[i], RedisString(args[i + 1]), ValueType.STRING)
            return RESPSerializer.encode_simple_string("OK")

        def _get_or_create_string(db, key) -> RedisString:
            entry = db.get_or_create(key, ValueType.STRING, lambda: RedisString("0"))
            return entry.value

        def cmd_incr(client, db, args) -> bytes:
            rstring = _get_or_create_string(db, args[0])
            result = rstring.incr()
            return RESPSerializer.encode_integer(result)

        def cmd_decr(client, db, args) -> bytes:
            rstring = _get_or_create_string(db, args[0])
            result = rstring.decr()
            return RESPSerializer.encode_integer(result)

        def cmd_incrby(client, db, args) -> bytes:
            amount = int(args[1])
            rstring = _get_or_create_string(db, args[0])
            result = rstring.incrby(amount)
            return RESPSerializer.encode_integer(result)

        def cmd_decrby(client, db, args) -> bytes:
            amount = int(args[1])
            rstring = _get_or_create_string(db, args[0])
            result = rstring.decrby(amount)
            return RESPSerializer.encode_integer(result)

        def cmd_incrbyfloat(client, db, args) -> bytes:
            amount = float(args[1])
            entry = db.get_or_create(
                args[0], ValueType.STRING, lambda: RedisString("0")
            )
            result = entry.value.incrbyfloat(amount)
            return RESPSerializer.encode_bulk_string(str(result))

        def cmd_append(client, db, args) -> bytes:
            entry = db.get_or_create(
                args[0], ValueType.STRING, lambda: RedisString("")
            )
            length = entry.value.append(args[1])
            return RESPSerializer.encode_integer(length)

        def cmd_strlen(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(0)
            if entry.type != ValueType.STRING:
                raise WrongTypeError()
            return RESPSerializer.encode_integer(entry.value.strlen())

        def cmd_getrange(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_bulk_string("")
            if entry.type != ValueType.STRING:
                raise WrongTypeError()
            start = int(args[1])
            end = int(args[2])
            result = entry.value.getrange(start, end)
            return RESPSerializer.encode_bulk_string(result)

        def cmd_setrange(client, db, args) -> bytes:
            entry = db.get_or_create(
                args[0], ValueType.STRING, lambda: RedisString("")
            )
            offset = int(args[1])
            length = entry.value.setrange(offset, args[2])
            return RESPSerializer.encode_integer(length)

        self.register(CommandSpec("GET", cmd_get, 1, 1, {"readonly", "fast"}))
        self.register(CommandSpec("SET", cmd_set, 2, -1, {"write"}))
        self.register(CommandSpec("SETNX", cmd_setnx, 2, 2, {"write"}))
        self.register(CommandSpec("SETEX", cmd_setex, 3, 3, {"write"}))
        self.register(CommandSpec("MGET", cmd_mget, 1, -1, {"readonly"}))
        self.register(CommandSpec("MSET", cmd_mset, 2, -1, {"write"}))
        self.register(CommandSpec("INCR", cmd_incr, 1, 1, {"write"}))
        self.register(CommandSpec("DECR", cmd_decr, 1, 1, {"write"}))
        self.register(CommandSpec("INCRBY", cmd_incrby, 2, 2, {"write"}))
        self.register(CommandSpec("DECRBY", cmd_decrby, 2, 2, {"write"}))
        self.register(CommandSpec("INCRBYFLOAT", cmd_incrbyfloat, 2, 2, {"write"}))
        self.register(CommandSpec("APPEND", cmd_append, 2, 2, {"write"}))
        self.register(CommandSpec("STRLEN", cmd_strlen, 1, 1, {"readonly"}))
        self.register(CommandSpec("GETRANGE", cmd_getrange, 3, 3, {"readonly"}))
        self.register(CommandSpec("SETRANGE", cmd_setrange, 3, 3, {"write"}))

    # =================================================================
    # KEY COMMANDS — DEL, EXISTS, TYPE, RENAME, EXPIRE, TTL, etc.
    # =================================================================

    def _register_key_commands(self) -> None:

        def cmd_del(client, db, args) -> bytes:
            count = db.delete(*args)
            return RESPSerializer.encode_integer(count)

        def cmd_exists(client, db, args) -> bytes:
            count = db.exists(*args)
            return RESPSerializer.encode_integer(count)

        def cmd_keys(client, db, args) -> bytes:
            pattern = args[0]
            matching = db.keys(pattern)
            return RESPSerializer.encode_array(matching)

        def cmd_type(client, db, args) -> bytes:
            type_name = db.type_of(args[0])
            if type_name is None:
                return RESPSerializer.encode_simple_string("none")
            return RESPSerializer.encode_simple_string(type_name)

        def cmd_rename(client, db, args) -> bytes:
            if not db.rename(args[0], args[1]):
                return RESPSerializer.encode_error("ERR no such key")
            return RESPSerializer.encode_simple_string("OK")

        def cmd_expire(client, db, args) -> bytes:
            import time
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(0)
            seconds = int(args[1])
            entry.expires_at = time.time() + seconds
            return RESPSerializer.encode_integer(1)

        def cmd_pexpire(client, db, args) -> bytes:
            import time
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(0)
            ms = int(args[1])
            entry.expires_at = time.time() + (ms / 1000.0)
            return RESPSerializer.encode_integer(1)

        def cmd_ttl(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(-2)  # key doesn't exist
            if entry.expires_at is None:
                return RESPSerializer.encode_integer(-1)  # no expiry set
            remaining = entry.ttl_remaining
            return RESPSerializer.encode_integer(int(remaining))

        def cmd_pttl(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(-2)
            if entry.expires_at is None:
                return RESPSerializer.encode_integer(-1)
            remaining = entry.ttl_remaining
            return RESPSerializer.encode_integer(int(remaining * 1000))

        def cmd_persist(client, db, args) -> bytes:
            entry = db.get(args[0])
            if entry is None:
                return RESPSerializer.encode_integer(0)
            if entry.expires_at is None:
                return RESPSerializer.encode_integer(0)  # no expiry to remove
            entry.expires_at = None
            return RESPSerializer.encode_integer(1)

        def cmd_scan(client, db, args) -> bytes:
            cursor = int(args[0])
            pattern = '*'
            count = 10

            i = 1
            while i < len(args):
                flag = args[i].upper()
                if flag == "MATCH" and i + 1 < len(args):
                    pattern = args[i + 1]
                    i += 2
                elif flag == "COUNT" and i + 1 < len(args):
                    count = int(args[i + 1])
                    i += 2
                else:
                    i += 1

            next_cursor, keys = db.scan(cursor, pattern, count)
            return RESPSerializer.encode_array([str(next_cursor), keys])

        def cmd_randomkey(client, db, args) -> bytes:
            key = db.random_key()
            if key is None:
                return RESPSerializer.encode_bulk_string(None)
            return RESPSerializer.encode_bulk_string(key)

        self.register(CommandSpec("DEL", cmd_del, 1, -1, {"write"}))
        self.register(CommandSpec("EXISTS", cmd_exists, 1, -1, {"readonly", "fast"}))
        self.register(CommandSpec("KEYS", cmd_keys, 1, 1, {"readonly"}))
        self.register(CommandSpec("TYPE", cmd_type, 1, 1, {"readonly", "fast"}))
        self.register(CommandSpec("RENAME", cmd_rename, 2, 2, {"write"}))
        self.register(CommandSpec("EXPIRE", cmd_expire, 2, 2, {"write"}))
        self.register(CommandSpec("PEXPIRE", cmd_pexpire, 2, 2, {"write"}))
        self.register(CommandSpec("TTL", cmd_ttl, 1, 1, {"readonly", "fast"}))
        self.register(CommandSpec("PTTL", cmd_pttl, 1, 1, {"readonly", "fast"}))
        self.register(CommandSpec("PERSIST", cmd_persist, 1, 1, {"write"}))
        self.register(CommandSpec("SCAN", cmd_scan, 1, -1, {"readonly"}))
        self.register(CommandSpec("RANDOMKEY", cmd_randomkey, 0, 0, {"readonly"}))