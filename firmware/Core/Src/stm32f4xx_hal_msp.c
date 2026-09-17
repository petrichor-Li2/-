/**
  ******************************************************************************
  * @file    stm32f4xx_hal_msp.c
  * @brief   HAL 底层初始化 (时钟使能 / GPIO 复用 / DMA / NVIC)
  ******************************************************************************
  */
#include "main.h"

/* -------------------------------------------------------------------------- */
void HAL_MspInit(void)
{
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    __HAL_RCC_PWR_CLK_ENABLE();

    /* 注意: 若要使用 PB3 / PB4 / PA15 (JTAG 引脚), 需要在这里关掉 JTAG-DP:
     *   __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_GPIOB_CLK_ENABLE();
     *   GPIO_InitStruct.Pin  = GPIO_PIN_15 | GPIO_PIN_3 | GPIO_PIN_4;
     *   GPIO_InitStruct.Mode = GPIO_MODE_AF_PP; ...  (保留 SWD: PA13/PA14)
     * 本工程只用 PB0, 不需要。 */
}

/* -------------------------------------------------------------------------- */
/* USART1: PA9 = TX, PA10 = RX   (GM65)                                        */
/* USART2: PA2 = TX, PA3 = RX   (MaixCAM, RX 走 DMA)                           */
/* -------------------------------------------------------------------------- */
void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (huart->Instance == USART1) {
        __HAL_RCC_USART1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        GPIO_InitStruct.Pin       = GPIO_PIN_9 | GPIO_PIN_10;
        GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Pull      = GPIO_PULLUP;
        GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
        GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

        /* 逐字节接收中断 */
        HAL_NVIC_SetPriority(USART1_IRQn, 1U, 0U);
        HAL_NVIC_EnableIRQ(USART1_IRQn);

    } else if (huart->Instance == USART2) {
        __HAL_RCC_USART2_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        GPIO_InitStruct.Pin       = GPIO_PIN_2 | GPIO_PIN_3;
        GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Pull      = GPIO_PULLUP;
        GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
        GPIO_InitStruct.Alternate = GPIO_AF7_USART2;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

        /* ---- USART2_RX = DMA1_Stream5, Channel 4, 循环模式 ---- */
        hdma_usart2_rx.Instance                 = DMA1_Stream5;
        hdma_usart2_rx.Init.Channel             = DMA_CHANNEL_4;
        hdma_usart2_rx.Init.Direction           = DMA_PERIPH_TO_MEMORY;
        hdma_usart2_rx.Init.PeriphInc           = DMA_PINC_DISABLE;
        hdma_usart2_rx.Init.MemInc              = DMA_MINC_ENABLE;
        hdma_usart2_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
        hdma_usart2_rx.Init.MemDataAlignment    = DMA_MDATAALIGN_BYTE;
        hdma_usart2_rx.Init.Mode                = DMA_CIRCULAR;
        hdma_usart2_rx.Init.Priority            = DMA_PRIORITY_HIGH;
        hdma_usart2_rx.Init.FIFOMode            = DMA_FIFOMODE_DISABLE;
        if (HAL_DMA_Init(&hdma_usart2_rx) != HAL_OK) {
            Error_Handler();
        }
        __HAL_LINKDMA(huart, hdmarx, hdma_usart2_rx);

        /* 空闲中断优先级 */
        HAL_NVIC_SetPriority(USART2_IRQn, 1U, 0U);
        HAL_NVIC_EnableIRQ(USART2_IRQn);
    }
}

/* -------------------------------------------------------------------------- */
void HAL_UART_MspDeInit(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        __HAL_RCC_USART1_CLK_DISABLE();
        HAL_GPIO_DeInit(GPIOA, GPIO_PIN_9 | GPIO_PIN_10);
        HAL_NVIC_DisableIRQ(USART1_IRQn);

    } else if (huart->Instance == USART2) {
        __HAL_RCC_USART2_CLK_DISABLE();
        HAL_GPIO_DeInit(GPIOA, GPIO_PIN_2 | GPIO_PIN_3);
        HAL_DMA_DeInit(huart->hdmarx);
        HAL_NVIC_DisableIRQ(USART2_IRQn);
    }
}
