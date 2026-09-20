#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 MaixCAM 端 v3 —— 视觉模块（合并版：既能跑协议，也能现场标定）
 2026 广东省工科大学生实验综合技能竞赛 · 赛项3 反恐排爆救援机器人
================================================================================

【这份文件是什么】
  视觉模块的唯一交付版。同一份文件里有三种状态，由顶部的 MODE 决定：

    MODE = "both"      ← 默认：一边打印给你看，一边正常回应单片机的命令
    MODE = "protocol"  ← 正式：不打印，只回应单片机（A16 上只有协议帧，最干净最快）
    MODE = "calib"     ← 标定：只每秒打印 LAB 读数，不理单片机（现场调阈值用）

【和单片机怎么配合】（单片机是主，本模块"完全被动"）
  单片机发 0x10 → 切到"颜色模式"
  单片机发 0x11 → 切到"形状模式"
  单片机发 0x12 → 本模块拍一帧、识别一次、回一帧结果，然后继续等命令
  它自己**不会**主动拍照、主动识别、主动上报

【回什么】
  颜色找到 → cmd=0x01，正文 = 颜色编号(1) + x(2) + y(2) + w(2) + h(2)  全小端
  形状找到 → cmd=0x02，正文 = 形状编号(1) + x(2) + y(2) + w(2) + h(2)
  没找到   → cmd=0x00 空帧（正文为空）

【协议帧格式】（与 STM32 端 protocol.c、PC 端 tools/maix_protocol.py 三方一致）
  AA CA AC BB | 长度(4B 小端) | flags(1B) | cmd(1B) | 正文(nB) | CRC16(2B 小端)
  长度 = flags + cmd + 正文 + CRC
  CRC16 = CRC16_IBM(flags + cmd + 正文)，即标准 CRC-16/ARC（"123456789" → 0xBB3D）

【接线】
  UART0（默认）: A16 = TX → 单片机 PA3(RX)；A17 = RX ← 单片机 PA2(TX)；GND 必须共地
  UART1（备选）: A19 = TX / A18 = RX，设备节点 /dev/ttyS1（代码会自动设引脚映射）
  两端统一 115200 8N1

【标定怎么做】
  1) 把 MODE 改成 "calib"，用 MaixVision 推送到设备
  2) 球/人质放到画面正中，看终端打印的 LAB 数字（例如 LAB=(46.2, 55.3, 38.1)）
  3) 按打印的数字改上面 COLOR_LAB 的三组阈值
  4) 改回 MODE = "both"（或 "protocol"）再推送

【形状识别怎么调】
  "both"/"calib" 模式下，每次识别都会打印宽度剖面：
      [形状] 312x300 剖面 w_top=118.2 w_mid=120.5 w_bot=119.0 -> 圆柱  (to_bytes)
  等相机位置固定后，按这些实测值决定 SHAPE_WIDTH_DIFF（或改用相对判据）

【已确认的设计决定】（逐条问答见 maixcam/DEV_LOG.md）
  · 单片机侧用现成的 S0~S12 整机流程测（配灯效对照表）
  · 只有一份文件：协议 + 标定 合并
  · 打印与协议同时开（MODE="both" 默认）；要最干净就切 "protocol"
  · 屏幕：白框 + 数字标签（如 1 x300 y140 w60 h60）；不写中文（默认字体不支持中文会变问号）
  · 相机尚未固定 → 距离/尺寸类参数留成可调项，等固定后再定
  · 形状识别沿用真机验证过的链路：转灰度 → 二值化 → 找白色连通域 → 逐行宽度剖面
================================================================================
"""

import time

from maix import app, camera, display, image, uart

# ==============================================================================
# 一、配置区（现场只改这里）
# ==============================================================================

VERSION = "v3-merged"          # 只用来在 banner 里确认跑的是哪一版

# ---- 运行状态 ---------------------------------------------------------------
#   "both"     : 打印 + 回应单片机（默认，联调时用）
#   "protocol" : 只回应单片机，不打印（比赛时最干净）
#   "calib"    : 只打印 LAB 读数，不理单片机（现场标定阈值用）
MODE = "both"

# ---- 串口 -------------------------------------------------------------------
UART_DEVICE = "/dev/ttyS0"     # UART0: A16=TX, A17=RX；改 UART1 就写 "/dev/ttyS1"
UART_BAUDRATE = 115200
UART1_PINMAP = (("A19", "UART1_TX"), ("A18", "UART1_RX"))

# ---- 相机 -------------------------------------------------------------------
CAM_WIDTH = 640                # 单片机按 640x320 做范围判断, 别乱改
CAM_HEIGHT = 320
FLUSH_BEFORE_CAPTURE = True    # 收到 0x12 后先丢一帧再拍, 保证是"机械臂停下后"的画面

# ---- 颜色阈值 (LAB) ---------------------------------------------------------
#   ⚠ 必须现场标定！用 MODE="calib" 读实测值再填这里。
#   顺序: (L_min, L_max, A_min, A_max, B_min, B_max)
#     L 亮度 0~100; A 绿(-)↔红(+); B 蓝(-)↔黄(+)
COLOR_LAB = {
    1: (11, 68, 29, 75, 21, 33),      # 红
    2: (25, 52, -41, -5, -16, 28),    # 绿
    3: (13, 59, -23, 13, -58, -15),   # 蓝
}
COLOR_NAME = {1: "红", 2: "绿", 3: "蓝"}

# ---- 颜色目标的杂点过滤 -----------------------------------------------------
MIN_AREA = 100                 # 小于这么多像素的色块丢掉
MIN_SIDE_PX = 20               # 宽和高都要 >= 这么多像素（实测有 13x14 的噪点混进来过）
ASPECT_MIN, ASPECT_MAX = 0.70, 1.40   # 长宽比范围（球近似圆）
FILL_MIN, FILL_MAX = 0.45, 0.95       # 饱满度 = 像素数/(w*h)，圆 ≈ 0.785
USE_BLOB_ROUNDNESS = False     # 打开则用官方 blob.roundness() 判圆度（更准，先看实测值）
ROUNDNESS_MIN = 0.55

# ---- 形状（白色人质）识别 ---------------------------------------------------
WHITE_GRAY_THR = 200           # 二值化灰度阈值：大于它算白色（白 PLA vs 黑台面）
SHAPE_MIN_PIXELS = 300         # 白色连通域最小像素数
#   判据（实测结论：只用绝对 50px 分不开真实比例的圆锥，因为顶部/底部 20% 区域的平均宽度
#   差只有 40px 左右；所以默认"绝对或相对，满足一个就算"，对远近都不敏感）：
#     "either"   绝对 or 相对 满足一个即可（推荐，默认）
#     "absolute" 只用绝对像素差（依赖距离，相机固定后才准）
#     "relative" 只用相对比例（对距离不敏感）
SHAPE_RULE = "either"
SHAPE_WIDTH_DIFF = 50          # 绝对判据：宽度差多少像素才算"更宽"
SHAPE_RELATIVE_RATIO = 1.25    # 相对判据：宽出多少倍才算"更宽"
PROFILE_ROW_STEP = 2           # 逐行扫描步长（1=最准最慢，2=快一倍）
SHAPE_NAME = {1: "圆柱", 2: "圆锥", 3: "腰鼓"}

# ---- LAB 读数（标定用） -----------------------------------------------------
LAB_PRINT_MS = 1000            # 打印间隔
LAB_PATCH_HALF = 6             # 取画面正中 (2*6+1)^2 的方块求平均

# ---- 屏幕显示 ---------------------------------------------------------------
DRAW = True                    # 在屏幕上画框 + 写数字标签
BOX_THICKNESS = 4              # 白色粗框（同色框会看不清）
BOX_WHITE = True               # True=统一白框；False=按识别到的颜色画框
LABEL_FIXED_POS = True         # True=标签固定写左上角（框跑出可见区域也看得到数字）

# ---- 距离限定（可选，默认关） ----------------------------------------------
#   原理: 球在画面里的宽度 w 与距离 d 成反比 → d = K / w，K = 标定距离 × 标定宽度
#   ⚠ "合格/不合格"本来是单片机判断的，这里开着只是用来挡掉明显太远的东西
USE_DISTANCE_LIMIT = False     # 相机固定后想开再开
CALIB_DISTANCE_CM = 10.0
CALIB_WIDTH_PX = {1: 0.0, 2: 0.0, 3: 0.0}   # 该颜色球放在 10cm 处时的 w
DIST_MIN_CM, DIST_MAX_CM = 5.0, 15.0


# ==============================================================================
# 二、协议层（与 v1 逐字节相同；改这里必须同时改 STM32 的 protocol.c 和 PC 的 maix_protocol.py）
# ==============================================================================
FRAME_HEAD = bytes([0xAA, 0xCA, 0xAC, 0xBB])

FLAG_REQUEST = 0x01            # 单片机 → MaixCAM
FLAG_REPORT = 0x21             # MaixCAM → 单片机

CMD_NONE = 0x00                # 空帧（没找到）
CMD_REPORT_COLOR = 0x01        # 上报颜色目标
CMD_REPORT_SHAPE = 0x02        # 上报形状目标
CMD_SET_MODE_COLOR = 0x10      # 设为颜色模式
CMD_SET_MODE_SHAPE = 0x11      # 设为形状模式
CMD_REQUEST_DETECT = 0x12      # 请求识别一次

CMD_NAMES = {
    CMD_NONE: "空帧", CMD_REPORT_COLOR: "上报颜色目标",
    CMD_REPORT_SHAPE: "上报形状目标", CMD_SET_MODE_COLOR: "设为颜色模式",
    CMD_SET_MODE_SHAPE: "设为形状模式", CMD_REQUEST_DETECT: "请求识别一次",
}

MODE_COLOR = 0
MODE_SHAPE = 1


def crc16_ibm(data):
    """CRC16_IBM = 标准 CRC-16/ARC；crc16_ibm(b"123456789") == 0xBB3D"""
    crc = 0x0000
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(flags, cmd, body=b""):
    data_len = 2 + len(body) + 2
    payload = bytes([flags, cmd]) + body
    return (FRAME_HEAD + data_len.to_bytes(4, "little") + payload
            + crc16_ibm(payload).to_bytes(2, "little"))


def build_report(cmd, target_id, x, y, w, h):
    body = (bytes([target_id & 0xFF])
            + int(x).to_bytes(2, "little") + int(y).to_bytes(2, "little")
            + int(w).to_bytes(2, "little") + int(h).to_bytes(2, "little"))
    return build_frame(FLAG_REPORT, cmd, body)


def build_none_report():
    return build_frame(FLAG_REPORT, CMD_NONE, b"")


class FrameParser:
    """逐字节解析（与 STM32 端 Protocol_PushByte 相同的状态机）"""

    HEAD1, HEAD2, HEAD3, HEAD4, LEN, DATA, CRC = range(7)

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = self.HEAD1
        self.data_len = 0
        self.got = 0
        self.buf = bytearray()

    def push(self, byte):
        """塞一个字节；收满一帧返回 (flags, cmd, body, crc_ok)，否则 None"""
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
                if self.data_len < 4 or self.data_len > 64:
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
# 三、兼容层：不同 MaixPy 固件的 API 差异都挡在这里
# ==============================================================================
def _val(obj, name, default=None):
    """blob.xxx 可能是属性也可能是方法"""
    v = getattr(obj, name, None)
    if v is None:
        return default
    try:
        return v() if callable(v) else v
    except Exception:
        return default


def blob_box(b):
    """取色块包围盒 (x, y, w, h)：下标写法与属性/方法写法都支持"""
    try:
        return int(b[0]), int(b[1]), int(b[2]), int(b[3])
    except Exception:
        pass
    return (int(_val(b, "x", 0)), int(_val(b, "y", 0)),
            int(_val(b, "w", 0)), int(_val(b, "h", 0)))


def blob_pixels(b):
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


def blob_roundness(b):
    v = _val(b, "roundness")
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _pixel_rgb(img, x, y):
    """
    取一个像素并归一化成 (r,g,b)。
    真机实测: get_pixel() 返回列表（取 [0] 是灰度值）。这里兼容 列表/元组/灰度/整数
    """
    try:
        v = img.get_pixel(x, y)
    except Exception:
        return None
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if len(v) >= 3:
            return int(v[0]) & 0xFF, int(v[1]) & 0xFF, int(v[2]) & 0xFF
        if len(v) >= 1:
            g = int(v[0]) & 0xFF
            return g, g, g
    if isinstance(v, int):
        return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
    return None


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f_lab(t):
    return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)


def rgb2lab(r, g, b):
    """标准 sRGB(D65) → CIELAB。find_blobs 内部同一套公式，所以读出的数可直接写阈值"""
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    fx, fy, fz = _f_lab(x / xn), _f_lab(y / yn), _f_lab(z / zn)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


# ---- 画图：颜色写法自动试错 -------------------------------------------------
#   真机已实测：**位置参数 + RGB 元组** 可用（用户 tested.py 里就是这么画的），所以放第一位
_BOX_RGB = {0: (255, 255, 255), 1: (255, 0, 0), 2: (0, 255, 0), 3: (0, 128, 255)}
_COLOR_MODE = None


def _color_candidates(cid, white=False):
    r, g, b = (255, 255, 255) if white else _BOX_RGB.get(cid, (255, 255, 255))
    out = [("tuple", (r, g, b))]
    cname = {0: "COLOR_WHITE", 1: "COLOR_RED",
             2: "COLOR_GREEN", 3: "COLOR_BLUE"}.get(cid if not white else 0)
    if cname:
        c = getattr(image, cname, None)
        if c is not None:
            out.append((cname, c))
    out.append(("int", (r << 16) | (g << 8) | b))
    if _COLOR_MODE is not None:
        picked = [c for c in out if c[0] == _COLOR_MODE]
        if picked:
            return picked
    return out


# ==============================================================================
# 四、视觉 1：颜色识别
# ==============================================================================
_err_seen = set()


def _log_once(key, msg):
    if key not in _err_seen:
        _err_seen.add(key)
        print(msg)


def judge_color_blob(b, w, h, px):
    """杂点/形状过滤；返回 None=通过，否则返回原因"""
    if px < MIN_AREA:
        return "面积%d<%d" % (px, MIN_AREA)
    if w < MIN_SIDE_PX or h < MIN_SIDE_PX:
        return "边长%d x %d 小于 %d" % (w, h, MIN_SIDE_PX)
    if USE_BLOB_ROUNDNESS:
        rn = blob_roundness(b)
        if rn is not None and rn < ROUNDNESS_MIN:
            return "圆度%.2f<%.2f" % (rn, ROUNDNESS_MIN)
    aspect = float(w) / float(h) if h else 0.0
    if aspect < ASPECT_MIN or aspect > ASPECT_MAX:
        return "长宽比%.2f 不在 %.2f~%.2f" % (aspect, ASPECT_MIN, ASPECT_MAX)
    fill = float(px) / float(w * h) if (w and h) else 0.0
    if fill < FILL_MIN or fill > FILL_MAX:
        return "饱满度%.2f 不在 %.2f~%.2f" % (fill, FILL_MIN, FILL_MAX)
    return None


def distance_cm(w, cid):
    k = CALIB_WIDTH_PX.get(cid, 0.0)
    if (not USE_DISTANCE_LIMIT) or k <= 0 or w <= 0:
        return None
    return (CALIB_DISTANCE_CM * k) / float(w)


def detect_color(img, cid):
    """找指定颜色里最大的那个合格色块；返回 dict 或 None"""
    thr = COLOR_LAB[cid]
    try:
        blobs = img.find_blobs([thr], area_threshold=MIN_AREA,
                               pixels_threshold=MIN_AREA, merge=True)
    except TypeError:
        try:
            blobs = img.find_blobs([thr])
        except Exception as e:
            _log_once("fb_err", "[错误] find_blobs 调用失败: %r" % (e,))
            return None
    except Exception as e:
        _log_once("fb_err", "[错误] find_blobs 调用失败: %r" % (e,))
        return None

    best = None
    for b in blobs or []:
        x, y, w, h = blob_box(b)
        px = blob_pixels(b)
        if judge_color_blob(b, w, h, px) is not None:
            continue
        d = distance_cm(w, cid)
        if (d is not None) and not (DIST_MIN_CM <= d <= DIST_MAX_CM):
            continue
        if best is None or px > best["pixels"]:
            best = {"id": cid, "x": x, "y": y, "w": w, "h": h,
                    "pixels": px, "dist": d}
    return best


# ==============================================================================
# 五、视觉 2：白色立体形状识别（沿用真机验证过的链路）
#   转灰度 → 二值化 → 找白色连通域 → 逐行宽度剖面 → 判别
# ==============================================================================
def _row_widths(binary, x, y, w, h, row_step):
    """
    统计二值图里每一行的白色像素数，返回 ({row: count}, 是否用了 to_bytes 快路径)
    优先 to_bytes() 一次取全部像素；不可用则退回 get_pixel 抽样（真机已验证可用）
    """
    rows = {}
    data = None
    try:
        data = binary.to_bytes()
    except Exception:
        data = None

    if data:
        try:
            total = len(data)
            stride = total // CAM_HEIGHT if total >= CAM_WIDTH * CAM_HEIGHT else CAM_WIDTH
            for row in range(y, y + h, row_step):
                off = row * stride + x
                seg = data[off:off + w]
                rows[row] = sum(1 for v in seg if v > 127) if seg else 0
            return rows, True
        except Exception:
            rows = {}

    # 退回 get_pixel 抽样：横向最多 64 列，避免 Python 端太慢
    col_step = max(1, w // 64)
    for row in range(y, y + h, row_step):
        cnt = 0
        for col in range(x, x + w, col_step):
            px = _pixel_rgb(binary, col, row)
            if px is not None and px[0] > 127:
                cnt += 1
        rows[row] = cnt * col_step
    return rows, False


def detect_shape(img):
    """
    返回 (shape_id, x, y, w, h, w_top, w_mid, w_bot) 或 None
    判别（对白色连通域逐行扫描）：
        w_top 顶部 20% 平均宽度; w_mid 中间 50%; w_bot 底部 20%
        w_mid 明显比上下都宽 → 腰鼓形(3)
        w_bot 明显比 w_top 宽 → 圆锥形(2)
        其它                 → 圆柱形(1)
    """
    try:
        gray = img.to_format(image.Format.FMT_GRAYSCALE)
        binary = gray.binary([(WHITE_GRAY_THR, 255)])
    except Exception as e:
        _log_once("gray_err", "[错误] 转灰度/二值化失败: %r" % (e,))
        return None

    try:
        blobs = binary.find_blobs([[255, 255]], pixels_threshold=SHAPE_MIN_PIXELS)
    except TypeError:
        try:
            blobs = binary.find_blobs([[255, 255]])
        except Exception as e:
            _log_once("wfb_err", "[错误] 白色连通域 find_blobs 失败: %r" % (e,))
            return None
    except Exception as e:
        _log_once("wfb_err", "[错误] 白色连通域 find_blobs 失败: %r" % (e,))
        return None

    if not blobs:
        return None

    def area_of(z):
        _, _, ww, hh = blob_box(z)
        return ww * hh

    b = max(blobs, key=area_of)
    x, y, w, h = blob_box(b)
    if w <= 0 or h <= 0:
        return None

    rows, used_bytes = _row_widths(binary, x, y, w, h, max(1, PROFILE_ROW_STEP))
    if not rows:
        return None

    def band_avg(r0, r1):
        vals = [rows[r] for r in rows if r0 <= r < r1]
        return (sum(vals) / len(vals)) if vals else 0.0

    w_top = band_avg(y, y + max(1, int(h * 0.20)))
    w_mid = band_avg(y + int(h * 0.25), y + int(h * 0.75))
    w_bot = band_avg(y + h - max(1, int(h * 0.20)), y + h)

    r = SHAPE_RELATIVE_RATIO
    d = SHAPE_WIDTH_DIFF
    use_abs = SHAPE_RULE in ("absolute", "either")
    use_rel = SHAPE_RULE in ("relative", "either")

    def wider(a, b):
        """a 是否明显比 b 宽"""
        if use_abs and (a > b + d):
            return True
        if use_rel and (a > b * r):
            return True
        return False

    if wider(w_mid, w_top) and wider(w_mid, w_bot):
        sid = 3
    elif wider(w_bot, w_top):
        sid = 2
    else:
        sid = 1

    if MODE != "protocol":
        print("[形状] %dx%d 剖面 w_top=%.1f w_mid=%.1f w_bot=%.1f -> %s  (%s)"
              % (w, h, w_top, w_mid, w_bot, SHAPE_NAME[sid],
                 "to_bytes" if used_bytes else "get_pixel抽样"))
    return sid, x, y, w, h, w_top, w_mid, w_bot


# ==============================================================================
# 六、主程序
# ==============================================================================
def now_ms():
    return int(time.time() * 1000)


class VisionNode:

    def __init__(self):
        self.mode = MODE_COLOR          # 默认颜色模式，单片机会用 0x10/0x11 覆盖
        self.parser = FrameParser()
        self.n_req = 0

        # ---- 串口 ----
        self.ser = None
        self.dev = UART_DEVICE
        for dev in (UART_DEVICE, "/dev/ttyS0", "/dev/ttyS1"):
            self._setup_pinmap(dev)
            try:
                self.ser = uart.UART(dev, UART_BAUDRATE)
                self.dev = dev
                break
            except Exception as e:
                print("[警告] 打开串口 %s 失败: %r" % (dev, e))
        if self.ser is None:
            raise RuntimeError("打不开串口, 检查 UART_DEVICE 配置")

        # ---- 相机 ----
        try:
            self.cam = camera.Camera(CAM_WIDTH, CAM_HEIGHT)
        except Exception as e:
            print("[警告] camera.Camera(%d,%d) 失败, 用默认分辨率: %r"
                  % (CAM_WIDTH, CAM_HEIGHT, e))
            self.cam = camera.Camera()

        # ---- 屏幕 ----
        self.disp = None
        if DRAW:
            try:
                self.disp = display.Display()
            except Exception as e:
                print("[警告] 屏幕不可用, 关掉画框: %r" % (e,))
                self.disp = None

    # ------------------------------------------------------------------
    @staticmethod
    def _setup_pinmap(dev):
        """用 UART1 时要先把 A18/A19 设成 UART 功能（UART0 是默认映射，不用设）"""
        if "ttyS1" not in dev:
            return
        try:
            from maix import pinmap, err
            for pin, func in UART1_PINMAP:
                err.check_raise(pinmap.set_pin_function(pin, func),
                                "设置 %s -> %s 失败" % (pin, func))
        except Exception as e:
            print("[警告] UART1 引脚映射设置失败(若固件已默认映射可忽略): %r" % (e,))

    def log(self, *a):
        """协议静音模式（MODE="protocol"）下不打印"""
        if MODE != "protocol":
            print(*a)

    # ------------------------------------------------------------------
    def banner(self):
        self.log("===== MaixCAM 视觉模块 %s  (MODE=%s) =====" % (VERSION, MODE))
        self.log("串口 %s  %d 8N1   画面 %dx%d"
                 % (self.dev, UART_BAUDRATE, CAM_WIDTH, CAM_HEIGHT))
        if self.disp is not None:
            try:
                dw, dh = self.disp.width(), self.disp.height()
                self.log("屏幕 %dx%d%s" % (dw, dh,
                         "" if (dw == CAM_WIDTH and dh == CAM_HEIGHT)
                         else "  (与画面不同, 显示时会缩放/裁剪)"))
            except Exception:
                pass
        self.log("颜色阈值: " + "  ".join(
            "%s(%d)=%s" % (COLOR_NAME[c], c, list(COLOR_LAB[c])) for c in (1, 2, 3)))
        self.log("形状: 灰度阈值 %d, 最小像素 %d, 判据 %s"
                 % (WHITE_GRAY_THR, SHAPE_MIN_PIXELS,
                    {"absolute": "绝对 %dpx" % SHAPE_WIDTH_DIFF,
                     "relative": "相对 %.2fx" % SHAPE_RELATIVE_RATIO,
                     "either": "绝对 %dpx 或 相对 %.2fx" % (SHAPE_WIDTH_DIFF,
                                                           SHAPE_RELATIVE_RATIO)}
                    .get(SHAPE_RULE, SHAPE_RULE)))
        if MODE == "calib":
            self.log("【标定模式】把物体放画面正中，每秒打印一次 LAB；改好 COLOR_LAB 后切回 both/protocol")
        else:
            self.log("等待单片机命令: 0x10 颜色模式 / 0x11 形状模式 / 0x12 请求识别")

    # ------------------------------------------------------------------
    def capture(self):
        img = self.cam.read()
        if FLUSH_BEFORE_CAPTURE:
            img = self.cam.read()          # 丢掉一帧，保证是"停下后"的画面
        return img

    # ------------------------------------------------------------------
    def handle_detect_request(self):
        """收到 0x12：拍一帧 → 识别一次 → 回一帧"""
        self.n_req += 1
        t0 = time.time()
        img = self.capture()

        if self.mode == MODE_COLOR:
            best = None
            for cid in (1, 2, 3):          # 三种颜色都找，取面积最大的那个
                b = detect_color(img, cid)
                if b is not None and (best is None or b["pixels"] > best["pixels"]):
                    best = b
            if best is None:
                self.log("[%d] 颜色: 没找到 -> 空帧" % self.n_req)
                self.send(build_none_report())
                self.draw(img, [None])
            else:
                self.log("[%d] 颜色: %s(%d) x=%d y=%d w=%d h=%d%s  (%dms)"
                         % (self.n_req, COLOR_NAME[best["id"]], best["id"],
                            best["x"], best["y"], best["w"], best["h"],
                            "" if best["dist"] is None
                            else " 距离≈%.1fcm" % best["dist"],
                            int((time.time() - t0) * 1000)))
                self.send(build_report(CMD_REPORT_COLOR, best["id"],
                                       best["x"], best["y"], best["w"], best["h"]))
                self.draw(img, [(best["id"], best)])
        else:
            r = detect_shape(img)
            if r is None:
                self.log("[%d] 形状: 没找到 -> 空帧" % self.n_req)
                self.send(build_none_report())
                self.draw(img, [None])
            else:
                sid, x, y, w, h = r[0], r[1], r[2], r[3], r[4]
                self.log("[%d] 形状: %s(%d) x=%d y=%d w=%d h=%d  (%dms)"
                         % (self.n_req, SHAPE_NAME[sid], sid, x, y, w, h,
                            int((time.time() - t0) * 1000)))
                self.send(build_report(CMD_REPORT_SHAPE, sid, x, y, w, h))
                self.draw(img, [(sid, {"x": x, "y": y, "w": w, "h": h})])

        if self.disp is not None:
            try:
                self.disp.show(img)
            except Exception as e:
                _log_once("show_err", "[错误] display.show 失败: %r" % (e,))

    # ------------------------------------------------------------------
    def send(self, data):
        try:
            self.ser.write(data)
        except Exception as e:
            print("[错误] 串口发送失败: %r" % (e,))
            return
        self.log("        -> 已回复: %s" % data.hex(" ").upper())

    # ------------------------------------------------------------------
    def handle_frame(self, flags, cmd, body, crc_ok):
        if not crc_ok:
            self.log("收到 CRC 错误的帧, 丢弃")
            return

        self.log("收到命令: %s (0x%02X)" % (CMD_NAMES.get(cmd, "未知"), cmd))

        if cmd == CMD_SET_MODE_COLOR:
            self.mode = MODE_COLOR
            self.log("       模式 = 颜色模式")
        elif cmd == CMD_SET_MODE_SHAPE:
            self.mode = MODE_SHAPE
            self.log("       模式 = 形状模式")
        elif cmd == CMD_REQUEST_DETECT:
            self.handle_detect_request()
        else:
            self.log("       不认识的命令, 忽略")

    # ------------------------------------------------------------------
    def print_center_lab(self, img):
        """打印画面正中那块的平均 RGB / LAB（把球放正中即可读该球的真实 LAB）"""
        cx, cy = CAM_WIDTH // 2, CAM_HEIGHT // 2
        hh = LAB_PATCH_HALF
        rs, gs, bs = [], [], []
        for yy in range(cy - hh, cy + hh + 1):
            for xx in range(cx - hh, cx + hh + 1):
                px = _pixel_rgb(img, xx, yy)
                if px is not None:
                    rs.append(px[0]); gs.append(px[1]); bs.append(px[2])
        if not rs:
            return
        ar, ag, ab = sum(rs) / len(rs), sum(gs) / len(gs), sum(bs) / len(bs)
        L, A, B = rgb2lab(ar, ag, ab)
        labs = [rgb2lab(r, g, b) for r, g, b in zip(rs, gs, bs)]
        print("[LAB] 中心%dx%d RGB=(%.0f,%.0f,%.0f)  LAB=(%.1f, %.1f, %.1f)  "
              "范围 L %.0f~%.0f A %.0f~%.0f B %.0f~%.0f"
              % (2 * hh + 1, 2 * hh + 1, ar, ag, ab, L, A, B,
                 min(v[0] for v in labs), max(v[0] for v in labs),
                 min(v[1] for v in labs), max(v[1] for v in labs),
                 min(v[2] for v in labs), max(v[2] for v in labs)))
        for cid in (1, 2, 3):
            t = COLOR_LAB[cid]
            if (t[0] <= L <= t[1]) and (t[2] <= A <= t[3]) and (t[4] <= B <= t[5]):
                print("       当前阈值 %s(%d) 命中这块区域 %s"
                      % (COLOR_NAME[cid], cid, list(t)))

    # ------------------------------------------------------------------
    def _draw_rect(self, img, x, y, w, h, cid, white=False):
        global _COLOR_MODE
        errs = []
        for name, c in _color_candidates(cid, white):
            try:
                img.draw_rect(x, y, w, h, c, BOX_THICKNESS)   # 真机验证过的位置参数写法
                if _COLOR_MODE is None:
                    _COLOR_MODE = name
                return True
            except Exception as e:
                errs.append("%s/%r" % (name, e))
            try:
                img.draw_rect(x, y, w, h, color=c, thickness=BOX_THICKNESS)
                if _COLOR_MODE is None:
                    _COLOR_MODE = name
                return True
            except Exception as e:
                errs.append("%s(关键字)/%r" % (name, e))
        _log_once("rect_err", "[错误] draw_rect 各种写法都失败: %s"
                  % "; ".join(errs[:3]))
        return False

    def _draw_string(self, img, x, y, s, cid, white=False):
        for name, c in _color_candidates(cid, white):
            try:
                img.draw_string(x, y, s, c)                   # 真机验证过的位置参数写法
                return True
            except Exception:
                pass
            try:
                img.draw_string(x, y, s, color=c, scale=1)    # scale 用整数
                return True
            except Exception:
                pass
        _log_once("str_err", "[错误] draw_string 各种写法都失败(数字标签画不出来)")
        return False

    def draw(self, img, results):
        """屏幕上画框 + 写数字标签：<编号> x<> y<> w<> h<>"""
        if self.disp is None:
            return
        i = 0
        for item in results:
            if item is None:
                continue
            cid, b = item
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            self._draw_rect(img, x, y, w, h, cid, white=BOX_WHITE)
            label = "%d x%d y%d w%d h%d" % (cid, x, y, w, h)
            if LABEL_FIXED_POS:
                self._draw_string(img, 4, 4 + i * 24, label, cid, white=BOX_WHITE)
            else:
                self._draw_string(img, x, (y - 22) if y > 26 else (y + 2),
                                  label, cid, white=BOX_WHITE)
            i += 1

    # ------------------------------------------------------------------
    def run(self):
        self.banner()
        last_lab = 0

        while not app.need_exit():
            # ---- 1. 收单片机的命令 ----
            if MODE != "calib":
                try:
                    data = self.ser.read()
                except Exception as e:
                    _log_once("read_err", "[错误] 串口读取失败: %r" % (e,))
                    data = None
                if data:
                    raw = bytes(data) if isinstance(data, (bytes, bytearray)) \
                        else bytes(bytearray(x & 0xFF for x in data))
                    for byte in raw:
                        r = self.parser.push(byte)
                        if r is not None:
                            self.handle_frame(*r)

            # ---- 2. 看画面 + 打印 LAB（both / calib）----
            if MODE != "protocol":
                img = self.cam.read()
                t = now_ms()
                if t - last_lab >= LAB_PRINT_MS:
                    last_lab = t
                    self.print_center_lab(img)
                if self.disp is not None:
                    try:
                        self.disp.show(img)
                    except Exception:
                        pass
            else:
                time.sleep(0.002)


def main():
    try:
        VisionNode().run()
    except Exception as e:
        print("[致命错误] %r" % (e,))
        raise


if __name__ == "__main__":
    main()
