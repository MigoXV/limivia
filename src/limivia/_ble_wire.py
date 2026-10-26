"""Bounded binary BLE framing candidate; no control commands are retried."""

from __future__ import annotations

import struct
import zlib

from ._exceptions import ProtocolError

HEADER = struct.Struct("<2sBBHHI")


def pack(raw: bytes) -> bytes:
    raw = raw.removesuffix(b"\n")
    if not 0 < len(raw) <= 8192:
        raise ProtocolError("二进制帧原始长度无效")
    compressed = raw
    flag = 0
    if len(raw) >= 256:
        encoder = zlib.compressobj(1, zlib.DEFLATED, 9, 1)
        candidate = encoder.compress(raw) + encoder.flush()
        if len(candidate) * 100 <= len(raw) * 85:
            compressed, flag = candidate, 1
    return HEADER.pack(b"LV", 4, flag, len(compressed), len(raw), zlib.crc32(raw)) + compressed


class Reader:
    def __init__(self, maximum: int = 8192):
        self.maximum = maximum
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        result = []
        offset = 0
        while offset < len(data):
            needed = HEADER.size
            if len(self.buffer) >= HEADER.size:
                magic, version, flag, packed, raw, crc = HEADER.unpack_from(self.buffer)
                if magic != b"LV" or version != 4 or flag not in (0, 1):
                    raise ProtocolError("二进制帧格式不匹配")
                if (
                    not 0 < packed <= self.maximum
                    or not 0 < raw <= self.maximum
                    or (not flag and packed != raw)
                ):
                    raise ProtocolError("二进制帧长度越界")
                needed += packed
            take = min(needed - len(self.buffer), len(data) - offset)
            self.buffer.extend(data[offset : offset + take])
            offset += take
            if len(self.buffer) < HEADER.size:
                continue
            magic, version, flag, packed, raw, crc = HEADER.unpack_from(self.buffer)
            if magic != b"LV" or version != 4 or flag not in (0, 1):
                raise ProtocolError("二进制帧格式不匹配")
            if (
                not 0 < packed <= self.maximum
                or not 0 < raw <= self.maximum
                or (not flag and packed != raw)
            ):
                raise ProtocolError("二进制帧长度越界")
            if len(self.buffer) != HEADER.size + packed:
                continue
            payload = bytes(self.buffer[HEADER.size :])
            if flag:
                try:
                    decoder = zlib.decompressobj(9)
                    payload = decoder.decompress(payload, raw + 1)
                    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                        raise ProtocolError("二进制压缩流不完整")
                except zlib.error as exc:
                    raise ProtocolError("二进制压缩流无效") from exc
            if len(payload) != raw or zlib.crc32(payload) != crc:
                raise ProtocolError("二进制帧校验失败")
            result.append(payload + b"\n")
            self.buffer.clear()
        return result
