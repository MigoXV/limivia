import zlib

import pytest

from limivia import ProtocolError
from limivia._ble_wire import HEADER, Reader, pack


@pytest.mark.parametrize("raw", [b"x", b"{}", b"x" * 1024, bytes(range(256)) * 32])
def test_roundtrip_every_fragment_boundary_and_joined_frames(raw):
    wire = pack(raw)
    for size in [1, 12, 20, 180, 512, len(wire)]:
        reader = Reader()
        result = []
        for i in range(0, len(wire), size):
            result.extend(reader.feed(wire[i : i + size]))
        assert result == [raw + b"\n"]
        assert not reader.buffer
    assert Reader().feed(wire + wire) == [raw + b"\n", raw + b"\n"]


def test_corruption_lengths_versions_and_zip_bomb_fail_closed():
    original = pack(b"x" * 1024)
    for offset in [0, 2, 3, 8, len(original) - 1]:
        wire = bytearray(original)
        wire[offset] ^= 128
        with pytest.raises(ProtocolError):
            Reader().feed(wire)
    for packed, raw in [(0, 1), (8193, 1), (1, 8193), (2, 1)]:
        with pytest.raises(ProtocolError):
            Reader().feed(HEADER.pack(b"LV", 4, 0, packed, raw, 0))
    compressed = zlib.compress(b"x" * 100000)
    with pytest.raises(ProtocolError):
        Reader().feed(HEADER.pack(b"LV", 4, 1, len(compressed), 1, 0) + compressed)
    with pytest.raises(ProtocolError):
        Reader().feed(
            HEADER.pack(b"LV", 4, 1, len(original) - 12 + 1, 1024, zlib.crc32(b"x" * 1024))
            + original[12:]
            + b"x"
        )
