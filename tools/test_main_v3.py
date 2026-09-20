#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_main_v3.py —— 在电脑上验证合并版 maixcam/main.py（不需要真机）

做法：伪造 maix 模块（camera / display / image / uart / app），把 main.py 当普通模块导入，
      然后：
        · 用假串口喂 0x10 / 0x11 / 0x12 命令，检查它回的帧与 PC 参考实现逐字节一致
        · 喂合成的色块，检查颜色识别（取最大、杂点过滤、三种颜色）
        · 喂合成的白色轮廓，检查形状剖面与判别（圆柱/圆锥/腰鼓），并覆盖 to_bytes 与
          get_pixel 两条路径
        · 检查 LAB 读数与标准值一致
        · 检查 MODE 的三种行为（protocol 静音 / both 打印 / calib 只打印）

    python tools/test_main_v3.py
"""

import importlib.util
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from maix_protocol import (build_mode_color, build_mode_shape, build_req_detect,
                           Parser as PcParser)   # PC 端参考实现


# ==========================================================================
# 一、伪造 maix 模块
# ==========================================================================
class FakeBlob:
    def __init__(self, x, y, w, h, pixels=None, roundness=None):
        self._v = (x, y, w, h, pixels if pixels is not None else int(w * h * 0.785))
        self._r = roundness

    def __getitem__(self, i):
        return self._v[i]

    def x(self): return self._v[0]

    def y(self): return self._v[1]

    def w(self): return self._v[2]

    def h(self): return self._v[3]

    def pixels(self): return self._v[4]

    def roundness(self): return self._r


class FakeBinary:
    """二值图替身：有像素缓冲(1字节/像素)，find_blobs([[255,255]]) 返回外接框"""

    def __init__(self, w, h, buf, blobs):
        self._w, self._h, self._d = w, h, buf
        self._blobs = blobs
        self.fail_to_bytes = False

    def find_blobs(self, thresholds, **kw):
        thr = tuple(thresholds[0])
        if thr == (255, 255) or thr == [255, 255]:
            return list(self._blobs)
        return []

    def to_bytes(self):
        if self.fail_to_bytes:
            raise TypeError("to_bytes 不支持(模拟老固件)")
        return bytes(self._d)

    def get_pixel(self, x, y):
        return [self._d[y * self._w + x]]


class FakeImage:
    def __init__(self, w=640, h=320, rgb=None, lab_map=None, binary=None):
        self._w, self._h = w, h
        self._rgb = rgb                      # 3 字节/像素
        self._gray = None
        self.lab_map = lab_map or {}
        self._binary = binary
        self.drawn = []

    # --- 尺寸/格式 ---
    def width(self): return self._w

    def height(self): return self._h

    def to_format(self, fmt):
        if self._binary is not None:
            return self
        g = FakeImage(self._w, self._h)
        g._binary = self._binary
        return g

    def binary(self, thresholds):
        if self._binary is None:
            self._binary = FakeBinary(self._w, self._h,
                                      bytearray(self._w * self._h), [])
        return self._binary

    # --- 找色块 ---
    def find_blobs(self, thresholds, **kw):
        thr = tuple(thresholds[0])
        if len(thr) == 6:
            return list(self.lab_map.get(thr, []))
        if thr == (255, 255):
            return list(self._binary.find_blobs([[255, 255]]) if self._binary else [])
        return []

    # --- 像素 ---
    def get_pixel(self, x, y):
        if self._rgb is not None:
            off = (y * self._w + x) * 3
            return [self._rgb[off], self._rgb[off + 1], self._rgb[off + 2]]
        return [0, 0, 0]

    def to_bytes(self):
        return bytes(self._rgb) if self._rgb is not None else b""

    # --- 画图 ---
    def draw_rect(self, x, y, w, h, *a, **k):
        self.drawn.append(("rect", x, y, w, h))

    def draw_string(self, x, y, s, *a, **k):
        self.drawn.append(("text", x, y, s))


class FakeUART:
    instances = []

    def __init__(self, dev, baud, *a, **k):
        self.dev, self.baud = dev, baud
        self.rx = bytearray()
        self.sent = bytearray()
        FakeUART.instances.append(self)

    def write(self, data):
        self.sent += bytes(data) if isinstance(data, (bytes, bytearray)) \
            else bytes(bytearray(x & 0xFF for x in data))

    def read(self, *a, **k):
        out = bytes(self.rx)
        self.rx = bytearray()
        return out


def install_fake_maix(frame=None):
    maix = types.ModuleType("maix")

    image_mod = types.ModuleType("maix.image")

    class _Fmt:
        FMT_GRAYSCALE = 1
        FMT_RGB888 = 0
    image_mod.Format = _Fmt
    image_mod.COLOR_WHITE = 0xFFFFFF
    image_mod.COLOR_RED = 0xFF0000
    image_mod.COLOR_GREEN = 0x00FF00
    image_mod.COLOR_BLUE = 0x0000FF
    image_mod.Image = FakeImage

    cam_mod = types.ModuleType("maix.camera")

    class FakeCamera:
        def __init__(self, *a, **k):
            self.frame = frame if frame is not None else FakeImage()

        def read(self):
            return self.frame

    cam_mod.Camera = FakeCamera

    disp_mod = types.ModuleType("maix.display")

    class FakeDisplay:
        def width(self): return 640

        def height(self): return 320

        def show(self, img): pass

    disp_mod.Display = FakeDisplay

    uart_mod = types.ModuleType("maix.uart")
    uart_mod.UART = FakeUART

    app_mod = types.ModuleType("maix.app")
    app_mod.need_exit = lambda: True      # 默认不跑主循环

    maix.image, maix.camera, maix.display = image_mod, cam_mod, disp_mod
    maix.uart, maix.app = uart_mod, app_mod
    for n, m in (("maix", maix), ("maix.image", image_mod), ("maix.camera", cam_mod),
                 ("maix.display", disp_mod), ("maix.uart", uart_mod),
                 ("maix.app", app_mod)):
        sys.modules[n] = m
    return maix


def load_main():
    fake = install_fake_maix()
    spec = importlib.util.spec_from_file_location(
        "maixcam_main", os.path.join(ROOT, "maixcam", "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fake._mod = mod
    return mod, fake


MAIN, FAKE = load_main()
RED = MAIN.COLOR_LAB[1]
GREEN = MAIN.COLOR_LAB[2]
BLUE = MAIN.COLOR_LAB[3]


def make_node(frame=None):
    """构造一个 VisionNode（串口/相机都换成假的）"""
    FAKE.camera.Camera = lambda *a, **k: type("C", (), {
        "read": lambda s: frame if frame is not None else FakeImage()})()
    FakeUART.instances.clear()
    n = MAIN.VisionNode()
    n.cam = type("C", (), {"read": lambda s: frame if frame is not None else FakeImage()})()
    return n


def color_frame(**kw):
    m = {}
    if "red" in kw:
        m[RED] = [FakeBlob(*b) for b in kw["red"]]
    if "green" in kw:
        m[GREEN] = [FakeBlob(*b) for b in kw["green"]]
    if "blue" in kw:
        m[BLUE] = [FakeBlob(*b) for b in kw["blue"]]
    return FakeImage(lab_map=m)


# ==========================================================================
# 二、协议：必须和 PC 参考实现逐字节一致
# ==========================================================================
class TestProtocol(unittest.TestCase):

    def test_crc_known_value(self):
        self.assertEqual(MAIN.crc16_ibm(b"123456789"), 0xBB3D)

    def test_build_frames_match_pc_reference(self):
        from maix_protocol import build_report as pc_report, build_none_report as pc_none
        self.assertEqual(MAIN.build_report(MAIN.CMD_REPORT_COLOR, 1, 300, 140, 60, 60),
                         pc_report(1, 1, 300, 140, 60, 60))
        self.assertEqual(MAIN.build_report(MAIN.CMD_REPORT_SHAPE, 2, 320, 160, 50, 70),
                         pc_report(2, 2, 320, 160, 50, 70))
        self.assertEqual(MAIN.build_none_report(), pc_none())

    def test_parser_accepts_stm32_commands(self):
        p = MAIN.FrameParser()
        got = []
        for b in build_mode_color() + build_mode_shape() + build_req_detect():
            r = p.push(b)
            if r is not None:
                got.append(r)
        self.assertEqual([g[1] for g in got],
                         [MAIN.CMD_SET_MODE_COLOR, MAIN.CMD_SET_MODE_SHAPE,
                          MAIN.CMD_REQUEST_DETECT])
        self.assertTrue(all(g[3] for g in got), "CRC 都应通过")

    def test_parser_rejects_bad_crc(self):
        bad = bytearray(build_mode_color())
        bad[9] ^= 0xFF                      # 破坏 cmd
        p = MAIN.FrameParser()
        r = p.push(bad[0])
        got = None
        for b in bad[1:]:
            got = p.push(b)
        self.assertIsNotNone(got)
        self.assertFalse(got[3])


# ==========================================================================
# 三、颜色识别
# ==========================================================================
class TestColorDetect(unittest.TestCase):

    def test_largest_blob_wins(self):
        img = color_frame(red=[(10, 10, 60, 60), (300, 140, 120, 120)])
        best = MAIN.detect_color(img, 1)
        self.assertIsNotNone(best)
        self.assertEqual((best["x"], best["y"]), (300, 140))

    def test_tiny_noise_filtered(self):
        img = color_frame(green=[(216, 150, 13, 14)])
        self.assertIsNone(MAIN.detect_color(img, 2), "13x14 的噪点不该被当成球")

    def test_three_colors_independent(self):
        img = color_frame(red=[(100, 100, 80, 80)],
                          blue=[(400, 150, 90, 90)])
        self.assertEqual(MAIN.detect_color(img, 1)["id"], 1)
        self.assertIsNone(MAIN.detect_color(img, 2))
        self.assertEqual(MAIN.detect_color(img, 3)["id"], 3)


# ==========================================================================
# 四、形状识别（合成白色轮廓）
# ==========================================================================
def make_binary_silhouette(profile, w=640, h=320):
    """按"每行白色宽度"生成二值图，并给出对应的 blob"""
    buf = bytearray(w * h)
    n = len(profile)
    y0 = (h - n) // 2
    for j, wj in enumerate(profile):
        row = y0 + j
        x0 = (w - wj) // 2
        for i in range(wj):
            buf[row * w + x0 + i] = 255
    bw = max(profile)
    blob = FakeBlob((w - bw) // 2, y0, bw, n)
    return FakeBinary(w, h, buf, [blob])


# 用**真实尺寸比例**生成轮廓（这是关键：假轮廓太好分, 会把问题藏起来）
#   圆柱 φ50mm；圆锥 上30 → 下50；腰鼓 上30 → 中66 → 下30
#   px_per_mm 模拟"相机到物体的距离"：越大 = 越近、越大只
def silhouette(kind, height=200, px_per_mm=2.4):
    def mm2px(mm):
        return max(6, int(mm * px_per_mm))
    if kind == "cylinder":
        return [mm2px(50)] * height
    if kind == "cone":
        return [mm2px(30 + 20 * i / (height - 1)) for i in range(height)]
    # 腰鼓：上30 → 中间66 → 下30（用抛物线近似）
    out = []
    for i in range(height):
        t = i / (height - 1)
        out.append(mm2px(30 + 36 * (1 - abs(2 * t - 1))))
    return out


class TestShapeDetect(unittest.TestCase):

    def classify(self, kind, fail_to_bytes=False):
        binary = make_binary_silhouette(silhouette(kind))
        binary.fail_to_bytes = fail_to_bytes
        img = FakeImage(binary=binary)
        return MAIN.detect_shape(img)

    def test_cylinder(self):
        r = self.classify("cylinder")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], 1)

    def test_cone(self):
        r = self.classify("cone")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], 2)

    def test_waist_drum(self):
        r = self.classify("waist_drum")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], 3)

    def test_get_pixel_fallback_path(self):
        """to_bytes 不支持时，必须能退回 get_pixel 抽样并仍然判对"""
        for kind, expect in (("cylinder", 1), ("cone", 2), ("waist_drum", 3)):
            r = self.classify(kind, fail_to_bytes=True)
            self.assertIsNotNone(r)
            self.assertEqual(r[0], expect, "%s 在 get_pixel 路径下判错了" % kind)

    def test_nothing_found(self):
        img = FakeImage(binary=FakeBinary(640, 320, bytearray(640 * 320), []))
        self.assertIsNone(MAIN.detect_shape(img))


# ==========================================================================
# 五、LAB 读数
# ==========================================================================
class TestLabReadout(unittest.TestCase):

    def test_known_colors(self):
        cases = {(255, 0, 0): (53.24, 80.09, 67.20),
                 (0, 255, 0): (87.73, -86.18, 83.18),
                 (0, 0, 255): (32.30, 79.19, -107.86)}
        for rgb, exp in cases.items():
            got = MAIN.rgb2lab(*rgb)
            for g, e in zip(got, exp):
                self.assertAlmostEqual(g, e, delta=0.6)

    def test_center_patch(self):
        img = FakeImage(rgb=bytearray([200, 60, 50] * (640 * 320)))
        node = make_node(img)
        buf = io.StringIO()
        with redirect_stdout(buf):
            node.print_center_lab(img)
        out = buf.getvalue()
        self.assertIn("[LAB] 中心13x13", out)
        self.assertIn("RGB=(200,60,50)", out.replace(" ", ""))


# ==========================================================================
# 六、端到端：喂命令 -> 收回复
# ==========================================================================
class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        MAIN.MODE = "both"          # 每个用例默认 both, 需要 protocol/calib 的自己改
        MAIN.FLUSH_BEFORE_CAPTURE = True

    def run_node_with(self, frame, cmds):
        node = make_node(frame)
        ser = node.ser
        ser.rx += cmds
        # 只让主循环转一圈：need_exit 第一次 False、第二次 True
        calls = {"n": 0}
        FAKE.app.need_exit = lambda: (calls.__setitem__("n", calls["n"] + 1) or calls["n"] > 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            node.run()
        FAKE.app.need_exit = lambda: True
        return bytes(ser.sent), buf.getvalue()

    def test_color_report_matches_pc_reference(self):
        frame = color_frame(red=[(300, 140, 60, 60)])
        sent, out = self.run_node_with(frame, build_mode_color() + build_req_detect())
        frames = PcParser().feed(sent)
        self.assertEqual(len(frames), 1, "应该正好回一帧")
        f = frames[0]
        self.assertTrue(f.crc_ok)
        self.assertEqual(f.cmd, 1)
        self.assertEqual((f.target_id, f.x, f.y, f.w, f.h), (1, 300, 140, 60, 60))
        self.assertIn("收到命令: 设为颜色模式", out)

    def test_empty_frame_when_nothing(self):
        sent, _ = self.run_node_with(FakeImage(), build_req_detect())
        frames = PcParser().feed(sent)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].cmd, 0)

    def test_shape_mode_report(self):
        binary = make_binary_silhouette(silhouette("cone"))
        frame = FakeImage(binary=binary)
        sent, _ = self.run_node_with(frame, build_mode_shape() + build_req_detect())
        frames = PcParser().feed(sent)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].cmd, 2)
        self.assertEqual(frames[0].target_id, 2, "圆锥应该报 2")

    def test_protocol_mode_is_silent(self):
        MAIN.MODE = "protocol"
        try:
            frame = color_frame(red=[(300, 140, 60, 60)])
            sent, out = self.run_node_with(frame, build_req_detect())
            frames = PcParser().feed(sent)
            self.assertEqual(len(frames), 1, "协议模式仍然必须回复")
            self.assertEqual(out.strip(), "", "协议模式不该打印任何东西")
        finally:
            MAIN.MODE = "both"


class TestShapeRuleRobustness(unittest.TestCase):
    """真实尺寸比例下, 判据要够用；并且换个距离(px_per_mm)也要判对"""

    def classify(self, kind, px_per_mm, rule):
        old = MAIN.SHAPE_RULE
        MAIN.SHAPE_RULE = rule
        try:
            binary = make_binary_silhouette(silhouette(kind, px_per_mm=px_per_mm))
            r = MAIN.detect_shape(FakeImage(binary=binary))
        finally:
            MAIN.SHAPE_RULE = old
        return None if r is None else r[0]

    def test_either_rule_works_at_two_distances(self):
        for ppm in (2.4, 1.2):          # 近一点 / 远一点
            self.assertEqual(self.classify("cylinder", ppm, "either"), 1)
            self.assertEqual(self.classify("cone", ppm, "either"), 2)
            self.assertEqual(self.classify("waist_drum", ppm, "either"), 3)

    def test_absolute_rule_alone_misclassifies_real_cone(self):
        """记录这个已知问题：只用绝对 50px 时, 真实比例的圆锥会被判成圆柱
           （顶部/底部 20% 区域的平均宽度差约 40px < 50px）——所以默认改用 either"""
        self.assertEqual(self.classify("cone", 2.4, "absolute"), 1)

    def test_relative_rule_alone_works(self):
        for ppm in (2.4, 1.2):
            self.assertEqual(self.classify("cone", ppm, "relative"), 2)
            self.assertEqual(self.classify("waist_drum", ppm, "relative"), 3)

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
