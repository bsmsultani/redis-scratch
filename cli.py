import sys
import shlex
import readline
from client import RedisClient
from protocol import RESPError


class Color:
    RESET  = "\033[0m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    WHITE  = "\033[37m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"


COMMANDS = [
    "PING", "ECHO", "SELECT", "DBSIZE", "FLUSHDB", "FLUSHALL",
    "QUIT", "EXIT", "COMMAND", "TIME",
    "GET", "SET", "SETNX", "SETEX", "MGET", "MSET",
    "INCR", "DECR", "INCRBY", "DECRBY", "INCRBYFLOAT",
    "APPEND", "STRLEN", "GETRANGE", "SETRANGE",
    "LPUSH", "RPUSH", "LPOP", "RPOP", "LLEN", "LRANGE",
    "LINDEX", "LSET", "LINSERT", "LREM", "LTRIM",
    "DEL", "EXISTS", "KEYS", "TYPE", "RENAME",
    "EXPIRE", "PEXPIRE", "TTL", "PTTL", "PERSIST",
    "SCAN", "RANDOMKEY",
    "CLEAR", "HELP",
]

SUBCOMMANDS = {
    "SET": ["EX", "PX", "NX", "XX"],
    "SCAN": ["MATCH", "COUNT"],
}


class RedisCompleter:
    # tab completion via readline
    def __init__(self):
        self._matches = []

    def complete(self, text: str, state: int):
        if state == 0:
            line = readline.get_line_buffer().lstrip()
            parts = line.split()
            text_upper = text.upper()

            if len(parts) <= 1:
                self._matches = [
                    cmd + " " for cmd in COMMANDS
                    if cmd.startswith(text_upper)
                ]
            else:
                cmd = parts[0].upper()
                subs = SUBCOMMANDS.get(cmd, [])
                self._matches = [
                    s + " " for s in subs
                    if s.startswith(text_upper)
                ]

        if state < len(self._matches):
            return self._matches[state]
        return None


def format_response(response, depth=0) -> str:
    indent = "   " * depth

    if response is None:
        return f"{indent}{Color.DIM}(nil){Color.RESET}"

    if isinstance(response, RESPError):
        return f"{indent}{Color.RED}(error) {response.message}{Color.RESET}"

    if isinstance(response, int):
        return f"{indent}{Color.CYAN}(integer) {response}{Color.RESET}"

    if isinstance(response, list):
        if len(response) == 0:
            return f"{indent}{Color.DIM}(empty array){Color.RESET}"

        lines = []
        width = len(str(len(response)))
        for i, item in enumerate(response, 1):
            num = f"{i})".rjust(width + 1)
            formatted = format_response(item, depth=depth + 1).lstrip()
            lines.append(f"{indent}{Color.YELLOW}{num}{Color.RESET} {formatted}")
        return "\n".join(lines)

    if isinstance(response, str):
        if response in ("OK", "PONG", "QUEUED"):
            return f"{indent}{Color.GREEN}{response}{Color.RESET}"
        return f'{indent}{Color.WHITE}"{response}"{Color.RESET}'

    return f"{indent}{response}"


def parse_input(line: str) -> list:
    # handle quoted strings like: SET key "hello world"
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def print_help():
    print(f"\n{Color.BOLD}Available commands:{Color.RESET}\n")
    groups = {
        "Server":  ["PING", "ECHO", "SELECT", "DBSIZE", "FLUSHDB",
                    "FLUSHALL", "COMMAND", "TIME"],
        "Strings": ["GET", "SET", "SETNX", "SETEX", "MGET", "MSET",
                    "INCR", "DECR", "INCRBY", "DECRBY", "INCRBYFLOAT",
                    "APPEND", "STRLEN", "GETRANGE", "SETRANGE"],
        "Lists":   ["LPUSH", "RPUSH", "LPOP", "RPOP", "LLEN", "LRANGE",
                    "LINDEX", "LSET", "LINSERT", "LREM", "LTRIM"],
        "Keys":    ["DEL", "EXISTS", "KEYS", "TYPE", "RENAME",
                    "EXPIRE", "PEXPIRE", "TTL", "PTTL", "PERSIST",
                    "SCAN", "RANDOMKEY"],
        "CLI":     ["HELP", "CLEAR", "QUIT / EXIT"],
    }
    for group, cmds in groups.items():
        print(f"  {Color.YELLOW}{group}:{Color.RESET}")
        print(f"    {', '.join(cmds)}")
    print()


def main():
    host = '127.0.0.1'
    port = 6379

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ('-h', '--host') and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] in ('-p', '--port') and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    try:
        client = RedisClient(host, port)
    except ConnectionRefusedError:
        print(f"{Color.RED}Could not connect to Redis at {host}:{port}{Color.RESET}")
        print("Is the server running? Start it with: python3 server.py")
        sys.exit(1)

    completer = RedisCompleter()
    readline.set_completer(completer.complete)
    readline.set_completer_delims(" ")
    readline.parse_and_bind("tab: complete")

    prompt = f"{Color.BOLD}{host}:{port}>{Color.RESET} "
    print(f"{Color.DIM}Connected to {host}:{port}. Type HELP for commands, TAB to autocomplete.{Color.RESET}")

    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Color.DIM}Bye!{Color.RESET}")
            break

        if not line:
            continue

        parts = parse_input(line)
        if not parts:
            continue

        cmd = parts[0].upper()

        if cmd in ("EXIT", "QUIT"):
            try:
                client.send_command("QUIT")
            except Exception:
                pass
            print(f"{Color.DIM}Bye!{Color.RESET}")
            break

        if cmd == "CLEAR":
            print("\033[2J\033[H", end="")
            continue

        if cmd == "HELP":
            print_help()
            continue

        try:
            response = client.send_command(*parts)
            print(format_response(response))
        except ConnectionError:
            print(f"{Color.RED}Connection lost. Server may have shut down.{Color.RESET}")
            break
        except Exception as e:
            print(f"{Color.RED}(error) {e}{Color.RESET}")

    client.close()


if __name__ == "__main__":
    main()
