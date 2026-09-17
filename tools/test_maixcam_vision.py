#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_maixcam_vision.py —— 在 PC 上验证 MaixCAM 端视觉算法 (不需要真机)

做法: 伪造一个 maix 模块 (camera / image / uart / display / app),
把 maixcam/main.py 当普通 Python 模块导入, 然后用**合成图**喂进去:

    · 圆柱形: 白色矩形 (上下一样宽)
    · 圆锥形: 白色梯形 (下宽上窄)
    · 腰鼓形: 白色桶形 (中间最宽)
    · 什么都没有: 全黑

验证 detect_shape() 能不能正确分类, 以及协议组帧/解析是否与 PC 参考实现一致。

    python tools/test_maixcam_vision.py
"""

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from maix_protocol import Parser, build_req_detect, build_mode_color  # noqa: E402


# ==========================================================================
# 一、伪造 maix 模块
# ==========================================================================
class FakeImage:
    """够用的灰度/RGB 图像替身 (只实现 main.py 用到的接口)"""

    def __init__(self, w, h, data=None):
        self._w = w
        self._h = h
        self._d = bytearray(data) if data is not None else bytearray(w * h)

    # ---- 尺寸 ----
    def width(self):
        return self._w

    def height(self):
        return self._h

    # ---- 格式/拷贝 ----
    def to_format(self, fmt):
        return FakeImage(self._w, self._h, bytes(self._d))

    def copy(self):
        return FakeImage(self._w, self._h, bytes(self._d))

    # ---- 区域 ----
    def crop(self, x, y, w, h):
        data = bytearray(w * h)
        for j in range(h):
            sy = y + j
            if 0 <= sy < self._h:
                for i in range(w):
                    sx = x + i
                    if 0 <= sx < self._w:
                        data[j * w + i] = self._d[sy * self._w + sx]
        return FakeImage(w, h, bytes(data))

    # ---- 缩放 (最近邻) ----
    def resize(self, w, h):
        data = bytearray(w * h)
        for j in range(h):
            sy = min(self._h - 1, int(j * self._h / h))
            for i in range(w):
                sx = min(self._w - 1, int(i * self._w / w))
                data[j * w + i] = self._d[sy * self._w + sx]
        return FakeImage(w, h, bytes(data))

    # ---- 取字节 ----
    def to_bytes(self):
        return bytes(self._d)

    def draw_rect(self, *a, **k):
        pass


class FakeBlob:
    """find_blobs 返回的色块替身"""

    def __init__(self, x, y, w, h, pixels):
        self._x, self._y, self._w, self._h, self._p = x, y, w, h, pixels

    def x(self):
        return self._x

    def y(self):
        return self._y

    def w(self):
        return self._w

    def h(self):
        return self._h

    def pixels(self):
        return self._p


class FakeFormat:
    FMT_GRAYSCALE = "gray"
    FMT_RGB888 = "rgb"


def install_fake_maix():
    """把假的 maix 模块塞进 sys.modules"""
    maix = types.ModuleType("maix")

    image_mod = types.ModuleType("maix.image")
    image_mod.Format = FakeFormat
    image_mod.COLOR_GREEN = 0x00FF00
    image_mod.Image = FakeImage
    image_mod.Blob = FakeBlob

    def _find_blobs(self, thresholds, **kwargs):
        """按阈值在图上找连通域 (只做简单的行列扫描, 够测试用)"""
        thr = thresholds[0]
        if len(thr) == 6:
            return []          # 彩色阈值在替身里不实现 (颜色识别另外用假 blob 测)
        lo, hi = thr
        w, h = self._w, self._h
        data = self._d
        minx, miny, maxx, maxy, cnt = w, h, -1, -1, 0
        for j in range(h):
            for i in range(w):
                v = data[j * w + i]
                if lo <= v <= hi:
                    cnt += 1
                    minx = min(minx, i); maxx = max(maxx, i)
                    miny = min(miny, j); maxy = max(maxy, j)
        if cnt == 0:
            return []
        return [FakeBlob(minx, miny, maxx - minx + 1, maxy - miny + 1, cnt)]

    FakeImage.find_blobs = _find_blobs

    camera_mod = types.ModuleType("maix.camera")

    class FakeCamera:
        def __init__(self, *a, **k):
            self._img = FakeImage(640, 320)

        def read(self):
            return self._img

        def set_img(self, img):
            self._img = img

    camera_mod.Camera = FakeCamera

    display_mod = types.ModuleType("maix.display")

    class FakeDisplay:
        def show(self, img):
            pass

    display_mod.Display = FakeDisplay

    uart_mod = types.ModuleType("maix.uart")

    class FakeUART:
        """把写出去的东西收在自己身上, 方便断言"""

        instances = []

        def __init__(self, dev, baud, *a, **k):
            self.dev = dev
            self.baud = baud
            self.sent = bytearray()
            self.rx = bytearray()
            FakeUART.instances.append(self)
            self.last = self

        def write(self, data):
            if isinstance(data, (bytes, bytearray)):
                self.sent += bytes(data)
            else:
                self.sent += bytes(bytearray(x & 0xFF for x in data))

        def read(self, *a, **k):
            out = bytes(self.rx)
            self.rx = bytearray()
            return out

    uart_mod.UART = FakeUART

    app_mod = types.ModuleType("maix.app")
    app_mod.need_exit = lambda: False

    maix.image = image_mod
    maix.camera = camera_mod
    maix.display = display_mod
    maix.uart = uart_mod
    maix.app = app_mod

    sys.modules["maix"] = maix
    sys.modules["maix.image"] = image_mod
    sys.modules["maix.camera"] = camera_mod
    sys.modules["maix.display"] = display_mod
    sys.modules["maix.uart"] = uart_mod
    sys.modules["maix.app"] = app_mod
    return FakeImage, FakeUART


FakeImage, FakeUART = install_fake_maix()

# ---- 把 maixcam/main.py 当普通模块导入 ----
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "maixcam_main", os.path.join(ROOT, "maixcam", "main.py"))
maixcam_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(maixcam_main)

maixcam_main.DEBUG = False          # 测试时别刷屏
maixcam_main.SHOW_PREVIEW = False


# ==========================================================================
# 二、造合成图
# ==========================================================================
W, H = 640, 320
BLACK, WHITE = 0, 255


def make_image(width_profile):
    """
    按"每行白色像素宽度"生成一张合成图
    width_profile: 长度 = 物体高度 (像素) 的列表, 每项是该行的白色宽度
    """
    data = bytearray([BLACK]) * (W * H)
    obj_h = len(width_profile)
    y0 = (H - obj_h) // 2
    for j, wj in enumerate(width_profile):
        y = y0 + j
        x0 = (W - wj) // 2
        row = y * W
        for i in range(wj):
            data[row + x0 + i] = WHITE
    return FakeImage(W, H, bytes(data))


def cylinder_profile(height=160, width=100):
    return [width] * height


def cone_profile(height=160, w_top=20, w_bot=140):
    return [int(w_top + (w_bot - w_top) * i / (height - 1)) for i in range(height)]


def waist_drum_profile(height=160, w_top=30, w_mid=160, w_bot=40):
    out = []
    for i in range(height):
        t = i / (height - 1)
        if t < 0.5:                      # 上半段: 从 w_top 涨到 w_mid
            w = w_top + (w_mid - w_top) * (t / 0.5)
        else:                            # 下半段: 从 w_mid 收到 w_bot
            w = w_mid - (w_mid - w_bot) * ((t - 0.5) / 0.5)
        out.append(int(w))
    return out


# ==========================================================================
# 三、测试
# ==========================================================================
class TestShapeDetect(unittest.TestCase):

    def test_cylinder(self):
        img = make_image(cylinder_profile())
        res = maixcam_main.detect_shape(img)
        self.assertIsNotNone(res)
        shape, x, y, w, h = res
        self.assertEqual(shape, maixcam_main.SHAPE_CYLINDER)
        self.assertAlmostEqual(w, 100, delta=8)
        self.assertAlmostEqual(h, 160, delta=12)

    def test_cone(self):
        img = make_image(cone_profile())
        res = maixcam_main.detect_shape(img)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], maixcam_main.SHAPE_CONE)

    def test_waist_drum(self):
        img = make_image(waist_drum_profile())
        res = maixcam_main.detect_shape(img)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], maixcam_main.SHAPE_WAIST_DRUM)

    def test_nothing_found(self):
        img = FakeImage(W, H, bytes([BLACK]) * (W * H))
        self.assertIsNone(maixcam_main.detect_shape(img))

    def test_relative_rule_also_works(self):
        """相对判据打开时, 三个形状也要分对 (对相机距离不敏感)"""
        maixcam_main.SHAPE_USE_RELATIVE_RULE = True
        try:
            for prof, expect in ((cylinder_profile(), maixcam_main.SHAPE_CYLINDER),
                                 (cone_profile(), maixcam_main.SHAPE_CONE),
                                 (waist_drum_profile(), maixcam_main.SHAPE_WAIST_DRUM)):
                res = maixcam_main.detect_shape(make_image(prof))
                self.assertIsNotNone(res)
                self.assertEqual(res[0], expect)
        finally:
            maixcam_main.SHAPE_USE_RELATIVE_RULE = False


class TestColorDetect(unittest.TestCase):
    """颜色识别: 用假 blob 直接验证"取面积最大"的逻辑"""

    def test_pick_largest(self):
        img = FakeImage(W, H)
        blobs_by_thr = {
            maixcam_main.COLOR_THRESHOLDS[maixcam_main.RED]:
                [FakeBlob(10, 10, 20, 20, 300)],
            maixcam_main.COLOR_THRESHOLDS[maixcam_main.GREEN]:
                [FakeBlob(200, 100, 60, 60, 3000)],
            maixcam_main.COLOR_THRESHOLDS[maixcam_main.BLUE]:
                [FakeBlob(300, 120, 40, 40, 900)],
        }

        def fake_find(self, thresholds, **kw):
            return blobs_by_thr.get(thresholds[0], [])

        img.find_blobs = types.MethodType(fake_find, img)
        res = maixcam_main.detect_color(img)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], maixcam_main.GREEN)        # 面积最大的那个
        self.assertEqual(res[1:], (200, 100, 60, 60))

    def test_none(self):
        img = FakeImage(W, H)
        img.find_blobs = types.MethodType(lambda self, t, **k: [], img)
        self.assertIsNone(maixcam_main.detect_color(img))


class TestProtocolOnDevice(unittest.TestCase):
    """设备端组帧/解析必须和 PC 参考实现一模一样"""

    def test_frames_match_pc_reference(self):
        from maix_protocol import (build_mode_color as pc_mode_color,
                                   build_mode_shape as pc_mode_shape,
                                   build_req_detect as pc_req,
                                   build_none_report as pc_none)
        self.assertEqual(maixcam_main.build_frame(maixcam_main.FLAG_REQUEST,
                                                  maixcam_main.CMD_SET_MODE_COLOR),
                         pc_mode_color())
        self.assertEqual(maixcam_main.build_frame(maixcam_main.FLAG_REQUEST,
                                                  maixcam_main.CMD_SET_MODE_SHAPE),
                         pc_mode_shape())
        self.assertEqual(maixcam_main.build_frame(maixcam_main.FLAG_REQUEST,
                                                  maixcam_main.CMD_REQUEST_DETECT),
                         pc_req())
        self.assertEqual(maixcam_main.build_none_report(), pc_none())

    def test_crc(self):
        self.assertEqual(maixcam_main.crc16_ibm(b"123456789"), 0xBB3D)

    def test_report_roundtrip(self):
        raw = maixcam_main.build_report(maixcam_main.CMD_REPORT_COLOR,
                                        maixcam_main.RED, 300, 140, 60, 60)
        frames = Parser().feed(raw)
        self.assertEqual(len(frames), 1)
        f = frames[0]
        self.assertTrue(f.crc_ok)
        self.assertEqual((f.cmd, f.target_id, f.x, f.y, f.w, f.h),
                         (1, 1, 300, 140, 60, 60))

    def test_device_parser_accepts_stm32_frames(self):
        p = maixcam_main.FrameParser()
        got = []
        for b in build_mode_color() + build_req_detect():
            r = p.push(b)
            if r is not None:
                got.append(r)
        self.assertEqual(len(got), 2)
        self.assertTrue(all(r[3] for r in got))            # crc_ok
        self.assertEqual([r[1] for r in got],
                         [maixcam_main.CMD_SET_MODE_COLOR,
                          maixcam_main.CMD_REQUEST_DETECT])


class TestNodeEndToEnd(unittest.TestCase):
    """整条链路: 收到 0x10 + 0x12 -> 回一帧颜色结果"""

    def test_color_reply(self):
        FakeUART.instances.clear()
        node = maixcam_main.VisionNode()
        node.cam.set_img(make_image(cylinder_profile()))

        # 让颜色识别固定返回"红, 300,140,60,60"
        node.mode = maixcam_main.MODE_COLOR
        orig = maixcam_main.detect_color
        maixcam_main.detect_color = lambda img: (maixcam_main.RED, 300, 140, 60, 60)
        try:
            for b in build_mode_color() + build_req_detect():
                r = node.parser.push(b)
                if r is not None:
                    node.handle_frame(*r)
        finally:
            maixcam_main.detect_color = orig

        ser = FakeUART.instances[-1]
        frames = Parser().feed(bytes(ser.sent))
        self.assertEqual(len(frames), 1)
        f = frames[0]
        self.assertTrue(f.crc_ok)
        self.assertEqual(f.cmd, 1)
        self.assertEqual((f.target_id, f.x, f.y, f.w, f.h), (1, 300, 140, 60, 60))
        self.assertTrue(f.in_valid_range())

    def test_shape_reply_and_none_frame(self):
        FakeUART.instances.clear()
        node = maixcam_main.VisionNode()
        node.mode = maixcam_main.MODE_SHAPE

        # 1) 有物体 -> 0x02 上报
        node.cam.set_img(make_image(cone_profile()))
        node.handle_detect_request()
        ser = FakeUART.instances[-1]
        frames = Parser().feed(bytes(ser.sent))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].cmd, 2)
        self.assertEqual(frames[0].target_id, maixcam_main.SHAPE_CONE)

        # 2) 没物体 -> 空帧 0x00
        ser.sent = bytearray()
        node.cam.set_img(FakeImage(W, H, bytes([BLACK]) * (W * H)))
        node.handle_detect_request()
        frames = Parser().feed(bytes(ser.sent))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].cmd, 0)
        self.assertFalse(frames[0].valid_target)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
