import socket
from protocol import RESPError, RESPParser, RESPSerializer


class RedisClient:
    def __init__(self, host='127.0.0.1', port=6379):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((host, port))
        self._parser = RESPParser()

    def send_command(self, *args) -> any:
        data = RESPSerializer.encode_command(*args)
        self._socket.sendall(data)

        # keep reading until we get a full response
        while True:
            result = self._parser.parse_one()
            if result is not None:
                return result
            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection ... ")
            self._parser.feed(chunk)

    def Pipeline(self) -> 'Pipeline':
        return Pipeline(self)

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Pipeline:
    # batch multiple commands into one round-trip
    def __init__(self, client: RedisClient):
        self._client = client
        self._commands: list = []

    def command(self, *args) -> 'Pipeline':
        self._commands.append(args)
        return self

    def execute(self) -> list:
        if not self._commands:
            return []

        # send everything at once
        buffer = bytearray()
        for args in self._commands:
            buffer.extend(RESPSerializer.encode_command(*args))
        self._client._socket.sendall(bytes(buffer))

        # read one response per command
        parser = self._client._parser
        results = []
        remaining = len(self._commands)

        while remaining > 0:
            result = parser.parse_one()
            if result is not None:
                results.append(result)
                remaining -= 1
            else:
                chunk = self._client._socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Server closed the connection")
                parser.feed(chunk)

        self._commands.clear()
        return results
