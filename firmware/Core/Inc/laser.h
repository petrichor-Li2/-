/**
  ******************************************************************************
  * @file    laser.h
  * @brief   650nm 红色激光控制 (PD15, 高电平开)
  ******************************************************************************
  */
#ifndef __LASER_H__
#define __LASER_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

void Laser_Init(void);
void Laser_On(void);
void Laser_Off(void);
uint8_t Laser_IsOn(void);

#ifdef __cplusplus
}
#endif

#endif /* __LASER_H__ */
