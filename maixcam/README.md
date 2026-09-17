# MaixCAM-Pro 端说明（视觉模块）

这个目录只有 **一个文件** `main.py`，它自带协议、CRC、解析器，所以可以直接用
MaixVision 推到设备上运行，不需要任何外部依赖。

---

## 一、它做什么

**完全被动的视觉模块**，识别节奏完全由 STM32 控制：

```
上电 → 初始化(串口/摄像头) → 等命令
   ├── 收到 0x10 → 模式 = 颜色
   ├── 收到 0x11 → 模式 = 形状
   └── 收到 0x12 → 拍一帧 → 按当前模式识别一次 → 上报一帧 → 回等待
```

* 只上报 **编号 + 原始坐标**；匹配判断、范围判断都在 STM32 做。
* 找到就报 `0x01`（颜色）/ `0x02`（形状），没找到就发空帧 `0x00`。
* 模式设置一次就记住，直到下次切换。

详细协议见 `../docs/通信协议.md`。

---

## 二、接线（两种方案，选一种）

### 方案 A：UART0（默认，按设计文档）

| MaixCAM-Pro | STM32 | 说明 |
| :--- | :--- | :--- |
| A16 = UART0_TX | PA3 = USART2_RX | MaixCAM 发 → STM32 收 |
| A17 = UART0_RX | PA2 = USART2_TX | STM32 发 → MaixCAM 收 |
| GND | GND | **必须共地** |

`main.py` 里 `UART_DEVICE = "/dev/ttyS0"`。

> ⚠ 官方提醒：UART0 是系统日志口，上电时会先吐一段启动日志；
> 而且 A16(TX) 兼作启动模式检测脚，**上电时不能被拉低**，否则 MaixCAM 起不来。
> 我们的 STM32 帧解析器会自动跳过这些垃圾字节（自检第 5 项专门验证过），所以不影响功能。

### 方案 B：UART1（官方推荐用于自定义通讯，更干净）

| MaixCAM-Pro | STM32 |
| :--- | :--- |
| A19 = UART1_TX | PA3 = USART2_RX |
| A18 = UART1_RX | PA2 = USART2_TX |
| GND | GND |

把 `main.py` 里改成 `UART_DEVICE = "/dev/ttyS1"` 即可，脚位映射（pinmap）代码会自动设置。

两端都是 **115200 8N1**（MaixCAM 只验证过 115200，别用别的波特率）。

---

## 三、怎么跑起来

1. 电脑装 **MaixVision**，USB 线接 MaixCAM-Pro。
2. 打开 `main.py`，点运行 → 代码推送到设备执行，屏幕上有画面预览。
3. 串口控制台会打印收到的命令和识别结果，例如：
   ```
   [MaixCAM] 串口打开成功: /dev/ttyS0
   [MaixCAM] 进入主循环, 等待 STM32 命令 (模式默认: 颜色)
   [MaixCAM] 收到命令: 设为颜色模式
   [MaixCAM] 模式 = 颜色模式
   [MaixCAM] 收到命令: 请求识别一次
   [MaixCAM] 第 1 次识别: 红(1) x=300 y=140 w=60 h=60  用时 38ms
   ```
4. **比赛时设为开机自启**：MaixVision 里把应用安装到设备（或让设备启动时自动运行
   这个脚本），否则断电重启后没人点"运行"，STM32 会一直等不到上报。

---

## 四、现场标定（最重要的一步）

### 4.1 颜色阈值

设备自带 **Find Blobs** 应用可以直接调阈值：对着目标点一下屏幕 → 左侧显示 LAB 值 →
点一下框自动生成阈值 → 再手动微调。把最终值填到 `main.py`：

```python
COLOR_THRESHOLDS = {
    1: (11, 68,  29,  75,  21,  33),   # 红  (L_MIN, L_MAX, A_MIN, A_MAX, B_MIN, B_MAX)
    2: (25, 52, -41,  -5, -16,  28),   # 绿
    3: (13, 59, -23,  13, -58, -15),   # 蓝
}
```

### 4.2 白色灰度阈值

```python
WHITE_GRAY_THR = 200     # 白 PLA 与黑亚克力台之间的值
```

调法：把设备串口日志打开（`DEBUG = True`），三个形状各测一遍，看打印的
`剖面 像素: top=.. mid=.. bottom=..` 是否能分开；分不开就先调 `WHITE_GRAY_THR`。

### 4.3 形状判别阈值

```python
SHAPE_WIDTH_DIFF = 50    # 绝对像素差（设计文档给的值，现场必须重标）
SHAPE_USE_RELATIVE_RULE = False   # 分不开时改成 True
SHAPE_RELATIVE_RATIO = 1.25       # 相对判据: 宽 25% 就算"更宽"
```

判别规则（与设计文档一致）：

```
w_mid > w_top + DIFF 且 w_mid > w_bottom + DIFF  → 腰鼓形
w_bottom > w_top + DIFF                          → 圆锥形
其它                                             → 圆柱形
```

> 💡 提醒：圆锥形上径 30mm / 下径 50mm，只差 20mm。如果相机距离让 50mm 只有 100 像素左右，
> 那 20mm ≈ 40 像素 < 50 像素阈值 → 会被判成圆柱形。所以要么把 `SHAPE_WIDTH_DIFF` 调小，
> 要么打开 `SHAPE_USE_RELATIVE_RULE`（对相机距离不敏感）。**必须用真物体实测三个形状各一次。**

### 4.4 性能

| 参数 | 说明 |
| :--- | :--- |
| `FLUSH_BEFORE_CAPTURE = True` | 收到 0x12 后先丢一帧再拍，保证是机械臂**停下后**的画面（更准，但慢一点） |
| `SHOW_PREVIEW = True` | 屏幕上显示画面和识别框，方便对准；比赛时可关掉省 CPU |
| `PROFILE_W/H = 160/80` | 形状剖面下采样尺寸，越小越快 |

如果 STM32 报 `[VIS] 重试`，多半是超时：把 STM32 的 `VISION_TIMEOUT_MS`
（`firmware/Core/Inc/app_config.h`）从 300 调到 500 再试。

---

## 五、在电脑上先验证算法（不用真机）

`../tools/test_maixcam_vision.py` 伪造了一个 `maix` 模块，用**合成的圆柱/圆锥/腰鼓轮廓图**
跑真实的 `detect_shape()`，13 项测试全过才会通过：

```powershell
python tools\test_maixcam_vision.py
```

改了算法先跑它，比拿真设备试快得多。
