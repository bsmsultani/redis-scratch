class RedisString:
    # stores a string but can also do integer/float math on it
    def __init__(self, val: str = ''):
        self._val: str = val

    def get(self) -> str:
        return self._val

    def set(self, val: str) -> None:
        self._val = val

    def append(self, val: str) -> int:
        self._val += val
        return len(self._val)

    def strlen(self) -> int:
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
        return self._val[start:end + 1]

    def setrange(self, offset: int, value: str) -> None:
        # zero-pad if offset is past the end
        current = self._val
        current_len = len(current)
        if offset > current_len:
            current = current + '\x00' * (offset - current_len)
        end_pos = offset + len(value)
        self._val = current[:offset] + value + current[end_pos:]
        return len(self._val)

    def _parse_int(self) -> int:
        try:
            return int(self._val)
        except (ValueError, OverflowError):
            raise ValueError("value is not an integer or out of range")

    def incr(self) -> int:
        result = self._parse_int() + 1
        self._val = str(result)
        return result

    def decr(self) -> int:
        result = self._parse_int() - 1
        self._val = str(result)
        return result

    def incrby(self, amount: int) -> int:
        result = self._parse_int() + amount
        self._val = str(result)
        return result

    def decrby(self, amount: int) -> int:
        result = self._parse_int() - amount
        self._val = str(result)
        return result

    def incrbyfloat(self, amount: float) -> float:
        try:
            current = float(self._val)
        except (ValueError, OverflowError):
            raise ValueError("value is not a valid float")
        result = current + amount
        # store without trailing zeros
        if result == int(result):
            self._val = str(int(result))
        else:
            self._val = f"{result:.17g}"
        return result

    def __repr__(self) -> str:
        return f"RedisString({self._val!r})"
