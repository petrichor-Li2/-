/**
  ******************************************************************************
  * @file    maix_link.h
  * @brief   STM32 <-> MaixCAM 链路 (USART2, 115200 8N1, RX = DMA循环 + 空闲中断)
  ******************************************************************************
  */
#ifndef __MAIX_LINK_H__
#define __MAIX_LINK_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* 初始化: 启动 DMA 接收 + 打开空闲中断 + 清空环形缓冲 */
void MaixLink_Init(void);

/* 主循环里调用: 把环形缓冲里的字节喂给协议解析器, 解析出帧后交给 Vision_OnFrame */
void MaixLink_Process(void);

/* 在 USART2 空闲中断里调用 (IRQ 上下文) */
void MaixLink_OnIdleIrq(void);

/* 重新启动接收 (DMA 出错后恢复用) */
void MaixLink_StartRx(void);

/* 清空环形缓冲 + 重置协议解析器 (S0 初始化时调用) */
void MaixLink_Flush(void);

/* DMA 错误回调里调用 */
void MaixLink_OnError(void);

/* DMA 半满/全满回调 + 空闲中断共用的事件: 把新到的字节搬进环形缓冲
 * (空闲中断和 DMA 完成中断都要调用, 否则长时间连续数据会丢) */
void MaixLink_OnDmaEvent(void);

/* -------------------------------------------------------------------------- */
/* 发送接口                                                                    */
/* -------------------------------------------------------------------------- */
/** 发送 0x10: 设为颜色模式 */
void Maix_SendModeColor(void);
/** 发送 0x11: 设为形状模式 */
void Maix_SendModeShape(void);
/** 发送 0x12: 请求识别一次 */
void Maix_SendReqDetect(void);
/** 通用发送 */
void Maix_SendCmd(uint8_t cmd, const uint8_t *body, uint8_t body_len);

/* 统计 */
extern volatile uint32_t g_maix_tx_frames;
extern volatile uint32_t g_maix_rx_frames;
extern volatile uint32_t g_maix_crc_err;
extern volatile uint32_t g_maix_overflow;

#ifdef __cplusplus
}
#endif

#endif /* __MAIX_LINK_H__ */
