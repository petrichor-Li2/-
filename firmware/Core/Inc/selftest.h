/**
  ******************************************************************************
  * @file    selftest.h
  * @brief   板级自检 (协议 / 解析 / 范围判断 / 二维码解析)
  *
  *  把 SELFTEST_ENABLE 改成 1 编译烧录, 上电后会在 USART1 TX (PA9) 打印
  *  PASS / FAIL 结果, 用来确认固件逻辑没问题, 再拿去比赛。
  ******************************************************************************
  */
#ifndef __SELFTEST_H__
#define __SELFTEST_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#ifndef SELFTEST_ENABLE
#define SELFTEST_ENABLE   0
#endif

/**
  * @brief 跑一遍自检, 结果通过串口打印
  * @retval 失败的测试项数量 (0 = 全部通过)
  */
uint16_t SelfTest_Run(void);

#ifdef __cplusplus
}
#endif

#endif /* __SELFTEST_H__ */
