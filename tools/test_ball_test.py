#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ball_test.py —— 在电脑上验证 v2 (maixcam/ball_test.py) 的逻辑, 不需要真机

做法: 伪造一个 maix 模块(camera/display/image/app), 把 ball_test.py 当普通模块导入,
      然后用"脚本化的候选项"喂进去, 检查:
        · 圆度/长宽比/面积 三个过滤是否按预期工作
        · 多个候选时是否取像素最多的合格者
        · 只测红色时, 绿色球会不会被误报
        · 打印策略: 首次找到打 / 不动不打 / 移动超过阈值才打 / 丢球立刻打
        · ALL_COLORS=True 时三种颜色互不干扰

    python tools/test_ball_test.py
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


# ==========================================================================
# 一、伪造 maix 模块
# ==========================================================================
class FakeBlob:
    """既支持下标访问(blob[0..3]), 也支持方法/属性"""

    def __init__(self, x, y, w, h, pixels):
        self._v = (x, y, w, h, pixels)

    def __getitem__(self, i):
        return self._v[i]

    def x(self):
        return self._v[0]

    def y(self):
        return self._v[1]

    def w(self):
        return self._v[2]

    def h(self):
        return self._v[3]

    def pixels(self):
        return self._v[4]


class FakeImage:
    """
    lab_map: {LAB阈值元组: [FakeBlob, ...]}
    find_blobs 按传入的阈值去查这张表 —— 这样我们就能精确控制"识别到什么"
    """

    def __init__(self, lab_map=None):
        self.lab_map = lab_map or {}
        self.drawn = []

    def find_blobs(self, thresholds, **kw):
        thr = tuple(thresholds[0])
        return list(self.lab_map.get(thr, []))

    def draw_rect(self, x, y, w, h, **kw):
        self.drawn.append(("rect", x, y, w, h))

    def draw_string(self, x, y, s, **kw):
        self.drawn.append(("text", x, y, s))


def install_fake_maix(frames):
    """frames: 一个列表, 每项是一张 FakeImage; read() 依次返回, 用完重复最后一张"""
    maix = types.ModuleType("maix")

    image_mod = types.ModuleType("maix.image")
    image_mod.COLOR_GREEN = 0x00FF00
    image_mod.COLOR_WHITE = 0xFFFFFF
    image_mod.Image = FakeImage

    cam_mod = types.ModuleType("maix.camera")

    class FakeCamera:
        def __init__(self, *a, **k):
            self.frames = frames
            self.i = 0

        def read(self):
            img = self.frames[min(self.i, len(self.frames) - 1)]
            self.i += 1
            return img

    cam_mod.Camera = FakeCamera

    disp_mod = types.ModuleType("maix.display")

    class FakeDisplay:
        def __init__(self, *a, **k):
            pass

        def show(self, img):
            pass

    disp_mod.Display = FakeDisplay

    app_mod = types.ModuleType("maix.app")

    class ExitCtl:
        left = 1

        def need_exit(self):
            if ExitCtl.left <= 0:
                return True
            ExitCtl.left -= 1
            return False

    app_mod.need_exit = ExitCtl().need_exit
    app_mod._ctl = ExitCtl

    maix.image = image_mod
    maix.camera = cam_mod
    maix.display = disp_mod
    maix.app = app_mod

    for name, mod in (("maix", maix), ("maix.image", image_mod),
                      ("maix.camera", cam_mod), ("maix.display", disp_mod),
                      ("maix.app", app_mod)):
        sys.modules[name] = mod

    return app_mod


APP = install_fake_maix([FakeImage()])

# ---- 把 maixcam/ball_test.py 当普通模块导入 ----
_spec = importlib.util.spec_from_file_location(
    "ball_test", os.path.join(ROOT, "maixcam", "ball_test.py"))
ball_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ball_test)

RED = ball_test.COLOR_LAB[1]
GREEN = ball_test.COLOR_LAB[2]
BLUE = ball_test.COLOR_LAB[3]


# ==========================================================================
# 二、工具
# ==========================================================================
def img_with(**kw):
    """img_with(red=[(x,y,w,h,px)], green=[...]) -> FakeImage"""
    m = {}
    if "red" in kw:
        m[RED] = [FakeBlob(*b) for b in kw["red"]]
    if "green" in kw:
        m[GREEN] = [FakeBlob(*b) for b in kw["green"]]
    if "blue" in kw:
        m[BLUE] = [FakeBlob(*b) for b in kw["blue"]]
    return FakeImage(m)


def make_tester(frames=None):
    """构造一个已初始化的 BallTester (相机用假帧)"""
    if frames:
        sys.modules["maix.camera"].Camera = None
    t = ball_test.BallTester.__new__(ball_test.BallTester)   # 不调 __init__
    t.cam = None
    t.disp = None
    t.targets = [1, 2, 3] if ball_test.ALL_COLORS else [ball_test.TARGET_COLOR]
    t.st = {cid: {"found": None, "cx": None, "cy": None, "t": 0}
            for cid in t.targets}
    t.t0 = 0.0
    return t


class Clock:
    """可控时钟: 替换 ball_test.now_ms 和时间戳"""

    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


# ==========================================================================
# 三、测试
# ==========================================================================
class TestFilters(unittest.TestCase):
    """圆度/长宽比/面积 三个过滤"""

    def setUp(self):
        self.t = make_tester()
        self.clock = Clock(0)
        ball_test.now_ms = self.clock

    def detect(self, img, cid=1):
        return ball_test.detect_color(img, cid)

    # ---- 圆球: 直径 100px 的圆 ~= 7854 像素, fill=0.785 ----
    def test_circle_passes(self):
        img = img_with(red=[(300, 140, 100, 100, 7854)])
        best, rejects = self.detect(img)
        self.assertIsNotNone(best, "圆球应该通过过滤")
        self.assertEqual((best["x"], best["y"], best["w"], best["h"]),
                         (300, 140, 100, 100))
        self.assertEqual(rejects, [])

    def test_square_rejected_by_fill(self):
        """实心方块(比如一块红色布/屏幕)饱满度=1.0 > 0.92, 应该被拒"""
        img = img_with(red=[(100, 100, 100, 100, 10000)])
        best, rejects = self.detect(img)
        self.assertIsNone(best, "方块不该被当成球")
        self.assertEqual(len(rejects), 1)
        self.assertIn("饱满度", rejects[0][5])

    def test_thin_strip_rejected_by_aspect(self):
        """细长红条(电线/反光)长宽比=10, 应该被拒"""
        img = img_with(red=[(100, 100, 200, 20, 2000)])
        best, rejects = self.detect(img)
        self.assertIsNone(best)
        self.assertIn("长宽比", rejects[0][5])

    def test_tiny_dot_rejected_by_area(self):
        """噪点 5x5=25 像素 < MIN_AREA(100), 应该被拒"""
        img = img_with(red=[(50, 50, 5, 5, 25)])
        best, rejects = self.detect(img)
        self.assertIsNone(best)
        self.assertIn("面积", rejects[0][5])

    def test_big_circle_wins(self):
        """多个合格候选 -> 取像素最多的那个"""
        img = img_with(red=[(10, 10, 60, 60, 2827),      # 小圆
                            (300, 140, 120, 120, 11310)])  # 大圆
        best, _ = self.detect(img)
        self.assertIsNotNone(best)
        self.assertEqual((best["x"], best["y"]), (300, 140))

    def test_green_ignored_when_testing_red(self):
        """只测红色时, 绿球不该被报出来"""
        img = img_with(green=[(300, 140, 100, 100, 7854)])
        best, rejects = self.detect(img, 1)
        self.assertIsNone(best)
        self.assertEqual(rejects, [])

    def test_ellipse_passes(self):
        """略微椭圆的球(宽高比 1.2)仍应通过"""
        img = img_with(red=[(300, 140, 110, 92, 7950)])
        best, _ = self.detect(img)
        self.assertIsNotNone(best)


class TestPrintPolicy(unittest.TestCase):
    """打印策略: 状态变化立即打, 位移受限流"""

    def setUp(self):
        self.t = make_tester()
        self.clock = Clock(1000)
        ball_test.now_ms = self.clock
        ball_test.PRINT_MOVE_PX = 20
        ball_test.PRINT_MIN_INTERVAL_MS = 1000

    def rep(self, best, cid=1):
        buf = io.StringIO()
        with redirect_stdout(buf):
            printed = self.t.report(cid, best, [])
        return printed, buf.getvalue().strip()

    @staticmethod
    def ball(x, y, w=100, h=100, px=7854):
        return {"id": 1, "x": x, "y": y, "w": w, "h": h, "pixels": px}

    def test_first_detection_prints(self):
        printed, line = self.rep(self.ball(300, 140))
        self.assertTrue(printed)
        self.assertIn("红(1) x=300 y=140 w=100 h=100", line)

    def test_no_move_no_print(self):
        self.rep(self.ball(300, 140))
        printed, line = self.rep(self.ball(300, 140))
        self.assertFalse(printed, "球没动就不该再打印")
        self.assertEqual(line, "")

    def test_small_move_no_print(self):
        self.rep(self.ball(300, 140))
        self.clock.t += 5000
        printed, _ = self.rep(self.ball(310, 145))     # 移动 10px < 20px
        self.assertFalse(printed)

    def test_big_move_prints_after_interval(self):
        self.rep(self.ball(300, 140))
        self.clock.t += 2000
        printed, line = self.rep(self.ball(400, 200))  # 移动 100px
        self.assertTrue(printed)
        self.assertIn("中心", line)

    def test_big_move_within_interval_throttled(self):
        self.rep(self.ball(300, 140))
        self.clock.t += 200                          # 不到 1000ms
        printed, _ = self.rep(self.ball(500, 300))   # 移动很多也不打
        self.assertFalse(printed, "限流期内不该打印")

    def test_lost_prints_immediately(self):
        self.rep(self.ball(300, 140))
        self.clock.t += 100                          # 限流期内
        printed, line = self.rep(None)               # 球丢了
        self.assertTrue(printed, "丢球属于状态变化, 必须立刻打印")
        self.assertIn("未找到红球", line)

    def test_lost_not_repeated(self):
        self.rep(self.ball(300, 140))
        self.rep(None)
        printed, _ = self.rep(None)                  # 一直没球
        self.assertFalse(printed, "持续无球不该刷屏")

    def test_found_again_prints(self):
        self.rep(self.ball(300, 140))
        self.rep(None)
        printed, line = self.rep(self.ball(305, 142))  # 又找到了
        self.assertTrue(printed)
        self.assertIn("红(1)", line)


class TestAllColorsIndependent(unittest.TestCase):
    """ALL_COLORS=True: 三种颜色各自独立状态, 不互相干扰"""

    def setUp(self):
        ball_test.ALL_COLORS = True
        self.t = make_tester()
        self.clock = Clock(1000)
        ball_test.now_ms = self.clock
        self.t.targets = [1, 2, 3]

    def tearDown(self):
        ball_test.ALL_COLORS = False

    @staticmethod
    def ball(cid, x, y, w=100, h=100, px=7854):
        return {"id": cid, "x": x, "y": y, "w": w, "h": h, "pixels": px}

    def test_no_crosstalk(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            # 第 1 帧: 红球在, 绿蓝没有
            self.t.report(1, self.ball(1, 300, 140), [])
            self.t.report(2, None, [])
            self.t.report(3, None, [])
            out1 = buf.getvalue()
            buf.truncate(0)
            buf.seek(0)
            # 第 2 帧: 完全一样 -> 一行都不该打
            self.t.report(1, self.ball(1, 300, 140), [])
            self.t.report(2, None, [])
            self.t.report(3, None, [])
            out2 = buf.getvalue()

        self.assertIn("红(1) x=300", out1)
        self.assertIn("未找到绿球", out1)
        self.assertIn("未找到蓝球", out1)
        self.assertEqual(out2.strip(), "",
                         "状态没变时不该打印(说明各颜色状态是独立的)")


class TestRunLoop(unittest.TestCase):
    """整条链路: 假相机喂几帧, 跑 run(), 看打印与画框"""

    def setUp(self):
        self.clock = Clock(0)
        ball_test.now_ms = self.clock
        ball_test.TARGET_COLOR = 1
        ball_test.ALL_COLORS = False

    def test_run_loop(self):
        frames = [
            img_with(red=[(300, 140, 100, 100, 7854)]),     # 第1帧: 找到
            img_with(red=[(300, 140, 100, 100, 7854)]),     # 第2帧: 没动
            img_with(),                                      # 第3帧: 丢了
        ]
        cam_mod = sys.modules["maix.camera"]
        orig_cam = cam_mod.Camera
        cam_mod.Camera = lambda *a, **k: type("C", (), {
            "read": lambda s: frames.pop(0) if frames else FakeImage()})()

        app_mod = sys.modules["maix.app"]
        app_mod.need_exit = lambda: False           # 由 frames 用完来控制
        calls = {"n": 0}

        def need_exit():
            calls["n"] += 1
            return calls["n"] > 3                   # 跑 3 帧后退出

        app_mod.need_exit = need_exit

        t = ball_test.BallTester()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t.run()
        out = buf.getvalue()

        cam_mod.Camera = orig_cam
        self.assertIn("红球测试 v2 启动", out)
        self.assertIn("红(1) x=300 y=140 w=100 h=100", out)
        self.assertIn("未找到红球", out)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
