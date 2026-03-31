import socket
from protocol import RESPParser, RESPSerializer
from command_router import CommandRouter
from database import KeyspaceManager
import selectors
import time


class ClientConnection:
    def __init__(self, socket, address):
        self._socket = socket
        self._address = address
        self._is_alive: bool = True
        self._write_buffer: bytearray = bytearray()
        self._parser: RESPParser = RESPParser()
        self._selected_db: int = 0
        self._authenticated: bool = False
        self._in_multi: bool = False
        self._multi_queue: list = []
        self._subscriptions: set = set()

    def read(self) -> list:
        try:
            data = self._socket.recv(4096)
            if not data:
                self._is_alive = False
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
            self._is_alive = False
            return []
        except OSError:
            self._is_alive = False
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
            self._is_alive = False
            self._write_buffer.clear()

    def close(self) -> None:
        self._is_alive = False
        self._write_buffer.clear()
        self._multi_queue.clear()
        self._subscriptions.clear()
        try:
            self._socket.close()
        except OSError:
            pass

    @property
    def has_pending_writes(self) -> bool:
        return len(self._write_buffer) > 0

    def fileno(self) -> int:
        return self._socket.fileno()


class RedisServer:
    def __init__(self, host='127.0.0.1', port=6379, config=None):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setblocking(False)

        self._host = host
        self._port = port

        self._selector = selectors.DefaultSelector()
        self._clients: dict = {}  # fd -> ClientConnection

        self._keyspace = KeyspaceManager()
        self._command_router = CommandRouter(self._keyspace)
        self._expiry_engine = None
        self._pubsub = None
        self._config = config

        self._start_time: float = time.time()
        self._running: bool = False

    def start(self) -> None:
        self._socket.bind((self._host, self._port))
        self._socket.listen(128)

        # None as data marks this as the server socket, not a client
        self._selector.register(self._socket, selectors.EVENT_READ, data=None)

        self._running = True
        print(f"Redis server running on {self._host}:{self._port}")

        while self._running:
            try:
                events = self._selector.select(timeout=1)

                for key, mask in events:
                    if key.data is None:
                        self._accept_connection()
                    else:
                        client = key.data
                        if mask & selectors.EVENT_READ:
                            self._handle_client(client)
                        if mask & selectors.EVENT_WRITE:
                            client._flush_write_buffer()
                            if not client.has_pending_writes:
                                self._selector.modify(
                                    client.fileno(),
                                    selectors.EVENT_READ,
                                    data=client
                                )

                self._run_periodic_tasks()

            except KeyboardInterrupt:
                print("\nShutting down...")
                self.shutdown()
                break

    def _accept_connection(self) -> None:
        try:
            client_socket, address = self._socket.accept()
            client_socket.setblocking(False)

            connection = ClientConnection(client_socket, address)
            self._selector.register(client_socket, selectors.EVENT_READ, data=connection)
            self._clients[client_socket.fileno()] = connection

            print(f"Client connected: {address}")

        except OSError:
            pass

    def _handle_client(self, client: ClientConnection) -> None:
        commands = client.read()

        if not client._is_alive:
            self._remove_client(client)
            return

        for cmd in commands:
            response = self._execute_command(client, cmd)
            client.write(response)

            # if the socket can't take all data right now, wait for write-ready
            if client.has_pending_writes:
                try:
                    self._selector.modify(
                        client.fileno(),
                        selectors.EVENT_READ | selectors.EVENT_WRITE,
                        data=client
                    )
                except (KeyError, ValueError):
                    pass

    def _execute_command(self, client: ClientConnection, cmd) -> bytes:
        return self._command_router.execute(client, cmd)

    def _remove_client(self, client: ClientConnection) -> None:
        fd = client.fileno()
        try:
            self._selector.unregister(fd)
        except (KeyError, ValueError):
            pass
        client.close()
        self._clients.pop(fd, None)
        print(f"Client disconnected: {client._address}")

    def _run_periodic_tasks(self) -> None:
        # placeholder for expiry sweep, persistence, eviction
        pass

    def shutdown(self) -> None:
        self._running = False
        for fd, client in list(self._clients.items()):
            self._remove_client(client)
        try:
            self._selector.unregister(self._socket)
        except (KeyError, ValueError):
            pass
        self._socket.close()
        self._selector.close()
        print("Server shut down.")

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    @property
    def connected_clients(self) -> int:
        return len(self._clients)


if __name__ == "__main__":
    server = RedisServer()
    server.start()
