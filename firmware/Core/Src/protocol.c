/**
  ******************************************************************************
  * @file    protocol.c
  * @brief   Maix 字节流协议: CRC16_IBM / 组帧 / 逐字节解析状态机
  ******************************************************************************
  */
#include "protocol.h"
#include <string.h>

/* -------------------------------------------------------------------------- */
/* CRC16_IBM: 多项式 0xA001 (反射), 初值 0x0000, 不异或输出                     */
/* -------------------------------------------------------------------------- */
uint16_t CRC16_IBM(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0x0000U;

    if (data == NULL) {
        return 0U;
    }

    for (uint16_t i = 0U; i < len; i++) {
        crc ^= (uint16_t)data[i];
        for (uint8_t bit = 0U; bit < 8U; bit++) {
            if ((crc & 0x0001U) != 0U) {
                crc = (uint16_t)((crc >> 1) ^ 0xA001U);
            } else {
                crc = (uint16_t)(crc >> 1);
            }
        }
    }
    return crc;
}

/* -------------------------------------------------------------------------- */
/* 组帧                                                                        */
/* -------------------------------------------------------------------------- */
uint16_t Protocol_BuildFrame(uint8_t *out, uint8_t flags, uint8_t cmd,
                             const uint8_t *body, uint8_t body_len)
{
    uint16_t idx = 0U;
    uint32_t data_len;
    uint16_t crc;

    if ((out == NULL) || (body_len > MAIX_MAX_BODY_LEN)) {
        return 0U;
    }

    /* 1. 帧头 */
    out[idx++] = MAIX_FRAME_HEAD_0;
    out[idx++] = MAIX_FRAME_HEAD_1;
    out[idx++] = MAIX_FRAME_HEAD_2;
    out[idx++] = MAIX_FRAME_HEAD_3;

    /* 2. 数据长度 = flags(1) + cmd(1) + body(n) + crc(2), 小端序 */
    data_len = 1U + 1U + (uint32_t)body_len + 2U;
    out[idx++] = (uint8_t)(data_len & 0xFFU);
    out[idx++] = (uint8_t)((data_len >> 8) & 0xFFU);
    out[idx++] = (uint8_t)((data_len >> 16) & 0xFFU);
    out[idx++] = (uint8_t)((data_len >> 24) & 0xFFU);

    /* 3. flags + cmd */
    out[idx++] = flags;
    out[idx++] = cmd;

    /* 4. body */
    if ((body != NULL) && (body_len > 0U)) {
        memcpy(&out[idx], body, body_len);
        idx = (uint16_t)(idx + body_len);
    }

    /* 5. CRC16 = crc(flags + cmd + body), 小端序 */
    crc = CRC16_IBM(&out[8], (uint16_t)(2U + body_len));
    out[idx++] = (uint8_t)(crc & 0xFFU);
    out[idx++] = (uint8_t)((crc >> 8) & 0xFFU);

    return idx;   /* = 10 + body_len */
}

/* -------------------------------------------------------------------------- */
/* 解析状态机                                                                  */
/* -------------------------------------------------------------------------- */
void Protocol_ParserInit(Parser_t *p)
{
    if (p == NULL) {
        return;
    }
    memset(p, 0, sizeof(Parser_t));
    p->state = PARSE_WAIT_HEAD1;
}

static void parser_reset(Parser_t *p)
{
    p->state    = PARSE_WAIT_HEAD1;
    p->head_idx = 0U;
    p->data_len = 0U;
    p->data_got = 0U;
}

uint8_t Protocol_PushByte(Parser_t *p, uint8_t byte)
{
    if (p == NULL) {
        return 0U;
    }

    switch (p->state) {

    /* ---------------- 找帧头 AA CA AC BB ---------------- */
    case PARSE_WAIT_HEAD1:
        if (byte == MAIX_FRAME_HEAD_0) {
            p->head_idx = 1U;
            p->state = PARSE_WAIT_HEAD2;
        }
        break;

    case PARSE_WAIT_HEAD2:
        if (byte == MAIX_FRAME_HEAD_1) {
            p->head_idx = 2U;
            p->state = PARSE_WAIT_HEAD3;
        } else if (byte == MAIX_FRAME_HEAD_0) {
            p->head_idx = 1U;               /* 重新开始数 AA */
        } else {
            parser_reset(p);
        }
        break;

    case PARSE_WAIT_HEAD3:
        if (byte == MAIX_FRAME_HEAD_2) {
            p->head_idx = 3U;
            p->state = PARSE_WAIT_HEAD4;
        } else if (byte == MAIX_FRAME_HEAD_0) {
            p->head_idx = 1U;
            p->state = PARSE_WAIT_HEAD2;
        } else {
            parser_reset(p);
        }
        break;

    case PARSE_WAIT_HEAD4:
        if (byte == MAIX_FRAME_HEAD_3) {
            p->state = PARSE_RECV_LEN;
            p->data_len = 0U;
            p->data_got = 0U;
        } else if (byte == MAIX_FRAME_HEAD_0) {
            p->head_idx = 1U;
            p->state = PARSE_WAIT_HEAD2;
        } else {
            parser_reset(p);
        }
        break;

    /* ---------------- 收 4 字节长度 (小端序) ---------------- */
    case PARSE_RECV_LEN:
        p->data_len |= ((uint32_t)byte << (8U * p->data_got));
        p->data_got++;
        if (p->data_got >= 4U) {
            /* 长度必须 >= 4 (flags+cmd+crc) 且 <= 缓冲区能装下的最大值 */
            if ((p->data_len < 4U) || (p->data_len > (uint32_t)(MAIX_MAX_BODY_LEN + 4U))) {
                p->err_len++;
                parser_reset(p);
            } else {
                p->data_got = 0U;
                p->state = PARSE_RECV_DATA;
            }
        }
        break;

    /* ---------------- 收 flags + cmd + body ---------------- */
    case PARSE_RECV_DATA:
        if (p->data_got < (p->data_len - 2U)) {
            p->buf[p->data_got] = byte;
            p->data_got++;
            if (p->data_got >= (p->data_len - 2U)) {
                p->state = PARSE_RECV_CRC;
            }
        } else {
            p->state = PARSE_RECV_CRC;   /* 保险: 不该发生 */
        }
        break;

    /* ---------------- 收 2 字节 CRC (小端序) ---------------- */
    case PARSE_RECV_CRC:
    {
        uint16_t crc_calc;
        uint16_t crc_rx;

        p->buf[p->data_got] = byte;
        p->data_got++;

        if (p->data_got < p->data_len) {
            break;                        /* 还要再收 1 个字节 */
        }

        /* 校验对象 = flags + cmd + body (长度 data_len - 2) */
        crc_calc = CRC16_IBM(p->buf, (uint16_t)(p->data_len - 2U));
        crc_rx   = (uint16_t)((uint16_t)p->buf[p->data_len - 2U] |
                              ((uint16_t)p->buf[p->data_len - 1U] << 8));

        p->frame.flags    = p->buf[0];
        p->frame.cmd      = p->buf[1];
        p->frame.body_len = (uint8_t)(p->data_len - 4U);
        if (p->frame.body_len > 0U) {
            memcpy(p->frame.body, &p->buf[2], p->frame.body_len);
        }
        p->frame.crc_ok = (crc_calc == crc_rx) ? 1U : 0U;

        if (p->frame.crc_ok == 0U) {
            p->err_crc++;
        }
        p->rx_frames++;

        parser_reset(p);
        return 1U;                        /* 收到一整帧 */
    }

    default:
        parser_reset(p);
        break;
    }

    return 0U;
}

const Frame_t *Protocol_GetFrame(const Parser_t *p)
{
    return (p == NULL) ? NULL : &p->frame;
}

uint16_t Protocol_GetU16LE(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}
