/**
  ******************************************************************************
  * @file    main.h
  * @brief   全局头文件: HAL 句柄、函数声明
  ******************************************************************************
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"
#include "app_config.h"

/* Exported types ------------------------------------------------------------*/

/* Exported constants --------------------------------------------------------*/

/* Exported macro ------------------------------------------------------------*/

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* 外设句柄 (定义在 main.c) */
extern UART_HandleTypeDef huart1;   /* GM65  9600   */
extern UART_HandleTypeDef huart2;   /* MaixCAM 115200 */
extern DMA_HandleTypeDef  hdma_usart2_rx;
extern IWDG_HandleTypeDef hiwdg;

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
