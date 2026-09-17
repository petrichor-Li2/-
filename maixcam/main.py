#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 反恐排爆救援机器人 —— MaixCAM-Pro 视觉端 (MaixPy v4)
 2026 广东省工科大学生实验综合技能竞赛 · 赛项3
================================================================================

【定位】完全被动的视觉模块, 识别节奏由 STM32 控制:
    · 不主动拍图、不主动识别、不主动上报
    · 收到 0x10 -> 模式 = 颜色
    · 收到 0x11 -> 模式 = 形状
    · 收到 0x12 -> 拍一帧、按当前模式识别一次、上报一帧、回等待

【上报什么】只报编号 + 原始坐标, 不做匹配判断、不做范围判断 (那是 STM32 的事)
    颜色: cmd=0x01, body = 颜色(1) + x(2) + y(2) + w(2) + h(2)
    形状: cmd=0x02, body = 形状(1) + x(2) + y(2) + w(2) + h(2)
    没找到: cmd=0x00 空帧

【协议】AA CA AC BB | 长度(4B 小端) | flags(1B) | cmd(1B) | body | CRC16(2B 小端)
    长度 = flags + cmd + body + CRC
    CRC16 = CRC16_IBM(flags + cmd + body) = 标准 CRC-16/ARC (校验值 0xBB3D)
    这段协议代码和 PC 端 tools/maix_protocol.py、STM32 端 protocol.c 是同一套逻辑。

【接线】UART0: A16 = TX -> STM32 PA3,  A17 = RX <- STM32 PA2,  GND 共地
       115200 8N1

【运行】MaixVision 里点运行即可; 比赛时建议设为开机自启。
================================================================================
"""

import os
import sys
import time as _time

from maix import app, camera, display, image, uart

# ==============================================================================
# 一、配置区 —— 现场只需要改这里
# ==============================================================================

# ---- 串口 ----
# 默认 UART0: A16 = TX, A17 = RX, 设备节点 /dev/ttyS0
#   ⚠ 官方说明: UART0 是系统日志口, 上电时会吐一堆启动日志 (帧解析器会自动跳过垃圾字节,
#     不影响我们), 而且 A16(TX) 还是启动模式检测脚, 上电时不能被拉低, 否则 MaixCAM 不启动。
# 更稳的选择是 UART1: A19 = TX, A18 = RX, 设备节点 /dev/ttyS1 (要先用 pinmap 设引脚功能),
#     代码里已经自动处理, 只要把 UART_DEVICE 改成 "/dev/ttyS1" 并把线改到 A18/A19 即可。
UART_DEVICE = "/dev/ttyS0"
UART_BAUDRATE = 115200

# UART1 的引脚映射 (UART_DEVICE = "/dev/ttyS1" 时自动生效)
UART1_PINMAP = (("A19", "UART1_TX"), ("A18", "UART1_RX"))

# ---- 相机 ----
CAM_WIDTH = 640                 # STM32 端按 640x320 判范围, 别乱改
CAM_HEIGHT = 320
FLUSH_BEFORE_CAPTURE = True     # 收到 0x12 后先丢掉一帧再拍, 保证画面是机械臂停下后的

# ---- 屏幕预览 (调机时开, 比赛时可以关掉省 CPU) ----
SHOW_PREVIEW = True

# ---- 颜色阈值 (LAB)  ⚠ 现场必须重标 ----
#   格式: (L_MIN, L_MAX, A_MIN, A_MAX, B_MIN, B_MAX)
COLOR_THRESHOLDS = {
    1: (11, 68, 29, 75, 21, 33),      # 红
    2: (25, 52, -41, -5, -16, 28),    # 绿
    3: (13, 59, -23, 13, -58, -15),   # 蓝
}
COLOR_MIN_PIXELS = 100          # 小于这么多像素的色块当噪声丢掉

# ---- 白色(人质)检测  ⚠ 现场必须重标 ----
WHITE_GRAY_THR = 200            # 灰度阈值: 大于它算白色 (白 PLA vs 黑亚克力台)

# ---- 形状判别  ⚠ 现场必须重标 ----
SHAPE_WIDTH_DIFF = 50           # 宽度差阈值 (原始 640 像素尺度下的像素数)
SHAPE_MIN_AREA = 200            # 白色区域最小像素数(下采样尺度)
# 可选: 相对判据 (默认关)。若现场发现"绝对像素差"分不开三个形状,
# 把它打开, 用"宽了多少倍"来判断, 对相机距离不敏感。
SHAPE_USE_RELATIVE_RULE = False
SHAPE_RELATIVE_RATIO = 1.25     # 1.25 = 宽出 25% 就算"更宽"

# ---- 形状剖面用的下采样尺寸 (越小越快, 越大越准) ----
PROFILE_W = 160
PROFILE_H = 80

# ---- 可选: 只分析画面中间一块 (背景有干扰时打开) ----
USE_ROI = False
ROI = (160, 80, 320, 160)       # (x, y, w, h) 画面上人质应该出现的区域

# ---- 调试打印 (会通过串口控制台输出; 比赛时建议 False 更安静) ----
DEBUG = True


# ==============================================================================
# 二、协议常量
# ==============================================================================
FRAME_HEAD = bytes([0xAA, 0xCA, 0xAC, 0xBB])

FLAG_REQUEST = 0x01             # STM32 -> MaixCAM
FLAG_REPORT = 0x21              # MaixCAM -> STM32

CMD_NONE = 0x00                 # 空帧
CMD_REPORT_COLOR = 0x01         # 上报颜色目标
CMD_REPORT_SHAPE = 0x02         # 上报形状目标
CMD_SET_MODE_COLOR = 0x10       # 设为颜色模式
CMD_SET_MODE_SHAPE = 0x11       # 设为形状模式
CMD_REQUEST_DETECT = 0x12       # 请求识别一次

MAX_BODY_LEN = 32

MODE_COLOR = 0
MODE_SHAPE = 1

# 颜色编号
RED, GREEN, BLUE = 1, 2, 3
# 形状编号
SHAPE_CYLINDER, SHAPE_CONE, SHAPE_WAIST_DRUM = 1, 2, 3

CMD_NAMES = {
    CMD_NONE: "空帧",
    CMD_REPORT_COLOR: "上报颜色目标",
    CMD_REPORT_SHAPE: "上报形状目标",
    CMD_SET_MODE_COLOR: "设为颜色模式",
    CMD_SET_MODE_SHAPE: "设为形状模式",
    CMD_REQUEST_DETECT: "请求识别一次",
}
COLOR_NAMES = {1: "红", 2: "绿", 3: "蓝"}
SHAPE_NAMES = {1: "圆柱", 2: "圆锥", 3: "腰鼓"}


def log(*args):
    if DEBUG:
        print("[MaixCAM]", *args)


# ==============================================================================
# 三、协议: CRC / 组帧 / 解析  (与 tools/maix_protocol.py 完全一致)
# ==============================================================================
def crc16_ibm(data: bytes) -> int:
    """CRC16_IBM = CRC-16/ARC;  crc16_ibm(b"123456789") == 0xBB3D"""
    crc = 0x0000
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(flags: int, cmd: int, body: bytes = b"") -> bytes:
    """组一帧: 帧头 + 长度(小端) + flags + cmd + body + CRC(小端)"""
    data_len = 1 + 1 + len(body) + 2
    payload = bytes([flags, cmd]) + body
    return (FRAME_HEAD
            + data_len.to_bytes(4, "little")
            + payload
            + crc16_ibm(payload).to_bytes(2, "little"))


def build_report(cmd: int, target_id: int, x: int, y: int,
                 w: int, h: int) -> bytes:
    """上报目标: 编号(1) + x(2) + y(2) + w(2) + h(2), 全部小端"""
    body = (bytes([target_id & 0xFF])
            + int(x).to_bytes(2, "little")
            + int(y).to_bytes(2, "little")
            + int(w).to_bytes(2, "little")
            + int(h).to_bytes(2, "little"))
    return build_frame(FLAG_REPORT, cmd, body)


def build_none_report() -> bytes:
    """空帧: 没有找到目标"""
    return build_frame(FLAG_REPORT, CMD_NONE, b"")


class FrameParser:
    """逐字节解析状态机 (与 STM32 端 Protocol_PushByte 一致)"""

    HEAD1, HEAD2, HEAD3, HEAD4, LEN, DATA, CRC = range(7)

    def __init__(self):
        self.state = self.HEAD1
        self.data_len = 0
        self.got = 0
        self.buf = bytearray()

    def reset(self):
        self.state = self.HEAD1
        self.data_len = 0
        self.got = 0
        self.buf = bytearray()

    def push(self, byte):
        """塞一个字节, 收满一帧返回 (flags, cmd, body, crc_ok), 否则返回 None"""
        byte &= 0xFF

        if self.state == self.HEAD1:
            if byte == 0xAA:
                self.state = self.HEAD2

        elif self.state == self.HEAD2:
            if byte == 0xCA:
                self.state = self.HEAD3
            elif byte != 0xAA:
                self.reset()

        elif self.state == self.HEAD3:
            if byte == 0xAC:
                self.state = self.HEAD4
            elif byte == 0xAA:
                self.state = self.HEAD2
            else:
                self.reset()

        elif self.state == self.HEAD4:
            if byte == 0xBB:
                self.state = self.LEN
                self.data_len = 0
                self.got = 0
            elif byte == 0xAA:
                self.state = self.HEAD2
            else:
                self.reset()

        elif self.state == self.LEN:
            self.data_len |= byte << (8 * self.got)
            self.got += 1
            if self.got >= 4:
                if self.data_len < 4 or self.data_len > MAX_BODY_LEN + 4:
                    self.reset()
                else:
                    self.got = 0
                    self.buf = bytearray()
                    self.state = self.DATA

        elif self.state == self.DATA:
            self.buf.append(byte)
            self.got += 1
            if self.got >= self.data_len - 2:
                self.state = self.CRC

        elif self.state == self.CRC:
            self.buf.append(byte)
            self.got += 1
            if self.got >= self.data_len:
                flags, cmd = self.buf[0], self.buf[1]
                body = bytes(self.buf[2:self.data_len - 2])
                crc_rx = int.from_bytes(
                    self.buf[self.data_len - 2:self.data_len], "little")
                crc_ok = (crc16_ibm(bytes(self.buf[:self.data_len - 2])) == crc_rx)
                self.reset()
                return flags, cmd, body, crc_ok

        return None


# ==============================================================================
# 四、兼容层: 不同 MaixPy 版本的 API 小差异都挡在这里
# ==============================================================================
def _val(obj, name):
    """blob.x 可能是属性也可能是方法, 两种都兼容"""
    v = getattr(obj, name, None)
    if v is None:
        return None
    return v() if callable(v) else v


def blob_box(b):
    """
    取色块包围盒 (x, y, w, h)
    MaixPy v4 的 blob 支持下标访问: blob[0..3] = x, y, w, h (官方文档示例就是这样用的)
    老的写法是 blob.x() 这种方法/属性, 两种都支持
    """
    try:
        return int(b[0]), int(b[1]), int(b[2]), int(b[3])
    except Exception:
        pass
    return (int(_val(b, "x") or 0), int(_val(b, "y") or 0),
            int(_val(b, "w") or 0), int(_val(b, "h") or 0))


def blob_pixels(b):
    """取色块像素数 (优先 pixels(), 退而求其次用 w*h)"""
    try:
        px = _val(b, "pixels")
        if px is not None:
            return int(px)
    except Exception:
        pass
    try:
        return int(b[4])
    except Exception:
        pass
    _, _, w, h = blob_box(b)
    return w * h


def apply_roi(img):
    """
    需要的话裁到 ROI 再分析, 返回 (待分析图, 偏移x, 偏移y)
    不启用 ROI 时偏移为 0
    """
    if not USE_ROI:
        return img, 0, 0
    x, y, w, h = ROI
    try:
        return img.crop(x, y, w, h), x, y
    except Exception as e:
        log("crop 失败, 改用整幅画面:", e)
        return img, 0, 0


def _to_bytes(data):
    """uart.read() / img.to_bytes() 返回 bytes 或 list[int] 都兼容"""
    if data is None:
        return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("latin-1")
    try:
        return bytes(bytearray(x & 0xFF for x in data))
    except Exception:
        return b""


def to_grayscale(img):
    """转灰度 (兼容几种写法)"""
    for name in ("FMT_GRAYSCALE", "FMT_GRAY", "FMT_GRAY8"):
        fmt = getattr(image.Format, name, None)
        if fmt is not None:
            try:
                return img.to_format(fmt)
            except Exception:
                pass
    for meth in ("to_grayscale", "grayscale"):
        fn = getattr(img, meth, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    return img          # 实在不行就用原图 (阈值会不准, 但不至于崩)


# ==============================================================================
# 五、视觉任务 1: 颜色识别 (find_blobs + LAB 阈值)
# ==============================================================================
def detect_color(img):
    """
    在画面里找红/绿/蓝块, 取面积最大的那个
    返回 (颜色编号, x, y, w, h) 或 None
    """
    work, ox, oy = apply_roi(img)
    best = None
    best_id = 0
    best_pixels = 0

    for color_id in (RED, GREEN, BLUE):
        thr = COLOR_THRESHOLDS[color_id]
        try:
            blobs = work.find_blobs([thr],
                                    area_threshold=COLOR_MIN_PIXELS,
                                    pixels_threshold=COLOR_MIN_PIXELS,
                                    merge=True)
        except TypeError:
            blobs = work.find_blobs([thr])
        except Exception as e:
            log("find_blobs 出错:", e)
            return None

        for b in blobs or []:
            px = blob_pixels(b)
            if px > best_pixels:
                best_pixels = px
                best = blob_box(b)
                best_id = color_id

    if best is None:
        return None

    x, y, w, h = best
    return (best_id, int(x) + ox, int(y) + oy, int(w), int(h))


# ==============================================================================
# 六、视觉任务 2: 白色立体形状识别 (灰度 + 二值化 + 宽度剖面)
# ==============================================================================
def _binarize_rows(gray, w, h):
    """
    把灰度图按行二值化并统计每行白色像素的 [left, right, count]
    用 bytes.translate 做二值化、bytes.find/rfind 找边界 —— 全是 C 速度
    返回 (rows, stride) ; rows[i] = (left, right, count) 或 None
    """
    small = gray.resize(w, h)
    try:
        raw = small.to_bytes()               # MaixPy v4: Image.to_bytes() -> bytes
    except TypeError:
        raw = small.to_bytes("grayscale")    # 个别版本要带格式参数
    data = _to_bytes(raw)
    if not data:
        return None, 0

    stride = len(data) // h if len(data) >= w * h else w
    if stride <= 0:
        return None, 0

    # 灰度 -> 二值 查表: <THR 变 0, >=THR 变 255
    table = bytes(0 if i < WHITE_GRAY_THR else 255 for i in range(256))

    rows = []
    for i in range(h):
        start = i * stride
        row = data[start:start + w]
        if len(row) < w:
            row = row + b"\x00" * (w - len(row))
        b = row.translate(table)
        left = b.find(b"\xff")
        if left < 0:
            rows.append(None)
            continue
        right = b.rfind(b"\xff")
        rows.append((left, right, b.count(255)))
    return rows, stride


def _img_size(img, fallback=(CAM_WIDTH, CAM_HEIGHT)):
    """取图像宽高 (不同版本 API 兼容)"""
    for name in ("width", "w"):
        fn = getattr(img, name, None)
        if callable(fn):
            try:
                w = int(fn())
                h = int(getattr(img, "height" if name == "width" else "h")())
                return w, h
            except Exception:
                pass
    return fallback


def detect_shape(img):
    """
    找白色人质并判断形状: 1 圆柱 / 2 圆锥 / 3 腰鼓
    返回 (形状编号, x, y, w, h) 或 None

    判别逻辑 (对白色连通域逐行扫描):
        w_top    顶部 20% 区域的平均宽度
        w_mid    中间 50% 区域的平均宽度
        w_bottom 底部 20% 区域的平均宽度
        if w_mid > w_top + DIFF and w_mid > w_bottom + DIFF -> 腰鼓形
        elif w_bottom > w_top + DIFF                        -> 圆锥形
        else                                                -> 圆柱形
    """
    work, ox, oy = apply_roi(img)
    work_w, work_h = _img_size(work)

    gray = to_grayscale(work)
    rows, stride = _binarize_rows(gray, PROFILE_W, PROFILE_H)
    if rows is None:
        return None

    # ---- 1. 找白色区域的上下边界 ----
    idx = [i for i, r in enumerate(rows) if r is not None]
    if not idx:
        return None
    y0, y1 = idx[0], idx[-1]
    height = y1 - y0 + 1
    if height < 4:
        return None

    # ---- 2. 总面积够不够 ----
    area = sum(rows[i][2] for i in idx)
    if area < SHAPE_MIN_AREA:
        return None

    # ---- 3. 水平边界 (在有效行里取最左/最右) ----
    left = min(rows[i][0] for i in idx)
    right = max(rows[i][1] for i in idx)
    width = right - left + 1
    if width < 3:
        return None

    # ---- 4. 三段平均宽度 (下采样尺度) ----
    def band_width(r_from, r_to):
        vals = [rows[i][1] - rows[i][0] + 1
                for i in range(r_from, r_to + 1) if rows[i] is not None]
        return (sum(vals) / len(vals)) if vals else 0.0

    top_end = y0 + max(1, int(height * 0.20)) - 1
    mid_from = y0 + int(height * 0.25)
    mid_to = y0 + int(height * 0.75)
    bot_from = y1 - max(1, int(height * 0.20)) + 1

    w_top = band_width(y0, top_end)
    w_mid = band_width(mid_from, mid_to)
    w_bot = band_width(bot_from, y1)

    # 换算回原图 (640) 像素尺度 —— STM32 端的阈值是按原图定的
    scale = float(work_w) / float(PROFILE_W)
    w_top *= scale
    w_mid *= scale
    w_bot *= scale

    # ---- 5. 判别 ----
    if SHAPE_USE_RELATIVE_RULE:
        # 相对判据: 对相机距离不敏感, 现场分不开形状时可以改用这个
        r = SHAPE_RELATIVE_RATIO
        if (w_mid > w_top * r) and (w_mid > w_bot * r):
            shape = SHAPE_WAIST_DRUM
        elif w_bot > w_top * r:
            shape = SHAPE_CONE
        else:
            shape = SHAPE_CYLINDER
    else:
        # 设计文档里的判据 (绝对像素差)
        if (w_mid > w_top + SHAPE_WIDTH_DIFF) and (w_mid > w_bot + SHAPE_WIDTH_DIFF):
            shape = SHAPE_WAIST_DRUM      # 腰鼓形: 中间最宽
        elif w_bot > w_top + SHAPE_WIDTH_DIFF:
            shape = SHAPE_CONE            # 圆锥形: 下宽上窄
        else:
            shape = SHAPE_CYLINDER        # 圆柱形: 上下一样宽

    log("剖面 像素: top=%.0f mid=%.0f bottom=%.0f -> %s"
        % (w_top, w_mid, w_bot, SHAPE_NAMES[shape]))

    # ---- 6. 把下采样坐标换算回原图坐标 (再补上 ROI 偏移) ----
    sx = float(work_w) / float(PROFILE_W)
    sy = float(work_h) / float(PROFILE_H)
    x = int(left * sx) + ox
    y = int(y0 * sy) + oy
    w = int(width * sx)
    h = int(height * sy)

    return (shape, x, y, w, h)


# ==============================================================================
# 七、主程序
# ==============================================================================
class VisionNode:

    def __init__(self):
        self.mode = MODE_COLOR          # 默认颜色模式, STM32 会用 0x10/0x11 覆盖
        self.parser = FrameParser()

        # ---- 串口 ----
        self.ser = None
        for dev in (UART_DEVICE, "/dev/ttyS0", "/dev/ttyS1"):
            self._setup_pinmap(dev)
            try:
                self.ser = uart.UART(dev, UART_BAUDRATE)
                log("串口打开成功:", dev)
                break
            except Exception as e:
                log("串口打开失败", dev, e)
        if self.ser is None:
            raise RuntimeError("打不开串口, 检查 UART_DEVICE 配置")

        # ---- 相机 ----
        try:
            self.cam = camera.Camera(CAM_WIDTH, CAM_HEIGHT)
        except Exception as e:
            log("camera.Camera(%d,%d) 失败, 用默认分辨率:" % (CAM_WIDTH, CAM_HEIGHT), e)
            self.cam = camera.Camera()

        self.disp = None
        if SHOW_PREVIEW:
            try:
                self.disp = display.Display()
            except Exception as e:
                log("屏幕不可用, 关掉预览:", e)
                self.disp = None

        self.n_req = 0

    # ------------------------------------------------------------------
    @staticmethod
    def _setup_pinmap(dev):
        """用 UART1 时要先把 A18/A19 设成 UART 功能 (UART0 是默认映射, 不用设)"""
        if "ttyS1" not in dev:
            return
        try:
            from maix import pinmap, err
            for pin, func in UART1_PINMAP:
                err.check_raise(pinmap.set_pin_function(pin, func),
                                "设置 %s -> %s 失败" % (pin, func))
            log("已设置 UART1 引脚映射:", UART1_PINMAP)
        except Exception as e:
            log("pinmap 设置失败 (若固件已默认映射可忽略):", e)

    # ------------------------------------------------------------------
    def send(self, data: bytes):
        try:
            self.ser.write(data)
        except Exception as e:
            log("串口发送失败:", e)

    # ------------------------------------------------------------------
    def capture(self):
        """拍一帧 (可选先丢一帧, 保证是机械臂停下后的画面)"""
        img = self.cam.read()
        if FLUSH_BEFORE_CAPTURE:
            img = self.cam.read()
        return img

    # ------------------------------------------------------------------
    def handle_detect_request(self):
        """收到 0x12: 拍一帧 -> 识别一次 -> 上报一帧"""
        self.n_req += 1
        t0 = _time.time()

        img = self.capture()

        if self.mode == MODE_COLOR:
            res = detect_color(img)
            cmd = CMD_REPORT_COLOR
            names = COLOR_NAMES
        else:
            res = detect_shape(img)
            cmd = CMD_REPORT_SHAPE
            names = SHAPE_NAMES

        if res is None:
            log("第 %d 次识别 (%s): 没找到 -> 空帧"
                % (self.n_req, "颜色" if self.mode == MODE_COLOR else "形状"))
            self.send(build_none_report())
        else:
            tid, x, y, w, h = res
            log("第 %d 次识别: %s(%d) x=%d y=%d w=%d h=%d  用时 %dms"
                % (self.n_req, names.get(tid, "?"), tid, x, y, w, h,
                   int((_time.time() - t0) * 1000)))
            self.send(build_report(cmd, tid, x, y, w, h))

        # 调机时把画面显示出来, 方便对准
        if self.disp is not None:
            try:
                if res is not None:
                    tid, x, y, w, h = res
                    img.draw_rect(x, y, w, h, color=image.COLOR_GREEN, thickness=2)
                self.disp.show(img)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def handle_frame(self, flags, cmd, body, crc_ok):
        if not crc_ok:
            log("收到 CRC 错误的帧, 丢弃")
            return

        log("收到命令:", CMD_NAMES.get(cmd, "未知(0x%02X)" % cmd))

        if cmd == CMD_SET_MODE_COLOR:
            self.mode = MODE_COLOR
            log("模式 = 颜色模式")

        elif cmd == CMD_SET_MODE_SHAPE:
            self.mode = MODE_SHAPE
            log("模式 = 形状模式")

        elif cmd == CMD_REQUEST_DETECT:
            self.handle_detect_request()

        else:
            log("不认识的命令, 忽略")

    # ------------------------------------------------------------------
    def run(self):
        log("进入主循环, 等待 STM32 命令 (模式默认: 颜色)")
        self.send_mode_ready_log()

        while not app.need_exit():
            try:
                data = _to_bytes(self.ser.read())
            except Exception as e:
                log("串口读取失败:", e)
                _time.sleep(0.1)
                continue

            if data:
                for b in data:
                    r = self.parser.push(b)
                    if r is not None:
                        self.handle_frame(*r)
            else:
                _time.sleep(0.005)      # 别把 CPU 跑满

    def send_mode_ready_log(self):
        log("UART0 %d 8N1, 分辨率 %dx%d, 白色阈值 %d, 形状阈值 %d 像素"
            % (UART_BAUDRATE, CAM_WIDTH, CAM_HEIGHT,
               WHITE_GRAY_THR, SHAPE_WIDTH_DIFF))


def main():
    try:
        VisionNode().run()
    except Exception as e:
        print("[MaixCAM] 致命错误:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
