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
        self._is_alive : bool = True
        self._write_buffer : bytearray = bytearray()
        self._parser : RESPParser = RESPParser()

        self._selected_db: int = 0

        self._authenticated: bool = False

        self._in_multi: bool = False

        self._multi_queue: list = []

        self._subscriptions: set = set()


    def read(self) -> list:
        """
        Reads bytes from the buffer and sends it to the parser for parsing
        """
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
            pass # socket maybe already closed


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

        self._selector.register(
            self._socket,
            selectors.EVENT_READ,
            data=None  # None = this is the server socket, not a client
        )

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

                # ── PERIODIC TASKS ────────────────────────────
                self._run_periodic_tasks()

            except KeyboardInterrupt:
                # Ctrl+C pressed — graceful shutdown
                print("\nShutting down...")
                self.shutdown()
                break

    def _accept_connection(self) -> None:
        try:
            client_socket, address = self._socket.accept()
            client_socket.setblocking(False)

            # Wrap in our ClientConnection — this creates the
            # dedicated parser, write buffer, and all client state.
            connection = ClientConnection(client_socket, address)

            # Register with selector: watch for READ events.
            # We attach the ClientConnection object as key.data
            # so we can retrieve it when events fire.
            self._selector.register(
                client_socket,
                selectors.EVENT_READ,
                data=connection
            )

            # Track by file descriptor for easy lookup/cleanup.
            self._clients[client_socket.fileno()] = connection

            print(f"Client connected: {address}")

        except OSError:
            pass  # accept() can fail if client disconnected immediately

    def _handle_client(self, client: ClientConnection) -> None:
        """
        Read commands from a client, execute them, send responses.

        Called when a client socket is readable (has data to read).
        One call might process multiple pipelined commands.
        """
        commands = client.read()

        # ── CHECK IF CLIENT DISCONNECTED ──────────────────────
        if not client._is_alive:
            self._remove_client(client)
            return

        # ── PROCESS EACH COMMAND ──────────────────────────────
        for cmd in commands:
            response = self._execute_command(client, cmd)
            client.write(response)

            # If write() filled the buffer and couldn't send
            # everything, start listening for WRITE events too
            # so we can flush when the socket is ready.
            if client.has_pending_writes:
                try:
                    self._selector.modify(
                        client.fileno(),
                        selectors.EVENT_READ | selectors.EVENT_WRITE,
                        data=client
                    )
                except (KeyError, ValueError):
                    pass  # already unregistered or closed

    def _execute_command(self, client: ClientConnection, cmd) -> bytes:
        """
        Route a single command and return the RESP-encoded response.
        Delegates to CommandRouter which handles all registered commands.
        """
        return self._command_router.execute(client, cmd)

    def _remove_client(self, client: ClientConnection) -> None:
        """
        Unregister a client from the selector and clean up.

        Called when client.i._is_alive is False (disconnect or error).
        """
        fd = client.fileno()

        try:
            self._selector.unregister(fd)
        except (KeyError, ValueError):
            pass  # already unregistered

        client.close()
        self._clients.pop(fd, None)

        print(f"Client disconnected: {client._address}")

    def _run_periodic_tasks(self) -> None:
        """
        Background maintenance tasks. Called once per event loop iteration.

        These are stubs — you'll fill them in as you build each module:
          - Expiry sweep (Phase 4): delete keys that have expired
          - Persistence check (Phase 5): trigger RDB/AOF save if needed
          - Eviction check (Phase 4): free memory if over the limit
        """
        # Phase 4: Expiry sweep
        # if self._expiry_engine:
        #     self._expiry_engine.sweep_active()

        # Phase 5: Persistence
        # if self._rdb and self._rdb.should_save(...):
        #     self._rdb.save()

        # Phase 4: Memory eviction
        # if self._eviction_manager:
        #     self._eviction_manager.check_and_evict(self._database)
        pass

    def shutdown(self) -> None:
        """
        Graceful shutdown: close all clients, close server socket.

        Order matters:
          1. Stop the loop (so we don't accept new work)
          2. Close every client (flush what we can, free resources)
          3. Unregister and close the server socket
          4. Close the selector
        """
        self._running = False

        # Close all client connections
        for fd, client in list(self._clients.items()):
            self._remove_client(client)

        # Close the server socket
        try:
            self._selector.unregister(self._socket)
        except (KeyError, ValueError):
            pass

        self._socket.close()
        self._selector.close()

        print("Server shut down.")

    # ── PROPERTIES ────────────────────────────────────────────

    @property
    def uptime(self) -> float:
        """Seconds since server started."""
        return time.time() - self._start_time

    @property
    def connected_clients(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)



if __name__ == "__main__":
    server = RedisServer()
    server.start()