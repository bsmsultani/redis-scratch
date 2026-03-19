
"""
rstring.py — Redis String Data Structure
=========================================

The simplest Redis data type, but don't underestimate it.
Redis strings are used for:
  - Simple key-value storage ("SET name Alice")
  - Counters (INCR, DECR — atomic increment/decrement)
  - Numeric storage that looks like strings but acts like numbers
  - Substrings (GETRANGE, SETRANGE)

THE KEY INSIGHT:
A Redis "string" is secretly a DUAL TYPE. It stores a string,
but if that string looks like an integer, you can do math on it.

  SET counter "100"
  INCR counter        → 101  (parsed as int, incremented, stored back as "101")
  APPEND counter "x"  → "101x"
  INCR counter        → ERR! ("101x" is not a valid integer)

This is a common interview topic: how do you design a value
that supports BOTH string operations AND numeric operations?

DSA CONCEPTS:
  - Type coercion / parsing
  - String manipulation with index handling
  - Negative index normalization (Python-style, but inclusive end)
"""

class RedisString:
    """
    Redis String — binary-safe string that also supports integer operations.

    Stored internally as a Python str. When a numeric operation is requested,
    we parse it as int, do the math, and store the result back as str.
    """

    def __init__(self, val : str = ''):
        self._val : str = val


    def get(self) -> str:
        """Return the stored string."""
        return self._val


    def set(self, val : str) -> None:
        """Overwrite with a new value"""
        self._val = val


    def append(self, val : str) -> int:
        """
        Append to the existing string, return new total length

        Example:
            "hello" + " world" -> "hello world", returns 11
        
        """
        self._val += val
        return len(self._val)



    def strlen(self) -> int:
        """Returns the length of the stored string"""
        return len(self._val)


    def getrange(self, start: int, end: int) -> str:

        length = len(self._val)
        if start < 0:
            start = max(length + start, 0)

        if end < 0:
            end = length + end


        end = min(end, length - 1)
        if start > end or start >= length:
            return ''
        return self._val[start:end+1]


    def setrange(self, offset: int, value : str) -> None:
        """
        Overwrite starting at offset, zero-padding if needed.
        Return new total length.

        Examples:
            "hello" setrange 5 " world" → "hello world", returns 11
            "hello" setrange 10 "x"     → "hello\x00\x00\x00\x00\x00x", returns 11
            ""      setrange 3 "hi"     → "\x00\x00\x00hi", returns 5
        """

        current = self._val
        current_len = len(current)

        if offset > current_len:
            current = current + '\x00' * (offset - current_len)


        end_pos = offset + len(value)
        self._val = current[:offset] + value + current[end_pos:]
        return len(self._val)



    def _parse_int(self) -> int:
        """
        Prase the stored value into a integer.
        Raises ValueError if it's not a valid integer string.
        """

        try:
            return int(self._val)
        except (ValueError, OverflowError):
            raise ValueError("value is not an integer or out of range")

    def incr(self) -> int:
        """
        Increment by 1, store result, return new value.

        "100" -> incre -> stores "101", return 101
        "abc" -> incre -> raises ValueError
        """
        result = self._parse_int() + 1
        self._val = str(result)
        return result


    def decr(self) -> int:
        """Decrement by 1"""
        result = self._parse_int() - 1
        self._val = str(result)
        return result


    def incrby(self, amount : int) -> int:
        """Increment by a given integer amount."""
        result = self._parse_int() + amount
        self._val = str(result)
        return result
    

    def decrby(self, amount : int) -> int:
        """Decrement by a given integer amount."""
        result = self._parse_int() - amount
        self._val = str(result)
        return result
    

    def incrbyfloat(self, amount : float) -> float:
        """
        Increment by a float number.
        Unlike integer ops, this parses as float, so both
        "1000" and "3.14" are valid starting values.

        Redis stores the value with minimal decimal places:
            "10" + 1.5 -> "11.5" (not 11.500000)
        """
        try:
            current = float(self._val)
        except (ValueError, OverflowError):
            raise ValueError("value is not a valid float")


        result = current + amount
        if result == int(result):
            self._val = str(int(result))
        else:
            self._val = f"{result:.17g}"

        return result
    

    def __repr__(self) -> str:
        return f"RedisString({self._val!r})"
        



