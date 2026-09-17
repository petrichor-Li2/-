/**
  ******************************************************************************
  * @file    protocol.h
  * @brief   Maix 字节流协议 —— CRC16_IBM / 组帧 / 逐字节解析状态机
  *
  *  帧格式:
  *    AA CA AC BB | 长度(4B LE) | flags(1B) | cmd(1B) | body(nB) | CRC16(2B LE)
  *
  *  · 长度 = flags + cmd + body + CRC 的总字节数 (小端序)
  *  · CRC16 = CRC16_IBM(flags + cmd + body) (小端序)
  ******************************************************************************
  */
#ifndef __PROTOCOL_H__
#define __PROTOCOL_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include "app_config.h"

/* -------------------------------------------------------------------------- */
/* CRC16_IBM (多项式 0xA001, 初值 0x0000)                                      */
/* -------------------------------------------------------------------------- */
uint16_t CRC16_IBM(const uint8_t *data, uint16_t len);

/* -------------------------------------------------------------------------- */
/* 组帧                                                                        */
/* -------------------------------------------------------------------------- */
/**
  * @brief  按协议拼一帧
  * @param  out       输出缓冲区, 至少 6 + 2 + body_len + 2 字节
  * @param  flags     标志位 (请求用 MAIX_FLAG_REQUEST, 上报用 MAIX_FLAG_REPORT)
  * @param  cmd       命令号
  * @param  body      正文, 可为 NULL
  * @param  body_len  正文长度
  * @retval 整帧长度 (字节数), 0 = 失败
  */
uint16_t Protocol_BuildFrame(uint8_t *out, uint8_t flags, uint8_t cmd,
                             const uint8_t *body, uint8_t body_len);

/* -------------------------------------------------------------------------- */
/* 解析状态机                                                                  */
/* -------------------------------------------------------------------------- */
typedef enum {
    PARSE_WAIT_HEAD1 = 0,
    PARSE_WAIT_HEAD2,
    PARSE_WAIT_HEAD3,
    PARSE_WAIT_HEAD4,
    PARSE_RECV_LEN,
    PARSE_RECV_DATA,
    PARSE_RECV_CRC
} ParseState_t;

/* 一帧解析结果 */
typedef struct {
    uint8_t  flags;                     /* 标志位 */
    uint8_t  cmd;                       /* 命令号 */
    uint8_t  body[MAIX_MAX_BODY_LEN];   /* 正文 */
    uint8_t  body_len;                  /* 正文长度 */
    uint8_t  crc_ok;                    /* CRC 校验结果: 1 通过, 0 失败 */
} Frame_t;

/* 解析器实例 */
typedef struct {
    ParseState_t state;
    uint8_t  head_idx;                  /* 帧头匹配到第几个字节 */
    uint32_t data_len;                  /* 长度字段 (flags+cmd+body+crc) */
    uint32_t data_got;                  /* 已收到的 长度字段 覆盖的字节数 */
    uint8_t  buf[MAIX_MAX_BODY_LEN + 2U + 2U]; /* flags + cmd + body + crc */
    Frame_t  frame;                     /* 最近一次解析完成的帧 */
    uint32_t rx_frames;                 /* 统计: 收到的完整帧 */
    uint32_t err_crc;                   /* 统计: CRC 错误帧 */
    uint32_t err_len;                   /* 统计: 长度非法帧 */
} Parser_t;

void Protocol_ParserInit(Parser_t *p);

/**
  * @brief  塞一个字节进解析器
  * @retval 1 = 收到一整帧 (结果在 p->frame, 通过 Protocol_GetFrame 取)
  *         0 = 还没收完
  */
uint8_t Protocol_PushByte(Parser_t *p, uint8_t byte);

/** 取最近一次解析完成的帧 */
const Frame_t *Protocol_GetFrame(const Parser_t *p);

/* -------------------------------------------------------------------------- */
/* 正文小工具: 小端序读写                                                     */
/* -------------------------------------------------------------------------- */
uint16_t Protocol_GetU16LE(const uint8_t *p);

#ifdef __cplusplus
}
#endif

#endif /* __PROTOCOL_H__ */
