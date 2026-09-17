/**
  ******************************************************************************
  * @file    debug.h
  * @brief   轻量串口调试打印 (vsnprintf + 阻塞发送, 不依赖 newlib 系统调用)
  *
  *  DEBUG_ENABLE = 0 时所有打印都被编译掉, 零开销。
  ******************************************************************************
  */
#ifndef __DEBUG_H__
#define __DEBUG_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include "app_config.h"

void Debug_Init(void);

#if DEBUG_ENABLE
void dbg_printf(const char *fmt, ...);
#else
#define dbg_printf(...)  ((void)0)
#endif

#ifdef __cplusplus
}
#endif

#endif /* __DEBUG_H__ */
