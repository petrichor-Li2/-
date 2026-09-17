/**
  ******************************************************************************
  * @file    app_fsm.c
  * @brief   主状态机 S0 ~ S12  (非阻塞, 全部用 HAL_GetTick() 判超时)
  *
  *  S0  初始化            S1  读二维码          S2  前往排爆区
  *  S3  排爆区识别        S4  排爆区抓取        S5  前往反恐区
  *  S6  反恐区识别        S7  反恐区打靶        S8  前往救援区
  *  S9  救援区识别        S10 救援区抓取        S11 返回返回区
  *  S12 任务完成
  ******************************************************************************
  */
#include "app_fsm.h"
#include "app_config.h"
#include "vision.h"
#include "maix_link.h"
#include "gm65.h"
#include "bsp_led.h"
#include "motion.h"
#include "arm.h"
#include "laser.h"
#include "debug.h"
#include "main.h"

/* -------------------------------------------------------------------------- */
/* 全局状态                                                                    */
/* -------------------------------------------------------------------------- */
volatile uint8_t state   = S0_INIT;
uint8_t          retry_count = 0U;

/* -------------------------------------------------------------------------- */
/* 内部: 子步骤调度                                                            */
/* -------------------------------------------------------------------------- */
static uint8_t  s_step  = 0U;
static uint32_t s_t     = 0U;      /* 当前子步骤开始时刻 */
static uint8_t  s_retry = 0U;      /* 当前识别环节的重试次数 */
static uint16_t s_cycle = 0U;      /* 第几轮任务 */

#define STEP_ARM()          do { s_t = HAL_GetTick(); } while (0)
#define STEP_ELAPSED(ms)    ((uint32_t)(HAL_GetTick() - s_t) >= (uint32_t)(ms))
#define STEP_NEXT()         do { s_step++; STEP_ARM(); } while (0)

static void fsm_goto(uint8_t next)
{
    state  = next;
    s_step = 0U;
    STEP_ARM();
}

/* -------------------------------------------------------------------------- */
/* 内部: 驱动底盘走一段 (占位: 整段用闪烁灯表示), 返回 1 表示动作做完          */
/* -------------------------------------------------------------------------- */
#define DRIVE_FORWARD   1U
#define DRIVE_BACKWARD  2U
#define DRIVE_LEFT      3U
#define DRIVE_RIGHT     4U

static uint8_t fsm_drive(uint8_t dir, uint32_t ms)
{
    switch (s_step) {
    case 0U:
        switch (dir) {
        case DRIVE_FORWARD:  Motion_Forward();   dbg_printf("[MOTOR] 前进\r\n"); break;
        case DRIVE_BACKWARD: Motion_Backward();  dbg_printf("[MOTOR] 后退\r\n"); break;
        case DRIVE_LEFT:     Motion_TurnLeft();  dbg_printf("[MOTOR] 左转\r\n"); break;
        case DRIVE_RIGHT:    Motion_TurnRight(); dbg_printf("[MOTOR] 右转\r\n"); break;
        default:             Motion_Stop();      break;
        }
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(ms)) {
            Motion_Stop();                 /* 停止: 三色 LED 全灭 */
            STEP_NEXT();
        }
        break;

    case 2U:
        if (STEP_ELAPSED(ACTION_GAP_MS)) {
            s_step = 0U;
            return 1U;                     /* 动作完成 */
        }
        break;

    default:
        s_step = 0U;
        break;
    }
    return 0U;
}

/* -------------------------------------------------------------------------- */
/* 内部: 一次完整的"识别"环节 (S3 / S6 / S9 共用)                              */
/*   mode_cmd   : 进入时要发的模式命令 (0 = 不发, 保持当前模式)                 */
/*   expect_cmd : 期望的 cmd (0x01 颜色 / 0x02 形状)                            */
/*   expect_id  : 期望的编号 (来自二维码)                                       */
/* -------------------------------------------------------------------------- */
typedef enum {
    DETECT_BUSY = 0,
    DETECT_OK,
    DETECT_FAIL
} Detect_e;

static void maix_request_once(void)
{
    Maix_SendReqDetect();                          /* 发 0x12 请求识别一次 */
    LED_SetEffect(LED_FX_BLINK_G, LED_BLINK_MS);   /* 绿灯慢闪 = 等上报 */
}

static Detect_e fsm_detect(uint8_t mode_cmd, uint8_t expect_cmd, uint8_t expect_id)
{
    switch (s_step) {

    case 0U:
        /* 1. 设置识别模式 (设置一次就记住) */
        if (mode_cmd != 0U) {
            Maix_SendCmd(mode_cmd, NULL, 0U);
        }
        g_vision_ready = 0U;
        s_retry = 0U;
        retry_count = 0U;
        /* 2. 机械臂移到识别位 (占位: 蓝灯常亮 500ms) */
        Arm_MoveToDetectPose();
        LED_SetEffect(LED_FX_SOLID_B, 0U);
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(ARM_MOVE_MS)) {
            LED_SetEffect(LED_FX_OFF, 0U);         /* 3. 全灭 200ms 等画面稳定 */
            STEP_NEXT();
        }
        break;

    case 2U:
        if (STEP_ELAPSED(ARM_SETTLE_MS)) {
            maix_request_once();                   /* 4. 发 0x12 */
            STEP_NEXT();
        }
        break;

    case 3U:
        /* 5. 等 MaixCAM 上报 (超时 VISION_TIMEOUT_MS) */
        if (g_vision_ready != 0U) {
            uint8_t ok;

            g_vision_ready = 0U;

            ok = (uint8_t)((g_vision.cmd == expect_cmd) &&
                           (g_vision.valid != 0U) &&
                           (g_vision.id == expect_id) &&
                           (Vision_IsInValidRange(g_vision.x, g_vision.y,
                                                  g_vision.w, g_vision.h) != 0U));

            dbg_printf("[VIS] cmd=0x%02X id=%d x=%d y=%d w=%d h=%d %s\r\n",
                       g_vision.cmd, g_vision.id, g_vision.x, g_vision.y,
                       g_vision.w, g_vision.h, (ok != 0U) ? "OK" : "NG");

            if (ok != 0U) {
                g_target = g_vision;               /* 判断通过, 存目标 */
                LED_SetEffect(LED_FX_OFF, 0U);
                s_step = 0U;
                return DETECT_OK;
            }
        } else if (!STEP_ELAPSED(VISION_TIMEOUT_MS)) {
            break;                                 /* 还没超时, 继续等 */
        }

        /* 走到这里 = 数据不匹配 / 空帧 / 超时 -> 原地重试 */
        s_retry++;
        retry_count = s_retry;
        if (s_retry >= VISION_RETRY_MAX) {
            dbg_printf("[VIS] 重试 %d 次失败, 跳过本任务\r\n", (int)s_retry);
            LED_SetEffect(LED_FX_OFF, 0U);
            s_step = 0U;
            return DETECT_FAIL;
        }
        dbg_printf("[VIS] 重试第 %d 次\r\n", (int)s_retry);
        maix_request_once();                       /* 原地重发 0x12 */
        STEP_ARM();
        break;

    default:
        s_step = 0U;
        break;
    }

    return DETECT_BUSY;
}

/* -------------------------------------------------------------------------- */
/* S0 初始化                                                                   */
/* -------------------------------------------------------------------------- */
static void FSM_S0(void)
{
    dbg_printf("\r\n===== S0 初始化 (第 %d 轮) =====\r\n", (int)(s_cycle + 1U));

    /* 重新初始化所有外设状态 */
    Vision_Init();
    g_vision_ready = 0U;
    MaixLink_Flush();                 /* 清空 USART2 接收缓冲 */
    GM65_Reset();
    s_retry = 0U;
    retry_count = 0U;

    /* 执行机构复位 */
    Motion_Stop();                    /* 停止编码电机 */
    Laser_Off();                      /* 关闭激光 */
    LED_SetEffect(LED_FX_OFF, 0U);    /* 熄灭三色 LED */
    Arm_Home();                       /* 机械臂回初始位置 */
    Heartbeat_SetBlink();             /* 心跳灯重新闪烁 */

    fsm_goto(S1_READ_QR);
}

/* -------------------------------------------------------------------------- */
/* S1 读二维码                                                                 */
/* -------------------------------------------------------------------------- */
static void FSM_S1(void)
{
    if (qr_done != QR_DONE_NONE) {
        dbg_printf("[S1] 二维码 %d%d%d -> 排爆:%s 靶:%s 人质:%s\r\n",
                   qr_bomb_color, qr_target_color, qr_rescue_shape,
                   Vision_ColorName(qr_bomb_color),
                   Vision_ColorName(qr_target_color),
                   Vision_ShapeName(qr_rescue_shape));
        fsm_goto(S2_TO_BOMB);
        return;
    }

    if (STEP_ELAPSED(QR_TIMEOUT_MS)) {          /* 读不到码 -> 用占位值继续 */
        GM65_LoadPlaceholder();
        dbg_printf("[S1] 读码超时 %dms, 使用占位值 %d%d%d\r\n",
                   (int)QR_TIMEOUT_MS, qr_bomb_color, qr_target_color, qr_rescue_shape);
        fsm_goto(S2_TO_BOMB);
    }
}

/* -------------------------------------------------------------------------- */
/* S2 前往排爆区                                                               */
/* -------------------------------------------------------------------------- */
static void FSM_S2(void)
{
    if (fsm_drive(DRIVE_FORWARD, MOTION_MS) != 0U) {
        fsm_goto(S3_DETECT_BOMB);
    }
}

/* -------------------------------------------------------------------------- */
/* S3 排爆区识别 (颜色模式, 找二维码指定的排爆物颜色)                          */
/* -------------------------------------------------------------------------- */
static void FSM_S3(void)
{
    switch (fsm_detect(MAIX_CMD_SET_MODE_COLOR, MAIX_CMD_REPORT_COLOR, qr_bomb_color)) {
    case DETECT_OK:
        dbg_printf("[S3] 找到排爆物: %s\r\n", Vision_ColorName(g_target.id));
        fsm_goto(S4_GRAB_BOMB);
        break;
    case DETECT_FAIL:
        dbg_printf("[S3] 跳过排爆, 直接去反恐区\r\n");
        fsm_goto(S5_TO_ANTI_TERROR);       /* 3 次都失败 -> 跳过排爆 */
        break;
    default:
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S4 排爆区抓取 + 放入排爆桶                                                  */
/* -------------------------------------------------------------------------- */
static void FSM_S4(void)
{
    switch (s_step) {
    case 0U:
        Arm_Grab();
        LED_SolidById(g_target.id);              /* 抓取: 对应颜色灯常亮 */
        dbg_printf("[S4] 抓取 %s 排爆物\r\n", Vision_ColorName(g_target.id));
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(ARM_GRAB_MS)) {
            Arm_Place();
            LED_SolidById(g_target.id);          /* 放入排爆桶 */
            dbg_printf("[S4] 放入排爆桶\r\n");
            STEP_NEXT();
        }
        break;

    case 2U:
        if (STEP_ELAPSED(ARM_GRAB_MS)) {
            LED_SetEffect(LED_FX_OFF, 0U);
            g_target.valid = 0U;
            STEP_NEXT();
        }
        break;

    case 3U:
        if (STEP_ELAPSED(ACTION_GAP_MS)) {
            fsm_goto(S5_TO_ANTI_TERROR);
        }
        break;

    default:
        s_step = 0U;
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S5 前往反恐区                                                               */
/* -------------------------------------------------------------------------- */
static void FSM_S5(void)
{
    if (fsm_drive(DRIVE_FORWARD, MOTION_MS) != 0U) {
        fsm_goto(S6_DETECT_TARGET);
    }
}

/* -------------------------------------------------------------------------- */
/* S6 反恐区识别 (保持颜色模式, 找二维码指定的靶标颜色)                         */
/* -------------------------------------------------------------------------- */
static void FSM_S6(void)
{
    switch (fsm_detect(0U, MAIX_CMD_REPORT_COLOR, qr_target_color)) {  /* 0 = 不重发模式命令 */
    case DETECT_OK:
        dbg_printf("[S6] 找到靶标: %s\r\n", Vision_ColorName(g_target.id));
        fsm_goto(S7_SHOOT_TARGET);
        break;
    case DETECT_FAIL:
        dbg_printf("[S6] 跳过打靶, 直接去救援区\r\n");
        fsm_goto(S8_TO_RESCUE);
        break;
    default:
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S7 反恐区打靶 (激光照射 1s)                                                 */
/* -------------------------------------------------------------------------- */
static void FSM_S7(void)
{
    switch (s_step) {
    case 0U:
        Laser_On();
        LED_SetEffect(LED_FX_BLINK_R, LED_BLINK_MS);   /* 激光开: 红灯闪 */
        dbg_printf("[S7] 激光开启, 瞄准 %s 靶心\r\n", Vision_ColorName(g_target.id));
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(LASER_ON_MS)) {
            Laser_Off();
            LED_SetEffect(LED_FX_OFF, 0U);             /* 激光关: 熄灭 */
            dbg_printf("[S7] 激光关闭\r\n");
            STEP_NEXT();
        }
        break;

    case 2U:
        if (STEP_ELAPSED(ACTION_GAP_MS)) {
            g_target.valid = 0U;
            fsm_goto(S8_TO_RESCUE);
        }
        break;

    default:
        s_step = 0U;
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S8 前往救援区                                                               */
/* -------------------------------------------------------------------------- */
static void FSM_S8(void)
{
    if (fsm_drive(DRIVE_FORWARD, MOTION_MS) != 0U) {
        fsm_goto(S9_DETECT_HOSTAGE);
    }
}

/* -------------------------------------------------------------------------- */
/* S9 救援区识别 (形状模式, 找二维码指定的人质形状)                            */
/* -------------------------------------------------------------------------- */
static void FSM_S9(void)
{
    switch (fsm_detect(MAIX_CMD_SET_MODE_SHAPE, MAIX_CMD_REPORT_SHAPE, qr_rescue_shape)) {
    case DETECT_OK:
        dbg_printf("[S9] 找到人质: %s\r\n", Vision_ShapeName(g_target.id));
        fsm_goto(S10_GRAB_HOSTAGE);
        break;
    case DETECT_FAIL:
        dbg_printf("[S9] 跳过救援, 直接返回\r\n");
        fsm_goto(S11_BACK_HOME);
        break;
    default:
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S10 救援区抓取人质                                                          */
/* -------------------------------------------------------------------------- */
static void FSM_S10(void)
{
    switch (s_step) {
    case 0U:
        Arm_Grab();
        LED_SolidById(g_target.id);              /* 圆柱->红, 圆锥->绿, 腰鼓->蓝 */
        dbg_printf("[S10] 抓取人质: %s\r\n", Vision_ShapeName(g_target.id));
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(ARM_GRAB_MS)) {
            LED_SetEffect(LED_FX_OFF, 0U);
            STEP_NEXT();
        }
        break;

    case 2U:
        if (STEP_ELAPSED(ACTION_GAP_MS)) {
            fsm_goto(S11_BACK_HOME);
        }
        break;

    default:
        s_step = 0U;
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S11 返回返回区并放置人质                                                    */
/* -------------------------------------------------------------------------- */
static void FSM_S11(void)
{
    switch (s_step) {
    case 0U:
        if (fsm_drive(DRIVE_FORWARD, MOTION_MS) != 0U) {
            s_step = 3U;                             /* 跳过 drive 的子步骤 */
            STEP_ARM();
        }
        break;

    case 3U:
        Arm_Place();
        if (g_target.valid != 0U) {
            LED_SolidById(g_target.id);
        }
        dbg_printf("[S11] 把人质放到返回区\r\n");
        STEP_NEXT();
        break;

    case 4U:
        if (STEP_ELAPSED(ARM_GRAB_MS)) {
            LED_SetEffect(LED_FX_OFF, 0U);
            g_target.valid = 0U;
            STEP_NEXT();
        }
        break;

    case 5U:
        if (STEP_ELAPSED(ACTION_GAP_MS)) {
            fsm_goto(S12_FINISH);
        }
        break;

    default:
        s_step = 0U;
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* S12 任务完成                                                                */
/* -------------------------------------------------------------------------- */
static void FSM_S12(void)
{
    switch (s_step) {
    case 0U:
        Motion_Stop();
        Laser_Off();
        LED_SetEffect(LED_FX_OFF, 0U);
        Heartbeat_SetSolid();                        /* 心跳灯常亮 */
        dbg_printf("[S12] 任务完成, 停留 %dms 后重新开始\r\n", (int)FINISH_HOLD_MS);
        STEP_NEXT();
        break;

    case 1U:
        if (STEP_ELAPSED(FINISH_HOLD_MS)) {
            s_cycle++;
            fsm_goto(S0_INIT);                       /* 跳回 S0, 循环运行 */
        }
        break;

    default:
        s_step = 0U;
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* 对外接口                                                                    */
/* -------------------------------------------------------------------------- */
void FSM_Init(void)
{
    state  = S0_INIT;
    s_step = 0U;
    s_t    = HAL_GetTick();
    s_retry = 0U;
    s_cycle = 0U;
}

void FSM_Run(void)
{
    switch (state) {
    case S0_INIT:          FSM_S0();  break;
    case S1_READ_QR:       FSM_S1();  break;
    case S2_TO_BOMB:       FSM_S2();  break;
    case S3_DETECT_BOMB:   FSM_S3();  break;
    case S4_GRAB_BOMB:     FSM_S4();  break;
    case S5_TO_ANTI_TERROR:FSM_S5();  break;
    case S6_DETECT_TARGET: FSM_S6();  break;
    case S7_SHOOT_TARGET:  FSM_S7();  break;
    case S8_TO_RESCUE:     FSM_S8();  break;
    case S9_DETECT_HOSTAGE:FSM_S9();  break;
    case S10_GRAB_HOSTAGE: FSM_S10(); break;
    case S11_BACK_HOME:    FSM_S11(); break;
    case S12_FINISH:       FSM_S12(); break;
    default:
        fsm_goto(S0_INIT);
        break;
    }
}

const char *FSM_StateName(uint8_t s)
{
    switch (s) {
    case S0_INIT:           return "S0 初始化";
    case S1_READ_QR:        return "S1 读二维码";
    case S2_TO_BOMB:        return "S2 前往排爆区";
    case S3_DETECT_BOMB:    return "S3 排爆区识别";
    case S4_GRAB_BOMB:      return "S4 排爆区抓取";
    case S5_TO_ANTI_TERROR: return "S5 前往反恐区";
    case S6_DETECT_TARGET:  return "S6 反恐区识别";
    case S7_SHOOT_TARGET:   return "S7 反恐区打靶";
    case S8_TO_RESCUE:      return "S8 前往救援区";
    case S9_DETECT_HOSTAGE: return "S9 救援区识别";
    case S10_GRAB_HOSTAGE:  return "S10 救援区抓取";
    case S11_BACK_HOME:     return "S11 返回返回区";
    case S12_FINISH:        return "S12 任务完成";
    default:                return "未知状态";
    }
}
