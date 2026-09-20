# 反恐排爆救援机器人 —— 2026 广东省工科大学生实验综合技能竞赛 · 赛项3

STM32F407VGT6 主控 + MaixCAM-Pro 视觉 + GM65 扫码的**全自主**比赛固件工程。
上电即从蓝色出发区开始，5 分钟内依次完成 **读码 → 排爆 → 反恐 → 救援 → 返回**。

```
AntiTerrorRobot/
├── firmware/                 ← STM32F407VGT6 工程 (CLion / CMake / HAL)
│   ├── CMakeLists.txt
│   ├── CMakePresets.json
│   ├── STM32F407VGTX_FLASH.ld
│   ├── cmake/gcc-arm-none-eabi.cmake
│   ├── startup/startup_stm32f407xx.s
│   ├── Core/Inc, Core/Src    ← 本工程全部业务代码
│   └── Drivers/              ← STM32CubeF4 HAL + CMSIS (已复制进来, 不依赖外部路径)
├── maixcam/                  ← MaixCAM-Pro 端 MaixPy 代码 (被动视觉模块)
│   ├── main.py               ← 直接推给 MaixVision 运行, 自带协议, 无外部依赖
│   └── README.md             ← 接线 / 标定 / 开机自启说明
├── tools/                    ← PC 端工具 (协议参考实现 / 模拟器 / 单元测试)
│   ├── maix_protocol.py      ← 协议 Python 参考实现 (与两端逐字节一致)
│   ├── test_maix_protocol.py ← 19 项协议单元测试
│   ├── test_maixcam_vision.py← 13 项视觉算法测试 (伪造 maix 模块 + 合成形状图)
│   ├── maix_sim.py           ← PC 端 MaixCAM 模拟器, 可注入故障
│   └── verify_flash.py       ← 烧录后校验: 芯片回读 vs .hex 逐字节比对
├── docs/
│   ├── 通信协议.md
│   └── 联调与现场调试.md
├── build.ps1                 ← 一键编译
├── flash.ps1                 ← 一键烧录（自动寻找产物；-Verify 自动回读校验）
├── check_stlink.ps1          ← ST-Link 探头 / SWD 接线自检（含接线表与故障解读）
├── debug.ps1                 ← 启动 ST-LINK GDB server / 一键进入 GDB 调试
└── run_tests.ps1             ← 一键跑完所有 PC 端测试
```

> `firmware/.idea/runConfigurations/` 里预置了两个 CLion 运行配置：
> **Flash to board (ST-Link)** 和 **Start ST-Link GDB server**。

---

## 一、环境（你这台电脑已经全部就绪，无需再装）

| 组件 | 版本 / 位置 | 用途 |
| :--- | :--- | :--- |
| arm-none-eabi-gcc | 13.3.1 · `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin` | 交叉编译 |
| CMake | `D:\STM32CubeCLT_1.18.0\CMake\bin` | 构建 |
| Ninja | `D:\STM32CubeCLT_1.18.0\Ninja\bin` | 生成器 |
| arm-none-eabi-gdb | `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin` | 调试 |
| ST-LINK_gdbserver | `D:\STM32CubeCLT_1.18.0\STLink-gdb-server\bin` | CLion 下载/调试 |
| STM32_Programmer_CLI | `D:\STM32CubeCLT_1.18.0\STM32CubeProgrammer\bin` | 烧录 |
| CLion | 2026.2 | 开发 |
| STM32CubeF4 HAL | V1.28.3（已复制进 `firmware/Drivers`） | HAL 库 |
| Python + pyserial 3.5 | 3.14 / 已安装 | PC 联调工具 |
| STM32CubeMX | `D:\STM32MX`（可选，改外设时用） | 图形化配置 |

> 已验证：本工程用上述工具链**编译通过，0 warning**。
> 当前体积：FLASH 18.5 KB / RAM 4.8 KB（1 MB / 128 KB 的芯片，余量极大）。

---

## 二、编译与烧录

### 2.1 命令行（推荐，最快）

```powershell
cd D:\stm32ideproject\AntiTerrorRobot
.\build.ps1                 # 编译 Debug 版
.\build.ps1 -SelfTest       # 编译"自带协议自检"的版本 (独立目录, 不污染比赛固件)
.\check_stlink.ps1          # 先自检: 探头在不在? SWD 接线对不对? 芯片认不认?
.\flash.ps1                 # 烧录 (自动找 build\ 或 cmake-build-debug\ 里的产物)
.\flash.ps1 -Verify         # 烧录 + 回读校验 (逐字节确认芯片内容 == .hex)
.\debug.ps1 -Gdb            # 在线调试: 启动 GDB server + 下载 + 断点
.\debug.ps1 -Gdb -FreqKHz 500   # ST-Link V2 克隆版 / 长杜邦线握手不稳时降频
.\debug.ps1 -Stop           # 关掉 GDB server
```

### 2.1.1 烧录前先自检 ST-Link（强烈建议）

```powershell
.\check_stlink.ps1
```

本机实测输出（ST-Link V2 + STM32F407VGT6）：

```
== 1. USB ==            [OK] STM32 STLink
== 2. SWD connect ==    ST-LINK SN : 37FF71064E5734364C6A1143
                        ST-LINK FW : V2J45S7
                        Voltage    : 3.27V          <- 板子已上电, 电平参考正常
                        Device ID  : 0x413
                        Device name: STM32F405xx/F407xx/F415xx/F417xx
                        Flash size : 1 MBytes
                        Device CPU : Cortex-M4
== 3. Result ==         OK - probe found the chip. SWD wiring is correct.
```

它还会打印 **ST-Link V2 ↔ STM32F407 接线表**，并把失败分两类：
* `No debug probe detected` → 电脑没认到探头（USB/驱动/克隆版固件太老）
* `DEV_CONNECT_ERR` / `No STM32 target found` → 探头好但 SWD 没连上
  （**最常见：GND 没接、SWDIO/SWCLK 接反、板子没上电、或探头已被别的程序占用**）

> ⚠ **同一个 ST-Link 只能被一个程序使用**。如果 `.\debug.ps1` 起的 GDB server 还开着，
> 或者 CLion 正在调试会话里，`flash.ps1` / `check_stlink.ps1` 都会报连接失败。
> 先 `.\debug.ps1 -Stop`，CLion 那边停止调试会话，再烧录。

### 2.1.2 烧录后校验芯片内容（可选但推荐）

```powershell
.\flash.ps1 -Verify
# 或者单独跑: python tools\verify_flash.py <固件.hex> <回读.bin>
```

判定标准是**回读内容与 `.hex`（烧录器真正写进去的东西）逐字节一致**。
注意：不要拿 `.bin` 直接比——`objcopy` 会把链接脚本的对齐空洞补 `0x00`，
而 flash 擦除后是 `0xFF`，所以差几个 `0x00/0xFF` 是正常的（本项目实测 8 字节），
`verify_flash.py` 会把这部分单独统计出来。

手动等价命令：

```powershell
cd firmware
cmake -S . -B build/Debug -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build/Debug
# 产物: build/Debug/AntiTerrorRobot.elf / .hex / .bin
```

### 2.2 CLion（编译 / 烧录 / 调试）

> ⚠ **一句话规则：编译按 Build（Ctrl+F9），烧录用 ST-LINK 配置或脚本；不要按 Run 去"运行"这个 target。**
> `AntiTerrorRobot` 是 ARM 固件，Windows 执行不了 `.elf`，点 Run 会报
> `CreateProcess error=193, %1 不是有效的 Win32 应用程序`。
> **这个报错恰恰说明编译已经成功了**，只是嵌入式工程没有"在电脑上运行"这一步。

1. `File → Open` 选 **`D:\stm32ideproject\AntiTerrorRobot\firmware`** 这个目录（不是仓库根目录）。
2. **编译**：`Build → Build Project`（Ctrl+F9），或用锤子图标。
   * CLion 默认用自己的 `firmware/cmake-build-debug` 目录，这没问题——
     `flash.ps1` / `debug.ps1` 会自动找到它，也会找 `firmware/build/…` 的产物。
   * 想让 CLion 用本工程的 CMake 预设（输出到 `firmware/build/Debug`）：
     `Settings → Build, Execution, Deployment → CMake`，Profile 选预设 `Debug`。
3. **删掉那两个 Application 型运行配置**（它们就是会报 193 的元凶）：
   `Run → Edit Configurations` → 选中 `AntiTerrorRobot` 和 `configuration` → 点减号删除。

4. **烧录（三条路，任选一条）**

   **路线 1 — CLion 原生 ST-LINK（最正规，能烧也能调）**
   CLion 2026.2 自带 `STM32 for CLion` 插件（内含 `ST-LINK` 调试配置类型），它会自动
   检测 STM32CubeCLT 与 `ST-LINK_gdbserver`：
   * `Settings → Build, Execution, Deployment → STM32`（或 Embedded Development）里
     确认 CubeCLT 路径被识别，`ST-LINK GDB Server Executable` 指向
     `D:\STM32CubeCLT_1.18.0\STLink-gdb-server\bin\ST-LINK_gdbserver.exe`。
   * `Run → Edit Configurations → + → ST-LINK`，Name 随便起，Target 选
     `AntiTerrorRobot.elf`（CMake profile 用 Debug），然后：
     **点 Debug（虫子图标）= 烧录 + 进入调试**；需要纯下载时用该配置附带的下载动作。
   * 前提：ST-Link 探头插好、板子上电（没插探头时 CLion 找不到目标，会提示 no probe）。

   **路线 2 — 我预置的 Shell Script 配置（在 CLion 里一键烧录）**
   `Run → Edit Configurations` 里选 **`Flash to board (ST-Link)`** 直接运行，
   它会在 CLion 的 Terminal 里执行 `flash.ps1`，输出就在 CLion 里看。
   如果这个配置没出现，手工加一个 `+ → Shell Script`：

   | 字段 | 值 |
   | :--- | :--- |
   | Interpreter path | `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` |
   | Interpreter options | `-ExecutionPolicy Bypass -File` |
   | Script path | `$PROJECT_DIR$/../flash.ps1` |
   | Script options | `-Config Debug` |
   | Working directory | `$PROJECT_DIR$` |
   | 勾选 | Execute in terminal |

   > ⚠ **解释器必须写绝对路径**。只写 `powershell.exe` 时 CLion 会直接报
   > **「错误: 找不到解释器」**，此时脚本根本不会被执行（所以 ST-LINK 的 GDB server
   > 也起不来，很容易误以为是 ST-Link V2 坏了）——CLion 的运行配置**不会去 PATH 里找**，
   > 这是它和你系统终端最大的区别。换电脑先在 cmd 里 `where powershell` 查路径。
   > 本机只有 Windows PowerShell 5.1（没装 PowerShell 7），上面这个路径实测可用。

   **路线 3 — CLion 自带终端（100% 不会出错）**
   `Alt+F12` 打开 Terminal，或者连按两下 `Ctrl`（Run Anything）输入：
   ```powershell
   .\flash.ps1                 # 注意脚本在仓库根目录, 不是在 firmware 里
   cd .. ; .\flash.ps1         # 如果终端当前在 firmware 目录
   ```

5. **在线调试（断点 / 单步 / 看变量）**

   **方式 A（推荐，一条命令）**：`Alt+F12` 打开 Terminal →
   ```powershell
   cd ..
   .\debug.ps1 -Gdb
   ```
   自动启动 ST-LINK GDB server → 下载 → 停在 `main`，就可以下断点、单步、看变量了。

   **方式 B（在 CLion 图形界面里调试）**
   * 先运行配置 **`Start ST-Link GDB server`**（或终端 `.\debug.ps1`）。
     这个配置的 Interpreter path 同样必须是绝对路径
     `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`，否则会报「找不到解释器」。
   * `Run → Edit Configurations → + → GDB Remote Debug`：
     * `target remote` 填 `tcp:localhost:61234`
     * Symbol file 选 `AntiTerrorRobot.elf`（`build/Debug/` 或 `cmake-build-debug/`）
     * GDB 选 `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin\arm-none-eabi-gdb.exe`
   * 用完 `.\debug.ps1 -Stop` 收工。

6. **看串口日志**：CLion 2026.2 自带 **Serial Monitor** 工具窗口
   （`View → Tool Windows → Serial Monitor`），选 USB-TTL 的 COM 口、**115200 8N1**，
   编码选 **UTF-8**（否则中文日志乱码）——不用再另开串口助手。

7. **不开图形界面，直接把芯片里正在跑的状态读出来**（排查"到底跑到哪一步"很快）：
   ```powershell
   .\debug.ps1                      # 起 GDB server (用完 .\debug.ps1 -Stop)
   # 然后在 firmware 目录下:
   #   gdb -batch -ex "target extended-remote localhost:61234" \
   #       -ex "print state" -ex "print qr_done" -ex "print qr_bomb_color" \
   #       -ex "print g_maix_tx_frames" -ex "detach" -ex "quit" AntiTerrorRobot.elf
   ```
   实测（没接任何外设时）：`state = 11`（已跑到 S11）、`qr_done = 2`（用占位值 112）、
   `retry_count = 3`（视觉 3 次重试后跳过）、`g_maix_tx_frames = 11`、`g_maix_rx_frames = 0`
   ——说明固件在无外设时按设计优雅降级、全程不卡死。

### 2.3 CLion 里指定工具链（若自动找不到）

`Settings → Build, Execution, Deployment → Toolchains → + → System`：

| 字段 | 值 |
| :--- | :--- |
| C Compiler | `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin\arm-none-eabi-gcc.exe` |
| C++ Compiler | `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin\arm-none-eabi-g++.exe` |
| Debugger | `D:\STM32CubeCLT_1.18.0\GNU-tools-for-STM32\bin\arm-none-eabi-gdb.exe` |
| CMake | `D:\STM32CubeCLT_1.18.0\CMake\bin\cmake.exe` |
| Ninja | `D:\STM32CubeCLT_1.18.0\Ninja\bin\ninja.exe` |

`cmake/gcc-arm-none-eabi.cmake` 里已经写好了自动搜索逻辑，所以**通常不用手工指定**；
换电脑时也可以用 `-DARM_TOOLCHAIN_DIR=<bin 目录>` 覆盖。

---

## 三、接线（按这个表插线，改线只改 `Core/Inc/app_config.h`）

| STM32 引脚 | 接到 | 说明 |
| :--- | :--- | :--- |
| PA9 / PA10 | GM65 模块 | USART1，**9600** 8N1；PA9 空闲，可以接 USB-TTL 看调试打印 |
| PA2 / PA3 | MaixCAM-Pro | USART2，**115200** 8N1（RX 走 DMA1_Stream5） |
| **PC10 / PC11 / PC12** | 三色 LED 红 / 绿 / 蓝 | 高电平点亮，占位显示机械臂/电机/激光动作（原 PD12/13/14，已按要求改到 PC10/11/12） |
| PB0 | 心跳灯 | 500 ms 翻转；S12 任务完成时常亮 |
| PD15 | 650 nm 激光驱动 | 高电平开（低电平有效的驱动板改 `LASER_ACTIVE_HIGH 0`） |
| **PA13** | **ST-Link SWDIO** | 调试/烧录用，**不要**接别的东西 |
| **PA14** | **ST-Link SWCLK** | 调试/烧录用 |
| NRST | ST-Link RST（可选） | 接上更稳，可支持 connect-under-reset |
| GND | 三块板共地 | **必须共地**，否则串口乱码 |

> ST-Link V2 那一侧是按功能丝印（`3.3V / SWDIO / SWCLK / GND / RST`），照名字对接即可。
> 3.3V(VTref) 只作电平参考：板子自己有电源时不要再从探头取电，避免互相倒灌。
> 本工程只用 PA13/PA14 做 SWD，**从不关闭调试口、也不进低功耗**，所以普通 SWD 一定能连上。

> MaixCAM 端：默认用 **UART0**，A16 = TX → STM32 PA3(RX)，A17 = RX ← STM32 PA2(TX)，GND 共地。
> ⚠ 官方提醒：UART0 是系统日志口（上电会吐启动日志，帧解析器会自动跳过垃圾字节），
> 且 A16(TX) 兼作启动模式脚、**上电时不能被拉低**。想更稳就改用 **UART1**
> （A19 = TX / A18 = RX / `/dev/ttyS1`），详见 `maixcam/README.md`。

---

## 四、上电后会发生什么（S0 ~ S12）

| 状态 | 名称 | 行为（当前为占位实现，用灯效代替执行机构） |
| :--- | :--- | :--- |
| S0 | 初始化 | 清缓冲、机械臂回原位、停电机、关激光、灭灯、心跳灯闪、清变量 |
| S1 | 读二维码 | 等 GM65 输出三位数字（超时 3 s → 用占位值 `112`） |
| S2 | 前往排爆区 | 前进 1 s（红+绿一起闪）→ 停 → 间隔 200 ms |
| S3 | 排爆区识别 | 发 `0x10` 设颜色模式 → 蓝灯常亮 500 ms → 全灭 200 ms → 发 `0x12` → 绿灯慢闪等上报（超时 300 ms），匹配颜色 + 范围判断，失败原地重试，最多 3 次 |
| S4 | 排爆区抓取 | 对应颜色灯常亮 500 ms（抓取）→ 500 ms（放入排爆桶） |
| S5 | 前往反恐区 | 前进 1 s |
| S6 | 反恐区识别 | **保持颜色模式**，移识别位 → 发 `0x12` → 匹配靶标颜色 |
| S7 | 反恐区打靶 | 激光开 + 红灯闪 1 s → 关激光 |
| S8 | 前往救援区 | 前进 1 s |
| S9 | 救援区识别 | 发 `0x11` 设形状模式 → 发 `0x12` → 匹配人质形状 |
| S10 | 救援区抓取 | 圆柱→红 / 圆锥→绿 / 腰鼓→蓝 常亮 500 ms |
| S11 | 返回返回区 | 前进 1 s → 放置人质 |
| S12 | 任务完成 | 停电机、关激光、心跳灯常亮、停留 3 s → 回到 S0 循环 |

任何识别环节 **CRC 错 / 空帧 / 超时 / 编号不匹配 / 坐标越界** 都是**原地重发 0x12**，
3 次都失败就跳过该任务继续下一状态，绝不卡死。

灯效对照表见 `docs/联调与现场调试.md`。

---

## 五、联调（没有 MaixCAM 也能把 STM32 跑通）

```powershell
pip install pyserial                                   # 已装好
python tools\maix_sim.py --list                        # 看有哪些串口
python tools\maix_sim.py --port COM5                   # 模拟 MaixCAM
python tools\maix_sim.py --port COM5 --crc-error-rate 0.2 --empty-rate 0.2
python tools\maix_sim.py --port COM5 --delay-ms 500    # 模拟超时, 验证重试
```

`maix_sim.py` 会像真 MaixCAM 一样应答，还可以**故意制造故障**（CRC 错、空帧、
编号错、坐标越界、干脆不回），用来验证 STM32 的重试与跳过逻辑。

协议逻辑本身用单元测试钉住了（PC 端 19 项 + MaixCAM 端 13 项全过）：

```powershell
.\run_tests.ps1                     # 一次跑完全部 PC 端测试
python tools\test_maix_protocol.py  # 协议参考实现
python tools\test_maixcam_vision.py # MaixCAM 视觉算法(合成图, 不需要真机)
```

> `test_maixcam_vision.py` 会伪造一个 `maix` 模块，用合成的**圆柱/圆锥/腰鼓轮廓图**
> 去跑真正的 `detect_shape()`，所以阈值逻辑改动后能在电脑上立刻验证。

板级自检（上电打印 PASS/FAIL，确认固件在真板上也一致）：

```powershell
.\build.ps1 -SelfTest ; .\flash.ps1 -Config SelfTest
# SelfTest 编译到独立的 firmware/build/SelfTest 目录, 不会污染比赛固件
# 用 USB-TTL 接 PA9 + GND, 115200 打开串口(编码 UTF-8), 复位即可看到自检结果
```

---

## 六、现场需要标定的东西

| 项目 | 在哪里改 | 说明 |
| :--- | :--- | :--- |
| 颜色 LAB 阈值 | `maixcam/main.py` 顶部 `COLOR_THRESHOLDS` | 现场灯光变了必须重标 |
| 白色灰度阈值 | `maixcam/main.py` 的 `WHITE_GRAY_THR`（暂 200） | 白 PLA vs 黑亚克力台 |
| 形状判别阈值 | `maixcam/main.py` 的 `SHAPE_WIDTH_DIFF`（暂 50 px） | 10 cm 距离下推算值，实测调整 |
| 有效范围 / 超时 / 重试次数 | `firmware/Core/Inc/app_config.h` | 视觉对准与否主要调这里 |
| 二维码占位值 | `app_config.h` 的 `QR_PLACEHOLDER_*` | 联调时不用真扫码 |
| 动作时长 | `app_config.h` 的 `MOTION_MS / ARM_*_MS / LASER_ON_MS` | 接上真实机构后按实际调 |

---

## 七、把占位换成真硬件

占位逻辑被刻意隔离成三个文件，接口不变，只换函数体：

| 文件 | 现在 | 换成 |
| :--- | :--- | :--- |
| `Core/Src/motion.c` | 灯效 | 4 路编码电机 PWM + 方向脚 + 编码器闭环（`Motion_SetWheel`） |
| `Core/Src/arm.c` | 灯效 | 总线舵机/串口舵机指令（`Arm_SetJoint`）或 PWM 舵机 |
| `Core/Src/laser.c` | 已可用 | 直接驱动激光（PD15） |
| `Core/Src/vision.c` | 已可用 | 视觉匹配 + 范围判断，接真 MaixCAM 直接生效 |

状态机 `app_fsm.c` **一行都不用改**。

---

## 八、文档

* `docs/通信协议.md` —— 帧格式、命令表、CRC、时序图、测试向量
* `docs/联调与现场调试.md` —— 灯效表、分步联调流程、常见故障排查
* `maixcam/main.py` 顶部注释 —— MaixCAM 端配置与标定说明
