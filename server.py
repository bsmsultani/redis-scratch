from typing import Any, Optional, List

class RESPError(Exception):
    """
    Represents a Redis protocol error.
    Examples of Redis errors:
        - "ERR unknown command 'FOOBAR'"
        - "WRONGTYPE Operation against a key holding the wrong kind of value"
        - "ERR value is not an integer or out of range"

    Usage:
        raise RESPError("ERR unkown command 'FOOBAR'")

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


class _Incomplete(Exception):
    """
    Internal signal: the buffer doesn't have enough bytes to complete parsing.
    Never escapes the parser - caught by parser_one() and converted to None.
    
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



class RESPParser():
    def __init__(self):
        self._buffer : bytearray = bytearray()
        self._pos : int = 0

    def feed(self, data : bytes) -> None:
        """
        Append raw data from the network into the internal buffer.

        Args:
            data: Raw Bytes receieved from the TCP socket.
        """
        self._buffer.extend(data)

    def parse_one(self) -> Optional[Any]:
        """
        Try to parse one complete RESP message from the buffer.

        Returns:
            - The parsed python object (str, int, list, None or RESPError)
              if a complete message was avaliable. 
            - None if buffer doesn't contain a complete message yet.
        """

        if self._pos >= len(self._buffer):
            return None
        saved_pos = self._pos


    def _read_byte(self) -> int:
        """
        Read a single byte from the buffer and advance the position.

        Returns:
            int: the byte value (0 - 255)
        
        Raises:
            _Incomplete: If the buffer is exhausted.

        Time complexity: O(1)
        """
        if self._pos >= len(self._buffer):
            return _Incomplete()

        byte = self._buffer[self._pos]
        self._pos += 1
        return byte


    def parse_next(self) -> Any:
        """
        Parse the current RESP element starting at the current position

        This is a TYPE DISPATCHER - it reads the first byte to determine the RESP type,
        then delegates to the approperiate sub-parser
        """

        type_byte = self._read_byte()

        # DISPATCH TABLE - each RESP type has a one-byte prefix. We dispatch it based on that
        if type_byte == ord("+"):
            # Simple String: +OK\r\n
            return self._parse_simple_string()

        elif type_byte == ord("-"):
            # SIMPLE: -ERR message\r\n
            return self._parse_error()
        
        elif type_byte == ord(":"):
            # Integer: 1000\r\n
            return self._parse_integer()
        
        elif type_byte == ord("$"):
            # Bulk String: $5\r\nhello\r\n or $-1\r\n (null)
            return self._parse_bulk_string()

        elif type_byte == ord("*"):
            # Array: *2\r\n...\r\n or *-1\r\n (null)
            return self._parse_array()

        elif type_byte == ord("_"):
            # Null (RESP3): _\r\n
            return self._parse_null()

        else:

            return self._parse_inline_command(type_byte)
        

    def _parse_bulk_string(self):

        length_line = self._read_line()
        length = int(length_line)

        if length == -1:
            return None
        

        data = self._read_byte(length)
        crlf = self._read_byte(2)
        
    
    def _parse_integer(self):
        """
        Parse an Integer: :<number>\r\n


        Returns:
            int: the parsed integer value.

        Raises:
            ValueError: if the content is not a valid integer.

        time complexity: O(d) where d is the number of digits
        
        """
        line = self._read_line()
        return int(line)


    
    def _parse_error(self) -> int:
        """
        Parse an Error: -<error message>\r\n

        Errors look just like simple strings but are semantically different.
        By wrapping them in RESPError, the calling code can be distinguish:

        result = parser.parse_one()
        if isinstance(result, RESPError):
            print(f"Server error: {result.message}")
        else:
            print(f"Success: {result}")
        
        """
        line = self._read_line()
        return RESPError(line)



    def _parse_simple_string(self) -> int:
        """
        Parse a simple string: +<content>\r\n

        EXAMPLES:
            +OK\r\n     -> "OK"
            +PONG\r\n   -> "PONG"
            +QUEUED\r\n -> "QUEUED"
        """
        line = self._read_line()
        return line



    def _read_line(self) -> str:
        """
        Read bytes until \r\n is found. Return content WITHOUT the \r\n.


        Returns:
            str: The line content (without \r\n)

        Raises:
            _Incomplete: if \r\n hasn't arrvied yet
        
        time Complexity: O(k) where k = length of the line
        """
        crlf_pos = self._buffer.find(b'\r\n', self._pos)
        if crlf_pos == -1:
            return _Incomplete()

        line_bytes = self._buffer[self._pos: crlf_pos]
        self._pos = crlf_pos + 2

        return line_bytes.decode('utf-8')