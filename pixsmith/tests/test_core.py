"""核心层测试：颜色解析、PNG 编码、画布图元与合成。"""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from pixsmith.canvas import Canvas
from pixsmith.codec import to_png
from pixsmith.color import (darken, gradient_stops, lerp, lighten, parse_color,
                            to_rgba8, with_alpha)


# ------------------------------------------------------------------ 颜色
@pytest.mark.parametrize("raw,expected", [
    ("#FF0000", (1.0, 0.0, 0.0, 1.0)),
    ("#f00", (1.0, 0.0, 0.0, 1.0)),
    ("#FF000080", (1.0, 0.0, 0.0, 128 / 255)),
    ((255, 0, 0), (1.0, 0.0, 0.0, 1.0)),
    ((255, 0, 0, 128), (1.0, 0.0, 0.0, 128 / 255)),
    ((1.0, 0.0, 0.0, 0.5), (1.0, 0.0, 0.0, 0.5)),
])
def test_parse_color_normalizes_to_unit_floats(raw, expected):
    got = parse_color(raw)
    assert all(abs(a - b) < 1e-6 for a, b in zip(got, expected))


@pytest.mark.parametrize("bad", ["#GG0000", "#12345", "", (1, 2), "#12"])
def test_parse_color_rejects_garbage(bad):
    with pytest.raises((ValueError, TypeError)):
        parse_color(bad)


def test_alpha_override_and_clamping():
    assert parse_color("#FF0000", alpha=0.25)[3] == 0.25
    assert parse_color("#FF0000")[3] == 1.0
    assert parse_color(("0", "0", "0", 999))[3] == 1.0


def test_to_rgba8_rounds_to_nearest():
    assert to_rgba8((0.0, 0.5, 1.0, 1.0)) == (0, 128, 255, 255)


def test_lerp_and_shades():
    assert lerp("#000000", "#FFFFFF", 0.5) == pytest.approx((0.5, 0.5, 0.5, 1.0))
    assert lerp("#000000", "#FFFFFF", -5)[0] == 0.0          # t 自动夹紧
    assert lighten("#000000", 0.5)[0] == 0.5
    assert darken("#FFFFFF", 0.5)[0] == 0.5
    assert with_alpha("#FFFFFF", 2.0)[3] == 1.0


def test_gradient_stops_is_clamped_outside_range():
    t = np.array([[-1.0, 0.0, 0.5, 1.0, 2.0]], dtype=np.float32)
    out = gradient_stops([(0.0, "#000000"), (1.0, "#FFFFFF")], t)
    assert out.shape == (1, 5, 4)
    assert out[0, 0, 0] == pytest.approx(0.0)
    assert out[0, -1, 0] == pytest.approx(1.0)
    assert out[0, 2, 0] == pytest.approx(0.5, abs=1e-3)


def test_gradient_stops_requires_two_stops():
    with pytest.raises(ValueError):
        gradient_stops([(0.0, "#000")], np.zeros((1, 1), np.float32))


# ------------------------------------------------------------------ 编码
def _parse_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"{tag} CRC 校验失败"
        chunks.setdefault(tag, b"")
        chunks[tag] += body
        pos += 12 + length
    return chunks


def test_png_structure_and_roundtrip_pixels():
    arr = np.zeros((4, 6, 4), dtype=np.uint8)
    arr[..., 0] = 10
    arr[..., 3] = 255
    arr[2, 3] = (1, 2, 3, 4)
    chunks = _parse_png(to_png(arr))
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (w, h, depth, ctype, comp, filt, inter) == (6, 4, 8, 6, 0, 0, 0)
    raw = zlib.decompress(chunks[b"IDAT"])
    assert len(raw) == 4 * (1 + 6 * 4)
    assert all(raw[i * 25] == 0 for i in range(4)), "每行 filter type 必须是 0"
    back = np.frombuffer(raw, np.uint8).reshape(4, 25)[:, 1:].reshape(4, 6, 4)
    assert np.array_equal(back, arr)


def test_png_bytes_are_deterministic():
    c = Canvas(40, 30, "#123456")
    c.disc(20, 15, 8, "#F2C14E")
    assert c.to_png() == c.to_png()


def test_codec_rejects_bad_shape():
    with pytest.raises(ValueError):
        to_png(np.zeros((4, 4, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        to_png(np.zeros((0, 4, 4), dtype=np.uint8))


# ------------------------------------------------------------------ 画布
def test_canvas_rejects_degenerate_size():
    with pytest.raises(ValueError):
        Canvas(0, 10)
    with pytest.raises(ValueError):
        Canvas(10, -1)


def test_fill_and_paint_alpha_paths():
    c = Canvas(4, 4, "#000000")
    assert tuple(c.buf[0, 0]) == (0.0, 0.0, 0.0, 1.0)
    c.paint((1.0, 1.0, 1.0), 0.5)            # 半透明 → 混合路径
    assert c.buf[0, 0, 0] == pytest.approx(0.5, abs=1e-3)
    c.paint((1.0, 0.0, 0.0))                 # 不透明 → 覆盖路径
    assert tuple(c.buf[0, 0][:3]) == (1.0, 0.0, 0.0)


def test_rect_edge_coverage_is_antialiased():
    c = Canvas(4, 1)
    c.rect(0.0, 0.0, 2.5, 1.0, "#FFFFFF")
    a = c.to_rgba8()[0, :, 3]
    assert a[0] == 255 and a[1] == 255
    assert a[2] == 128, f"半覆盖像素应约 128，实测 {a[2]}"
    assert a[3] == 0


def test_alpha_compositing_math():
    c = Canvas(2, 2, "#000000")
    c.rect(0, 0, 2, 2, "#FFFFFF80")           # 50% 白叠黑
    assert c.to_rgba8()[0, 0, 0] == 128


def test_erase_disc_punches_real_transparency():
    c = Canvas(40, 40, "#FF0000")
    c.erase_disc(20, 20, 8)
    px = c.to_rgba8()
    assert px[20, 20, 3] == 0, "圆心应完全透明"
    assert px[0, 0, 3] == 255, "远离孔的区域不应受影响"
    assert px[20, 20, 0] > 0, "擦除只动 alpha，不改 RGB（直通道语义）"


def test_capsule_chunks_do_not_double_blend():
    """长线段分块后重叠区不得被合成两次（半透明下会显出一条偏色带）。"""
    c = Canvas(300, 40)
    c.capsule(10.0, 20.0, 290.0, 20.0, 6.0, "#5FD6A0C0")
    a = c.to_rgba8()[..., 3]
    on_line = a[20, 60:240]
    assert on_line.min() == on_line.max(), "同一条线段上的 alpha 应处处相等"
    assert abs(int(on_line[0]) - int(0.75 * 255)) <= 1


def test_polygon_validates_input():
    c = Canvas(20, 20)
    with pytest.raises(ValueError):
        c.polygon([(0, 0), (1, 1)], "#FFFFFF")            # 少于 3 个顶点
    with pytest.raises(ValueError):
        c.polygon([1.0, 2.0, 3.0], "#FFFFFF")             # 不是 (N, 2) 形状
    c.polygon([(0, 0), (5, 0), (5, 5)], "#FFFFFF")        # 合法：不应抛异常


def test_star_has_point_up_and_is_solid_inside():
    """星形：正上方有尖角、中心实心、外接圆之外全透明。

    ⚠️ 不要在**尖端像素**上断言"不透明" —— 尖角极窄，超采样后那一格覆盖率只有 ~1/9。
    """
    c = Canvas(200, 200)
    c.star(100.0, 100.0, 60.0, 5, "#FFFFFF")
    px = c.to_rgba8()
    assert px[100, 70, 3] > 200, "正上方 30px 处应已被星体覆盖"
    assert px[100, 100, 3] == 255, "中心应实心"
    assert px[100, 100 - 75, 3] == 0, "外接圆之外应透明"
    assert px[100, 100 + 55, 3] < 40, "正下方是凹口，应基本露出"


def test_regular_polygon_covers_expected_area():
    """rotation=-45° 的正方形，顶点落在 (±r/√2, ±r/√2)，即 64.6–135.4 的轴对齐方块。"""
    d = Canvas(200, 200)
    d.regular_polygon(100.0, 100.0, 50.0, 4, "#FFFFFF", ang=-45.0)
    q = d.to_rgba8()
    assert q[100, 100, 3] == 255, "中心应实心"
    assert q[70, 70, 3] == 255 and q[130, 130, 3] == 255, "内部对角应被覆盖"
    assert q[55, 55, 3] == 0, "顶点(64.6,64.6)之外应透明"
    assert q[10, 10, 3] == 0
