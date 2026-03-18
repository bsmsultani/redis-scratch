"""
protocol.py — RESP (REdis Serialization Protocol) Parser & Serializer
======================================================================

WHAT IS RESP?
-------------
RESP is the wire protocol Redis uses for client-server communication.
Every command you type in redis-cli (like "SET name Alice") gets serialized
into RESP bytes before being sent over TCP, and every response comes back
as RESP bytes too.

Think of it like JSON for Redis — a simple, human-readable-ish format for
encoding structured data over the wire.

WHY BUILD THIS FIRST?
---------------------
1. It's a standalone module with ZERO dependencies on the rest of the project.
   You can test it in complete isolation.
2. It teaches PARSING — a skill tested in many FAANG interviews:
   - LeetCode #394 (Decode String) uses the same recursive descent approach
   - LeetCode #722 (Remove Comments) is similar buffer/state tracking
   - System design: "How would you design a protocol?" comes up at Amazon/Google
3. It teaches BUFFER MANAGEMENT — handling partial TCP reads is a real-world
   problem in any networked system.

RESP DATA TYPES
---------------
Each RESP message starts with a single byte that identifies its type:

    +  Simple String   →  +OK\r\n                         (status replies)
    -  Error           →  -ERR unknown command\r\n         (error replies)
    :  Integer         →  :1000\r\n                        (numeric replies)
    $  Bulk String     →  $5\r\nhello\r\n                  (binary-safe strings)
    *  Array           →  *2\r\n$3\r\nGET\r\n$4\r\nname\r\n  (lists of elements)
    _  Null            →  _\r\n                            (null/nil value)

Every line ends with \r\n (CRLF), just like HTTP.

KEY DESIGN CHALLENGE: PARTIAL READS
------------------------------------
TCP is a STREAM protocol, not a MESSAGE protocol. When we do socket.recv(4096),
we might get:
  - Exactly one complete message          ✓ easy
  - Multiple complete messages            ✓ need to parse in a loop
  - Half a message (rest comes later)     ✗ must NOT crash — save state and wait
  - End of one message + start of another ✗ must parse first, save remainder

Our parser handles ALL of these cases by:
  1. Accumulating bytes in a buffer (feed())
  2. Attempting to parse from the buffer (parse_one())
  3. If parsing fails due to incomplete data → raise _Incomplete → return None
  4. If parsing succeeds → consume those bytes from buffer, return the result

This is the same pattern used in production protocol parsers (HTTP, gRPC, etc.).

DSA CONCEPTS IN THIS FILE
--------------------------
- Recursive descent parsing (parse_array calls parse_one recursively)
- State machine (type byte dispatches to different parse paths)
- Buffer management (tracking position, compacting consumed bytes)
- Serialization / Deserialization (encoding Python objects ↔ bytes)
"""

from typing import Any, Optional, List


# =============================================================================
# CUSTOM EXCEPTION: RESPERROR
# =============================================================================
# In Redis, errors are a FIRST-CLASS data type in the protocol (the '-' type).
# We model this as a Python exception so that:
#   1. The server can RAISE errors in command handlers
#   2. The serializer can catch them and encode as RESP errors
#   3. The client can distinguish errors from normal strings
#
# OOP Concept: Custom exceptions inherit from Exception, allowing us to use
# Python's exception hierarchy for type-safe error handling.
# =============================================================================

class RESPError(Exception):
    """
    Represents a Redis protocol error.

    Examples of Redis errors:
        - "ERR unknown command 'FOOBAR'"
        - "WRONGTYPE Operation against a key holding the wrong kind of value"
        - "ERR value is not an integer or out of range"

    Usage:
        raise RESPError("ERR unknown command 'FOOBAR'")
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"RESPError({self.message!r})"

    def __eq__(self, other: object) -> bool:
        """Allow comparison in tests: assert result == RESPError('ERR ...')"""
        if isinstance(other, RESPError):
            return self.message == other.message
        return NotImplemented


# =============================================================================
# SENTINEL: INCOMPLETE PARSE SIGNAL
# =============================================================================
# This is a PRIVATE exception used ONLY inside the parser. It is never exposed
# to the outside world. When a sub-parser runs out of bytes mid-message, it
# raises _Incomplete. The top-level parse_one() catches it, resets the buffer
# position, and returns None ("I don't have enough data yet, feed me more").
#
# Why not just return None from sub-parsers?
#   Because None is a VALID parse result! ($-1\r\n is a null bulk string.)
#   We need a way to distinguish "parsed successfully as null" from
#   "not enough bytes to parse." A sentinel exception solves this cleanly.
#
# Design Pattern: This is the "Sentinel Value" pattern — using a special
# marker to represent an exceptional state without ambiguity.
# =============================================================================

class _Incomplete(Exception):
    """
    Internal signal: the buffer doesn't have enough bytes to complete parsing.
    Never escapes the parser — caught by parse_one() and converted to None.
    """
    pass


# =============================================================================
# RESP PARSER
# =============================================================================
# The parser takes raw bytes from the network and produces Python objects.
#
# Architecture:
#   ┌──────────┐    feed()    ┌──────────┐   parse_one()   ┌──────────┐
#   │  Network  │ ──────────→ │  Buffer   │ ──────────────→ │  Python  │
#   │  (bytes)  │             │  (bytes)  │                 │  object  │
#   └──────────┘              └──────────┘                  └──────────┘
#
# The buffer acts as a STAGING AREA between the unpredictable network and
# the structured parser. This decoupling is a key design principle in
# networked systems.
#
# COMPLEXITY ANALYSIS:
#   - feed(): O(n) where n = bytes received (memoryview could optimize this)
#   - parse_one(): O(m) where m = size of one RESP message
#   - Space: O(b) where b = total buffered bytes
# =============================================================================

class RESPParser:
    """
    Incremental parser for the RESP protocol.

    "Incremental" means it can handle partial data gracefully. You feed it
    bytes as they arrive from the network, and it yields complete messages
    as soon as they're available.

    Usage:
        parser = RESPParser()
        parser.feed(b"+OK\r\n")          # feed raw bytes
        result = parser.parse_one()       # returns "OK"
        result = parser.parse_one()       # returns None (buffer empty)

        # Partial read scenario:
        parser.feed(b"$5\r\nhel")         # only half the bulk string arrived
        result = parser.parse_one()       # returns None (incomplete!)
        parser.feed(b"lo\r\n")            # rest arrives
        result = parser.parse_one()       # returns "hello"
    """

    def __init__(self) -> None:
        # ─── THE BUFFER ───────────────────────────────────────────────
        # We store incoming bytes in a bytearray (mutable bytes).
        # Why bytearray and not bytes?
        #   - bytes is IMMUTABLE → concatenation creates a new copy every time → O(n²)
        #   - bytearray is MUTABLE → we can extend in place → O(n) amortized
        #
        # Interview parallel: This is the same tradeoff as StringBuilder vs
        # String concatenation in Java — a classic question.
        # ──────────────────────────────────────────────────────────────
        self._buffer: bytearray = bytearray()

        # ─── THE POSITION CURSOR ──────────────────────────────────────
        # Instead of slicing/copying the buffer every time we consume bytes,
        # we track a read position. This avoids O(n) copies on every parse.
        #
        # When parse_one() succeeds, _pos advances past the consumed bytes.
        # When it fails (_Incomplete), _pos resets to where it started.
        #
        # After a successful parse, we compact the buffer (remove consumed
        # bytes from the front) to prevent unbounded memory growth.
        #
        #   _buffer:  [consumed bytes | unprocessed bytes | free space]
        #              ^                ^
        #              0                _pos (read cursor)
        # ──────────────────────────────────────────────────────────────
        self._pos: int = 0

    # =====================================================================
    # PUBLIC API
    # =====================================================================

    def feed(self, data: bytes) -> None:
        """
        Append raw bytes from the network into the internal buffer.

        This is called every time the server does a socket.recv(). The data
        might contain zero, one, or multiple complete RESP messages, or even
        a partial message. We don't care — we just accumulate.

        Args:
            data: Raw bytes received from the TCP socket.

        Time Complexity: O(n) where n = len(data)
            bytearray.extend() is amortized O(n) — similar to list.append()
            because bytearray over-allocates capacity internally.
        """
        self._buffer.extend(data)

    def parse_one(self) -> Optional[Any]:
        """
        Try to parse ONE complete RESP message from the buffer.

        Returns:
            - The parsed Python object (str, int, list, None, or RESPError)
              if a complete message was available.
            - None if the buffer doesn't contain a complete message yet.

        This is the MAIN ENTRY POINT for the parser. It:
        1. Saves the current position (in case we need to rollback)
        2. Tries to parse a complete message via _parse_next()
        3. On success: compacts the buffer and returns the result
        4. On failure (_Incomplete): rolls back position and returns None

        IMPORTANT DESIGN DECISION — WHY RETURN NONE FOR INCOMPLETE?
        In a real server, after calling parse_one() and getting None, you'd
        go back to the event loop and wait for more data. When more bytes
        arrive, you feed() them and try parse_one() again. This is the
        standard non-blocking I/O pattern.

        Time Complexity: O(m) where m = size of one RESP message
        """
        # Nothing to parse
        if self._pos >= len(self._buffer):
            return None

        # Save position so we can rollback on incomplete data.
        # This is like a DATABASE SAVEPOINT — if the transaction (parse)
        # fails, we roll back to this point.
        saved_pos = self._pos

        try:
            result = self._parse_next()

            # ─── BUFFER COMPACTION ────────────────────────────────────
            # After successfully parsing, remove consumed bytes from the
            # front of the buffer. Without this, the buffer grows forever.
            #
            # We do this by slicing: buffer = buffer[pos:]
            # This is O(remaining_bytes), which is acceptable because:
            #   1. We only compact on successful parse (not on every call)
            #   2. In practice, the remaining bytes are usually small
            #
            # A more advanced approach would use a circular buffer (ring
            # buffer) for O(1) compaction, but that adds complexity.
            # ──────────────────────────────────────────────────────────
            self._buffer = self._buffer[self._pos:]
            self._pos = 0

            return result

        except _Incomplete:
            # Not enough data yet — rollback and wait for more bytes.
            self._pos = saved_pos
            return None

    def has_complete_message(self) -> bool:
        """
        Peek at the buffer to check if at least one complete message exists.

        This is a NON-DESTRUCTIVE check — it doesn't consume any bytes.
        Useful for the server to decide whether to call parse_one().

        Implementation: we attempt a parse, then rollback regardless.
        This is a "speculative execution" — try it and undo if needed.

        Time Complexity: O(m) where m = size of the next message.
        """
        saved_pos = self._pos
        try:
            self._parse_next()
            self._pos = saved_pos  # rollback — we're just peeking
            return True
        except _Incomplete:
            self._pos = saved_pos
            return False

    # =====================================================================
    # CORE DISPATCHER
    # =====================================================================

    def _parse_next(self) -> Any:
        """
        Parse the next RESP element starting at the current buffer position.

        This is a TYPE DISPATCHER — it reads the first byte to determine
        the RESP type, then delegates to the appropriate sub-parser.

        This is the RECURSIVE DESCENT pattern:
        - _parse_next() is the top-level rule
        - Each _parse_*() method is a sub-rule
        - _parse_array() calls _parse_next() recursively for each element

        The same pattern is used in:
        - JSON parsers
        - Expression evaluators (LeetCode #224, #772)
        - HTML/XML parsers
        - Compilers (recursive descent is the simplest parsing technique)

        Raises:
            _Incomplete: If there aren't enough bytes in the buffer.
            ValueError: If the type byte is not a recognized RESP type.
        """
        # Read the type byte. _read_byte() raises _Incomplete if buffer is empty.
        type_byte = self._read_byte()

        # ─── DISPATCH TABLE ───────────────────────────────────────────
        # Each RESP type has a one-byte prefix. We dispatch based on it.
        #
        # Interview note: This is essentially a SWITCH/MATCH statement.
        # In a language with enums (Java, Rust), you'd use a switch.
        # In Python, if/elif chains or a dict dispatch table work.
        #
        # We use if/elif here for clarity, but a dict-based dispatch
        # would be more extensible:
        #   dispatch = {ord('+'): self._parse_simple_string, ...}
        #   return dispatch[type_byte]()
        # ──────────────────────────────────────────────────────────────

        if type_byte == ord('+'):
            # Simple String: +OK\r\n
            return self._parse_simple_string()

        elif type_byte == ord('-'):
            # Error: -ERR message\r\n
            return self._parse_error()

        elif type_byte == ord(':'):
            # Integer: :1000\r\n
            return self._parse_integer()

        elif type_byte == ord('$'):
            # Bulk String: $5\r\nhello\r\n  or  $-1\r\n (null)
            return self._parse_bulk_string()

        elif type_byte == ord('*'):
            # Array: *2\r\n...\r\n  or  *-1\r\n (null)
            return self._parse_array()

        elif type_byte == ord('_'):
            # Null (RESP3): _\r\n
            return self._parse_null()

        else:
            # ─── INLINE COMMAND SUPPORT ───────────────────────────────
            # Real redis-cli also supports "inline" commands where you
            # just type: PING\r\n  (no RESP framing at all).
            # We handle this as a fallback: if the first byte isn't a
            # known type prefix, treat the entire line as a space-
            # separated inline command.
            # ──────────────────────────────────────────────────────────
            return self._parse_inline_command(type_byte)

    # =====================================================================
    # SUB-PARSERS — One for each RESP type
    # =====================================================================

    def _parse_simple_string(self) -> str:
        """
        Parse a Simple String: +<content>\r\n

        Simple strings are used for short, non-binary status replies like
        "OK", "PONG", "QUEUED". They CANNOT contain \r or \n characters
        (use bulk strings for binary data).

        Examples:
            +OK\r\n          → "OK"
            +PONG\r\n        → "PONG"
            +QUEUED\r\n      → "QUEUED"

        Returns:
            str: The string content (without the + prefix or \r\n suffix).

        Time Complexity: O(k) where k = length of the string.
        """
        line = self._read_line()
        return line

    def _parse_error(self) -> RESPError:
        """
        Parse an Error: -<error message>\r\n

        Errors look just like simple strings but are semantically different.
        By wrapping them in RESPError, the calling code can distinguish:

            result = parser.parse_one()
            if isinstance(result, RESPError):
                print(f"Server error: {result.message}")
            else:
                print(f"Success: {result}")

        Examples:
            -ERR unknown command 'FOOBAR'\r\n
            -WRONGTYPE Operation against a key holding the wrong kind of value\r\n

        The first word (before the space) is conventionally the error TYPE
        (ERR, WRONGTYPE, MOVED, etc.), and the rest is the human-readable message.

        Returns:
            RESPError: An error object wrapping the message.
        """
        line = self._read_line()
        return RESPError(line)

    def _parse_integer(self) -> int:
        """
        Parse an Integer: :<number>\r\n

        Redis uses integers for many replies:
            - INCR/DECR return the new value
            - LLEN returns list length
            - EXISTS returns 0 or 1
            - DEL returns count of deleted keys

        Examples:
            :0\r\n      → 0
            :1000\r\n   → 1000
            :-42\r\n    → -42

        Returns:
            int: The parsed integer value.

        Raises:
            ValueError: If the content is not a valid integer.

        Time Complexity: O(d) where d = number of digits.
        """
        line = self._read_line()
        return int(line)

    def _parse_bulk_string(self) -> Optional[str]:
        """
        Parse a Bulk String: $<length>\r\n<data>\r\n

        Bulk strings are the workhorse of RESP. Unlike simple strings, they:
        1. Can contain ANY bytes (binary safe — can include \r\n, \0, etc.)
        2. Have an explicit length prefix (so we know exactly how many bytes to read)
        3. Can represent NULL with $-1\r\n

        This is the most COMPLEX sub-parser because it involves TWO reads:
        one for the length line, one for the data block.

        Examples:
            $5\r\nhello\r\n       → "hello"     (5 bytes of content)
            $0\r\n\r\n            → ""          (empty string, NOT null)
            $-1\r\n               → None        (null bulk string)
            $11\r\nhello\r\nworld\r\n → "hello\r\nworld"  (contains \r\n!)

        The null case ($-1) is how Redis represents "key does not exist"
        when you do GET on a missing key.

        HOW IT WORKS:
        1. Read the length line → get the byte count
        2. If length is -1 → return None (null)
        3. Read exactly `length` bytes from the buffer
        4. Read the trailing \r\n
        5. Return the data as a string

        Returns:
            str if data present, None if null ($-1).

        Time Complexity: O(n) where n = length of the string.
        """
        # Step 1: Read the length prefix
        length_line = self._read_line()
        length = int(length_line)

        # Step 2: Handle null bulk string
        # $-1\r\n means "null" — the key doesn't exist, or the value is nil.
        if length == -1:
            return None

        # Step 3: Read exactly `length` bytes of content
        # Unlike _read_line(), we read a FIXED number of bytes here.
        # This is what makes bulk strings "binary safe" — we don't scan for
        # \r\n in the data, we trust the length prefix.
        data = self._read_bytes(length)

        # Step 4: Read and discard the trailing \r\n
        # Every RESP element ends with \r\n, even after the bulk data.
        crlf = self._read_bytes(2)
        if crlf != b'\r\n':
            raise ValueError(
                f"Expected \\r\\n after bulk string data, got {crlf!r}"
            )

        # Step 5: Decode bytes to string
        # Note: Real Redis is binary-safe (values can be raw bytes).
        # We decode as UTF-8 for convenience in this implementation.
        # A production version might return bytes and let the caller decide.
        return data.decode('utf-8')

    def _parse_array(self) -> Optional[list]:
        """
        Parse an Array: *<count>\r\n<element1><element2>...

        Arrays are how COMMANDS are sent from client to server.
        The command "SET name Alice" becomes:

            *3\r\n        ← array of 3 elements
            $3\r\nSET\r\n ← first element: bulk string "SET"
            $4\r\nname\r\n ← second: bulk string "name"
            $5\r\nAlice\r\n ← third: bulk string "Alice"

        Arrays can also NEST (arrays of arrays), which is how commands
        like EXEC return their results.

        THIS IS WHERE RECURSION HAPPENS:
        We read the count, then call self._parse_next() for each element.
        Each element can be ANY RESP type — including another array!

        Examples:
            *0\r\n                                → []         (empty array)
            *-1\r\n                               → None       (null array)
            *2\r\n$3\r\nfoo\r\n$3\r\nbar\r\n     → ["foo", "bar"]
            *3\r\n:1\r\n:2\r\n:3\r\n             → [1, 2, 3]
            *2\r\n*1\r\n:1\r\n*1\r\n:2\r\n       → [[1], [2]]  (nested!)

        RECURSION DEPTH:
        In practice, Redis arrays rarely nest more than 2-3 levels deep.
        But our parser handles arbitrary nesting because _parse_next()
        dispatches to _parse_array() which calls _parse_next() again.

        Interview parallel: This is the same recursion pattern as:
        - LeetCode #394 "Decode String": k[encoded_string]
        - LeetCode #341 "Flatten Nested List Iterator"
        - Any recursive descent parser

        Returns:
            list if array present, None if null (*-1).

        Time Complexity: O(n) total across all elements.
        """
        # Step 1: Read the element count
        count_line = self._read_line()
        count = int(count_line)

        # Step 2: Handle null array
        if count == -1:
            return None

        # Step 3: Parse each element recursively
        # _parse_next() will dispatch to the correct sub-parser based on
        # the type byte of each element. If ANY element is incomplete,
        # _Incomplete propagates up and the ENTIRE array parse is rolled back.
        elements: list = []
        for _ in range(count):
            element = self._parse_next()
            elements.append(element)

        return elements

    def _parse_null(self) -> None:
        """
        Parse a RESP3 Null: _\r\n

        RESP3 introduced a dedicated null type (separate from null bulk
        strings and null arrays). This is cleaner but we include it for
        completeness.

        Returns:
            None
        """
        # Just consume the trailing \r\n
        self._read_line()  # reads empty string before \r\n
        return None

    def _parse_inline_command(self, first_byte: int) -> list:
        """
        Parse an inline command (non-RESP plain text).

        When a human telnets to Redis and types "PING\r\n", there's no
        RESP framing — it's just raw text. Redis supports this for
        convenience. We treat the entire line as a space-separated command.

        Example:
            PING\r\n              → ["PING"]
            SET name Alice\r\n    → ["SET", "name", "Alice"]

        We already consumed the first byte (in _parse_next), so we need
        to prepend it to whatever _read_line() gives us.

        Args:
            first_byte: The byte we already read (not a RESP type prefix).

        Returns:
            list: The command split into parts.
        """
        rest_of_line = self._read_line()

        # Reconstruct the full line: first_byte + rest
        full_line = chr(first_byte) + rest_of_line

        # Split on whitespace, filter empty strings
        parts = full_line.split()
        return parts

    # =====================================================================
    # LOW-LEVEL BUFFER OPERATIONS
    # =====================================================================
    # These are the "primitives" that all sub-parsers are built on.
    # There are only THREE operations:
    #   1. Read one byte
    #   2. Read until \r\n (line-oriented)
    #   3. Read exactly N bytes (length-prefixed)
    #
    # All three raise _Incomplete if there aren't enough bytes.
    # =====================================================================

    def _read_byte(self) -> int:
        """
        Read a single byte from the buffer and advance the position.

        Returns:
            int: The byte value (0-255).

        Raises:
            _Incomplete: If the buffer is exhausted.

        Time Complexity: O(1)
        """
        if self._pos >= len(self._buffer):
            raise _Incomplete()

        byte = self._buffer[self._pos]
        self._pos += 1
        return byte

    def _read_line(self) -> str:
        """
        Read bytes until \r\n is found. Return content WITHOUT the \r\n.

        This is used for simple strings, errors, integers, and length
        prefixes — any "line-oriented" part of the protocol.

        HOW IT WORKS:
        We scan forward from _pos looking for the \r\n sequence.
        If found, we extract everything between _pos and the \r\n,
        advance _pos past the \r\n, and return the content as a string.

        WHY SCAN FOR \r\n AND NOT JUST \n?
        RESP mandates \r\n (CRLF) as the line terminator, just like HTTP.
        If we only checked for \n, a bulk string containing \r could
        confuse the parser. The two-byte terminator is more robust.

        Returns:
            str: The line content (without \r\n).

        Raises:
            _Incomplete: If \r\n hasn't arrived yet.

        Time Complexity: O(k) where k = length of the line.
        """
        # Look for \r\n starting from current position.
        # bytearray.find() returns -1 if not found.
        #
        # We search for b'\r\n' which is efficient — Python's find()
        # uses an optimized algorithm internally (Boyer-Moore variant).
        crlf_pos = self._buffer.find(b'\r\n', self._pos)

        if crlf_pos == -1:
            # \r\n not found — the complete line hasn't arrived yet.
            # Raise _Incomplete to signal "feed me more bytes."
            raise _Incomplete()

        # Extract the content between current position and the \r\n.
        line_bytes = self._buffer[self._pos:crlf_pos]

        # Advance position past the \r\n (hence +2).
        self._pos = crlf_pos + 2

        # Decode to string. Using 'utf-8' is safe for RESP because
        # line-oriented content (types +, -, :) is always ASCII-compatible.
        return line_bytes.decode('utf-8')

    def _read_bytes(self, count: int) -> bytes:
        """
        Read exactly `count` bytes from the buffer.

        This is used for bulk string DATA (after the length prefix).
        Unlike _read_line(), we don't scan for a delimiter — we read
        a fixed number of bytes based on the length we already parsed.

        Args:
            count: Exact number of bytes to read.

        Returns:
            bytes: Exactly `count` bytes.

        Raises:
            _Incomplete: If fewer than `count` bytes are available.

        Time Complexity: O(count) for the slice.
        """
        if self._pos + count > len(self._buffer):
            raise _Incomplete()

        data = bytes(self._buffer[self._pos:self._pos + count])
        self._pos += count
        return data

    # =====================================================================
    # UTILITY METHODS
    # =====================================================================

    def reset(self) -> None:
        """Clear the buffer and reset state. Useful for error recovery."""
        self._buffer = bytearray()
        self._pos = 0

    @property
    def buffer_size(self) -> int:
        """How many unprocessed bytes remain in the buffer."""
        return len(self._buffer) - self._pos

    def __repr__(self) -> str:
        return (
            f"RESPParser(buffer_size={self.buffer_size}, "
            f"pos={self._pos}, "
            f"total_buffer={len(self._buffer)})"
        )


# =============================================================================
# RESP SERIALIZER
# =============================================================================
# The serializer does the REVERSE of the parser: it takes Python objects and
# converts them into RESP bytes for sending over the wire.
#
# The server uses this to encode responses.
# The client uses this to encode commands.
#
# DESIGN: All methods are @staticmethod because the serializer is STATELESS.
# It doesn't need to track any buffer or position — each call is independent.
# This makes it thread-safe and easy to test.
#
# OOP Concept: @staticmethod vs @classmethod vs instance method
#   - Instance method: needs self (access to instance state)
#   - Class method: needs cls (access to class, useful for factory patterns)
#   - Static method: needs neither (pure function, just logically grouped)
#
# The serializer is a collection of pure functions — no state needed.
# =============================================================================

class RESPSerializer:
    """
    Encodes Python objects into RESP byte sequences.

    This is the opposite of RESPParser. The parser reads bytes → Python objects.
    The serializer writes Python objects → bytes.

    All methods are static because serialization is STATELESS —
    each encode call is independent with no shared context.

    Usage:
        # Server encoding responses:
        response = RESPSerializer.encode_simple_string("OK")  # b"+OK\r\n"
        response = RESPSerializer.encode_integer(42)           # b":42\r\n"

        # Client encoding commands:
        cmd = RESPSerializer.encode_array(["SET", "name", "Alice"])
        # b"*3\r\n$3\r\nSET\r\n$4\r\nname\r\n$5\r\nAlice\r\n"
    """

    @staticmethod
    def encode_simple_string(value: str) -> bytes:
        """
        Encode a simple string: +<value>\r\n

        Used by the server for status replies like "OK" and "PONG".
        Simple strings MUST NOT contain \r or \n characters.

        Args:
            value: The string to encode (must not contain \\r or \\n).

        Returns:
            bytes: The RESP-encoded simple string.

        Example:
            encode_simple_string("OK")  → b"+OK\r\n"
        """
        return f"+{value}\r\n".encode('utf-8')

    @staticmethod
    def encode_error(message: str) -> bytes:
        """
        Encode an error: -<message>\r\n

        Convention: Start with an error type like "ERR", "WRONGTYPE", etc.

        Args:
            message: The error message.

        Returns:
            bytes: The RESP-encoded error.

        Example:
            encode_error("ERR unknown command")  → b"-ERR unknown command\r\n"
        """
        return f"-{message}\r\n".encode('utf-8')

    @staticmethod
    def encode_integer(value: int) -> bytes:
        """
        Encode an integer: :<value>\r\n

        Args:
            value: The integer to encode (can be negative).

        Returns:
            bytes: The RESP-encoded integer.

        Example:
            encode_integer(1000)  → b":1000\r\n"
            encode_integer(-1)    → b":-1\r\n"
        """
        return f":{value}\r\n".encode('utf-8')

    @staticmethod
    def encode_bulk_string(value: Optional[str]) -> bytes:
        """
        Encode a bulk string: $<length>\r\n<data>\r\n
        Or null: $-1\r\n

        Bulk strings are the PRIMARY way to send data in RESP because
        they're binary-safe (the length prefix means we don't need to
        escape special characters).

        Args:
            value: The string to encode, or None for null.

        Returns:
            bytes: The RESP-encoded bulk string.

        Examples:
            encode_bulk_string("hello")  → b"$5\r\nhello\r\n"
            encode_bulk_string("")       → b"$0\r\n\r\n"
            encode_bulk_string(None)     → b"$-1\r\n"
        """
        if value is None:
            return b"$-1\r\n"

        # Encode to bytes first to get the BYTE length (not char length).
        # This matters for multi-byte UTF-8 characters:
        #   "café" is 4 chars but 5 bytes (é = 2 bytes in UTF-8)
        encoded = value.encode('utf-8')
        length = len(encoded)
        return f"${length}\r\n".encode('utf-8') + encoded + b"\r\n"

    @staticmethod
    def encode_array(items: Optional[List]) -> bytes:
        """
        Encode an array: *<count>\r\n<element1><element2>...
        Or null: *-1\r\n

        Each element is recursively encoded using encode().

        This is the MOST IMPORTANT encoding method because:
        - Clients send ALL commands as arrays of bulk strings
        - Servers return multi-element replies as arrays

        Args:
            items: List of items to encode, or None for null array.
                   Each item is auto-encoded via encode().

        Returns:
            bytes: The RESP-encoded array.

        Example:
            encode_array(["SET", "key", "value"])
            → b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n"

            encode_array([1, "hello", None])
            → b"*3\r\n:1\r\n$5\r\nhello\r\n$-1\r\n"
        """
        if items is None:
            return b"*-1\r\n"

        # Header: *<count>\r\n
        result = f"*{len(items)}\r\n".encode('utf-8')

        # Encode each element. encode() auto-detects the type.
        for item in items:
            result += RESPSerializer.encode(item)

        return result

    @staticmethod
    def encode(obj: Any) -> bytes:
        """
        Auto-detect the type of a Python object and encode it as RESP.

        This is the "smart" encoder that looks at the Python type and
        chooses the right RESP encoding. It's used by encode_array()
        for recursive encoding.

        TYPE MAPPING:
            Python type     → RESP type
            ──────────────────────────────
            None            → Null bulk string ($-1)
            bool            → Integer (True=1, False=0)  ← MUST check before int!
            int             → Integer (:N)
            float           → Bulk string (Redis stores floats as strings)
            str             → Bulk string ($N)
            list / tuple    → Array (*N)
            RESPError       → Error (-msg)

        WHY CHECK bool BEFORE int?
        In Python, bool is a SUBCLASS of int:
            isinstance(True, int)  → True!
        So if we check int first, True would encode as :1 instead of :1.
        They happen to produce the same result here, but it's a good habit
        and a common Python gotcha in interviews.

        Args:
            obj: Any Python object to encode.

        Returns:
            bytes: The RESP-encoded representation.

        Raises:
            TypeError: If the object type is not supported.
        """
        # ─── None → Null bulk string ─────────────────────────────────
        if obj is None:
            return RESPSerializer.encode_bulk_string(None)

        # ─── RESPError → Error ────────────────────────────────────────
        # Check BEFORE str because we want errors to use the '-' prefix.
        if isinstance(obj, RESPError):
            return RESPSerializer.encode_error(obj.message)

        # ─── bool → Integer ──────────────────────────────────────────
        # MUST be checked before int because bool is a subclass of int.
        if isinstance(obj, bool):
            return RESPSerializer.encode_integer(1 if obj else 0)

        # ─── int → Integer ───────────────────────────────────────────
        if isinstance(obj, int):
            return RESPSerializer.encode_integer(obj)

        # ─── float → Bulk string (Redis convention) ──────────────────
        if isinstance(obj, float):
            return RESPSerializer.encode_bulk_string(str(obj))

        # ─── str → Bulk string ───────────────────────────────────────
        if isinstance(obj, str):
            return RESPSerializer.encode_bulk_string(obj)

        # ─── list/tuple → Array ──────────────────────────────────────
        if isinstance(obj, (list, tuple)):
            return RESPSerializer.encode_array(list(obj))

        # ─── Unknown type ────────────────────────────────────────────
        raise TypeError(
            f"Cannot encode object of type {type(obj).__name__} to RESP. "
            f"Supported types: None, bool, int, float, str, list, tuple, RESPError."
        )

    @staticmethod
    def encode_command(*args: str) -> bytes:
        """
        Convenience method: encode a Redis command as a RESP array of bulk strings.

        This is what the CLIENT uses to send commands. Every argument
        becomes a bulk string, wrapped in an array.

        Args:
            *args: Command parts, e.g., "SET", "name", "Alice"

        Returns:
            bytes: RESP-encoded command.

        Example:
            encode_command("SET", "name", "Alice")
            → b"*3\r\n$3\r\nSET\r\n$4\r\nname\r\n$5\r\nAlice\r\n"

            encode_command("GET", "name")
            → b"*2\r\n$3\r\nGET\r\n$4\r\nname\r\n"

            encode_command("PING")
            → b"*1\r\n$4\r\nPING\r\n"
        """
        return RESPSerializer.encode_array(list(args))


# =============================================================================
# MODULE-LEVEL DOCSTRING SUMMARY
# =============================================================================
#
# What you've built:
#   1. RESPParser    — Incremental, stateful parser that handles partial reads
#   2. RESPSerializer — Stateless encoder for all RESP types
#   3. RESPError     — Custom exception for Redis error responses
#
# Key patterns used:
#   - Recursive descent parsing (arrays contain elements parsed recursively)
#   - Sentinel exception (_Incomplete) for flow control
#   - Position-based buffer with rollback for incomplete data
#   - Static methods for stateless operations
#   - Type dispatch (first byte → sub-parser)
#
# What to test (in test_protocol.py):
#   - Round-trip: encode → parse → should equal original
#   - Partial reads: feed half a message, parse → None, feed rest, parse → value
#   - Edge cases: empty strings, null values, negative integers
#   - Nested arrays: arrays containing arrays
#   - Binary safety: bulk strings with \r\n in the data
#   - Inline commands: "PING\r\n" without RESP framing
#   - Error encoding/decoding round-trip
#   - Multiple messages: feed two messages, parse twice
#
# Next step: Build test_protocol.py, then move to rstring.py and database.py.
# =============================================================================
