/**
  ******************************************************************************
  * @file    bsp_led.c
  * @brief   三色 LED + 心跳灯 (全部非阻塞)
  ******************************************************************************
  */
#include "bsp_led.h"
#include "app_config.h"
#include "main.h"

/* -------------------------------------------------------------------------- */
/* 三色 LED                                                                    */
/* -------------------------------------------------------------------------- */
static volatile LedEffect_t s_fx      = LED_FX_OFF;
static uint32_t s_period  = LED_BLINK_MS;
static uint32_t s_last    = 0U;
static uint8_t  s_phase   = 0U;

void LED_Init(void)
{
    s_fx     = LED_FX_OFF;
    s_period = LED_BLINK_MS;
    s_last   = HAL_GetTick();
    s_phase  = 0U;
    LED_AllOff();
}

void LED_Set(uint8_t r, uint8_t g, uint8_t b)
{
    HAL_GPIO_WritePin(LED_R_GPIO_PORT, LED_R_PIN, (r != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(LED_G_GPIO_PORT, LED_G_PIN, (g != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(LED_B_GPIO_PORT, LED_B_PIN, (b != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

void LED_AllOff(void)
{
    LED_Set(0U, 0U, 0U);
}

void LED_SolidById(uint8_t id)
{
    switch (id) {
    case 1U:  s_fx = LED_FX_SOLID_R; break;   /* 红 / 圆柱 */
    case 2U:  s_fx = LED_FX_SOLID_G; break;   /* 绿 / 圆锥 */
    case 3U:  s_fx = LED_FX_SOLID_B; break;   /* 蓝 / 腰鼓 */
    default:  s_fx = LED_FX_OFF;     break;
    }
}

void LED_SetEffect(LedEffect_t fx, uint32_t period_ms)
{
    s_fx = fx;
    if (period_ms > 0U) {
        s_period = period_ms;
    }
    s_last  = HAL_GetTick();
    s_phase = 1U;                             /* 立刻亮起, 方便肉眼看 */
    LED_Update();
}

void LED_Update(void)
{
    uint32_t now = HAL_GetTick();

    switch (s_fx) {

    case LED_FX_OFF:
        LED_AllOff();
        return;

    case LED_FX_SOLID_R:  LED_Set(1U, 0U, 0U); return;
    case LED_FX_SOLID_G:  LED_Set(0U, 1U, 0U); return;
    case LED_FX_SOLID_B:  LED_Set(0U, 0U, 1U); return;

    default:
        break;
    }

    /* 闪烁类: 每 period 翻转一次相位 */
    if ((now - s_last) >= s_period) {
        s_last = now;
        s_phase = (uint8_t)(s_phase ^ 1U);
    }

    switch (s_fx) {
    case LED_FX_BLINK_R:   LED_Set(s_phase, 0U, 0U); return;
    case LED_FX_BLINK_G:   LED_Set(0U, s_phase, 0U); return;
    case LED_FX_BLINK_RG:  LED_Set(s_phase, s_phase, 0U); return;
    case LED_FX_BLINK_GB:  LED_Set(0U, s_phase, s_phase); return;
    case LED_FX_BLINK_RB:  LED_Set(s_phase, 0U, s_phase); return;
    case LED_FX_BLINK_RGB: LED_Set(s_phase, s_phase, s_phase); return;
    default:               LED_AllOff(); return;
    }
}

/* -------------------------------------------------------------------------- */
/* 心跳灯 (PB0, 独立于三色 LED)                                                */
/* -------------------------------------------------------------------------- */
static uint32_t s_hb_last = 0U;
static uint8_t  s_hb_state = 0U;
static uint8_t  s_hb_solid = 0U;

void Heartbeat_Init(void)
{
    s_hb_last  = HAL_GetTick();
    s_hb_state = 0U;
    s_hb_solid = 0U;
    HAL_GPIO_WritePin(HEARTBEAT_GPIO_PORT, HEARTBEAT_PIN, GPIO_PIN_RESET);
}

void Heartbeat_SetBlink(void)
{
    s_hb_solid = 0U;
    s_hb_last  = HAL_GetTick();
}

void Heartbeat_SetSolid(void)
{
    s_hb_solid = 1U;
    HAL_GPIO_WritePin(HEARTBEAT_GPIO_PORT, HEARTBEAT_PIN, GPIO_PIN_SET);
}

void Heartbeat_Toggle(void)
{
    if (s_hb_solid != 0U) {
        HAL_GPIO_WritePin(HEARTBEAT_GPIO_PORT, HEARTBEAT_PIN, GPIO_PIN_SET);
        return;
    }

    if ((HAL_GetTick() - s_hb_last) >= HEARTBEAT_MS) {
        s_hb_last = HAL_GetTick();
        s_hb_state = (uint8_t)(s_hb_state ^ 1U);
        HAL_GPIO_WritePin(HEARTBEAT_GPIO_PORT, HEARTBEAT_PIN,
                          (s_hb_state != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    }
}
