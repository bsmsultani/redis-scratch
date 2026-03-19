import socket
from protocol import RESPParser

class ClientConnection:
    def __init__(self, socket, address):

        self._socket = socket
        self._address = address
        self._alive : bool = False
        self._write_buffer : bytearray = bytearray()
        self._parser : RESPParser = RESPParser()

        # Which of the 16 databases this client is talking to.
        # Client A can do SELECT 3, Client B stays on 0.
        # They see completely different keyspaces.
        self._selected_db: int = 0

        # Has this client logged in? Only matters if server
        # has a password set. Until True, most commands are rejected.
        self._authenticated: bool = False

        # Is this client inside a MULTI/EXEC transaction block?
        # When True, commands get QUEUED instead of executed immediately.
        self._in_multi: bool = False

        # The queue of commands waiting for EXEC to run them all at once.
        self._multi_queue: list = []

        # Pub/sub channels this client is listening to.
        # A subscribed client can ONLY receive messages — no GET/SET.
        self._subscriptions: set = set()


    def read(self) -> list:
        """
        Reads bytes from the buffer and sends it to the parser for parsing
        """
        try:

            data = self._socket.recv(4096)

            if not data:
                self._alive = False
                return []

            self._parser.feed(data)

            commands = []
            while True:
                parsed = self._parser.parse_one()
                if parsed is None:
                    break

                commands.append(parsed)

            return commands
        
        except BlockingIOError:
            return []

        except ConnectionResetError:
            self._alive = False
            return []

        except OSError:
            self._alive = False
            return []

    def write(self, response) -> None:
        self._write_buffer.extend(response)
        self._flush_write_buffer()


    def _flush_write_buffer(self) -> None:
        if not self._write_buffer:
            return

        try:
            sent = self._socket.send(bytes(self._write_buffer))
            self._write_buffer = self._write_buffer[sent:]

        except BlockingIOError:
            pass
        except (ConnectionError, BrokenPipeError, OSError):
            self._alive = False
            self._write_buffer.clear()

    def close(self) -> None:
        self._alive = False
        self._write_buffer.clear()
        self._multi_queue.clear()
        self._subscriptions.clear()

        try:
            self._socket.close()
        
        except OSError:
            pass # socket maybe already closed


    def fileno(self) -> int:
        return self._socket.fileno()

        




class RedisServer:
    def __init__(self, host = '127.0.0.1', port = 8818, config = None):
        self._host = host
        self._port = port
        self._config = config



