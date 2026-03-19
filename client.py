import socket
from protocol import RESPError, RESPParser, RESPSerializer

class RedisClient:
    def __init__(self, host = '127.0.0.1', port = 6379):
        """
        Simple Redis Client that connects over TCP and sends commands.

        Usuage:
            client = RedisClient()
            client.send_command("SET", "name", "Alice") # 'OK'
            client.send_command("GET", "name")  # Alice
            client.close()
        """
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((host, port))

        self._parser = RESPParser()



    def send_command(self, *args) -> any:
        """
        Send command and wait for response.

        Args:
            *args: Command part e.g. "SET", "name", "Alice"

        Returns:
            The parsed response: str, int, list, None or RESPError
        
        """
        data = RESPSerializer.encode_command(*args)
        self._socket.sendall(data)



        # Read until we have a complete response.
        # The server always sends exactly one response per command,
        # but it might arrive across multiple recv() calls.

        while True:
            result = self._parser.parse_one()
            if result is not None:
                return result
            

            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection ... ")
            
            self._parser.feed(chunk)




    def Pipeline(self) -> 'Pipeline':
        """Returns Pipeline for batching multiple commands"""
        return Pipeline(self)


    def close(self) -> None:
        """Disconnect from the server."""
        try:
            self._socket.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()



class Pipeline:

    """
    Batch multiple commands into one network round-trip.

    Without pipelining:
        SET name Alice  →  send, wait for OK
        SET age 30      →  send, wait for OK
        GET name        →  send, wait for "Alice"
        = 3 round trips

    With pipelining:
        Send all 3 at once → read all 3 responses
        = 1 round trip

    Usage:
        pipe = client.pipeline()
        pipe.command("SET", "name", "Alice")
        pipe.command("SET", "age", "30")
        pipe.command("GET", "name")
        results = pipe.execute()  # ["OK", "OK", "Alice"]

    Or with chaining:
        results = (client.pipeline()
            .command("SET", "x", "1")
            .command("INCR", "x")
            .execute())  # ["OK", 2]
    """
    def __init__(self, client: RedisClient):
        self._client = client
        self._commands : list = []


    def command(self, *args) -> 'Pipeline':
        """Queue a command, return self for chaining"""
        self._commands.append(args)
        return self

    def execute(self) -> list:
        """
        Send all queued commands at once, read all responses.

        This is faster than sending one-by-one because:
        1. One big send() instead of many small ones
        2. One burst of recv() instead of waiting between each
        3. Fewer TCP packets (Nagle's algorithm can batch them)
        """
        if not self._commands:
            return []

        # ── SEND ALL AT ONCE ──────────────────────────────────
        buffer = bytearray()
        for args in self._commands:
            buffer.extend(RESPSerializer.encode_command(*args))
        self._client._socket.sendall(bytes(buffer))

        # ── READ ALL RESPONSES ────────────────────────────────
        # We expect exactly one response per command sent.
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

        # Clear the queue so the pipeline can be reused.
        self._commands.clear()

        return results
