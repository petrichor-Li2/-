#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_maix_protocol.py —— 协议参考实现的单元测试

    python tools/test_maix_protocol.py            # 直接跑
    python -m unittest discover -s tools          # 用 unittest 跑

测试向量和 STM32 端 firmware/Core/Src/selftest.c 里的完全一致。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maix_protocol import (  # noqa: E402
    crc16_ibm, build_frame, build_report, build_none_report,
    build_mode_color, build_mode_shape, build_req_detect,
    Parser, Frame, is_in_valid_range,
    FRAME_HEAD, FLAG_REQUEST, FLAG_REPORT,
    CMD_NONE, CMD_REPORT_COLOR, CMD_REPORT_SHAPE,
    CMD_SET_MODE_COLOR, CMD_SET_MODE_SHAPE, CMD_REQUEST_DETECT,
)

# --------------------------------------------------------------------------
# 钉死的测试向量
# --------------------------------------------------------------------------
V_MODE_COLOR = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00,
                      0x01, 0x10, 0x00, 0x5C])
V_MODE_SHAPE = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00,
                      0x01, 0x11, 0xC1, 0x9C])
V_REQ_DETECT = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00,
                      0x01, 0x12, 0x81, 0x9D])
V_REPORT_COLOR = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x0D, 0x00, 0x00, 0x00,
                        0x21, 0x01,
                        0x01, 0x2C, 0x01, 0x8C, 0x00, 0x3C, 0x00, 0x3C, 0x00,
                        0xE3, 0xB8])
V_REPORT_SHAPE = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x0D, 0x00, 0x00, 0x00,
                        0x21, 0x02,
                        0x02, 0x40, 0x01, 0xA0, 0x00, 0x32, 0x00, 0x46, 0x00,
                        0x27, 0x1E])
V_NONE = bytes([0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00,
                0x21, 0x00, 0x18, 0x50])


class TestCRC(unittest.TestCase):

    def test_catalogue_vector(self):
        """CRC-16/ARC 标准校验值 (也叫 CRC16_IBM)"""
        self.assertEqual(crc16_ibm(b"123456789"), 0xBB3D)

    def test_small_vectors(self):
        self.assertEqual(crc16_ibm(b"\x01\x10"), 0x5C00)
        self.assertEqual(crc16_ibm(b"\x01\x12"), 0x9D81)

    def test_empty(self):
        self.assertEqual(crc16_ibm(b""), 0x0000)


class TestBuild(unittest.TestCase):

    def test_head_and_len(self):
        f = build_req_detect()
        self.assertEqual(f[:4], FRAME_HEAD)
        self.assertEqual(int.from_bytes(f[4:8], "little"), 4)   # flags+cmd+crc
        self.assertEqual(len(f), 12)

    def test_mode_commands(self):
        self.assertEqual(build_mode_color(), V_MODE_COLOR)
        self.assertEqual(build_mode_shape(), V_MODE_SHAPE)
        self.assertEqual(build_req_detect(), V_REQ_DETECT)

    def test_reports(self):
        self.assertEqual(build_report(CMD_REPORT_COLOR, 1, 300, 140, 60, 60),
                         V_REPORT_COLOR)
        self.assertEqual(build_report(CMD_REPORT_SHAPE, 2, 320, 160, 50, 70),
                         V_REPORT_SHAPE)
        self.assertEqual(build_none_report(), V_NONE)

    def test_report_len_field(self):
        f = build_report(CMD_REPORT_COLOR, 3, 10, 20, 30, 40)
        # 长度 = flags(1) + cmd(1) + body(9) + crc(2) = 13
        self.assertEqual(int.from_bytes(f[4:8], "little"), 13)
        # 整帧 = 帧头(4) + 长度(4) + 长度字段(13) = 21
        self.assertEqual(len(f), 21)
        self.assertEqual(len(f), 12 + 9)

    def test_body_too_long(self):
        with self.assertRaises(ValueError):
            build_frame(FLAG_REPORT, CMD_REPORT_COLOR, b"\x00" * 33)


class TestParse(unittest.TestCase):

    def check_roundtrip(self, raw: bytes) -> Frame:
        p = Parser()
        frames = p.feed(raw)
        self.assertEqual(len(frames), 1, "应该解析出正好 1 帧")
        f = frames[0]
        self.assertTrue(f.crc_ok, "CRC 应该通过")
        return f

    def test_roundtrip_all(self):
        for raw in (V_MODE_COLOR, V_MODE_SHAPE, V_REQ_DETECT,
                    V_REPORT_COLOR, V_REPORT_SHAPE, V_NONE):
            self.check_roundtrip(raw)

    def test_color_target_fields(self):
        f = self.check_roundtrip(V_REPORT_COLOR)
        self.assertEqual(f.cmd, CMD_REPORT_COLOR)
        self.assertTrue(f.valid_target)
        self.assertEqual((f.target_id, f.x, f.y, f.w, f.h), (1, 300, 140, 60, 60))
        self.assertEqual((f.cx, f.cy), (330, 170))
        self.assertTrue(f.in_valid_range())

    def test_shape_target_fields(self):
        f = self.check_roundtrip(V_REPORT_SHAPE)
        self.assertEqual(f.cmd, CMD_REPORT_SHAPE)
        self.assertEqual((f.target_id, f.x, f.y, f.w, f.h), (2, 320, 160, 50, 70))

    def test_empty_frame(self):
        f = self.check_roundtrip(V_NONE)
        self.assertEqual(f.cmd, CMD_NONE)
        self.assertFalse(f.valid_target)

    def test_crc_reject(self):
        bad = bytearray(V_REPORT_COLOR)
        bad[12] ^= 0xFF
        p = Parser()
        frames = p.feed(bytes(bad))
        self.assertEqual(len(frames), 1)
        self.assertFalse(frames[0].crc_ok)
        self.assertEqual(p.crc_errors, 1)

    def test_resync_after_junk(self):
        p = Parser()
        junk = bytes([0x00, 0xFF, 0xAA, 0xAA, 0x55, 0xCA, 0xAC])
        frames = p.feed(junk + V_REQ_DETECT)
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].crc_ok)
        self.assertEqual(frames[0].cmd, CMD_REQUEST_DETECT)

    def test_two_frames_back_to_back(self):
        p = Parser()
        frames = p.feed(V_MODE_COLOR + V_REPORT_COLOR)
        self.assertEqual(len(frames), 2)
        self.assertEqual([f.cmd for f in frames],
                         [CMD_SET_MODE_COLOR, CMD_REPORT_COLOR])

    def test_bad_length_rejected(self):
        p = Parser()
        bad = FRAME_HEAD + (999).to_bytes(4, "little") + b"\x01\x10\x00\x00"
        frames = p.feed(bad)
        self.assertEqual(frames, [])
        self.assertGreaterEqual(p.length_errors, 1)

    def test_byte_by_byte(self):
        """一字节一字节喂 (模拟 UART 中断)"""
        p = Parser()
        out = []
        for b in V_REPORT_COLOR:
            f = p.push(b)
            if f is not None:
                out.append(f)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].crc_ok)


class TestVisionRange(unittest.TestCase):

    def test_in_range(self):
        self.assertTrue(is_in_valid_range(300, 140, 60, 60))   # cx=330 cy=170
        self.assertTrue(is_in_valid_range(160, 80, 0, 0))      # 边界
        self.assertTrue(is_in_valid_range(320, 160, 0, 0))

    def test_out_of_range(self):
        self.assertFalse(is_in_valid_range(100, 140, 60, 60))  # cx=130
        self.assertFalse(is_in_valid_range(300, 40, 60, 60))   # cy=70
        self.assertFalse(is_in_valid_range(480, 240, 2, 2))    # cx=481 cy=241


if __name__ == "__main__":
    unittest.main(verbosity=2)
