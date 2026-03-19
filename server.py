import socket
from protocol import RESPParser
import selectors
import time

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

        # ── SERVER SOCKET ─────────────────────────────────────
        # AF_INET = IPv4, SOCK_STREAM = TCP
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # SO_REUSEADDR lets us restart the server immediately after
        # a crash. Without it, the OS holds the port for ~60 seconds
        # (TIME_WAIT state) and you get "Address already in use."
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setblocking(False)

        self._host = host
        self._port = port

        # ── I/O MULTIPLEXING ──────────────────────────────────
        # selectors picks the best method for your OS:
        #   Linux  → epoll   (O(1) per ready fd)
        #   macOS  → kqueue  (O(1) per ready fd)
        #   Other  → select  (O(n) scan every fd)
        #
        # This is how ONE thread handles thousands of clients.
        # Instead of blocking on one socket, we ask the OS:
        # "which sockets have data ready?" — then handle only those.
        self._selector = selectors.DefaultSelector()

        # ── CLIENT TRACKING ───────────────────────────────────
        # Maps file descriptor (int) → ClientConnection
        # fd is the unique ID the OS assigns to each socket.
        # We use it as the key because selectors return fds.
        self._clients: dict = {}   # fd -> ClientConnection

        # ── CORE COMPONENTS (stubs for now) ───────────────────
        # These will be real classes as you build each module.
        # For now, None is fine — the server can start and accept
        # connections without them.
        self._database = None       # KeyspaceManager (Phase 2)
        self._command_router = None  # CommandRouter   (Phase 2)
        self._expiry_engine = None   # ExpiryEngine    (Phase 4)
        self._pubsub = None          # PubSubManager   (Phase 4)
        self._config = config        # ServerConfig    (Phase 6)

        # ── SERVER METADATA ───────────────────────────────────
        self._start_time: float = time.time()
        self._running: bool = False
    
    def start(self) -> None:
        """
        Bind and listen to the server
        """
        self._socket.bind((self._host, self._port))
        self._socket.listen()

        self._selector.register(self._socket, selectors.EVENT_READ, self._accept_connection)


    
    def _accept_connection(self, sock):
        client_sock, add = sock.accept()
        client_sock.set_blocking(False)


