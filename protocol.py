from typing import Any, Optional, List


class RESPError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"RESPError({self.message!r})"

    def __eq__(self, other: object) -> bool:
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
            # not enough data yet, wait for more
            self._pos = saved_pos
            return None

    def has_complete_message(self) -> bool:
        saved_pos = self._pos
        try:
            self._parse_next()
            self._pos = saved_pos
            return True
        except _Incomplete:
            self._pos = saved_pos
            return False

    def _parse_next(self) -> Any:
        type_byte = self._read_byte()

        if type_byte == ord('+'):
            return self._parse_simple_string()
        elif type_byte == ord('-'):
            return self._parse_error()
        elif type_byte == ord(':'):
            return self._parse_integer()
        elif type_byte == ord('$'):
            return self._parse_bulk_string()
        elif type_byte == ord('*'):
            return self._parse_array()
        elif type_byte == ord('_'):
            return self._parse_null()
        else:
            return self._parse_inline_command(type_byte)

    def _parse_simple_string(self) -> str:
        return self._read_line()

    def _parse_error(self) -> RESPError:
        return RESPError(self._read_line())

    def _parse_integer(self) -> int:
        return int(self._read_line())

    def _parse_bulk_string(self) -> Optional[str]:
        length = int(self._read_line())
        if length == -1:
            return None
        data = self._read_bytes(length)
        crlf = self._read_bytes(2)
        if crlf != b'\r\n':
            raise ValueError(f"Expected \\r\\n after bulk string data, got {crlf!r}")
        return data.decode('utf-8')

    def _parse_array(self) -> Optional[list]:
        count = int(self._read_line())
        if count == -1:
            return None
        elements: list = []
        for _ in range(count):
            elements.append(self._parse_next())
        return elements

    def _parse_null(self) -> None:
        self._read_line()
        return None

    def _parse_inline_command(self, first_byte: int) -> list:
        rest_of_line = self._read_line()
        full_line = chr(first_byte) + rest_of_line
        return full_line.split()

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

    def reset(self) -> None:
        self._buffer = bytearray()
        self._pos = 0

    @property
    def buffer_size(self) -> int:
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
        # use byte length, not char length (matters for multi-byte utf-8)
        encoded = value.encode('utf-8')
        length = len(encoded)
        return f"${length}\r\n".encode('utf-8') + encoded + b"\r\n"

    @staticmethod
    def encode_array(items: Optional[List]) -> bytes:
        if items is None:
            return b"*-1\r\n"
        result = f"*{len(items)}\r\n".encode('utf-8')
        for item in items:
            result += RESPSerializer.encode(item)
        return result

    @staticmethod
    def encode(obj: Any) -> bytes:
        if obj is None:
            return RESPSerializer.encode_bulk_string(None)
        if isinstance(obj, RESPError):
            return RESPSerializer.encode_error(obj.message)
        # check bool before int — bool is a subclass of int
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
        raise TypeError(
            f"Cannot encode object of type {type(obj).__name__} to RESP. "
            f"Supported types: None, bool, int, float, str, list, tuple, RESPError."
        )

    @staticmethod
    def encode_command(*args: str) -> bytes:
        return RESPSerializer.encode_array(list(args))
