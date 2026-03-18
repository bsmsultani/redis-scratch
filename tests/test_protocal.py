"""
test_protocol.py — Tests for the RESP Parser & Serializer
==========================================================

RUN WITH:  python -m pytest tests/test_protocol.py -v
    OR:    python tests/test_protocol.py   (uses unittest runner)

TESTING STRATEGY:
We test three categories:
  1. SERIALIZER: encode Python objects → verify exact bytes
  2. PARSER:     feed bytes → verify parsed Python objects
  3. ROUND-TRIP: encode → parse → should equal original value

Plus edge cases:
  4. PARTIAL READS: simulate TCP fragmentation
  5. MULTIPLE MESSAGES: several messages in one buffer
  6. ERROR CASES: malformed input, unknown types
"""

import sys
import os
import unittest

# Add project root to path so we can import pyredis
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from protocol import RESPParser, RESPSerializer, RESPError


class TestRESPSerializer(unittest.TestCase):
    """Test encoding Python objects → RESP bytes."""

    # ── Simple Strings ────────────────────────────────────────────────

    def test_encode_simple_string(self):
        self.assertEqual(RESPSerializer.encode_simple_string("OK"), b"+OK\r\n")

    def test_encode_simple_string_pong(self):
        self.assertEqual(RESPSerializer.encode_simple_string("PONG"), b"+PONG\r\n")

    # ── Errors ────────────────────────────────────────────────────────

    def test_encode_error(self):
        result = RESPSerializer.encode_error("ERR unknown command")
        self.assertEqual(result, b"-ERR unknown command\r\n")

    def test_encode_error_wrongtype(self):
        result = RESPSerializer.encode_error("WRONGTYPE bad type")
        self.assertEqual(result, b"-WRONGTYPE bad type\r\n")

    # ── Integers ──────────────────────────────────────────────────────

    def test_encode_integer_positive(self):
        self.assertEqual(RESPSerializer.encode_integer(1000), b":1000\r\n")

    def test_encode_integer_zero(self):
        self.assertEqual(RESPSerializer.encode_integer(0), b":0\r\n")

    def test_encode_integer_negative(self):
        self.assertEqual(RESPSerializer.encode_integer(-42), b":-42\r\n")

    # ── Bulk Strings ──────────────────────────────────────────────────

    def test_encode_bulk_string(self):
        self.assertEqual(
            RESPSerializer.encode_bulk_string("hello"),
            b"$5\r\nhello\r\n"
        )

    def test_encode_bulk_string_empty(self):
        self.assertEqual(RESPSerializer.encode_bulk_string(""), b"$0\r\n\r\n")

    def test_encode_bulk_string_null(self):
        self.assertEqual(RESPSerializer.encode_bulk_string(None), b"$-1\r\n")

    def test_encode_bulk_string_with_crlf(self):
        """Bulk strings can contain \\r\\n — length prefix makes it safe."""
        result = RESPSerializer.encode_bulk_string("hello\r\nworld")
        self.assertEqual(result, b"$12\r\nhello\r\nworld\r\n")

    # ── Arrays ────────────────────────────────────────────────────────

    def test_encode_array_of_strings(self):
        result = RESPSerializer.encode_array(["SET", "key", "value"])
        expected = b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n"
        self.assertEqual(result, expected)

    def test_encode_empty_array(self):
        self.assertEqual(RESPSerializer.encode_array([]), b"*0\r\n")

    def test_encode_null_array(self):
        self.assertEqual(RESPSerializer.encode_array(None), b"*-1\r\n")

    def test_encode_mixed_array(self):
        """Array with different types: int, string, None."""
        result = RESPSerializer.encode_array([1, "hello", None])
        expected = b"*3\r\n:1\r\n$5\r\nhello\r\n$-1\r\n"
        self.assertEqual(result, expected)

    # ── Auto-detect encode() ──────────────────────────────────────────

    def test_encode_auto_none(self):
        self.assertEqual(RESPSerializer.encode(None), b"$-1\r\n")

    def test_encode_auto_int(self):
        self.assertEqual(RESPSerializer.encode(42), b":42\r\n")

    def test_encode_auto_str(self):
        self.assertEqual(RESPSerializer.encode("hi"), b"$2\r\nhi\r\n")

    def test_encode_auto_list(self):
        result = RESPSerializer.encode(["a", "b"])
        expected = b"*2\r\n$1\r\na\r\n$1\r\nb\r\n"
        self.assertEqual(result, expected)

    def test_encode_auto_error(self):
        result = RESPSerializer.encode(RESPError("ERR bad"))
        self.assertEqual(result, b"-ERR bad\r\n")

    def test_encode_auto_bool(self):
        """bool must encode as integer, not raise TypeError."""
        self.assertEqual(RESPSerializer.encode(True), b":1\r\n")
        self.assertEqual(RESPSerializer.encode(False), b":0\r\n")

    def test_encode_auto_float(self):
        self.assertEqual(RESPSerializer.encode(3.14), b"$4\r\n3.14\r\n")

    def test_encode_unsupported_type(self):
        with self.assertRaises(TypeError):
            RESPSerializer.encode({"not": "supported"})

    # ── Command helper ────────────────────────────────────────────────

    def test_encode_command_set(self):
        result = RESPSerializer.encode_command("SET", "name", "Alice")
        expected = b"*3\r\n$3\r\nSET\r\n$4\r\nname\r\n$5\r\nAlice\r\n"
        self.assertEqual(result, expected)

    def test_encode_command_ping(self):
        result = RESPSerializer.encode_command("PING")
        expected = b"*1\r\n$4\r\nPING\r\n"
        self.assertEqual(result, expected)


class TestRESPParser(unittest.TestCase):
    """Test parsing RESP bytes → Python objects."""

    def setUp(self):
        """Create a fresh parser before each test."""
        self.parser = RESPParser()

    # ── Simple Strings ────────────────────────────────────────────────

    def test_parse_simple_string(self):
        self.parser.feed(b"+OK\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, "OK")

    def test_parse_simple_string_pong(self):
        self.parser.feed(b"+PONG\r\n")
        self.assertEqual(self.parser.parse_one(), "PONG")

    # ── Errors ────────────────────────────────────────────────────────

    def test_parse_error(self):
        self.parser.feed(b"-ERR unknown command\r\n")
        result = self.parser.parse_one()
        self.assertIsInstance(result, RESPError)
        self.assertEqual(result.message, "ERR unknown command")

    # ── Integers ──────────────────────────────────────────────────────

    def test_parse_integer(self):
        self.parser.feed(b":1000\r\n")
        self.assertEqual(self.parser.parse_one(), 1000)

    def test_parse_integer_zero(self):
        self.parser.feed(b":0\r\n")
        self.assertEqual(self.parser.parse_one(), 0)

    def test_parse_integer_negative(self):
        self.parser.feed(b":-42\r\n")
        self.assertEqual(self.parser.parse_one(), -42)

    # ── Bulk Strings ──────────────────────────────────────────────────

    def test_parse_bulk_string(self):
        self.parser.feed(b"$5\r\nhello\r\n")
        self.assertEqual(self.parser.parse_one(), "hello")

    def test_parse_bulk_string_empty(self):
        self.parser.feed(b"$0\r\n\r\n")
        self.assertEqual(self.parser.parse_one(), "")

    def test_parse_bulk_string_null(self):
        self.parser.feed(b"$-1\r\n")
        result = self.parser.parse_one()
        self.assertIsNone(result)

    def test_parse_bulk_string_with_crlf_in_data(self):
        """The data 'hello\\r\\nworld' is 12 bytes. Length prefix handles it."""
        self.parser.feed(b"$12\r\nhello\r\nworld\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, "hello\r\nworld")

    # ── Arrays ────────────────────────────────────────────────────────

    def test_parse_array_of_bulk_strings(self):
        self.parser.feed(b"*2\r\n$3\r\nGET\r\n$4\r\nname\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, ["GET", "name"])

    def test_parse_empty_array(self):
        self.parser.feed(b"*0\r\n")
        self.assertEqual(self.parser.parse_one(), [])

    def test_parse_null_array(self):
        self.parser.feed(b"*-1\r\n")
        self.assertIsNone(self.parser.parse_one())

    def test_parse_array_of_integers(self):
        self.parser.feed(b"*3\r\n:1\r\n:2\r\n:3\r\n")
        self.assertEqual(self.parser.parse_one(), [1, 2, 3])

    def test_parse_mixed_array(self):
        """Array containing integer, string, and null."""
        self.parser.feed(b"*3\r\n:1\r\n$5\r\nhello\r\n$-1\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, [1, "hello", None])

    def test_parse_nested_array(self):
        """Array of arrays: [[1], [2]]"""
        self.parser.feed(b"*2\r\n*1\r\n:1\r\n*1\r\n:2\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, [[1], [2]])

    # ── Null (RESP3) ──────────────────────────────────────────────────

    def test_parse_null(self):
        self.parser.feed(b"_\r\n")
        self.assertIsNone(self.parser.parse_one())

    # ── Inline Commands ───────────────────────────────────────────────

    def test_parse_inline_ping(self):
        self.parser.feed(b"PING\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, ["PING"])

    def test_parse_inline_command_with_args(self):
        self.parser.feed(b"SET name Alice\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, ["SET", "name", "Alice"])


class TestPartialReads(unittest.TestCase):
    """
    Test that the parser correctly handles TCP fragmentation.

    In real networking, a single RESP message might arrive across
    multiple recv() calls. The parser MUST:
      - Return None when data is incomplete
      - NOT corrupt its internal state
      - Successfully parse once all bytes arrive
    """

    def setUp(self):
        self.parser = RESPParser()

    def test_bulk_string_split_at_length(self):
        """Data arrives in two chunks: length line first, then data."""
        self.parser.feed(b"$5\r\n")
        self.assertIsNone(self.parser.parse_one())  # incomplete!

        self.parser.feed(b"hello\r\n")
        self.assertEqual(self.parser.parse_one(), "hello")  # now complete

    def test_bulk_string_split_mid_data(self):
        """Data arrives mid-string: 'hel' first, then 'lo'."""
        self.parser.feed(b"$5\r\nhel")
        self.assertIsNone(self.parser.parse_one())

        self.parser.feed(b"lo\r\n")
        self.assertEqual(self.parser.parse_one(), "hello")

    def test_array_elements_arrive_one_by_one(self):
        """Each element of an array arrives in a separate TCP packet."""
        # Array header
        self.parser.feed(b"*2\r\n")
        self.assertIsNone(self.parser.parse_one())

        # First element
        self.parser.feed(b"$3\r\nGET\r\n")
        self.assertIsNone(self.parser.parse_one())  # still need second element

        # Second element
        self.parser.feed(b"$4\r\nname\r\n")
        self.assertEqual(self.parser.parse_one(), ["GET", "name"])

    def test_byte_at_a_time(self):
        """Extreme case: feed one byte at a time."""
        message = b"+OK\r\n"
        for i, byte in enumerate(message):
            self.parser.feed(bytes([byte]))
            result = self.parser.parse_one()
            if i < len(message) - 1:
                self.assertIsNone(result, f"Should be None at byte {i}")
            else:
                self.assertEqual(result, "OK")

    def test_simple_string_without_crlf(self):
        """Line hasn't ended yet — missing \\r\\n."""
        self.parser.feed(b"+OK")  # no \r\n yet
        self.assertIsNone(self.parser.parse_one())

        self.parser.feed(b"\r\n")
        self.assertEqual(self.parser.parse_one(), "OK")


class TestMultipleMessages(unittest.TestCase):
    """
    Test parsing multiple RESP messages from a single buffer.

    TCP can deliver multiple messages in one recv() call (Nagle's algorithm,
    or just fast sends). We must parse each one separately.
    """

    def setUp(self):
        self.parser = RESPParser()

    def test_two_simple_strings(self):
        self.parser.feed(b"+OK\r\n+PONG\r\n")
        self.assertEqual(self.parser.parse_one(), "OK")
        self.assertEqual(self.parser.parse_one(), "PONG")

    def test_mixed_types(self):
        self.parser.feed(b":42\r\n$5\r\nhello\r\n+OK\r\n")
        self.assertEqual(self.parser.parse_one(), 42)
        self.assertEqual(self.parser.parse_one(), "hello")
        self.assertEqual(self.parser.parse_one(), "OK")

    def test_no_more_messages(self):
        """parse_one returns None when buffer is fully consumed."""
        self.parser.feed(b"+OK\r\n")
        self.assertEqual(self.parser.parse_one(), "OK")
        self.assertIsNone(self.parser.parse_one())

    def test_message_plus_partial(self):
        """One complete message followed by an incomplete one."""
        self.parser.feed(b"+OK\r\n$5\r\nhel")
        self.assertEqual(self.parser.parse_one(), "OK")    # complete
        self.assertIsNone(self.parser.parse_one())          # incomplete

        self.parser.feed(b"lo\r\n")
        self.assertEqual(self.parser.parse_one(), "hello")  # now complete


class TestHasCompleteMessage(unittest.TestCase):
    """Test the has_complete_message() peek method."""

    def setUp(self):
        self.parser = RESPParser()

    def test_empty_buffer(self):
        self.assertFalse(self.parser.has_complete_message())

    def test_complete_message(self):
        self.parser.feed(b"+OK\r\n")
        self.assertTrue(self.parser.has_complete_message())

    def test_incomplete_message(self):
        self.parser.feed(b"$5\r\nhel")
        self.assertFalse(self.parser.has_complete_message())

    def test_peek_does_not_consume(self):
        """has_complete_message() should NOT consume the message."""
        self.parser.feed(b"+OK\r\n")
        self.assertTrue(self.parser.has_complete_message())
        # Message should still be there for parse_one()
        self.assertEqual(self.parser.parse_one(), "OK")


class TestRoundTrip(unittest.TestCase):
    """
    Test encode → parse → should equal original value.

    Round-trip testing is the GOLD STANDARD for serialization code.
    If encode(x) → bytes → parse(bytes) → x for all x, your
    serializer and parser are consistent.
    """

    def _round_trip(self, value, encoder):
        """Helper: encode a value, parse it, return the parsed result."""
        parser = RESPParser()
        encoded = encoder(value)
        parser.feed(encoded)
        return parser.parse_one()

    def test_round_trip_simple_string(self):
        result = self._round_trip("OK", RESPSerializer.encode_simple_string)
        self.assertEqual(result, "OK")

    def test_round_trip_integer(self):
        result = self._round_trip(42, RESPSerializer.encode_integer)
        self.assertEqual(result, 42)

    def test_round_trip_bulk_string(self):
        result = self._round_trip("hello world", RESPSerializer.encode_bulk_string)
        self.assertEqual(result, "hello world")

    def test_round_trip_null(self):
        result = self._round_trip(None, RESPSerializer.encode_bulk_string)
        self.assertIsNone(result)

    def test_round_trip_array(self):
        original = ["SET", "mykey", "myvalue"]
        result = self._round_trip(original, RESPSerializer.encode_array)
        self.assertEqual(result, original)

    def test_round_trip_error(self):
        parser = RESPParser()
        parser.feed(RESPSerializer.encode_error("ERR something broke"))
        result = parser.parse_one()
        self.assertIsInstance(result, RESPError)
        self.assertEqual(result.message, "ERR something broke")

    def test_round_trip_command(self):
        """Simulate a real client→server→client cycle."""
        # Client encodes a command
        cmd_bytes = RESPSerializer.encode_command("SET", "greeting", "hello")

        # Server parses it
        server_parser = RESPParser()
        server_parser.feed(cmd_bytes)
        command = server_parser.parse_one()
        self.assertEqual(command, ["SET", "greeting", "hello"])

        # Server sends response
        response_bytes = RESPSerializer.encode_simple_string("OK")

        # Client parses response
        client_parser = RESPParser()
        client_parser.feed(response_bytes)
        response = client_parser.parse_one()
        self.assertEqual(response, "OK")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        self.parser = RESPParser()

    def test_empty_feed(self):
        """Feeding empty bytes should not crash."""
        self.parser.feed(b"")
        self.assertIsNone(self.parser.parse_one())

    def test_large_bulk_string(self):
        """Test with a 10KB string."""
        data = "x" * 10000
        encoded = RESPSerializer.encode_bulk_string(data)
        self.parser.feed(encoded)
        result = self.parser.parse_one()
        self.assertEqual(result, data)
        self.assertEqual(len(result), 10000)

    def test_deeply_nested_array(self):
        """Array nested 5 levels deep: [[[[[42]]]]]"""
        # Build from inside out
        inner = b":42\r\n"
        for _ in range(5):
            inner = b"*1\r\n" + inner
        self.parser.feed(inner)
        result = self.parser.parse_one()
        self.assertEqual(result, [[[[[42]]]]])

    def test_array_with_null_elements(self):
        """Array containing null bulk strings."""
        self.parser.feed(b"*3\r\n$-1\r\n$3\r\nfoo\r\n$-1\r\n")
        result = self.parser.parse_one()
        self.assertEqual(result, [None, "foo", None])

    def test_reset_clears_state(self):
        """reset() should clear partial data."""
        self.parser.feed(b"$5\r\nhel")  # partial
        self.parser.reset()
        self.parser.feed(b"+OK\r\n")
        self.assertEqual(self.parser.parse_one(), "OK")

    def test_buffer_size_property(self):
        """buffer_size tracks unprocessed bytes."""
        self.assertEqual(self.parser.buffer_size, 0)
        self.parser.feed(b"+OK\r\n")
        self.assertEqual(self.parser.buffer_size, 5)
        self.parser.parse_one()
        self.assertEqual(self.parser.buffer_size, 0)

    def test_repr(self):
        """__repr__ should not crash."""
        repr_str = repr(self.parser)
        self.assertIn("RESPParser", repr_str)


# =============================================================================
# RUN TESTS
# =============================================================================
if __name__ == '__main__':
    unittest.main(verbosity=2)