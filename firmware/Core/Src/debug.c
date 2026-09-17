/**
  ******************************************************************************
  * @file    debug.c
  * @brief   串口调试打印 (vsnprintf + 阻塞发送)
  *
  *  发送走 USART1 的 TX (PA9)。GM65 只用它的 TX, 所以 PA9 是空闲的,
  *  接一个 USB-TTL 就能在电脑上看日志。
  ******************************************************************************
  */
#include "debug.h"
#include "main.h"

#if DEBUG_ENABLE
#include <stdio.h>
#include <stdarg.h>

void Debug_Init(void)
{
    /* USART1 已经在 main 里初始化好了, 这里不需要额外动作 */
}

void dbg_printf(const char *fmt, ...)
{
    char    buf[128];
    va_list ap;
    int     n;

    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    if (n <= 0) {
        return;
    }
    if (n > (int)(sizeof(buf) - 1U)) {
        n = (int)(sizeof(buf) - 1U);
    }

    (void)HAL_UART_Transmit(&DEBUG_UART, (uint8_t *)buf, (uint16_t)n, 100U);
}

#else

void Debug_Init(void)
{
}

#endif /* DEBUG_ENABLE */
