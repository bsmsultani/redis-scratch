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






class RESPParser():
    def __init__(self):
        self._buffer : bytearray = bytearray()
        self._pos = 0

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

        