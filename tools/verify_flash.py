#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_flash.py —— 烧录后校验: 比较"实际烧进芯片的 .hex"和"从芯片回读的 .bin"

为什么不能直接拿 .bin 比?
    objcopy 生成的 .bin 会把链接脚本里的对齐空洞补 0x00,
    而 flash 擦除后的空值是 0xFF, .hex 里根本不包含这些空洞地址。
    所以 .bin 和回读结果差几个 0x00/0xFF 是正常的, 不是烧录失败。
    真正该比的是 .hex(它就是烧录器写进去的东西)。

用法:
    # 1) 回读芯片 flash (0x08000000, 长度取够放下固件)
    STM32_Programmer_CLI -c port=SWD -u 0x08000000 0x5000 readback.bin

    # 2) 校验
    python tools/verify_flash.py firmware/build/Debug/AntiTerrorRobot.hex readback.bin
    python tools/verify_flash.py x.hex readback.bin --diff-bin x.bin   # 顺便解释 .bin 的差异
"""

import argparse
import sys


def parse_intel_hex(path):
    """解析 Intel HEX, 返回 {绝对地址: 字节值} 和记录统计"""
    mem = {}
    stats = {"data_records": 0, "eof": False, "max_addr": 0}
    upper = 0

    with open(path, "r", encoding="ascii", errors="ignore") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise ValueError(f"{path}:{lineno} 不是合法的 HEX 行: {line[:20]}")

            raw = bytes.fromhex(line[1:])
            count, addr, rectype = raw[0], (raw[1] << 8) | raw[2], raw[3]
            data = raw[4:4 + count]

            # 校验和: 所有字节求和应为 0
            if (sum(raw) & 0xFF) != 0:
                raise ValueError(f"{path}:{lineno} 校验和错误")

            if rectype == 0x00:                       # 数据
                base = upper + addr
                for i, b in enumerate(data):
                    mem[base + i] = b
                stats["data_records"] += 1
                stats["max_addr"] = max(stats["max_addr"], base + len(data))
            elif rectype == 0x01:                     # 文件结束
                stats["eof"] = True
                break
            elif rectype == 0x04:                     # 扩展线性地址
                upper = int.from_bytes(data, "big") << 16
            elif rectype == 0x02:                     # 扩展段地址
                upper = int.from_bytes(data, "big") << 4
            elif rectype in (0x03, 0x05):             # 起始地址记录, 忽略
                pass
            else:
                print(f"  警告: 忽略未知记录类型 0x{rectype:02X} (行 {lineno})")

    return mem, stats


def main():
    ap = argparse.ArgumentParser(description="校验芯片 flash 内容与 .hex 是否一致")
    ap.add_argument("hex_file", help="烧录用的 .hex")
    ap.add_argument("readback", help="从芯片回读的 .bin")
    ap.add_argument("--diff-bin", help="可选的 .bin, 用来解释 0x00/0xFF 空洞差异")
    ap.add_argument("--base", default="0x08000000",
                    help="回读起始地址 (默认 0x08000000)")
    args = ap.parse_args()

    base = int(args.base, 0)
    mem, stats = parse_intel_hex(args.hex_file)

    with open(args.readback, "rb") as f:
        dump = f.read()

    print(f"HEX   : {args.hex_file}")
    print(f"        数据记录 {stats['data_records']} 条, 覆盖地址 "
          f"0x{min(mem):08X} ~ 0x{stats['max_addr'] - 1:08X} "
          f"({len(mem)} 字节), 结束记录: {'有' if stats['eof'] else '无'}")
    print(f"回读  : {args.readback}  ({len(dump)} 字节, 起始 0x{base:08X})")

    if len(dump) < stats["max_addr"] - base:
        print(f"❌ 回读数据不够: 需要 {stats['max_addr'] - base} 字节, "
              f"只有 {len(dump)} 字节 (回读长度调大一点)")
        return 2

    mismatches = []
    for addr, val in mem.items():
        off = addr - base
        if 0 <= off < len(dump) and dump[off] != val:
            mismatches.append((addr, val, dump[off]))

    if not mismatches:
        print(f"✅ 一致: HEX 覆盖的 {len(mem)} 个字节与芯片回读完全相同")
        print("   -> 芯片里跑的就是这个固件")
    else:
        print(f"❌ 有 {len(mismatches)} 个字节不一致, 前 10 个:")
        for addr, want, got in mismatches[:10]:
            print(f"   0x{addr:08X}: HEX=0x{want:02X}  芯片=0x{got:02X}")

    # 顺带解释 .bin 的差异 (链接空洞: objcopy 补 0x00, flash 是 0xFF)
    if args.diff_bin:
        with open(args.diff_bin, "rb") as f:
            bin_data = f.read()
        n = min(len(bin_data), len(dump))
        pad_only = 0
        real_diff = []
        for i in range(n):
            if bin_data[i] != dump[i]:
                if (bin_data[i], dump[i]) == (0x00, 0xFF):
                    pad_only += 1
                else:
                    real_diff.append((base + i, bin_data[i], dump[i]))
        print(f"\n与 {args.diff_bin} 对比 (前 {n} 字节):")
        print(f"  .bin=0x00 / 芯片=0xFF 的链接空洞差异: {pad_only} 字节 (正常, 无影响)")
        if real_diff:
            print(f"  ⚠ 其它差异 {len(real_diff)} 字节 (需要留意):")
            for addr, b, d in real_diff[:10]:
                print(f"    0x{addr:08X}: bin=0x{b:02X} flash=0x{d:02X}")
        else:
            print("  其它差异: 0 字节")

    return 0 if not mismatches else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    sys.exit(main())
