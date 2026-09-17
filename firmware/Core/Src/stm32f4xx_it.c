/**
  ******************************************************************************
  * @file    stm32f4xx_it.c
  * @brief   中断服务函数
  ******************************************************************************
  */
#include "main.h"
#include "stm32f4xx_it.h"
#include "maix_link.h"

/* -------------------------------------------------------------------------- */
/* Cortex-M4 内核异常                                                          */
/* -------------------------------------------------------------------------- */
void NMI_Handler(void)
{
    while (1) {
    }
}

void HardFault_Handler(void)
{
    /* 出错就停在这里, 方便用调试器看调用栈 */
    while (1) {
    }
}

void MemManage_Handler(void)
{
    while (1) {
    }
}

void BusFault_Handler(void)
{
    while (1) {
    }
}

void UsageFault_Handler(void)
{
    while (1) {
    }
}

void SVC_Handler(void)
{
}

void DebugMon_Handler(void)
{
}

void PendSV_Handler(void)
{
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

/* -------------------------------------------------------------------------- */
/* USART1: GM65 二维码, 逐字节接收中断                                          */
/* -------------------------------------------------------------------------- */
void USART1_IRQHandler(void)
{
    HAL_UART_IRQHandler(&huart1);
}

/* -------------------------------------------------------------------------- */
/* USART2: MaixCAM                                                             */
/*   空闲中断 -> 把 DMA 缓冲里新到的数据搬进环形缓冲                            */
/* -------------------------------------------------------------------------- */
void USART2_IRQHandler(void)
{
    if (__HAL_UART_GET_FLAG(&huart2, UART_FLAG_IDLE) != RESET) {
        __HAL_UART_CLEAR_IDLEFLAG(&huart2);      /* 先清标志, 再处理 */
        MaixLink_OnIdleIrq();
    }

    HAL_UART_IRQHandler(&huart2);
}

/* -------------------------------------------------------------------------- */
/* DMA1_Stream5: USART2_RX                                                     */
/* -------------------------------------------------------------------------- */
void DMA1_Stream5_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&hdma_usart2_rx);
}
