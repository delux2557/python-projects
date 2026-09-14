"""PNG 写出（标准库 ``zlib`` + ``struct``，不依赖图像库）。

刻意与参考实现保持**逐字节兼容**：8 位 RGBA、filter type 0、非隔行、单个 IDAT。
这样「NumPy 加速版」的输出可以拿「纯 Python 参考版」当校验基准。
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

__all__ = ["to_png", "write_png"]

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# 压缩级别固定 6：跨平台跨版本稳定，便于「同输入 → 同字节」的回归断言
_COMPRESS_LEVEL = 6


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def to_png(rgba: np.ndarray) -> bytes:
    """``(h, w, 4)`` 的 0–255 uint8 数组 → PNG 字节串。"""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"需要 (h, w, 4) 的数组，收到 {rgba.shape}")
    h, w = rgba.shape[0], rgba.shape[1]
    if h < 1 or w < 1:
        raise ValueError("宽高必须 ≥ 1")

    raw = np.zeros((h, 1 + w * 4), dtype=np.uint8)      # 每行开头 1 字节 filter type
    raw[:, 1:] = np.ascontiguousarray(rgba, dtype=np.uint8).reshape(h, w * 4)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8bit / RGBA / deflate / 非隔行
    return (_PNG_MAGIC + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw.tobytes(), _COMPRESS_LEVEL))
            + _chunk(b"IEND", b""))


def write_png(path, rgba: np.ndarray) -> str:
    """写出 PNG 并返回路径字符串（目录不存在会自动创建）。"""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(to_png(rgba))
    return str(p)
