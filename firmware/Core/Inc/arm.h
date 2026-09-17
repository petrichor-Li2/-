/**
  ******************************************************************************
  * @file    arm.h
  * @brief   机械臂 —— 当前为占位实现 (只亮灯), 真实舵机驱动接进来后替换函数体
  ******************************************************************************
  */
#ifndef __ARM_H__
#define __ARM_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

void Arm_Init(void);          /* 复位到初始位置 */
void Arm_Update(void);        /* 预留: 真实实现里做轨迹插补 */

void Arm_MoveToDetectPose(void);  /* 移到识别位 (占位: 蓝灯常亮 500ms) */
void Arm_MoveToTargetPose(void);  /* 移到抓取位 */
void Arm_Grab(void);              /* 夹爪闭合 */
void Arm_Release(void);           /* 夹爪张开 */
void Arm_Place(void);             /* 把物体放到桶里/返回区 */
void Arm_Home(void);              /* 回原点 */
uint8_t Arm_IsBusy(void);         /* 占位: 动作是否还在进行 */

/* 真实硬件预留 (TODO): 总线舵机角度控制 */
void Arm_SetJoint(uint8_t joint, uint16_t angle_deg);

#ifdef __cplusplus
}
#endif

#endif /* __ARM_H__ */
