/**
  ******************************************************************************
  * @file    gm65.h
  * @brief   GM65 二维码扫码模块 (USART1, 9600 8N1, 逐字节中断 + \r\n 结束)
  *
  *  GM65 扫到码后会主动把字符串吐出来 (默认以 CR/LF 结尾), STM32 只管收。
  *  协议: 三位数字, 例如 "213"
  *        第1位 排爆物颜色 (1红 2绿 3蓝)
  *        第2位 反恐靶颜色 (1红 2绿 3蓝)
  *        第3位 救援目标形状 (1圆柱 2圆锥 3腰鼓)
  ******************************************************************************
  */
#ifndef __GM65_H__
#define __GM65_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* 全局变量 (与设计文档一致) */
extern uint8_t qr_bomb_color;    /* 排爆物颜色 */
extern uint8_t qr_target_color;  /* 反恐靶颜色 */
extern uint8_t qr_rescue_shape;  /* 救援目标形状 */
extern uint8_t qr_done;          /* 二维码已读标志: 0 未读 / 1 真码 / 2 占位值 */

/* 初始化: 打开 USART1 逐字节接收中断 */
void GM65_Init(void);

/* 主循环里调用: 如果收到一整行就去解析 */
void GM65_Process(void);

/* 在 USART1 中断里调用 (IRQ 上下文) */
void GM65_OnRxByte(uint8_t byte);

/* 有新的一行待解析 (调试用) */
uint8_t GM65_HasLine(void);

/* 把二维码字符串解析成三个目标 (内部使用, 也方便单元测试) */
uint8_t GM65_ParseString(const char *s,
                         uint8_t *bomb_color,
                         uint8_t *target_color,
                         uint8_t *rescue_shape);

/* 载入占位值 (读码失败时用) */
void GM65_LoadPlaceholder(void);

/* 清空接收状态 (S0 初始化时调用) */
void GM65_Reset(void);

#ifdef __cplusplus
}
#endif

#endif /* __GM65_H__ */
