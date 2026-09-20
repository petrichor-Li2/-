/**
  ******************************************************************************
  * @file    main.c
  * @brief   2026 广东省工科大学生实验综合技能竞赛 · 赛项3
  *          反恐排爆救援机器人 —— STM32F407VGT6 主控
  *
  *  硬件连接:
  *    USART1  PA9/PA10  -> GM65 扫码模块   9600  8N1
  *    USART2  PA2/PA3   -> MaixCAM-Pro     115200 8N1 (RX 走 DMA)
  *    PC10/PC11/PC12    -> 三色 LED 红/绿/蓝
  *    PD15              -> 650nm 激光
  *    PB0               -> 心跳灯
  *
  *  启动: 放到蓝色出发区, 上电/复位即开始, 全自主, 无遥控。
  ******************************************************************************
  */
#include "main.h"
#include "app_fsm.h"
#include "vision.h"
#include "maix_link.h"
#include "gm65.h"
#include "bsp_led.h"
#include "motion.h"
#include "arm.h"
#include "laser.h"
#include "debug.h"
#include "selftest.h"

/* 看门狗: 调试阶段建议 0, 比赛时改 1 (约 1s 超时) */
#define USE_IWDG   0

/* -------------------------------------------------------------------------- */
/* 外设句柄                                                                    */
/* -------------------------------------------------------------------------- */
UART_HandleTypeDef  huart1;          /* GM65    9600   */
UART_HandleTypeDef  huart2;          /* MaixCAM 115200 */
DMA_HandleTypeDef   hdma_usart2_rx;
IWDG_HandleTypeDef  hiwdg;

/* -------------------------------------------------------------------------- */
/* 私有函数声明                                                                */
/* -------------------------------------------------------------------------- */
static void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_USART2_UART_Init(void);
#if USE_IWDG
static void MX_IWDG_Init(void);
#endif

/* -------------------------------------------------------------------------- */
int main(void)
{
    /* 1. HAL 初始化 (内含 SysTick 1ms) */
    HAL_Init();

    /* 2. 时钟 168MHz */
    SystemClock_Config();

    /* 3. 外设初始化 */
    MX_GPIO_Init();
    MX_DMA_Init();
    MX_USART1_UART_Init();       /* GM65 */
    MX_USART2_UART_Init();       /* MaixCAM */
#if USE_IWDG
    MX_IWDG_Init();
#endif

    /* 4. 业务模块初始化 */
    Debug_Init();
    LED_Init();                  /* 三色 LED */
    Heartbeat_Init();            /* 心跳灯 */
    Laser_Init();                /* 激光 (先关) */
    Motion_Init();               /* 底盘 (先停) */
    Arm_Init();                  /* 机械臂回原位 */
    Vision_Init();               /* 视觉数据 */
    MaixLink_Init();             /* USART2 DMA + 空闲中断 */
    GM65_Init();                 /* USART1 逐字节中断 */
    FSM_Init();                  /* 状态机 */

    dbg_printf("\r\n");
    dbg_printf("========================================\r\n");
    dbg_printf(" 反恐排爆救援机器人 STM32F407VGT6\r\n");
    dbg_printf(" SysClk=%d Hz\r\n", (int)SystemCoreClock);
    dbg_printf(" GM65   : USART1 9600  8N1\r\n");
    dbg_printf(" MaixCAM: USART2 115200 8N1 (DMA+IDLE)\r\n");
    dbg_printf(" 状态机启动, 一键自主运行\r\n");
    dbg_printf("========================================\r\n");

    /* 5. 板级自检 (SELFTEST_ENABLE=1 时才编译进来, 比赛固件里是空的) */
#if SELFTEST_ENABLE
    (void)SelfTest_Run();
#endif

    /* 6. 主循环 */
    while (1) {
        /* ---- 1. 处理串口数据 ---- */
        GM65_Process();          /* ProcessUSART1(): 解析二维码 */
        MaixLink_Process();      /* ProcessUSART2(): 解析视觉帧, 置 g_vision_ready */

        /* ---- 2. 跑状态机 ---- */
        FSM_Run();

        /* ---- 3. 灯效 / 执行机构刷新 ---- */
        LED_Update();
        Heartbeat_Toggle();
        Motion_Update();
        Arm_Update();

        /* ---- 4. 喂狗 ---- */
#if USE_IWDG
        HAL_IWDG_Refresh(&hiwdg);
#endif
    }
}

/* -------------------------------------------------------------------------- */
/* 系统时钟: HSE 8MHz -> PLL -> 168MHz                                         */
/*   SYSCLK = 8 / PLLM(8) * PLLN(336) / PLLP(2) = 168MHz                       */
/*   USB/SDIO = 8 / 8 * 336 / PLLQ(7) = 48MHz                                  */
/* -------------------------------------------------------------------------- */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState   = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM       = 8U;      /* 25MHz 晶振时改成 25 */
    RCC_OscInitStruct.PLL.PLLN       = 336U;
    RCC_OscInitStruct.PLL.PLLP       = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ       = 7U;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) {
        Error_Handler();
    }

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                                  RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;    /* 168MHz */
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;      /*  42MHz */
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;      /*  84MHz */
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK) {
        Error_Handler();
    }
}

/* -------------------------------------------------------------------------- */
/* GPIO: 三色 LED / 心跳灯 / 激光                                              */
/* -------------------------------------------------------------------------- */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    /* 上电先全部输出低电平 */
    HAL_GPIO_WritePin(GPIOB, HEARTBEAT_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(LED_R_GPIO_PORT, LED_R_PIN | LED_G_PIN | LED_B_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOD, LASER_PIN, GPIO_PIN_RESET);

    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;

    /* 心跳灯 PB0 */
    GPIO_InitStruct.Pin = HEARTBEAT_PIN;
    HAL_GPIO_Init(HEARTBEAT_GPIO_PORT, &GPIO_InitStruct);

    /* 三色 LED: PC10 红 / PC11 绿 / PC12 蓝 */
    GPIO_InitStruct.Pin = LED_R_PIN | LED_G_PIN | LED_B_PIN;
    HAL_GPIO_Init(LED_R_GPIO_PORT, &GPIO_InitStruct);

    /* 激光 PD15 */
    GPIO_InitStruct.Pin = LASER_PIN;
    HAL_GPIO_Init(LASER_GPIO_PORT, &GPIO_InitStruct);

    /* TODO: 真实硬件时在这里补
     *   · 4 个编码电机的 PWM(TIMx) + 方向脚 + 编码器脚
     *   · 机械臂舵机 PWM 或串口
     */
}

/* -------------------------------------------------------------------------- */
/* DMA: USART2_RX = DMA1_Stream5_Channel4                                      */
/* -------------------------------------------------------------------------- */
static void MX_DMA_Init(void)
{
    __HAL_RCC_DMA1_CLK_ENABLE();

    HAL_NVIC_SetPriority(DMA1_Stream5_IRQn, 0U, 0U);
    HAL_NVIC_EnableIRQ(DMA1_Stream5_IRQn);

    /* DMA1_Stream6 是 USART2_TX 用的, 本工程发送用阻塞方式, 不需要 */
}

/* -------------------------------------------------------------------------- */
/* USART1 -> GM65 扫码模块 9600 8N1                                            */
/* -------------------------------------------------------------------------- */
static void MX_USART1_UART_Init(void)
{
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = GM65_UART_BAUDRATE;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK) {
        Error_Handler();
    }
}

/* -------------------------------------------------------------------------- */
/* USART2 -> MaixCAM-Pro 115200 8N1                                            */
/* -------------------------------------------------------------------------- */
static void MX_USART2_UART_Init(void)
{
    huart2.Instance          = USART2;
    huart2.Init.BaudRate     = MAIX_UART_BAUDRATE;
    huart2.Init.WordLength   = UART_WORDLENGTH_8B;
    huart2.Init.StopBits     = UART_STOPBITS_1;
    huart2.Init.Parity       = UART_PARITY_NONE;
    huart2.Init.Mode         = UART_MODE_TX_RX;
    huart2.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart2) != HAL_OK) {
        Error_Handler();
    }
}

#if USE_IWDG
/* -------------------------------------------------------------------------- */
/* 独立看门狗: LSI 32kHz / 32 = 1kHz, reload 1000 -> 约 1s                     */
/* -------------------------------------------------------------------------- */
static void MX_IWDG_Init(void)
{
    hiwdg.Instance       = IWDG;
    hiwdg.Init.Prescaler = IWDG_PRESCALER_32;
    hiwdg.Init.Reload    = 1000U;
    if (HAL_IWDG_Init(&hiwdg) != HAL_OK) {
        Error_Handler();
    }
}
#endif

/* -------------------------------------------------------------------------- */
/* 出错: 红灯快闪 + 停在这里 (方便示波器/肉眼发现)                             */
/* -------------------------------------------------------------------------- */
void Error_Handler(void)
{
    __disable_irq();

    while (1) {
        HAL_GPIO_TogglePin(LED_R_GPIO_PORT, LED_R_PIN);
        for (volatile uint32_t i = 0U; i < 400000U; i++) {
            __NOP();
        }
    }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    (void)file;
    (void)line;
    Error_Handler();
}
#endif
