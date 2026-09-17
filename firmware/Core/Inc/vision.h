/**
  ******************************************************************************
  * @file    vision.h
  * @brief   视觉结果的存放与判断 (STM32 端负责匹配 + 范围判断)
  ******************************************************************************
  */
#ifndef __VISION_H__
#define __VISION_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* 一帧视觉结果 */
typedef struct {
    uint8_t  cmd;     /* 0x01 颜色 / 0x02 形状 */
    uint8_t  id;      /* 颜色编号 (1红2绿3蓝) 或 形状编号 (1圆柱2圆锥3腰鼓) */
    uint16_t x;
    uint16_t y;
    uint16_t w;
    uint16_t h;
    uint8_t  valid;   /* 数据是否有效: 1 有效 */
} VisionResult;

/* -------------------------------------------------------------------------- */
/* 全局变量 (与设计文档一致)                                                   */
/* -------------------------------------------------------------------------- */
extern VisionResult g_vision;        /* MaixCAM 上报的原始数据 */
extern volatile uint8_t g_vision_ready; /* 视觉数据就绪标志 (主循环处理完清 0) */
extern VisionResult g_target;        /* S3/S6/S9 判断通过后的目标 */

/* -------------------------------------------------------------------------- */
/* 接口                                                                        */
/* -------------------------------------------------------------------------- */
void Vision_Init(void);

/**
  * @brief  解析一条完整视觉帧, 写入 g_vision 并置 g_vision_ready
  * @param  cmd       0x01 / 0x02 / 0x00
  * @param  body      正文
  * @param  body_len  正文长度
  */
void Vision_OnFrame(uint8_t cmd, const uint8_t *body, uint8_t body_len);

/**
  * @brief  判断目标中心点是否在有效范围内
  * @retval 1 = 在范围内
  */
uint8_t Vision_IsInValidRange(uint16_t x, uint16_t y, uint16_t w, uint16_t h);

/** 目标中心 X / Y */
uint16_t Vision_CenterX(const VisionResult *v);
uint16_t Vision_CenterY(const VisionResult *v);

/** 编号 -> 中文名 (调试打印用) */
const char *Vision_ColorName(uint8_t id);
const char *Vision_ShapeName(uint8_t id);

#ifdef __cplusplus
}
#endif

#endif /* __VISION_H__ */
