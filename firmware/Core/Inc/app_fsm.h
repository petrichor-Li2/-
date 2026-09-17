/**
  ******************************************************************************
  * @file    app_fsm.h
  * @brief   主状态机 S0 ~ S12
  ******************************************************************************
  */
#ifndef __APP_FSM_H__
#define __APP_FSM_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* 状态编号 */
typedef enum {
    S0_INIT = 0,          /* 初始化 */
    S1_READ_QR,           /* 读二维码 */
    S2_TO_BOMB,           /* 前往排爆区 */
    S3_DETECT_BOMB,       /* 排爆区识别 */
    S4_GRAB_BOMB,         /* 排爆区抓取 */
    S5_TO_ANTI_TERROR,    /* 前往反恐区 */
    S6_DETECT_TARGET,     /* 反恐区识别 */
    S7_SHOOT_TARGET,      /* 反恐区打靶 */
    S8_TO_RESCUE,         /* 前往救援区 */
    S9_DETECT_HOSTAGE,    /* 救援区识别 */
    S10_GRAB_HOSTAGE,     /* 救援区抓取 */
    S11_BACK_HOME,        /* 返回返回区 */
    S12_FINISH,           /* 任务完成 */
    S_COUNT
} AppState_t;

extern volatile uint8_t state;        /* 当前状态 (与设计文档一致) */
extern uint8_t retry_count;           /* 视觉重试计数 */

void FSM_Init(void);                  /* 上电调用一次 */
void FSM_Run(void);                   /* 主循环里每轮调用一次 (非阻塞) */
const char *FSM_StateName(uint8_t s);

#ifdef __cplusplus
}
#endif

#endif /* __APP_FSM_H__ */
