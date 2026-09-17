/**
  ******************************************************************************
  * @file    app_config.h
  * @brief   全局硬件/参数配置 —— 所有需要按现场情况修改的东西都在这个文件里
  *
  *  2026 广东省工科大学生实验综合技能竞赛 · 赛项3 反恐排爆救援机器人
  *
  *  ⚠ 换板子/换接线时，只需要改这个文件。
  ******************************************************************************
  */
#ifndef __APP_CONFIG_H__
#define __APP_CONFIG_H__

/* ==========================================================================
 * 一、调试开关
 * ========================================================================== */
/* 1 = 打开串口调试打印 (走 USART1 的 TX 引脚 PA9，GM65 只发不收，TX 是空闲的)
 * 0 = 关闭，比赛时建议关掉                        */
#define DEBUG_ENABLE                1
/* 调试打印的串口，绑到 USART1 (PA9) */
#define DEBUG_UART                  huart1

/* ==========================================================================
 * 二、引脚定义  (⚠ 按实际接线修改)
 * ==========================================================================
 *  USART1  PA9 (TX) / PA10 (RX)  -> GM65 扫码模块   9600  8N1
 *  USART2  PA2 (TX) / PA3 (RX)   -> MaixCAM-Pro     115200 8N1  (RX 走 DMA)
 *  PD12/13/14                    -> 三色 LED  红/绿/蓝 (高电平点亮)
 *  PB0                           -> 心跳灯     (高电平点亮)
 *  PD15                          -> 650nm 激光 控制脚 (高电平开激光)
 * ------------------------------------------------------------------------ */
/* --- 心跳灯 --- */
#define HEARTBEAT_GPIO_PORT         GPIOB
#define HEARTBEAT_PIN               GPIO_PIN_0

/* --- 三色 LED --- */
#define LED_R_GPIO_PORT             GPIOD
#define LED_R_PIN                   GPIO_PIN_12
#define LED_G_GPIO_PORT             GPIOD
#define LED_G_PIN                   GPIO_PIN_13
#define LED_B_GPIO_PORT             GPIOD
#define LED_B_PIN                   GPIO_PIN_14

/* --- 激光 (650nm 红色) --- */
#define LASER_GPIO_PORT             GPIOD
#define LASER_PIN                   GPIO_PIN_15
/* 1 = 高电平开激光；如果你的激光驱动板是低电平有效，改成 0 */
#define LASER_ACTIVE_HIGH           1

/* --- 机械臂 / 编码电机 (占位阶段只亮灯，真实驱动接进来时在这里补引脚) ---
 *   TODO: 机械臂 (总线舵机/串口舵机) 的串口与引脚
 *   TODO: 4 个编码电机的 PWM(TIMx_CHx) 与 方向脚、编码器 A/B 相 (TIMx 编码器模式)
 * ------------------------------------------------------------------------ */

/* ==========================================================================
 * 三、串口参数
 * ========================================================================== */
#define GM65_UART_BAUDRATE          9600U
#define MAIX_UART_BAUDRATE          115200U

/* MaixCAM 接收: DMA 循环模式缓冲区大小 */
#define MAIX_DMA_BUF_SIZE           256U
/* MaixCAM 接收软件环形缓冲区大小 (必须是 2 的幂) */
#define MAIX_RX_RING_SIZE           1024U
/* 协议单帧最大正文长度 */
#define MAIX_MAX_BODY_LEN           32U

/* GM65 一行二维码字符串最大长度 */
#define GM65_RX_BUF_SIZE            64U

/* ==========================================================================
 * 四、协议常量
 * ========================================================================== */
#define MAIX_FRAME_HEAD_0           0xAAU
#define MAIX_FRAME_HEAD_1           0xCAU
#define MAIX_FRAME_HEAD_2           0xACU
#define MAIX_FRAME_HEAD_3           0xBBU

/* flags */
#define MAIX_FLAG_REQUEST           0x01U   /* STM32 -> MaixCAM 请求 */
#define MAIX_FLAG_REPORT            0x21U   /* MaixCAM -> STM32 主动上报 */

/* cmd */
#define MAIX_CMD_NONE               0x00U   /* 空帧 (没找到目标) */
#define MAIX_CMD_REPORT_COLOR       0x01U   /* 上报颜色目标 */
#define MAIX_CMD_REPORT_SHAPE       0x02U   /* 上报形状目标 */
#define MAIX_CMD_SET_MODE_COLOR     0x10U   /* 设为颜色模式 */
#define MAIX_CMD_SET_MODE_SHAPE     0x11U   /* 设为形状模式 */
#define MAIX_CMD_REQUEST_DETECT     0x12U   /* 请求识别一次 */

/* 颜色编码 */
#define COLOR_RED                   1U
#define COLOR_GREEN                 2U
#define COLOR_BLUE                  3U
/* 形状编码 */
#define SHAPE_CYLINDER              1U      /* 圆柱形 */
#define SHAPE_CONE                  2U      /* 圆锥形 */
#define SHAPE_WAIST_DRUM            3U      /* 腰鼓形 */

/* ==========================================================================
 * 五、视觉有效范围 (MaixCAM 分辨率 640x320)
 * ========================================================================== */
#define VISION_FRAME_W              640U
#define VISION_FRAME_H              320U
#define VISION_CENTER_X             320U
#define VISION_CENTER_Y             160U
#define VISION_X_MIN                160U
#define VISION_X_MAX                480U
#define VISION_Y_MIN                80U
#define VISION_Y_MAX                240U

/* ==========================================================================
 * 六、时间参数 (ms)
 * ========================================================================== */
#define VISION_TIMEOUT_MS           300U    /* 等 MaixCAM 上报的超时
                                             * ⚠ 如果 MaixCAM 端开了 FLUSH_BEFORE_CAPTURE
                                             *   (先丢一帧再拍, 保证画面是机械臂停下后的),
                                             *   实测一次识别 + 回传可能超过 300ms,
                                             *   那就把这个值调到 500。 */
#define VISION_RETRY_MAX            3U      /* 每个识别环节最多重试次数 */

#define ARM_MOVE_MS                 500U    /* 机械臂移动到识别位 (占位: 蓝灯常亮) */
#define ARM_SETTLE_MS               200U    /* 动作之间的稳定间隔 */
#define ARM_GRAB_MS                 500U    /* 机械臂抓取 */
#define LASER_ON_MS                 1000U   /* 激光打靶 */
#define MOTION_MS                   1000U   /* 电机前进/后退/转向 */
#define ACTION_GAP_MS               200U    /* 动作之间的间隔 */

#define LED_BLINK_MS                500U    /* 占位闪烁周期 */
#define HEARTBEAT_MS                500U    /* 心跳灯翻转周期 */

#define FINISH_HOLD_MS              3000U   /* S12 任务完成后停留 */
#define QR_TIMEOUT_MS               3000U   /* 读二维码超时 -> 用占位值 */

/* ==========================================================================
 * 七、二维码占位值 (读不到码或联调阶段使用)
 * ========================================================================== */
#define QR_PLACEHOLDER_BOMB_COLOR   COLOR_RED       /* 排爆物颜色: 红 */
#define QR_PLACEHOLDER_TARGET_COLOR COLOR_RED       /* 反恐靶颜色: 红 */
#define QR_PLACEHOLDER_RESCUE_SHAPE SHAPE_CONE      /* 救援目标形状: 圆锥形 */

/* qr_done 取值 */
#define QR_DONE_NONE                0U
#define QR_DONE_REAL                1U      /* 真的读到了二维码 */
#define QR_DONE_PLACEHOLDER         2U      /* 超时, 用的占位值 */

#endif /* __APP_CONFIG_H__ */
