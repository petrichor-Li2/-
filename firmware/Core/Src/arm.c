/**
  ******************************************************************************
  * @file    arm.c
  * @brief   机械臂 —— 占位实现 (只亮灯)
  *
  *  ⚠ 接真实机械臂 (总线舵机 / 串口舵机 / 步进) 时, 改 Arm_SetJoint() 和各动作
  *     函数体即可, 状态机一行都不用改。
  ******************************************************************************
  */
#include "arm.h"
#include "app_config.h"
#include "main.h"

/* 占位用的"动作计时" —— 真实实现里改成读舵机到位状态 */
static uint32_t s_cmd_tick = 0U;
static uint8_t  s_busy     = 0U;

void Arm_SetJoint(uint8_t joint, uint16_t angle_deg)
{
    /* TODO: 接真实舵机
     *   · 总线舵机: 往舵机串口发指令帧 (SERVO_ID, 角度, 时间)
     *   · PWM 舵机: __HAL_TIM_SET_COMPARE(&htim_servo, ch, pulse_us);
     */
    (void)joint; (void)angle_deg;
}

uint8_t Arm_IsBusy(void)
{
    return s_busy;
}

void Arm_Init(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 0U;
    Arm_Home();
}

void Arm_Update(void)
{
    if ((s_busy != 0U) && ((HAL_GetTick() - s_cmd_tick) >= ARM_MOVE_MS)) {
        s_busy = 0U;   /* 占位: 时间到了就算到位 */
    }
}

void Arm_MoveToDetectPose(void)
{
    /* 占位: 蓝灯常亮 (由状态机负责亮灯时长), 这里只记录动作 */
    s_cmd_tick = HAL_GetTick();
    s_busy = 1U;
}

void Arm_MoveToTargetPose(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 1U;
}

void Arm_Grab(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 1U;
}

void Arm_Release(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 1U;
}

void Arm_Place(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 1U;
}

void Arm_Home(void)
{
    s_cmd_tick = HAL_GetTick();
    s_busy = 0U;
}
