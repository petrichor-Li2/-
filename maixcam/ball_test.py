#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 MaixCAM 端 v2 —— 三色小球(红/绿/蓝)颜色识别 · 纯打印测试版
 2026 广东省工科大学生实验综合技能竞赛 · 赛项3
================================================================================

【这一版是干什么的】
  MaixCAM 现在只通过 USB 连电脑(用 MaixVision 在线运行), 与 STM32 的串口还没接。
  所以这一版**不参与整机联调**, 只做三件事:
      1. 把摄像头看到的红/绿/蓝小球找出来 —— **检测到什么颜色就打印什么颜色**
      2. 用像素宽度反推**距离**, 只保留 5~15cm 内的球(把"后面的东西"排掉)
      3. 终端打印 + 屏幕画框(标签用数字形式, 与将来发给 STM32 的串口字段一致)

【怎么跑】
  1. USB 线连 MaixCAM 与电脑, 打开 MaixVision
  2. 打开本文件, 点运行 -> 代码推送到设备执行
  3. MaixVision 终端看打印; MaixCAM 屏幕看画框

【终端输出长这样】
  ===== 小球测试 v2 启动 =====
  分辨率 640x320  检测颜色: 红(1) 绿(2) 蓝(3)
  [  1.20s] 红(1) x=300 y=140 w=60 h=60
  [  2.05s] 绿(2) x=120 y=160 w=58 h=57
  [  2.41s] 红(1) x=330 y=150 w=62 h=58  距离≈9.7cm
  [  3.02s] 未找到任何小球(红/绿/蓝)
  (标定后每行会追加 距离≈X.Xcm)

【已确认的需求】
  第一轮(详见 maixcam/DEV_LOG.md):
    1  只测小球(排爆物球体)的颜色识别
    2  打印字段: 包围盒 x/y/w/h (+颜色编号/名称)
    3  终端打印 + 屏幕画框, 两者都要
    4  球会移动 -> 全画面检测, 不做 ROI 限定
    5  暂不做 LAB 标定模式, 先用 v1 的三组阈值
    6  先只测一种颜色: 红(1)
    7  打印只在结果变化时触发
    8  不带 UART 协议
    9  不加截图 / 不加 FPS 显示
    10 误识别过滤: 最小面积 + 圆度(长宽比 + 饱满度)
  第二轮(真机试跑后):
    R1 距离限定 = 用像素大小反推距离, 并打印 cm 数
    R2 只接受 5~15cm(超出时打印"最近候选 xx cm")
    R3 屏幕标签改成数字形式(与串口 body 字段一致): 1 x300 y140 w60 h60
       终端保留中文+数字(真机已验证终端支持 UTF-8)
    R4 标定值先留空: 未标定时不卡距离, 只打印 w 和提示
  第三轮(本次):
    S1 三种颜色(红/绿/蓝)都检测, 检测到什么颜色就打印什么颜色
       -> PRINT_ONLY_DETECTED = True: 只打印检到的球; 全场没有时才打印一行
          "未找到任何小球(红/绿/蓝)", 不会为"没检到的颜色"各刷一行
    S2 距离标定改成**按颜色分开**: 三个球大小一样就填同一个数;
       大小不同就各自标定(标定方法见 CALIB_WIDTH_PX 注释)
================================================================================
"""

import time

from maix import app, camera, display, image

# ==============================================================================
# 一、配置区 —— 现场只需要改这里
# ==============================================================================

# ---- 检测哪些颜色: 赛题编码 1 红 / 2 绿 / 3 蓝 ----
#   现在三种都检测(检测到什么颜色就打什么颜色)
ALL_COLORS = True
#   想只测一种时就把它改成 False, 并把 TARGET_COLOR 设成 1/2/3
TARGET_COLOR = 1

# ---- 打印策略 ----
#   True  : 只打印"检测到的球"; 整幅画面一个都没检到时, 才打印一行"未找到任何小球"
#           (推荐: 三色同时检测时输出最干净)
#   False : 每种颜色各自打印, 包括"未找到绿球"这种逐色提示(调单色阈值时用)
PRINT_ONLY_DETECTED = True

# ---- 相机 ----
CAM_WIDTH = 640
CAM_HEIGHT = 320

# ---- 颜色阈值 (LAB) —— v1 里已确认的三组, 现场灯光变了要重标 ----
COLOR_LAB = {
    1: (11, 68, 29, 75, 21, 33),      # 红
    2: (25, 52, -41, -5, -16, 28),    # 绿
    3: (13, 59, -23, 13, -58, -15),   # 蓝
}
COLOR_NAME = {1: "红", 2: "绿", 3: "蓝"}

# ---- 过滤: 只要"像球的" ----
MIN_AREA = 100          # 小于这么多像素的色块丢掉 (噪点/碎斑)
ASPECT_MIN = 0.70       # 长宽比 w/h 下限 (球在画面里近似圆)
ASPECT_MAX = 1.40       # 长宽比 w/h 上限
FILL_MIN = 0.50         # 饱满度 = 像素数/(w*h): 圆的理想值 ≈ π/4 = 0.785
FILL_MAX = 0.92         # 实心方块/整块背景 ≈ 1.0, 上限卡掉

# ---- 距离限定 (第二轮 R1~R4 + 第三轮 S2) -----------------------------------
#   原理: 球在画面里的宽度 w 与距离 d 成反比  ->  d = K / w
#        K = CALIB_DISTANCE_CM * CALIB_WIDTH_PX[颜色]
#   标定: 把球放在 CALIB_DISTANCE_CM 处(比如 10cm), 读终端打印的 w,
#         把它填进 CALIB_WIDTH_PX 对应颜色里(只做一次)
CALIB_DISTANCE_CM = 10.0    # 标定时球放的距离 (cm)
CALIB_WIDTH_PX = {          # ★标定时读到的 w(像素); 0 = 该颜色还没标定(不卡该颜色的距离)
    1: 0.0,                 # 红
    2: 0.0,                 # 绿
    3: 0.0,                 # 蓝
}
DIST_MIN_CM = 5.0           # 只接受这个范围内的球
DIST_MAX_CM = 15.0
PRINT_DISTANCE = True       # 打印估算距离

# ---- 打印策略 ----
PRINT_MOVE_PX = 20            # 中心点移动超过这么多像素才再打一行
PRINT_MIN_INTERVAL_MS = 1000  # 位移打印的最小间隔(兜底限流); 有球/无球切换不受限
SHOW_REJECT = False           # True: 打印结果时附带"被过滤掉的候选及原因"

# ---- 屏幕显示 ----
DRAW = True              # 画框 + 写数字标签
DRAW_DEBUG = True        # True: 打印"当前用的是哪种颜色写法"/画图报错原文
                         #       (正在排查"屏幕上没有框", 查完可以改回 False)
DRAW_SELFTEST = True     # True: 启动后前 2 秒在画面正中画一个测试框 + "DRAW TEST"
                         #       用来区分"画图 API 有问题"和"没检测到球"
                         #       (正在排查, 查完可以改回 False)
LABEL_FIXED_POS = True   # True: 文字标签固定写在画面左上角(多个球依次往下排)
                         #       这样即使球的框在屏幕可见区域之外, 数字也一定看得到
                         #       False: 标签跟在框旁边(好看但可能跑出可见区域)
# 框色: 优先用 image 模块自带的常量(最兼容), 拿不到才用下面这组 RGB 元组
RECT_COLOR_RGB = {
    1: (255, 0, 0),      # 红球红框
    2: (0, 255, 0),      # 绿球绿框
    3: (0, 128, 255),    # 蓝球蓝框
}


# ==============================================================================
# 二、兼容层: MaixPy 不同版本的 API 小差异都挡在这里
# ==============================================================================
def _val(obj, name, default=None):
    """blob.x 在不同版本里可能是属性, 也可能是方法"""
    v = getattr(obj, name, None)
    if v is None:
        return default
    try:
        return v() if callable(v) else v
    except Exception:
        return default


# 画图用的颜色形式: 不同固件支持的不一样(Color.from_rgb / COLOR_XXX 常量 / 元组 / 整数),
# 代码会自动依次试, 记住能用的那种。None = 还没试出来。
_COLOR_MODE = None


def color_candidates(color_id):
    """按"最可能被支持"的顺序, 列出画图颜色的几种写法"""
    r, g, b = RECT_COLOR_RGB.get(color_id, (0, 255, 0))
    out = []

    # ① image.Color.from_rgb(r,g,b) —— 官方 API 文档写法
    try:
        f = getattr(getattr(image, "Color", None), "from_rgb", None)
        if callable(f):
            out.append(("Color.from_rgb", f(r, g, b)))
    except Exception:
        pass

    # ② image.COLOR_XXX 常量 —— 官网 find_blobs 例子里用的是 image.COLOR_GREEN
    cname = {1: "COLOR_RED", 2: "COLOR_GREEN", 3: "COLOR_BLUE"}.get(color_id)
    if cname:
        c = getattr(image, cname, None)
        if c is not None:
            out.append((cname, c))

    # ③ 直接给 (r,g,b) 元组 —— API 文档里 draw_rect 也接受元组
    out.append(("rgb tuple", (r, g, b)))

    # ④ 直接给 0xRRGGBB 整数
    out.append(("rgb int", (r << 16) | (g << 8) | b))

    # 已经试出可用的写法, 就只用它, 不再每次试错
    if _COLOR_MODE is not None:
        picked = [c for c in out if c[0] == _COLOR_MODE]
        if picked:
            return picked
    return out


def blob_box(b):
    """
    取色块包围盒 (x, y, w, h)
    MaixPy v4 官网例子用下标访问: blob[0..3] = x, y, w, h
    老写法是 blob.x() 这种属性/方法, 两种都支持
    """
    try:
        return int(b[0]), int(b[1]), int(b[2]), int(b[3])
    except Exception:
        pass
    return (int(_val(b, "x", 0)), int(_val(b, "y", 0)),
            int(_val(b, "w", 0)), int(_val(b, "h", 0)))


def blob_pixels(b):
    """取色块像素数 (优先 pixels(), 其次下标 4, 最后用 w*h 兜底)"""
    px = _val(b, "pixels")
    if px is not None:
        try:
            return int(px)
        except Exception:
            pass
    try:
        return int(b[4])
    except Exception:
        pass
    _, _, w, h = blob_box(b)
    return w * h


# ==============================================================================
# 三、距离估算 (第二轮 R1/R2/R4, 第三轮 S2 改成按颜色标定)
# ==============================================================================
def _calib_px(color_id):
    v = CALIB_WIDTH_PX.get(color_id, 0.0)
    try:
        return float(v)
    except Exception:
        return 0.0


def calib_ready(color_id=None):
    """color_id 省略时, 只要有一个颜色标定过就算 True"""
    if color_id is None:
        return any(_calib_px(c) > 0.0 for c in (1, 2, 3))
    return _calib_px(color_id) > 0.0


def estimate_distance_cm(w, color_id):
    """
    用像素宽度反推距离: d = K / w,  K = CALIB_DISTANCE_CM * CALIB_WIDTH_PX[颜色]
    该颜色未标定时返回 None (此时不卡它的距离, 只打印 w)
    """
    if w <= 0:
        return None
    k_px = _calib_px(color_id)
    if k_px <= 0.0:
        return None
    return (CALIB_DISTANCE_CM * k_px) / float(w)


def distance_ok(d):
    """距离是否在接受范围内; 未标定(d=None)时一律通过"""
    if d is None:
        return True
    return (DIST_MIN_CM <= d <= DIST_MAX_CM)


# ==============================================================================
# 四、识别: 找"像球的"色块
# ==============================================================================
def judge(w, h, pixels):
    """形状判断; 返回 None = 通过, 否则返回被拒绝的原因"""
    if pixels < MIN_AREA:
        return "面积%d<%d" % (pixels, MIN_AREA)
    if w <= 0 or h <= 0:
        return "尺寸异常"

    aspect = float(w) / float(h)
    if aspect < ASPECT_MIN or aspect > ASPECT_MAX:
        return "长宽比%.2f 不在 %.2f~%.2f" % (aspect, ASPECT_MIN, ASPECT_MAX)

    fill = float(pixels) / float(w * h)
    if fill < FILL_MIN or fill > FILL_MAX:
        return "饱满度%.2f 不在 %.2f~%.2f" % (fill, FILL_MIN, FILL_MAX)

    return None


_FIND_BLOBS_ERR_PRINTED = False


def detect_color(img, color_id):
    """
    在整幅画面里找指定颜色的"球": 形状合格 + 距离在范围内
    返回 (best, rejects):
      best    = dict(id,x,y,w,h,pixels,dist) 或 None
      rejects = [(x,y,w,h,pixels,原因), ...] 方便调参数
    """
    global _FIND_BLOBS_ERR_PRINTED

    thr = COLOR_LAB[color_id]
    try:
        blobs = img.find_blobs([thr], area_threshold=MIN_AREA,
                               pixels_threshold=MIN_AREA, merge=True)
    except TypeError:
        try:
            blobs = img.find_blobs([thr])      # 个别版本没有这些关键字参数
        except Exception as e:
            if not _FIND_BLOBS_ERR_PRINTED:
                print("[错误] find_blobs 调用失败:", e)
                _FIND_BLOBS_ERR_PRINTED = True
            return None, []
    except Exception as e:
        if not _FIND_BLOBS_ERR_PRINTED:
            print("[错误] find_blobs 调用失败:", e)
            _FIND_BLOBS_ERR_PRINTED = True
        return None, []

    best = None
    rejects = []

    for b in blobs or []:
        x, y, w, h = blob_box(b)
        px = blob_pixels(b)

        # ① 形状过滤 (只要像球的)
        reason = judge(w, h, px)
        if reason is not None:
            rejects.append((x, y, w, h, px, reason))
            continue

        # ② 距离过滤 (把后面的东西排掉)
        d = estimate_distance_cm(w, color_id) if PRINT_DISTANCE else None
        if not distance_ok(d):
            rejects.append((x, y, w, h, px,
                            "距离%.1fcm 超出 %.0f~%.0fcm"
                            % (d, DIST_MIN_CM, DIST_MAX_CM)))
            continue

        if (best is None) or (px > best["pixels"]):
            best = {"id": color_id, "x": x, "y": y, "w": w, "h": h,
                    "pixels": px, "dist": d}

    return best, rejects


def nearest_reject_cm(rejects, color_id):
    """从被拒候选里找最近的估算距离(用它的 w 反推), 给"未找到"一个解释"""
    if not PRINT_DISTANCE or not calib_ready(color_id):
        return None
    ds = []
    for r in rejects:
        d = estimate_distance_cm(r[2], color_id)
        if d is not None:
            ds.append(d)
    return min(ds) if ds else None


# ==============================================================================
# 五、主程序
# ==============================================================================
def now_ms():
    return int(time.time() * 1000)


def format_ball(color_id, best, with_move=False, cx=None, cy=None):
    """一行结果文本: 红(1) x=300 y=140 w=60 h=60  距离≈9.7cm"""
    line = "%s(%d) x=%d y=%d w=%d h=%d" % (
        COLOR_NAME[color_id], color_id,
        best["x"], best["y"], best["w"], best["h"])
    if best.get("dist") is not None:
        line += "  距离≈%.1fcm" % best["dist"]
    if with_move and (cx is not None):
        line += "  (中心 %d,%d)" % (cx, cy)
    return line


class BallTester:

    def __init__(self):
        try:
            self.cam = camera.Camera(CAM_WIDTH, CAM_HEIGHT)
        except Exception as e:
            print("[警告] camera.Camera(%d,%d) 失败, 改用默认分辨率:"
                  % (CAM_WIDTH, CAM_HEIGHT), e)
            self.cam = camera.Camera()

        self.disp = None
        if DRAW:
            try:
                self.disp = display.Display()
            except Exception as e:
                print("[警告] 屏幕不可用, 关掉画框:", e)
                self.disp = None

        self.targets = [1, 2, 3] if ALL_COLORS else [TARGET_COLOR]
        self.t0 = time.time()
        self.draw_err_seen = set()      # 画图报错只打一次, 不刷屏

        # ---- 打印状态 ----
        # 逐色模式(PRINT_ONLY_DETECTED=False)用: 每个颜色一套状态
        self.st = {cid: {"found": None, "cx": None, "cy": None, "t": 0}
                   for cid in self.targets}
        # 只报检到模式(True)用: 上一帧检到的颜色与中心点
        self.prev_centers = {}          # {cid: (cx, cy)}
        self.prev_keys = ()             # 上一帧检到的颜色集合
        self.last_any_ms = 0

    # ------------------------------------------------------------------
    def elapsed_s(self):
        return time.time() - self.t0

    # ------------------------------------------------------------------
    def banner(self):
        print("===== 小球测试 v2 启动 =====")
        print("分辨率 %dx%d  检测颜色: %s"
              % (CAM_WIDTH, CAM_HEIGHT,
                 " ".join("%s(%d)" % (COLOR_NAME[c], c) for c in self.targets)))
        if not ALL_COLORS:
            print("注意: 当前只测 %s(%d) —— 想三色都测就把 ALL_COLORS 改成 True"
                  % (COLOR_NAME[TARGET_COLOR], TARGET_COLOR))
        print("过滤: 面积>=%dpx  长宽比 %.2f~%.2f  饱满度 %.2f~%.2f"
              % (MIN_AREA, ASPECT_MIN, ASPECT_MAX, FILL_MIN, FILL_MAX))

        ready = [c for c in self.targets if calib_ready(c)]
        if ready:
            print("距离: 已标定 %s  只接受 %.0f~%.0fcm"
                  % (" ".join("%s %dpx" % (COLOR_NAME[c], int(_calib_px(c)))
                              for c in ready), DIST_MIN_CM, DIST_MAX_CM))
            left = [c for c in self.targets if not calib_ready(c)]
            if left:
                print("      未标定: %s (这几个颜色暂时不卡距离)"
                      % " ".join(COLOR_NAME[c] for c in left))
        else:
            print("距离: **未标定** -> 现在不卡距离, 但会把 w 打出来;")
            print("      把球放到 %.0fcm 处, 读下面的 w=?? , 填进 CALIB_WIDTH_PX 对应颜色"
                  % CALIB_DISTANCE_CM)

        if PRINT_ONLY_DETECTED:
            print("打印: 只报检测到的球; 整幅画面都没有时才打印一行'未找到任何小球'")
        else:
            print("打印: 每种颜色各自独立打印(含'未找到X球')")
        print("      位移超过 %dpx 且间隔>%dms 才重复打印" %
              (PRINT_MOVE_PX, PRINT_MIN_INTERVAL_MS))

    # ------------------------------------------------------------------
    # 逐色模式 (PRINT_ONLY_DETECTED = False)
    # ------------------------------------------------------------------
    def report_one(self, color_id, best, rejects):
        """逐色模式: 打印 + 更新这个颜色的状态; 返回是否打印了"""
        s = self.st[color_id]
        t_ms = now_ms()

        if best is None:
            if s["found"] is not False:
                line = "[%6.2fs] 未找到%s球" % (self.elapsed_s(),
                                                COLOR_NAME[color_id])
                nd = nearest_reject_cm(rejects, color_id)
                if (nd is not None) and (not distance_ok(nd)):
                    line += "  (最近候选 %.1fcm, 超出 %.0f~%.0fcm)" % (
                        nd, DIST_MIN_CM, DIST_MAX_CM)
                elif SHOW_REJECT and rejects:
                    line += "  (过滤掉: " + "; ".join(
                        "%dx%d %dpx %s" % (r[2], r[3], r[4], r[5])
                        for r in rejects) + ")"
                print(line)
                s["found"] = False
                s["cx"] = s["cy"] = None
                s["t"] = t_ms
                return True
            return False

        x, y, w, h = best["x"], best["y"], best["w"], best["h"]
        cx, cy = x + w // 2, y + h // 2
        state_changed = (s["found"] is not True)
        moved = False
        if not state_changed and s["cx"] is not None:
            if (t_ms - s["t"] >= PRINT_MIN_INTERVAL_MS) and \
               (abs(cx - s["cx"]) > PRINT_MOVE_PX or
                    abs(cy - s["cy"]) > PRINT_MOVE_PX):
                moved = True

        if not (state_changed or moved):
            s["cx"], s["cy"] = cx, cy
            return False

        print("[%6.2fs] %s" % (self.elapsed_s(),
                               format_ball(color_id, best, moved, cx, cy)))
        s["found"] = True
        s["cx"], s["cy"] = cx, cy
        s["t"] = t_ms
        return True

    # ------------------------------------------------------------------
    # 只报检到模式 (PRINT_ONLY_DETECTED = True) —— 第三轮 S1
    # ------------------------------------------------------------------
    def report_multi(self, found, rejects_by_color):
        """
        found: [(cid, best), ...]  本帧检到的球
        只打印"检到的"; 整幅画面一个都没有时, 若上一帧有, 打印一行"未找到任何小球"
        """
        t_ms = now_ms()

        if not found:
            if self.prev_keys:
                line = "[%6.2fs] 未找到任何小球(%s)" % (
                    self.elapsed_s(),
                    "/".join(COLOR_NAME[c] for c in self.targets))
                # 有候选但被"距离"排掉的, 给出提示
                hints = []
                for cid in self.targets:
                    nd = nearest_reject_cm(rejects_by_color.get(cid, []), cid)
                    if (nd is not None) and (not distance_ok(nd)):
                        hints.append("%s %.1fcm" % (COLOR_NAME[cid], nd))
                if hints:
                    line += "  (最近候选 " + ", ".join(hints) + \
                            ", 超出 %.0f~%.0fcm)" % (DIST_MIN_CM, DIST_MAX_CM)
                elif SHOW_REJECT:
                    n = sum(len(v) for v in rejects_by_color.values())
                    if n:
                        line += "  (共过滤掉 %d 个候选)" % n
                print(line)
                self.prev_keys = ()
                self.prev_centers = {}
                self.last_any_ms = t_ms
            return

        keys = tuple(sorted(cid for cid, _ in found))
        printed_any = False

        for cid, best in found:
            x, y, w, h = best["x"], best["y"], best["w"], best["h"]
            cx, cy = x + w // 2, y + h // 2

            prev = self.prev_centers.get(cid)
            is_new = (prev is None)
            moved = False
            if (not is_new) and (t_ms - self.last_any_ms >= PRINT_MIN_INTERVAL_MS):
                if (abs(cx - prev[0]) > PRINT_MOVE_PX or
                        abs(cy - prev[1]) > PRINT_MOVE_PX):
                    moved = True

            if is_new or moved:
                print("[%6.2fs] %s" % (self.elapsed_s(),
                                       format_ball(cid, best, moved, cx, cy)))
                printed_any = True

            self.prev_centers[cid] = (cx, cy)

        if printed_any:
            self.last_any_ms = t_ms
        self.prev_keys = keys

    # ------------------------------------------------------------------
    # 画图: 颜色写法自动试错 —— 不同 MaixPy 固件支持的形式不一样, 不再猜
    # ------------------------------------------------------------------
    def _draw_rect(self, img, x, y, w, h, cid):
        global _COLOR_MODE
        errs = []
        for name, c in color_candidates(cid):
            try:
                img.draw_rect(x, y, w, h, color=c, thickness=2)
                if _COLOR_MODE is None:
                    _COLOR_MODE = name
                    if DRAW_DEBUG:
                        print("[提示] 画框可用的颜色写法: %s" % name)
                return True
            except Exception as e:
                errs.append("%s -> %r" % (name, e))
        if "draw_rect" not in self.draw_err_seen:
            self.draw_err_seen.add("draw_rect")
            print("[错误] draw_rect 四种颜色写法都失败了:")
            for e in errs:
                print("        ", e)
            print("        -> 把这几行发我, 我按你的固件改")
        return False

    def _draw_string(self, img, x, y, s, cid):
        """
        写文字: 不同固件的参数写法/类型要求不一样, 依次尝试:
          ① color= + scale=1(整数!)   ② 只给 color=   ③ 位置参数 (x,y,s,c,1)
          ④ 位置参数 (x,y,s,c)        ⑤ 只给 (x,y,s)  ⑥ (x,y,s,c) 不带 scale
        注意 scale 用整数: 官方文档是 scale=2, 传浮点 1.0 有些固件会抛 TypeError
        """
        errs = []
        for name, c in color_candidates(cid):
            attempts = (
                (dict(color=c, scale=1), "color=+scale=1"),
                (dict(color=c), "color="),
                ((c, 1), "位置(c,1)"),
                ((c,), "位置(c)"),
                ((), "位置()"),
            )
            for extra, how in attempts:
                try:
                    if isinstance(extra, dict):
                        img.draw_string(x, y, s, **extra)
                    else:
                        img.draw_string(x, y, s, *extra)
                    if DRAW_DEBUG and ("ok_string" not in self.draw_err_seen):
                        self.draw_err_seen.add("ok_string")
                        print("[提示] 写字可用的写法: 颜色=%s, %s" % (name, how))
                    return True
                except Exception as e:
                    errs.append("%s/%s -> %r" % (name, how, e))
        if "draw_string" not in self.draw_err_seen:
            self.draw_err_seen.add("draw_string")
            print("[错误] draw_string 所有写法都失败了, 前几种原因:")
            for e in errs[:6]:
                print("        ", e)
            print("        -> 把这几行发我, 我按你的固件改")
        return False

    # ------------------------------------------------------------------
    def draw_result(self, img, found):
        """
        屏幕上给每个检到的球画框 + 写标签。
        标签是**数字形式**(纯 ASCII), 字段顺序与将来发给 STM32 的串口 body 一致:
            <颜色编号> x<> y<> w<> h<>
        画框与写字**各自独立**, 互不影响; 颜色写法自动试错。
        """
        if self.disp is None:
            return
        for i, (cid, best) in enumerate(found):
            x, y, w, h = best["x"], best["y"], best["w"], best["h"]

            # ① 画框
            self._draw_rect(img, x, y, w, h, cid)

            # ② 写字(失败也不影响框)
            label = "%d x%d y%d w%d h%d" % (cid, x, y, w, h)
            if LABEL_FIXED_POS:
                self._draw_string(img, 4, 4 + i * 24, label, cid)
            else:
                ty = y - 22 if y > 26 else y + 2
                self._draw_string(img, x, ty, label, cid)

    # ------------------------------------------------------------------
    def warn_if_out_of_frame(self, found):
        """
        目标坐标超出画面时提醒一次 —— 球半个在画面外时, 框会贴着边缘甚至看不见,
        终端里这行警告能立刻说明是"球的位置问题"而不是"画图坏了"
        """
        for cid, best in found:
            x, y, w, h = best["x"], best["y"], best["w"], best["h"]
            if (x < 0) or (y < 0) or (x + w > CAM_WIDTH) or (y + h > CAM_HEIGHT):
                if "out_of_frame" not in self.draw_err_seen:
                    self.draw_err_seen.add("out_of_frame")
                    print("[警告] 目标超出画面: x=%d y=%d w=%d h=%d (画面 %dx%d)"
                          % (x, y, w, h, CAM_WIDTH, CAM_HEIGHT))
                    print("       半个球在画面外时, 框可能贴着边缘甚至看不见 -> "
                          "把球往画面中间挪一点再看")
                return

    # ------------------------------------------------------------------
    def _draw_err(self, what, e):
        """其它画图相关错误(如 display.show): 默认只记一次不刷屏"""
        if DRAW_DEBUG and (what not in self.draw_err_seen):
            self.draw_err_seen.add(what)
            print("[错误] %s 失败: %r" % (what, e))

    # ------------------------------------------------------------------
    def draw_selftest(self, img, seconds=2.0):
        """
        画图自检: 启动后前几秒在画面正中画一个测试框 + DRAW TEST。
        用来区分两种"屏幕上没框":
           · 能看到这个测试框  -> 画图 API 正常, 问题在"没检测到球"
           · 连测试框都没有    -> 画图 API / display 有问题(终端会打印错误)
        """
        if (self.disp is None) or (self.elapsed_s() > seconds):
            return
        w, h = 220, 110
        x = (CAM_WIDTH - w) // 2
        y = (CAM_HEIGHT - h) // 2
        self._draw_rect(img, x, y, w, h, 1)
        self._draw_string(img, x + 6, y + 6, "DRAW TEST", 1)

    # ------------------------------------------------------------------
    def run(self):
        self.banner()
        print("连续识别中... (MaixVision 里点停止即结束)")

        while not app.need_exit():
            img = self.cam.read()

            found = []
            rejects_by_color = {}
            for cid in self.targets:
                best, rejects = detect_color(img, cid)
                rejects_by_color[cid] = rejects
                if PRINT_ONLY_DETECTED:
                    if best is not None:
                        found.append((cid, best))
                else:
                    self.report_one(cid, best, rejects)

            if PRINT_ONLY_DETECTED:
                self.report_multi(found, rejects_by_color)

            self.draw_result(img, found)
            self.warn_if_out_of_frame(found)
            if DRAW_SELFTEST:
                self.draw_selftest(img)

            if self.disp is not None:
                try:
                    self.disp.show(img)
                except Exception as e:
                    self._draw_err("display.show", e)


def main():
    try:
        BallTester().run()
    except Exception as e:
        print("[致命错误]", e)
        raise


if __name__ == "__main__":
    main()
