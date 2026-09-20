/**
  ******************************************************************************
  * @file    bsp_led.h
  * @brief   三色 LED (PC10红/PC11绿/PC12蓝) + 心跳灯 (PB0)
  *
  *  占位方案用 LED 来表示"机械臂/电机/激光"的动作, 全部非阻塞:
  *  调用 LED_SetEffect() 之后, 主循环里每轮调 LED_Update() 即可。
  ******************************************************************************
  */
#ifndef __BSP_LED_H__
#define __BSP_LED_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* 灯效 */
typedef enum {
    LED_FX_OFF = 0,      /* 全灭 */
    LED_FX_SOLID_R,      /* 红灯常亮 (抓红色 / 圆柱形) */
    LED_FX_SOLID_G,      /* 绿灯常亮 (抓绿色 / 圆锥形) */
    LED_FX_SOLID_B,      /* 蓝灯常亮 (抓蓝色 / 腰鼓形) */
    LED_FX_BLINK_R,      /* 红灯闪  = 激光开 */
    LED_FX_BLINK_RG,     /* 红+绿闪 = 电机前进 */
    LED_FX_BLINK_GB,     /* 绿+蓝闪 = 电机后退 */
    LED_FX_BLINK_RB,     /* 红+蓝闪 = 左转 */
    LED_FX_BLINK_RGB,    /* 红+绿+蓝闪 = 右转 */
    LED_FX_BLINK_G       /* 绿灯慢闪 = 等待 MaixCAM 上报 */
} LedEffect_t;

void LED_Init(void);
void LED_Update(void);                       /* 主循环每轮调用 */

void LED_AllOff(void);
void LED_Set(uint8_t r, uint8_t g, uint8_t b);
void LED_SetEffect(LedEffect_t fx, uint32_t period_ms);
/** 按编号亮常亮灯: 1=红, 2=绿, 3=蓝, 其它=全灭 */
void LED_SolidById(uint8_t id);

/* --- 心跳灯 --- */
void Heartbeat_Init(void);
void Heartbeat_Toggle(void);                  /* 主循环每轮调用, 内部按 500ms 计时 */
void Heartbeat_SetBlink(void);                /* 正常运行: 500ms 翻转 */
void Heartbeat_SetSolid(void);                /* 任务完成: 常亮 */

#ifdef __cplusplus
}
#endif

#endif /* __BSP_LED_H__ */
