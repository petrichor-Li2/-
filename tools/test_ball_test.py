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
        ball_test.PRINT_ONLY_DETECTED = False
        ball_test.PRINT_MOVE_PX = 20
        ball_test.PRINT_MIN_INTERVAL_MS = 1000

    def rep(self, best, cid=1):
        buf = io.StringIO()
        with redirect_stdout(buf):
            printed = self.t.report_one(cid, best, [])
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
    """逐色模式(PRINT_ONLY_DETECTED=False): 三种颜色各自独立状态, 不互相干扰"""

    def setUp(self):
        ball_test.ALL_COLORS = True
        ball_test.PRINT_ONLY_DETECTED = False
        self.t = make_tester()
        self.clock = Clock(1000)
        ball_test.now_ms = self.clock
        self.t.targets = [1, 2, 3]

    def tearDown(self):
        ball_test.ALL_COLORS = False
        ball_test.PRINT_ONLY_DETECTED = True

    @staticmethod
    def ball(cid, x, y, w=100, h=100, px=7854):
        return {"id": cid, "x": x, "y": y, "w": w, "h": h, "pixels": px}

    def test_no_crosstalk(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            # 第 1 帧: 红球在, 绿蓝没有
            self.t.report_one(1, self.ball(1, 300, 140), [])
            self.t.report_one(2, None, [])
            self.t.report_one(3, None, [])
            out1 = buf.getvalue()
            buf.truncate(0)
            buf.seek(0)
            # 第 2 帧: 完全一样 -> 一行都不该打
            self.t.report_one(1, self.ball(1, 300, 140), [])
            self.t.report_one(2, None, [])
            self.t.report_one(3, None, [])
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
        ball_test.PRINT_ONLY_DETECTED = True

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
        self.assertIn("小球测试 v2 启动", out)
        self.assertIn("红(1) x=300 y=140 w=100 h=100", out)
        self.assertIn("未找到任何小球(红)", out)


class TestMultiColor(unittest.TestCase):
    """第三轮 S1: 三色都检测, 检测到什么颜色就打印什么颜色"""

    def setUp(self):
        self.t = make_tester()
        ball_test.ALL_COLORS = True
        ball_test.PRINT_ONLY_DETECTED = True
        ball_test.PRINT_MOVE_PX = 20
        ball_test.PRINT_MIN_INTERVAL_MS = 1000
        ball_test.CALIB_WIDTH_PX = {1: 0.0, 2: 0.0, 3: 0.0}
        self.clock = Clock(1000)
        ball_test.now_ms = self.clock
        self.t.targets = [1, 2, 3]
        self.t.prev_centers = {}
        self.t.prev_keys = ()
        self.t.last_any_ms = 0

    def tearDown(self):
        ball_test.ALL_COLORS = False
        ball_test.CALIB_WIDTH_PX = {1: 0.0, 2: 0.0, 3: 0.0}

    @staticmethod
    def ball(cid, x, y, w=100, h=100, px=7854):
        return {"id": cid, "x": x, "y": y, "w": w, "h": h,
                "pixels": px, "dist": None}

    def run_frame(self, found):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.t.report_multi(found, {1: [], 2: [], 3: []})
        return buf.getvalue()

    def test_only_detected_colors_are_printed(self):
        """只有红球 -> 只打一行红; 不该出现"未找到绿球/蓝球"这种噪声"""
        out = self.run_frame([(1, self.ball(1, 300, 140))])
        self.assertIn("红(1) x=300", out)
        self.assertNotIn("未找到绿球", out)
        self.assertNotIn("未找到蓝球", out)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_two_colors_at_once(self):
        """红球 + 绿球同时出现 -> 两行"""
        out = self.run_frame([(1, self.ball(1, 300, 140)),
                              (2, self.ball(2, 120, 160))])
        self.assertIn("红(1) x=300 y=140", out)
        self.assertIn("绿(2) x=120 y=160", out)

    def test_nothing_found_after_something(self):
        """之前有球, 现在全场都没有 -> 打一行"未找到任何小球(\u7ea2/\u7eff/\u84dd)\""""
        self.run_frame([(1, self.ball(1, 300, 140))])
        out = self.run_frame([])
        self.assertIn("未找到任何小球(红/绿/蓝)", out)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_nothing_found_repeated_is_quiet(self):
        self.run_frame([(1, self.ball(1, 300, 140))])
        self.run_frame([])
        out = self.run_frame([])
        self.assertEqual(out.strip(), "", "持续无球不该刷屏")

    def test_color_switch_prints(self):
        """红球移走换成绿球 -> 打印绿球(颜色变化属于状态变化)"""
        self.run_frame([(1, self.ball(1, 300, 140))])
        out = self.run_frame([(2, self.ball(2, 300, 140))])
        self.assertIn("绿(2)", out)

    def test_move_within_interval_is_throttled(self):
        self.run_frame([(1, self.ball(1, 300, 140))])
        self.clock.t += 200                                   # 限流期内
        out = self.run_frame([(1, self.ball(1, 500, 300))])
        self.assertEqual(out.strip(), "")

    def test_move_after_interval_prints(self):
        self.run_frame([(1, self.ball(1, 300, 140))])
        self.clock.t += 2000
        out = self.run_frame([(1, self.ball(1, 500, 300))])
        self.assertIn("红(1) x=500", out)
        self.assertIn("中心", out)

    def test_distance_filter_per_color(self):
        """距离标定按颜色分开: 只标红球 -> 红球卡距离, 绿球不卡"""
        ball_test.CALIB_WIDTH_PX = {1: 100.0, 2: 0.0, 3: 0.0}
        self.assertTrue(ball_test.calib_ready(1))
        self.assertFalse(ball_test.calib_ready(2))
        # 红球 50px -> 20cm 超范围, 被拒
        best, rejects = ball_test.detect_color(
            img_with(red=[(300, 140, 50, 50, 1963)]), 1)
        self.assertIsNone(best)
        self.assertIn("距离", rejects[0][5])
        # 绿球同样 50px, 但绿球没标定 -> 不卡距离, 通过
        best, rejects = ball_test.detect_color(
            img_with(green=[(300, 140, 50, 50, 1963)]), 2)
        self.assertIsNotNone(best)

    def test_all_three_detected_in_one_frame(self):
        out = self.run_frame([(1, self.ball(1, 100, 100)),
                              (2, self.ball(2, 300, 140)),
                              (3, self.ball(3, 500, 180))])
        for cid, name in ((1, "红"), (2, "绿"), (3, "蓝")):
            self.assertIn("%s(%d)" % (name, cid), out)

    def test_draw_all_balls_with_numeric_labels(self):
        """屏幕: 两个球都画框, 标签各自是数字形式"""
        t = make_tester()
        t.disp = object()
        img = img_with(red=[])
        found = [(1, self.ball(1, 100, 100, 60, 60)),
                 (2, self.ball(2, 300, 140, 50, 50))]
        t.draw_result(img, found)
        rects = [d for d in img.drawn if d[0] == "rect"]
        texts = sorted(d[3] for d in img.drawn if d[0] == "text")
        self.assertEqual(len(rects), 2)
        self.assertEqual(texts, ["1 x100 y100 w60 h60", "2 x300 y140 w50 h50"])
        for tx in texts:
            self.assertTrue(all(ord(c) < 128 for c in tx))


class TestDistanceFilter(unittest.TestCase):
    """第二轮新增: 用像素宽度反推距离, 只接受 5~15cm"""

    def setUp(self):
        self.t = make_tester()
        ball_test.now_ms = Clock(0)
        ball_test.PRINT_ONLY_DETECTED = False
        ball_test.PRINT_MOVE_PX = 20
        ball_test.PRINT_MIN_INTERVAL_MS = 1000
        ball_test.CALIB_DISTANCE_CM = 10.0
        ball_test.DIST_MIN_CM = 5.0
        ball_test.DIST_MAX_CM = 15.0
        ball_test.CALIB_WIDTH_PX = {1: 0.0}

    def tearDown(self):
        ball_test.CALIB_WIDTH_PX = {1: 0.0}

    def detect(self, boxes):
        return ball_test.detect_color(img_with(red=boxes), 1)

    # ---- 未标定: 不卡距离, 只给 w ----
    def test_uncalibrated_does_not_filter(self):
        best, rejects = self.detect([(300, 140, 50, 50, 1963)])   # 很小(很远)
        self.assertIsNotNone(best, "未标定时不该按距离过滤")
        self.assertIsNone(best["dist"], "未标定时距离应为 None")
        self.assertEqual(rejects, [])

    # ---- 公式 d = K / w ----
    def test_distance_math(self):
        ball_test.CALIB_WIDTH_PX = {1: 100.0}        # 10cm -> 100px, 即 K = 1000
        self.assertAlmostEqual(ball_test.estimate_distance_cm(100, 1), 10.0, places=3)
        self.assertAlmostEqual(ball_test.estimate_distance_cm(50, 1), 20.0, places=3)
        self.assertAlmostEqual(ball_test.estimate_distance_cm(200, 1), 5.0, places=3)
        self.assertIsNone(ball_test.estimate_distance_cm(0, 1))

    def test_in_range_passes_with_distance(self):
        ball_test.CALIB_WIDTH_PX = {1: 100.0}
        best, rejects = self.detect([(300, 140, 90, 90, 6360)])  # d = 1000/90 = 11.1cm
        self.assertIsNotNone(best)
        self.assertAlmostEqual(best["dist"], 11.1, places=1)
        self.assertEqual(rejects, [])

    def test_too_far_rejected(self):
        """后面的东西(远) -> w 小 -> 距离大 -> 被排掉"""
        ball_test.CALIB_WIDTH_PX = {1: 100.0}
        best, rejects = self.detect([(300, 140, 50, 50, 1963)])  # d = 20cm
        self.assertIsNone(best)
        self.assertEqual(len(rejects), 1)
        self.assertIn("距离", rejects[0][5])
        self.assertIn("超出", rejects[0][5])

    def test_too_close_rejected(self):
        ball_test.CALIB_WIDTH_PX = {1: 100.0}
        best, rejects = self.detect([(300, 140, 250, 250, 49087)])  # d = 4cm
        self.assertIsNone(best)
        self.assertIn("距离", rejects[0][5])

    def test_boundary_values_pass(self):
        ball_test.CALIB_WIDTH_PX = {1: 100.0}
        # d = 5.0cm 正好在下限, 15.0cm 正好在上限 -> 都该通过
        best, _ = self.detect([(10, 10, 200, 200, 31416)])       # d = 5.0
        self.assertIsNotNone(best)
        best, _ = self.detect([(10, 10, 67, 67, 3526)])          # d ≈ 14.9
        self.assertIsNotNone(best)

    def test_nearest_candidate_hint(self):
        """"未找到"时要能看出是"太远被排掉"而不是"没识别到\""""
        ball_test.CALIB_WIDTH_PX = {1: 100.0}
        best, rejects = self.detect([(300, 140, 50, 50, 1963)])  # d = 20cm
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.t.report_one(1, best, rejects)
        out = buf.getvalue()
        self.assertIn("未找到红球", out)
        self.assertIn("最近候选 20.0cm", out)
        self.assertIn("超出 5~15cm", out)


class TestScreenLabel(unittest.TestCase):
    """第二轮 R3: 屏幕标签用数字形式(与串口 body 字段一致, 纯 ASCII)"""

    def setUp(self):
        self.t = make_tester()
        self.t.disp = object()          # 非 None 才会走到画框分支
        ball_test.now_ms = Clock(0)

    def test_numeric_label(self):
        img = img_with(red=[])
        best = {"id": 1, "x": 300, "y": 140, "w": 60, "h": 60,
                "pixels": 2827, "dist": None}
        self.t.draw_result(img, [(1, best)])

        rects = [d for d in img.drawn if d[0] == "rect"]
        texts = [d[3] for d in img.drawn if d[0] == "text"]
        self.assertEqual(len(rects), 1)
        self.assertEqual(rects[0][1:], (300, 140, 60, 60))
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0], "1 x300 y140 w60 h60")

    def test_label_is_pure_ascii(self):
        """之前中文被默认字体渲染成问号, 所以标签必须是纯 ASCII"""
        img = img_with(red=[])
        best = {"id": 3, "x": 10, "y": 20, "w": 30, "h": 40,
                "pixels": 942, "dist": None}
        self.t.draw_result(img, [(3, best)])
        text = [d[3] for d in img.drawn if d[0] == "text"][0]
        self.assertTrue(all(ord(c) < 128 for c in text), "标签里不该有非 ASCII 字符")

    def test_rect_survives_string_failure(self):
        """写字那步不被支持时, 框也必须画出来(之前两步共用一个 try, 会连框都没有)"""
        t = make_tester()
        t.disp = object()
        img = img_with(red=[])

        def boom(*a, **k):
            raise TypeError("draw_string 签名不支持")

        img.draw_string = boom
        t.draw_result(img, [(1, {"id": 1, "x": 10, "y": 20, "w": 30, "h": 40,
                                 "pixels": 942, "dist": None})])
        rects = [d for d in img.drawn if d[0] == "rect"]
        self.assertEqual(len(rects), 1, "文字画不出来时, 框不能一起消失")

    def test_draw_error_is_reported(self):
        """DRAW_DEBUG=True 时, 画图报错要打出来(默认静默, 之前就是这个把人坑了)"""
        t = make_tester()
        t.disp = object()
        t.draw_err_seen = set()
        img = img_with(red=[])

        def boom(*a, **k):
            raise ValueError("color 参数不支持这种写法")

        img.draw_rect = boom
        ball_test.DRAW_DEBUG = True
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                t.draw_result(img, [(1, {"id": 1, "x": 1, "y": 2, "w": 3, "h": 4,
                                         "pixels": 10, "dist": None})])
                t.draw_result(img, [(1, {"id": 1, "x": 1, "y": 2, "w": 3, "h": 4,
                                         "pixels": 10, "dist": None})])
            out = buf.getvalue()
        finally:
            ball_test.DRAW_DEBUG = False
        self.assertIn("draw_rect", out)
        self.assertEqual(out.count("[错误] draw_rect"), 1, "同样的错误只报一次, 不刷屏")

    def test_draw_flag_off(self):
        t = make_tester()
        t.disp = None
        img = img_with(red=[])
        t.draw_result(img, [(1, {"id": 1, "x": 1, "y": 2, "w": 3, "h": 4,
                                 "pixels": 10, "dist": None})])
        self.assertEqual(img.drawn, [])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
