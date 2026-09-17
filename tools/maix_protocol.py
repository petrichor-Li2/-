#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maix_protocol.py —— Maix 字节流协议 (Python 参考实现)

帧格式:
    AA CA AC BB | 长度(4B 小端) | flags(1B) | cmd(1B) | body(nB) | CRC16(2B 小端)

· 长度 = flags + cmd + body + CRC 的总字节数
· CRC16 = CRC16_IBM(flags + cmd + body), 多项式 0xA001, 初值 0x0000 (即 CRC-16/ARC)

这个文件和 STM32 端的 Core/Src/protocol.c 是同一套逻辑,
PC 端模拟器 (maix_sim.py)、MaixCAM 端 (main.py) 都用它, 保证两端完全一致。
"""

from __future__ import annotations

import sys
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
FRAME_HEAD = bytes([0xAA, 0xCA, 0xAC, 0xBB])

FLAG_REQUEST = 0x01          # STM32 -> MaixCAM
FLAG_REPORT = 0x21           # MaixCAM -> STM32

CMD_NONE = 0x00              # 空帧 (没有找到目标)
CMD_REPORT_COLOR = 0x01      # 上报颜色目标
CMD_REPORT_SHAPE = 0x02      # 上报形状目标
CMD_SET_MODE_COLOR = 0x10    # 设为颜色模式
CMD_SET_MODE_SHAPE = 0x11    # 设为形状模式
CMD_REQUEST_DETECT = 0x12    # 请求识别一次

# 颜色编码
COLOR_RED, COLOR_GREEN, COLOR_BLUE = 1, 2, 3
# 形状编码
SHAPE_CYLINDER, SHAPE_CONE, SHAPE_WAIST_DRUM = 1, 2, 3

MAX_BODY_LEN = 32

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


# --------------------------------------------------------------------------
# CRC16_IBM (= CRC-16/ARC, 标准校验值: crc16(b"123456789") == 0xBB3D)
# --------------------------------------------------------------------------
def crc16_ibm(data: bytes) -> int:
    crc = 0x0000
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


# --------------------------------------------------------------------------
# 组帧
# --------------------------------------------------------------------------
def build_frame(flags: int, cmd: int, body: bytes = b"") -> bytes:
    """按协议拼一帧 (和 STM32 端 Protocol_BuildFrame 一致)"""
    if len(body) > MAX_BODY_LEN:
        raise ValueError("body 太长")

    data_len = 1 + 1 + len(body) + 2          # flags + cmd + body + crc
    payload = bytes([flags, cmd]) + body
    crc = crc16_ibm(payload)

    return (FRAME_HEAD
            + data_len.to_bytes(4, "little")
            + payload
            + crc.to_bytes(2, "little"))


def build_report(cmd: int, target_id: int,
                 x: int, y: int, w: int, h: int) -> bytes:
    """上报颜色/形状目标: id(1) + x(2) + y(2) + w(2) + h(2), 全部小端"""
    body = (bytes([target_id])
            + int(x).to_bytes(2, "little")
            + int(y).to_bytes(2, "little")
            + int(w).to_bytes(2, "little")
            + int(h).to_bytes(2, "little"))
    return build_frame(FLAG_REPORT, cmd, body)


def build_none_report() -> bytes:
    """空帧: 没找到目标, cmd = 0x00, body 为空"""
    return build_frame(FLAG_REPORT, CMD_NONE, b"")


def build_mode_color() -> bytes:
    return build_frame(FLAG_REQUEST, CMD_SET_MODE_COLOR, b"")


def build_mode_shape() -> bytes:
    return build_frame(FLAG_REQUEST, CMD_SET_MODE_SHAPE, b"")


def build_req_detect() -> bytes:
    return build_frame(FLAG_REQUEST, CMD_REQUEST_DETECT, b"")


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
class Frame:
    """一帧解析结果"""

    __slots__ = ("flags", "cmd", "body", "crc_ok", "raw")

    def __init__(self, flags: int, cmd: int, body: bytes,
                 crc_ok: bool, raw: bytes = b""):
        self.flags = flags
        self.cmd = cmd
        self.body = body
        self.crc_ok = crc_ok
        self.raw = raw

    # ---- 颜色/形状目标 ----
    @property
    def valid_target(self) -> bool:
        return (self.crc_ok
                and self.cmd in (CMD_REPORT_COLOR, CMD_REPORT_SHAPE)
                and len(self.body) >= 9)

    @property
    def target_id(self) -> int:
        return self.body[0] if self.valid_target else 0

    @property
    def x(self) -> int:
        return int.from_bytes(self.body[1:3], "little") if self.valid_target else 0

    @property
    def y(self) -> int:
        return int.from_bytes(self.body[3:5], "little") if self.valid_target else 0

    @property
    def w(self) -> int:
        return int.from_bytes(self.body[5:7], "little") if self.valid_target else 0

    @property
    def h(self) -> int:
        return int.from_bytes(self.body[7:9], "little") if self.valid_target else 0

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def in_valid_range(self, x_min=160, x_max=480, y_min=80, y_max=240) -> bool:
        """和 STM32 端 Vision_IsInValidRange 一致: 用中心点判断"""
        if not self.valid_target:
            return False
        return (x_min <= self.cx <= x_max) and (y_min <= self.cy <= y_max)

    def __repr__(self) -> str:
        name = CMD_NAMES.get(self.cmd, f"未知(0x{self.cmd:02X})")
        if self.valid_target:
            kind = COLOR_NAMES if self.cmd == CMD_REPORT_COLOR else SHAPE_NAMES
            return (f"<Frame {name} id={self.target_id}"
                    f"({kind.get(self.target_id, '?')}) "
                    f"x={self.x} y={self.y} w={self.w} h={self.h} "
                    f"crc={'OK' if self.crc_ok else 'BAD'}>")
        return f"<Frame {name} crc={'OK' if self.crc_ok else 'BAD'}>"

    def hex(self) -> str:
        return self.raw.hex(" ").upper()


class Parser:
    """逐字节解析状态机 (和 STM32 端 Protocol_PushByte 一致)"""

    WAIT_HEAD1, WAIT_HEAD2, WAIT_HEAD3, WAIT_HEAD4 = 0, 1, 2, 3
    RECV_LEN, RECV_DATA, RECV_CRC = 4, 5, 6

    def __init__(self):
        self.reset()
        self.frames_received = 0
        self.crc_errors = 0
        self.length_errors = 0

    def reset(self):
        self.state = self.WAIT_HEAD1
        self.data_len = 0
        self.got = 0
        self.buf = bytearray()
        self.raw = bytearray()

    def push(self, byte: int) -> Optional[Frame]:
        """塞一个字节; 收满一帧返回 Frame, 否则返回 None"""
        byte &= 0xFF
        self.raw.append(byte)

        st = self.state

        if st == self.WAIT_HEAD1:
            if byte == 0xAA:
                self.state = self.WAIT_HEAD2

        elif st == self.WAIT_HEAD2:
            if byte == 0xCA:
                self.state = self.WAIT_HEAD3
            elif byte == 0xAA:
                pass
            else:
                self._restart()

        elif st == self.WAIT_HEAD3:
            if byte == 0xAC:
                self.state = self.WAIT_HEAD4
            elif byte == 0xAA:
                self.state = self.WAIT_HEAD2
            else:
                self._restart()

        elif st == self.WAIT_HEAD4:
            if byte == 0xBB:
                self.state = self.RECV_LEN
                self.data_len = 0
                self.got = 0
            elif byte == 0xAA:
                self.state = self.WAIT_HEAD2
            else:
                self._restart()

        elif st == self.RECV_LEN:
            self.data_len |= byte << (8 * self.got)
            self.got += 1
            if self.got >= 4:
                if self.data_len < 4 or self.data_len > MAX_BODY_LEN + 4:
                    self.length_errors += 1
                    self._restart()
                else:
                    self.got = 0
                    self.buf = bytearray()
                    self.state = self.RECV_DATA

        elif st == self.RECV_DATA:
            self.buf.append(byte)
            self.got += 1
            if self.got >= self.data_len - 2:
                self.state = self.RECV_CRC

        elif st == self.RECV_CRC:
            self.buf.append(byte)
            self.got += 1
            if self.got >= self.data_len:
                raw = bytes(self.raw)
                flags, cmd = self.buf[0], self.buf[1]
                body = bytes(self.buf[2:self.data_len - 2])
                crc_rx = int.from_bytes(self.buf[self.data_len - 2:self.data_len],
                                        "little")
                crc_ok = (crc16_ibm(bytes(self.buf[:self.data_len - 2])) == crc_rx)
                self.frames_received += 1
                if not crc_ok:
                    self.crc_errors += 1
                self._restart()
                return Frame(flags, cmd, body, crc_ok, raw)

        return None

    def feed(self, data: bytes) -> List[Frame]:
        """一次塞多个字节, 返回所有完整帧"""
        out = []
        for b in data:
            f = self.push(b)
            if f is not None:
                out.append(f)
        return out

    def _restart(self):
        self.state = self.WAIT_HEAD1
        self.data_len = 0
        self.got = 0
        self.raw = bytearray()


# --------------------------------------------------------------------------
# 视觉有效范围 (和 STM32 端 app_config.h / vision.c 一致)
# --------------------------------------------------------------------------
VISION_FRAME_W, VISION_FRAME_H = 640, 320
VISION_CENTER_X, VISION_CENTER_Y = 320, 160
VISION_X_MIN, VISION_X_MAX = 160, 480
VISION_Y_MIN, VISION_Y_MAX = 80, 240


def is_in_valid_range(x: int, y: int, w: int, h: int) -> bool:
    cx = x + w // 2
    cy = y + h // 2
    return (VISION_X_MIN <= cx <= VISION_X_MAX
            and VISION_Y_MIN <= cy <= VISION_Y_MAX)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    print("CRC16_IBM(b'123456789') = 0x%04X (标准值 0xBB3D)" %
          crc16_ibm(b"123456789"))
    print("设为颜色模式:", build_mode_color().hex(" ").upper())
    print("设为形状模式:", build_mode_shape().hex(" ").upper())
    print("请求识别一次:", build_req_detect().hex(" ").upper())
    print("上报颜色(红):", build_report(CMD_REPORT_COLOR, 1, 300, 140, 60, 60).hex(" ").upper())
    print("空帧:", build_none_report().hex(" ").upper())
