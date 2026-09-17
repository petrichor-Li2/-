/**
  ******************************************************************************
  * @file    laser.c
  * @brief   650nm 红色激光开关 (PD15)
  ******************************************************************************
  */
#include "laser.h"
#include "app_config.h"
#include "main.h"

static uint8_t s_on = 0U;

void Laser_Init(void)
{
    Laser_Off();
}

void Laser_On(void)
{
#if LASER_ACTIVE_HIGH
    HAL_GPIO_WritePin(LASER_GPIO_PORT, LASER_PIN, GPIO_PIN_SET);
#else
    HAL_GPIO_WritePin(LASER_GPIO_PORT, LASER_PIN, GPIO_PIN_RESET);
#endif
    s_on = 1U;
}

void Laser_Off(void)
{
#if LASER_ACTIVE_HIGH
    HAL_GPIO_WritePin(LASER_GPIO_PORT, LASER_PIN, GPIO_PIN_RESET);
#else
    HAL_GPIO_WritePin(LASER_GPIO_PORT, LASER_PIN, GPIO_PIN_SET);
#endif
    s_on = 0U;
}

uint8_t Laser_IsOn(void)
{
    return s_on;
}
