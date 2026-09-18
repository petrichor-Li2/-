#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 MaixCAM 端 v2 —— 单色小球(排爆物球体)颜色识别 · 纯打印测试版
 2026 广东省工科大学生实验综合技能竞赛 · 赛项3
================================================================================

【这一版是干什么的】
  现在 MaixCAM 只通过 USB 连电脑(用 MaixVision 在线运行), 与 STM32 的串口还没接。
  所以这一版**不参与整机联调**, 只做一件事:
      把摄像头看到的红色小球找出来, 把 x/y/w/h 打印到 MaixVision 终端,
      同时在 MaixCAM 屏幕上给球画个框并写上颜色名。
  用来: 对着真实物体看识别准不准、看阈值宽窄、看画面不同位置的表现。

【和 v1 的关系】
  v1(接 STM32 的串口协议版)已备份在 maixcam/backup/main_v1_stm32_uart.py,
  这一版完全独立, 不含任何 UART / 协议代码。将来联调直接跑 v1。

【怎么跑】
  1. USB 线连 MaixCAM 与电脑, 打开 MaixVision
  2. 打开本文件, 点运行 -> 代码推送到设备执行
  3. MaixVision 下方终端看打印; MaixCAM 屏幕看画框

【终端输出长这样】
  ===== 红球测试 v2 启动 =====
  分辨率 640x320  目标颜色 红(1)  阈值 [11, 68, 29, 75, 21, 33]
  过滤: 面积>=100px  长宽比 0.70~1.40  饱满度 0.50~0.92
  打印: 有球<->无球切换立即打; 位移超过 20px 且间隔>1000ms 才再打
  [  1.20s] 红(1) x=300 y=140 w=60 h=60
  [  2.41s] 红(1) x=330 y=150 w=62 h=58  (中心 361,179)     <- 球动了才再打
  [  3.02s] 未找到红球                                       <- 丢了立刻打

【已确认的需求(见 maixcam/DEV_LOG.md)】
  1  只测小球(排爆物球体)的颜色识别
  2  打印字段: 包围盒 x/y/w/h (+颜色编号/名称, 否则不知道是哪一行)
  3  终端打印 + 屏幕画框写字, 两者都要
  4  球会移动, 不固定位置 -> 全画面检测, 不做 ROI 限定
  5  暂不做 LAB 标定模式, 先用 v1 的三组阈值
  6  先只测一种颜色: 红(1); 改一个常量即可切绿/蓝
  7  打印只在结果变化时触发(见 PRINT_* 参数)
  8  不带 UART 协议
  9  不加截图 / 不加 FPS 显示(保持最小)
  10 误识别过滤: 最小面积 + 圆度(长宽比 + 饱满度), 只要"像球的"
================================================================================
"""

import time

from maix import app, camera, display, image

# ==============================================================================
# 一、配置区 —— 现场只需要改这里
# ==============================================================================

# ---- 目标颜色: 1 红 / 2 绿 / 3 蓝 (赛题编码) ----
TARGET_COLOR = 1

# ---- 调试用: True 时三种颜色都找、各自独立打印, 用来比较哪个阈值太宽/太窄 ----
ALL_COLORS = False

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

# ---- 过滤: 只要"像球的" (第 11 问的结论) ----
MIN_AREA = 100          # 小于这么多像素的色块丢掉 (噪点/碎斑)
ASPECT_MIN = 0.70       # 长宽比 w/h 下限: 球在画面里近似圆, 太扁/太细的不要
ASPECT_MAX = 1.40       # 长宽比 w/h 上限
FILL_MIN = 0.50         # 饱满度 = 像素数/(w*h): 圆的理想值是 π/4≈0.785
FILL_MAX = 0.92         # 长方块/整块背景会接近 1.0, 上限卡掉

# ---- 打印策略 (第 7 问的结论) ----
PRINT_MOVE_PX = 20            # 中心点移动超过这么多像素才再打一行
PRINT_MIN_INTERVAL_MS = 1000  # 位移打印的最小间隔(兜底限流); 有球/无球切换不受限
SHOW_REJECT = False           # True: 打印结果时附带"被过滤掉的候选及原因"

# ---- 屏幕显示 ----
DRAW = True                   # 在屏幕上画框 + 写颜色名


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
# 三、识别: 找"像球的"色块
# ==============================================================================
def judge(w, h, pixels):
    """对候选色块做形状判断; 返回 None = 通过, 否则返回被拒绝的原因"""
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
    在整幅画面里找指定颜色的"球"
    返回 (best, rejects):
      best    = dict(id,x,y,w,h,pixels) 或 None (最大的那个合格候选)
      rejects = [(x,y,w,h,pixels,原因), ...] 被过滤掉的候选, 方便调参数
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
        reason = judge(w, h, px)
        if reason is None:
            if (best is None) or (px > best["pixels"]):
                best = {"id": color_id, "x": x, "y": y, "w": w, "h": h,
                        "pixels": px}
        else:
            rejects.append((x, y, w, h, px, reason))

    return best, rejects


# ==============================================================================
# 四、主程序
# ==============================================================================
def now_ms():
    return int(time.time() * 1000)


class BallTester:
    """每个颜色各有一套打印状态, 所以 ALL_COLORS=True 时也不会互相干扰"""

    def __init__(self):
        # ---- 相机 ----
        try:
            self.cam = camera.Camera(CAM_WIDTH, CAM_HEIGHT)
        except Exception as e:
            print("[警告] camera.Camera(%d,%d) 失败, 改用默认分辨率:"
                  % (CAM_WIDTH, CAM_HEIGHT), e)
            self.cam = camera.Camera()

        # ---- 屏幕 ----
        self.disp = None
        if DRAW:
            try:
                self.disp = display.Display()
            except Exception as e:
                print("[警告] 屏幕不可用, 关掉画框:", e)
                self.disp = None

        self.targets = [1, 2, 3] if ALL_COLORS else [TARGET_COLOR]
        self.st = {cid: {"found": None, "cx": None, "cy": None, "t": 0}
                   for cid in self.targets}
        self.t0 = time.time()

    # ------------------------------------------------------------------
    def elapsed_s(self):
        return time.time() - self.t0

    # ------------------------------------------------------------------
    def banner(self):
        print("===== 红球测试 v2 启动 =====")
        print("分辨率 %dx%d  目标颜色 %s(%d)  阈值 %s"
              % (CAM_WIDTH, CAM_HEIGHT, COLOR_NAME[TARGET_COLOR],
                 TARGET_COLOR, list(COLOR_LAB[TARGET_COLOR])))
        if ALL_COLORS:
            print("注意: ALL_COLORS=True, 三种颜色都会找并各自独立打印")
        print("过滤: 面积>=%dpx  长宽比 %.2f~%.2f  饱满度 %.2f~%.2f"
              % (MIN_AREA, ASPECT_MIN, ASPECT_MAX, FILL_MIN, FILL_MAX))
        print("打印: 有球<->无球切换立即打; 位移超过 %dpx 且间隔>%dms 才再打"
              % (PRINT_MOVE_PX, PRINT_MIN_INTERVAL_MS))
        if SHOW_REJECT:
            print("SHOW_REJECT=True: 被过滤的候选会一起打出来")

    # ------------------------------------------------------------------
    def report(self, color_id, best, rejects):
        """打印 + 更新这个颜色的状态; 返回是否打印了"""
        s = self.st[color_id]
        t_ms = now_ms()

        # ---------- 没找到 ----------
        if best is None:
            if s["found"] is not False:              # 有球 -> 无球, 立刻打
                line = "[%6.2fs] 未找到%s球" % (self.elapsed_s(),
                                                COLOR_NAME[color_id])
                if SHOW_REJECT and rejects:
                    line += "  (过滤掉: " + "; ".join(
                        "%dx%d %dpx %s" % (r[2], r[3], r[4], r[5])
                        for r in rejects) + ")"
                print(line)
                s["found"] = False
                s["cx"] = s["cy"] = None
                s["t"] = t_ms
                return True
            return False

        # ---------- 找到 ----------
        x, y, w, h, px = (best["x"], best["y"], best["w"], best["h"],
                          best["pixels"])
        cx, cy = x + w // 2, y + h // 2

        state_changed = (s["found"] is not True)
        moved = False
        if not state_changed and s["cx"] is not None:
            if (t_ms - s["t"] >= PRINT_MIN_INTERVAL_MS) and \
               (abs(cx - s["cx"]) > PRINT_MOVE_PX or
                    abs(cy - s["cy"]) > PRINT_MOVE_PX):
                moved = True

        if not (state_changed or moved):
            s["cx"], s["cy"] = cx, cy      # 记最新位置, 但不打印
            return False

        line = "[%6.2fs] %s(%d) x=%d y=%d w=%d h=%d" % (
            self.elapsed_s(), COLOR_NAME[color_id], color_id, x, y, w, h)
        if moved:
            line += "  (中心 %d,%d)" % (cx, cy)
        if SHOW_REJECT and rejects:
            line += "  (另过滤掉 %d 个候选)" % len(rejects)
        print(line)

        s["found"] = True
        s["cx"], s["cy"] = cx, cy
        s["t"] = t_ms
        return True

    # ------------------------------------------------------------------
    def draw_result(self, img, found_list):
        """屏幕上给所有找到的球画框"""
        if self.disp is None:
            return
        for cid, best in found_list:
            try:
                x, y, w, h = best["x"], best["y"], best["w"], best["h"]
                img.draw_rect(x, y, w, h, color=image.COLOR_GREEN, thickness=2)
                ty = y - 22 if y > 26 else y + 2
                img.draw_string(x, ty,
                                "%s %dx%d" % (COLOR_NAME[cid], w, h),
                                color=image.COLOR_GREEN, scale=1.2)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def run(self):
        self.banner()
        print("连续识别中... (MaixVision 里点停止即结束)")

        while not app.need_exit():
            img = self.cam.read()

            found_list = []
            for cid in self.targets:
                best, rejects = detect_color(img, cid)
                self.report(cid, best, rejects)
                if best is not None:
                    found_list.append((cid, best))

            self.draw_result(img, found_list)

            if self.disp is not None:
                try:
                    self.disp.show(img)
                except Exception:
                    pass


def main():
    try:
        BallTester().run()
    except Exception as e:
        print("[致命错误]", e)
        raise


if __name__ == "__main__":
    main()
