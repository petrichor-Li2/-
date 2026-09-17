/**
  ******************************************************************************
  * @file    stm32f4xx_it.h
  * @brief   中断服务函数声明
  ******************************************************************************
  */
#ifndef __STM32F4xx_IT_H
#define __STM32F4xx_IT_H

#ifdef __cplusplus
extern "C" {
#endif

void NMI_Handler(void);
void HardFault_Handler(void);
void MemManage_Handler(void);
void BusFault_Handler(void);
void UsageFault_Handler(void);
void SVC_Handler(void);
void DebugMon_Handler(void);
void PendSV_Handler(void);
void SysTick_Handler(void);

/* 本工程用到 */
void USART1_IRQHandler(void);        /* GM65 二维码, 逐字节中断 */
void USART2_IRQHandler(void);        /* MaixCAM, DMA + 空闲中断 */
void DMA1_Stream5_IRQHandler(void);  /* USART2_RX DMA */

#ifdef __cplusplus
}
#endif

#endif /* __STM32F4xx_IT_H */
