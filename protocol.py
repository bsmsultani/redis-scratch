
from typing import Any, Optional, List

class RESPError(Exception):


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



class _Incomplete(Exception):

    pass




class RESPParser:


    def __init__(self) -> None:

        self._buffer: bytearray = bytearray()

        self._pos: int = 0
    def feed(self, data: bytes) -> None:

        self._buffer.extend(data)

    def parse_one(self) -> Optional[Any]:

        if self._pos >= len(self._buffer):
            return None

        saved_pos = self._pos

        try:
            result = self._parse_next()

            self._buffer = self._buffer[self._pos:]
            self._pos = 0

            return result

        except _Incomplete:
            # Not enough data yet — rollback and wait for more bytes.
            self._pos = saved_pos
            return None

    def has_complete_message(self) -> bool:

        saved_pos = self._pos
        try:
            self._parse_next()
            self._pos = saved_pos  # rollback — we're just peeking
            return True
        except _Incomplete:
            self._pos = saved_pos
            return False
    def _parse_next(self) -> Any:

        type_byte = self._read_byte()


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

            return self._parse_inline_command(type_byte)



    def _parse_simple_string(self) -> str:

        line = self._read_line()
        return line

    def _parse_error(self) -> RESPError:

        line = self._read_line()
        return RESPError(line)

    def _parse_integer(self) -> int:

        line = self._read_line()
        return int(line)

    def _parse_bulk_string(self) -> Optional[str]:

        # Step 1: Read the length prefix
        length_line = self._read_line()
        length = int(length_line)

        if length == -1:
            return None

        data = self._read_bytes(length)

        crlf = self._read_bytes(2)
        if crlf != b'\r\n':
            raise ValueError(
                f"Expected \\r\\n after bulk string data, got {crlf!r}"
            )


        return data.decode('utf-8')

    def _parse_array(self) -> Optional[list]:

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

        self._read_line()  # reads empty string before \r\n
        return None

    def _parse_inline_command(self, first_byte: int) -> list:

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

        if self._pos >= len(self._buffer):
            raise _Incomplete()

        byte = self._buffer[self._pos]
        self._pos += 1
        return byte

    def _read_line(self) -> str:

        crlf_pos = self._buffer.find(b'\r\n', self._pos)

        if crlf_pos == -1:
            raise _Incomplete()

        line_bytes = self._buffer[self._pos:crlf_pos]

        self._pos = crlf_pos + 2

        return line_bytes.decode('utf-8')

    def _read_bytes(self, count: int) -> bytes:

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



class RESPSerializer:


    @staticmethod
    def encode_simple_string(value: str) -> bytes:

        return f"+{value}\r\n".encode('utf-8')

    @staticmethod
    def encode_error(message: str) -> bytes:

        return f"-{message}\r\n".encode('utf-8')

    @staticmethod
    def encode_integer(value: int) -> bytes:

        return f":{value}\r\n".encode('utf-8')

    @staticmethod
    def encode_bulk_string(value: Optional[str]) -> bytes:

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

        # ─── None → Null bulk string ─────────────────────────────────
        if obj is None:
            return RESPSerializer.encode_bulk_string(None)

        # Check BEFORE str because we want errors to use the '-' prefix.
        if isinstance(obj, RESPError):
            return RESPSerializer.encode_error(obj.message)

        # MUST be checked before int because bool is a subclass of int.
        if isinstance(obj, bool):
            return RESPSerializer.encode_integer(1 if obj else 0)

        if isinstance(obj, int):
            return RESPSerializer.encode_integer(obj)

        if isinstance(obj, float):
            return RESPSerializer.encode_bulk_string(str(obj))

        if isinstance(obj, str):
            return RESPSerializer.encode_bulk_string(obj)

        if isinstance(obj, (list, tuple)):
            return RESPSerializer.encode_array(list(obj))

        # ─── Unknown type ────────────────────────────────────────────
        raise TypeError(
            f"Cannot encode object of type {type(obj).__name__} to RESP. "
            f"Supported types: None, bool, int, float, str, list, tuple, RESPError."
        )

    @staticmethod
    def encode_command(*args: str) -> bytes:
        return RESPSerializer.encode_array(list(args))

