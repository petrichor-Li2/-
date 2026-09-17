/**
  ******************************************************************************
  * @file    motion.c
  * @brief   底盘运动 —— 占位实现 (只用 LED 表示动作)
  *
  *  ⚠ 接真实驱动时, 只需要改 motion_apply() 里的内容:
  *     · 4 个编码电机: TIMx PWM (20kHz) + 方向 GPIO
  *     · 编码器: TIMx 编码器模式读计数, 做速度闭环
  ******************************************************************************
  */
#include "motion.h"
#include "bsp_led.h"
#include "app_config.h"
#include "main.h"

volatile uint8_t g_motion_state = 0U;   /* 0停 1前进 2后退 3左转 4右转 */

#define MOTION_STOP     0U
#define MOTION_FORWARD  1U
#define MOTION_BACKWARD 2U
#define MOTION_LEFT     3U
#define MOTION_RIGHT    4U

/* -------------------------------------------------------------------------- */
/* 真实硬件挂载点                                                              */
/* -------------------------------------------------------------------------- */
void Motion_SetWheel(uint8_t idx, uint8_t dir, int16_t pwm)
{
    /* TODO: 接真实驱动
     *   idx 0~3 分别对应 左前/右前/左后/右后
     *   1) 设置方向脚 (GPIO 高/低)
     *   2) 设置 PWM 占空比: __HAL_TIM_SET_COMPARE(&htimx, TIM_CHANNEL_x, duty);
     */
    (void)idx; (void)dir; (void)pwm;
}

int32_t Motion_GetEncoder(uint8_t idx)
{
    /* TODO: return (int32_t)__HAL_TIM_GET_COUNTER(&htim_encoder[idx]); */
    (void)idx;
    return 0;
}

/* 把"运动状态"变成"灯效" —— 这就是当前的占位输出 */
static void motion_apply(uint8_t st)
{
    switch (st) {
    case MOTION_FORWARD:  LED_SetEffect(LED_FX_BLINK_RG,  LED_BLINK_MS); break;
    case MOTION_BACKWARD: LED_SetEffect(LED_FX_BLINK_GB,  LED_BLINK_MS); break;
    case MOTION_LEFT:     LED_SetEffect(LED_FX_BLINK_RB,  LED_BLINK_MS); break;
    case MOTION_RIGHT:    LED_SetEffect(LED_FX_BLINK_RGB, LED_BLINK_MS); break;
    case MOTION_STOP:
    default:              LED_SetEffect(LED_FX_OFF, LED_BLINK_MS);       break;
    }
}

/* -------------------------------------------------------------------------- */
void Motion_Init(void)
{
    g_motion_state = MOTION_STOP;
    Motion_Stop();
}

void Motion_Update(void)
{
    /* 真实实现: 速度闭环 / 加减速斜坡
     * 占位实现: 什么都不用做, LED 由 LED_Update() 自己刷新 */
}

void Motion_Forward(void)
{
    g_motion_state = MOTION_FORWARD;
    motion_apply(MOTION_FORWARD);
}

void Motion_Backward(void)
{
    g_motion_state = MOTION_BACKWARD;
    motion_apply(MOTION_BACKWARD);
}

void Motion_TurnLeft(void)
{
    g_motion_state = MOTION_LEFT;
    motion_apply(MOTION_LEFT);
}

void Motion_TurnRight(void)
{
    g_motion_state = MOTION_RIGHT;
    motion_apply(MOTION_RIGHT);
}

void Motion_Stop(void)
{
    g_motion_state = MOTION_STOP;
    motion_apply(MOTION_STOP);
}
