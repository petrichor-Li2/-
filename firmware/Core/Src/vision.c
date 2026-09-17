/**
  ******************************************************************************
  * @file    vision.c
  * @brief   视觉结果存放 + 有效范围判断 (STM32 端负责匹配与范围判断)
  ******************************************************************************
  */
#include "vision.h"
#include "protocol.h"
#include "app_config.h"
#include <string.h>

/* 通信协议定义在 protocol.h, 这里再包一层业务判断 */

VisionResult g_vision;
volatile uint8_t g_vision_ready = 0U;
VisionResult g_target;

void Vision_Init(void)
{
    memset(&g_vision, 0, sizeof(g_vision));
    memset(&g_target, 0, sizeof(g_target));
    g_vision_ready = 0U;
}

/* -------------------------------------------------------------------------- */
/* 收到一帧视觉数据 (已经过 CRC 校验)                                          */
/*   cmd = 0x01 颜色: body = id(1) x(2) y(2) w(2) h(2)                         */
/*   cmd = 0x02 形状: body = id(1) x(2) y(2) w(2) h(2)                         */
/*   cmd = 0x00 空帧: 没有找到目标                                            */
/* -------------------------------------------------------------------------- */
void Vision_OnFrame(uint8_t cmd, const uint8_t *body, uint8_t body_len)
{
    g_vision.cmd   = cmd;
    g_vision.id    = 0U;
    g_vision.x     = 0U;
    g_vision.y     = 0U;
    g_vision.w     = 0U;
    g_vision.h     = 0U;
    g_vision.valid = 0U;

    if (((cmd == MAIX_CMD_REPORT_COLOR) || (cmd == MAIX_CMD_REPORT_SHAPE)) &&
        (body != NULL) && (body_len >= 9U)) {
        g_vision.id    = body[0];
        g_vision.x     = Protocol_GetU16LE(&body[1]);
        g_vision.y     = Protocol_GetU16LE(&body[3]);
        g_vision.w     = Protocol_GetU16LE(&body[5]);
        g_vision.h     = Protocol_GetU16LE(&body[7]);
        g_vision.valid = 1U;
    }
    /* cmd == 0x00 或正文长度不对 -> valid = 0 (状态机会重试) */

    g_vision_ready = 1U;
}

/* -------------------------------------------------------------------------- */
/* 有效范围判断: 用目标中心点判断                                              */
/*   640x320, 中心 (320,160), X:160~480, Y:80~240                              */
/* -------------------------------------------------------------------------- */
uint8_t Vision_IsInValidRange(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
    uint16_t cx = (uint16_t)(x + (w / 2U));
    uint16_t cy = (uint16_t)(y + (h / 2U));

    if ((cx >= VISION_X_MIN) && (cx <= VISION_X_MAX) &&
        (cy >= VISION_Y_MIN) && (cy <= VISION_Y_MAX)) {
        return 1U;
    }
    return 0U;
}

uint16_t Vision_CenterX(const VisionResult *v)
{
    return (v == NULL) ? 0U : (uint16_t)(v->x + (v->w / 2U));
}

uint16_t Vision_CenterY(const VisionResult *v)
{
    return (v == NULL) ? 0U : (uint16_t)(v->y + (v->h / 2U));
}

const char *Vision_ColorName(uint8_t id)
{
    switch (id) {
    case COLOR_RED:   return "红";
    case COLOR_GREEN: return "绿";
    case COLOR_BLUE:  return "蓝";
    default:          return "未知";
    }
}

const char *Vision_ShapeName(uint8_t id)
{
    switch (id) {
    case SHAPE_CYLINDER:   return "圆柱";
    case SHAPE_CONE:       return "圆锥";
    case SHAPE_WAIST_DRUM: return "腰鼓";
    default:               return "未知";
    }
}
