/**
  ******************************************************************************
  * @file    motion.h
  * @brief   底盘运动 (4 个编码电机) —— 当前为占位实现, 只用 LED 表示动作
  *
  *  真实驱动接进来后, 只要把 motion.c 里每个函数体换成"设置 PWM + 方向脚"
  *  即可, 上层状态机完全不用改。
  ******************************************************************************
  */
#ifndef __MOTION_H__
#define __MOTION_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

void Motion_Init(void);
void Motion_Update(void);         /* 预留: 真实实现里用来做闭环/斜坡 */

void Motion_Forward(void);        /* 前进 (占位: 红+绿一起闪) */
void Motion_Backward(void);       /* 后退 (占位: 绿+蓝一起闪) */
void Motion_TurnLeft(void);       /* 左转 (占位: 红+蓝一起闪) */
void Motion_TurnRight(void);      /* 右转 (占位: 红+绿+蓝一起闪) */
void Motion_Stop(void);           /* 停止 (占位: 全灭) */

/* --- 真实硬件预留接口 (TODO) --- */
/** 设置单个轮子: idx 0~3, dir 0=停 1=正转 2=反转, pwm -1000~1000 */
void Motion_SetWheel(uint8_t idx, uint8_t dir, int16_t pwm);
/** 读编码器累计计数 (预留) */
int32_t Motion_GetEncoder(uint8_t idx);

extern volatile uint8_t g_motion_state;   /* 0 停 1 前进 2 后退 3 左转 4 右转 */

#ifdef __cplusplus
}
#endif

#endif /* __MOTION_H__ */
