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


class _incomplete(Exception):
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
            return _incomplete()

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


    def _parse_simple_string(self) -> int:
        """
        Parse a simple string: +<content>\r\n

        
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
        