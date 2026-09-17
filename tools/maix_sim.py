#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maix_sim.py —— PC 端 MaixCAM 模拟器 (联调神器)

在没有 MaixCAM 的时候, 用电脑 + USB-TTL 接 STM32 的 USART2 (PA2/PA3),
就能把整个 STM32 状态机跑通: 它会像真的 MaixCAM 一样
  · 收到 0x10 -> 记成颜色模式
  · 收到 0x11 -> 记成形状模式
  · 收到 0x12 -> 回一帧识别结果
还能故意制造故障 (CRC 错 / 空帧 / 超范围 / 迟不回复)
来验证 STM32 端的重试、跳过逻辑。

用法:
    pip install pyserial
    python tools/maix_sim.py --port COM5
    python tools/maix_sim.py --port COM5 --fail-rate 0.3        # 30% 概率乱来
    python tools/maix_sim.py --port COM5 --crc-error-rate 0.2   # 20% CRC 错
    python tools/maix_sim.py --list                             # 列出串口
    python tools/maix_sim.py --selfcheck                        # 不接串口, 自测
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maix_protocol import (  # noqa: E402
    Parser, build_report, build_none_report, crc16_ibm,
    CMD_NAMES, COLOR_NAMES, SHAPE_NAMES,
    CMD_NONE, CMD_REPORT_COLOR, CMD_REPORT_SHAPE,
    CMD_SET_MODE_COLOR, CMD_SET_MODE_SHAPE, CMD_REQUEST_DETECT,
    FRAME_HEAD,
)


class MaixSim:
    """模拟 MaixCAM 的行为"""

    def __init__(self, args):
        self.args = args
        self.parser = Parser()
        self.mode = "color"          # color / shape
        self.color_round = 0         # 颜色模式下第几次被请求
        self.rng = random.Random(args.seed)
        self.n_req = 0

    # ------------------------------------------------------------------
    def make_target(self):
        """按当前模式造一个"识别结果" """
        if self.mode == "color":
            # 第 1 次请求 = 排爆区(找排爆物颜色), 之后 = 反恐区(找靶标颜色)
            if self.args.always_bomb or self.color_round == 0:
                tid = self.args.bomb_color
                name = f"排爆物/{COLOR_NAMES.get(tid, '?')}"
            else:
                tid = self.args.target_color
                name = f"靶标/{COLOR_NAMES.get(tid, '?')}"
            self.color_round += 1
            return CMD_REPORT_COLOR, tid, name
        else:
            tid = self.args.rescue_shape
            return CMD_REPORT_SHAPE, tid, f"人质/{SHAPE_NAMES.get(tid, '?')}"

    def build_reply(self):
        """造一帧回复 (含故障注入)"""
        args = self.args
        r = self.rng.random()

        fail_rate = args.fail_rate
        if r < args.crc_error_rate:
            cmd, tid, name = self.make_target()
            frame = bytearray(build_report(cmd, tid, *self.random_box()))
            frame[12] ^= 0xFF                      # 破坏正文 -> CRC 必错
            print(f"    -> 故意发 CRC 错误的帧 ({name})")
            return bytes(frame)

        if r < args.crc_error_rate + args.empty_rate:
            print("    -> 故意发空帧 (cmd=0x00)")
            return build_none_report()

        if r < args.crc_error_rate + args.empty_rate + args.bad_id_rate:
            cmd, tid, name = self.make_target()
            wrong = (tid % 3) + 1                  # 换个编号 -> STM32 应判为不匹配
            print(f"    -> 故意发错编号的帧 (期望{tid}, 发{wrong})")
            return build_report(cmd, wrong, *self.random_box())

        if r < (args.crc_error_rate + args.empty_rate + args.bad_id_rate
                + args.out_of_range_rate):
            cmd, tid, name = self.make_target()
            print(f"    -> 故意发超范围坐标的帧 ({name})")
            return build_report(cmd, tid, 20, 20, 40, 40)   # 中心 (40,40) 超范围

        if r < fail_rate:
            print("    -> 故意不回 (模拟超时)")
            return None

        cmd, tid, name = self.make_target()
        box = self.random_box()
        print(f"    -> 回复 {name} id={tid} x={box[0]} y={box[1]} w={box[2]} h={box[3]}")
        return build_report(cmd, tid, *box)

    def random_box(self):
        """造一个中心点在有效范围内的框"""
        args = self.args
        w = self.rng.randint(args.min_size, args.max_size)
        h = self.rng.randint(args.min_size, args.max_size)
        cx = self.rng.randint(200, 440)
        cy = self.rng.randint(110, 210)
        return (cx - w // 2, cy - h // 2, w, h)

    # ------------------------------------------------------------------
    def handle_frame(self, frame):
        """收到 STM32 的一帧命令"""
        name = CMD_NAMES.get(frame.cmd, f"未知(0x{frame.cmd:02X})")
        print(f"[收] {name}  {frame.hex()}")

        if not frame.crc_ok:
            print("     CRC 错, 忽略")
            return None

        if frame.cmd == CMD_SET_MODE_COLOR:
            self.mode = "color"
            self.color_round = 0
            print("     模式 = 颜色")
            return None

        if frame.cmd == CMD_SET_MODE_SHAPE:
            self.mode = "shape"
            print("     模式 = 形状")
            return None

        if frame.cmd == CMD_REQUEST_DETECT:
            self.n_req += 1
            print(f"     第 {self.n_req} 次识别请求 (模式={self.mode}), 处理中...")
            if self.args.delay_ms > 0:
                time.sleep(self.args.delay_ms / 1000.0)
            return self.build_reply()

        print("     不认识的命令, 忽略")
        return None


# ----------------------------------------------------------------------
def selfcheck():
    """不接硬件, 用内存跑一遍收发"""
    class A:
        pass
    a = A()
    a.bomb_color, a.target_color, a.rescue_shape = 1, 2, 3
    a.fail_rate = a.crc_error_rate = a.empty_rate = 0
    a.bad_id_rate = a.out_of_range_rate = 0
    a.delay_ms = 0
    a.seed = 1
    a.always_bomb = False
    a.min_size, a.max_size = 40, 80

    sim = MaixSim(a)
    from maix_protocol import build_mode_color, build_req_detect, build_mode_shape

    print("--- selfcheck: 颜色模式 ---")
    for f in sim.parser.feed(build_mode_color()):
        sim.handle_frame(f)
    for f in sim.parser.feed(build_req_detect()):
        reply = sim.handle_frame(f)
        assert reply is not None
        rf = Parser().feed(reply)
        assert len(rf) == 1 and rf[0].crc_ok
        assert rf[0].cmd == CMD_REPORT_COLOR and rf[0].valid_target
        assert rf[0].in_valid_range(), "模拟器发的坐标必须在有效范围内"

    print("--- selfcheck: 形状模式 ---")
    for f in sim.parser.feed(build_mode_shape()):
        sim.handle_frame(f)
    for f in sim.parser.feed(build_req_detect()):
        reply = sim.handle_frame(f)
        rf = Parser().feed(reply)
        assert rf[0].cmd == CMD_REPORT_SHAPE and rf[0].target_id == 3
        assert rf[0].in_valid_range()

    print("--- selfcheck: 故障注入 ---")
    a.crc_error_rate = 1.0
    sim2 = MaixSim(a)
    for f in sim2.parser.feed(build_mode_shape() + build_req_detect()):
        reply = sim2.handle_frame(f)
    if reply is not None:
        rf = Parser().feed(reply)
        assert rf and not rf[0].crc_ok, "应该造出 CRC 错的帧"

    print("selfcheck OK")


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        print("未安装 pyserial: pip install pyserial")
        return
    ports = list(lp.comports())
    if not ports:
        print("没有找到串口")
    for p in ports:
        print(f"{p.device:<10} {p.description}")


def main():
    # Windows 控制台编码兜底: 中文/符号打不出来也不至于崩
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="PC 端 MaixCAM 模拟器")
    ap.add_argument("--port", help="串口, 例如 COM5 (接 STM32 的 USART2)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--bomb-color", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--target-color", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--rescue-shape", type=int, default=2, choices=[1, 2, 3])
    ap.add_argument("--always-bomb", action="store_true",
                    help="颜色模式下每次都报排爆物颜色 (调试 S3 用)")
    ap.add_argument("--delay-ms", type=int, default=0,
                    help="收到请求后延迟多少毫秒才回复")
    ap.add_argument("--fail-rate", type=float, default=0.0,
                    help="完全不理会的概率 (模拟超时)")
    ap.add_argument("--crc-error-rate", type=float, default=0.0)
    ap.add_argument("--empty-rate", type=float, default=0.0)
    ap.add_argument("--bad-id-rate", type=float, default=0.0)
    ap.add_argument("--out-of-range-rate", type=float, default=0.0)
    ap.add_argument("--min-size", type=int, default=40)
    ap.add_argument("--max-size", type=int, default=80)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--list", action="store_true", help="列出可用串口")
    ap.add_argument("--selfcheck", action="store_true", help="不接串口自测")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return 0
    if args.selfcheck:
        selfcheck()
        return 0
    if not args.port:
        ap.error("必须指定 --port (或者用 --list / --selfcheck)")

    try:
        import serial
    except ImportError:
        print("未安装 pyserial, 请先执行:  pip install pyserial")
        return 1

    sim = MaixSim(args)
    print(f"打开 {args.port} @ {args.baud} ...")
    print(f"排爆物颜色={args.bomb_color} 靶标颜色={args.target_color} "
          f"人质形状={args.rescue_shape}")
    print("等待 STM32 命令 (Ctrl+C 退出)")

    with serial.Serial(args.port, args.baud, timeout=0.05) as ser:
        try:
            while True:
                data = ser.read(256)
                if data:
                    for frame in sim.parser.feed(data):
                        reply = sim.handle_frame(frame)
                        if reply:
                            ser.write(reply)
                            ser.flush()
        except KeyboardInterrupt:
            print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
