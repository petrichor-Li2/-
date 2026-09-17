/**
  ******************************************************************************
  * @file    selftest.c
  * @brief   板级自检 —— 把协议/解析/范围/二维码的逻辑全部验一遍
  *
  *  期望值来自 tools/maix_protocol.py (Python 参考实现), 两端钉在同一组
  *  测试向量上, 改协议必须同时改两边。
  ******************************************************************************
  */
#include "selftest.h"
#include "protocol.h"
#include "vision.h"
#include "gm65.h"
#include "debug.h"
#include <string.h>

#define SELFTEST_VERSION_STR "v1.0"

static uint16_t s_pass;
static uint16_t s_fail;

/* -------------------------------------------------------------------------- */
/* 测试向量 (与 tools/maix_protocol.py 完全一致)                               */
/* -------------------------------------------------------------------------- */
static const uint8_t V_MODE_COLOR[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00, 0x01, 0x10, 0x00, 0x5C
};
static const uint8_t V_MODE_SHAPE[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00, 0x01, 0x11, 0xC1, 0x9C
};
static const uint8_t V_REQ_DETECT[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00, 0x01, 0x12, 0x81, 0x9D
};
static const uint8_t V_REPORT_COLOR[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x0D, 0x00, 0x00, 0x00, 0x21, 0x01,
    0x01, 0x2C, 0x01, 0x8C, 0x00, 0x3C, 0x00, 0x3C, 0x00, 0xE3, 0xB8
};
static const uint8_t V_REPORT_SHAPE[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x0D, 0x00, 0x00, 0x00, 0x21, 0x02,
    0x02, 0x40, 0x01, 0xA0, 0x00, 0x32, 0x00, 0x46, 0x00, 0x27, 0x1E
};
static const uint8_t V_NONE[] = {
    0xAA, 0xCA, 0xAC, 0xBB, 0x04, 0x00, 0x00, 0x00, 0x21, 0x00, 0x18, 0x50
};

/* -------------------------------------------------------------------------- */
static void check(const char *name, uint8_t ok)
{
    if (ok != 0U) {
        s_pass++;
        dbg_printf("  [PASS] %s\r\n", name);
    } else {
        s_fail++;
        dbg_printf("  [FAIL] %s\r\n", name);
    }
}

/* -------------------------------------------------------------------------- */
/* 1. CRC16_IBM 标准校验值                                                     */
/* -------------------------------------------------------------------------- */
static void test_crc(void)
{
    static const uint8_t digits[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    static const uint8_t fcolor[] = {0x01, 0x10};
    static const uint8_t freqs[]  = {0x01, 0x12};

    dbg_printf("[1] CRC16_IBM\r\n");
    check("crc16(\"123456789\") == 0xBB3D", CRC16_IBM(digits, 9U) == 0xBB3DU);
    check("crc16(01 10) == 0x5C00", CRC16_IBM(fcolor, 2U) == 0x5C00U);
    check("crc16(01 12) == 0x9D81", CRC16_IBM(freqs, 2U) == 0x9D81U);
    check("crc16(len=0) == 0", CRC16_IBM(digits, 0U) == 0x0000U);
}

/* -------------------------------------------------------------------------- */
/* 2. 组帧                                                                     */
/* -------------------------------------------------------------------------- */
static void test_build(void)
{
    uint8_t buf[64];
    uint16_t n;

    dbg_printf("[2] 组帧\r\n");

    n = Protocol_BuildFrame(buf, MAIX_FLAG_REQUEST, MAIX_CMD_SET_MODE_COLOR, NULL, 0U);
    check("设为颜色模式 0x10", (n == sizeof(V_MODE_COLOR)) &&
          (memcmp(buf, V_MODE_COLOR, n) == 0));

    n = Protocol_BuildFrame(buf, MAIX_FLAG_REQUEST, MAIX_CMD_SET_MODE_SHAPE, NULL, 0U);
    check("设为形状模式 0x11", (n == sizeof(V_MODE_SHAPE)) &&
          (memcmp(buf, V_MODE_SHAPE, n) == 0));

    n = Protocol_BuildFrame(buf, MAIX_FLAG_REQUEST, MAIX_CMD_REQUEST_DETECT, NULL, 0U);
    check("请求识别 0x12", (n == sizeof(V_REQ_DETECT)) &&
          (memcmp(buf, V_REQ_DETECT, n) == 0));

    n = Protocol_BuildFrame(buf, MAIX_FLAG_REPORT, MAIX_CMD_NONE, NULL, 0U);
    check("空帧 0x00", (n == sizeof(V_NONE)) &&
          (memcmp(buf, V_NONE, n) == 0));
}

/* -------------------------------------------------------------------------- */
/* 3. 解析: 把上面每一帧喂进状态机                                             */
/* -------------------------------------------------------------------------- */
static uint8_t feed_and_check(Parser_t *p, const uint8_t *frame, uint16_t len)
{
    const Frame_t *f;
    uint8_t done = 0U;

    Protocol_ParserInit(p);
    for (uint16_t i = 0U; i < len; i++) {
        if (Protocol_PushByte(p, frame[i]) != 0U) {
            done = 1U;
            break;
        }
    }
    if (done == 0U) {
        return 0U;
    }
    f = Protocol_GetFrame(p);
    if ((f == NULL) || (f->crc_ok == 0U)) {
        return 0U;
    }
    if (f->cmd != frame[9]) {
        return 0U;
    }
    if (f->body_len != (uint8_t)(len - 12U)) {
        return 0U;
    }
    return 1U;
}

static void test_parse(void)
{
    Parser_t p;
    const Frame_t *f;

    dbg_printf("[3] 逐字节解析\r\n");

    check("解析 0x10", feed_and_check(&p, V_MODE_COLOR, sizeof(V_MODE_COLOR)));
    check("解析 0x11", feed_and_check(&p, V_MODE_SHAPE, sizeof(V_MODE_SHAPE)));
    check("解析 0x12", feed_and_check(&p, V_REQ_DETECT, sizeof(V_REQ_DETECT)));
    check("解析 空帧", feed_and_check(&p, V_NONE, sizeof(V_NONE)));

    /* 颜色上报: id=1, x=300, y=140, w=60, h=60 */
    Protocol_ParserInit(&p);
    (void)feed_and_check(&p, V_REPORT_COLOR, sizeof(V_REPORT_COLOR));
    Protocol_ParserInit(&p);
    {
        uint8_t done = 0U;
        for (uint16_t i = 0U; i < sizeof(V_REPORT_COLOR); i++) {
            if (Protocol_PushByte(&p, V_REPORT_COLOR[i]) != 0U) {
                done = 1U;
                break;
            }
        }
        f = Protocol_GetFrame(&p);
        check("颜色报文 (1,300,140,60,60)",
              (done != 0U) && (f != NULL) && (f->crc_ok != 0U) &&
              (f->cmd == MAIX_CMD_REPORT_COLOR) &&
              (f->body_len == 9U) &&
              (f->body[0] == 1U) &&
              (Protocol_GetU16LE(&f->body[1]) == 300U) &&
              (Protocol_GetU16LE(&f->body[3]) == 140U) &&
              (Protocol_GetU16LE(&f->body[5]) == 60U) &&
              (Protocol_GetU16LE(&f->body[7]) == 60U));
    }

    /* 形状上报: id=2, x=320, y=160, w=50, h=70 */
    Protocol_ParserInit(&p);
    {
        uint8_t done = 0U;
        for (uint16_t i = 0U; i < sizeof(V_REPORT_SHAPE); i++) {
            if (Protocol_PushByte(&p, V_REPORT_SHAPE[i]) != 0U) {
                done = 1U;
                break;
            }
        }
        f = Protocol_GetFrame(&p);
        check("形状报文 (2,320,160,50,70)",
              (done != 0U) && (f != NULL) && (f->crc_ok != 0U) &&
              (f->cmd == MAIX_CMD_REPORT_SHAPE) &&
              (f->body[0] == 2U) &&
              (Protocol_GetU16LE(&f->body[1]) == 320U) &&
              (Protocol_GetU16LE(&f->body[3]) == 160U) &&
              (Protocol_GetU16LE(&f->body[5]) == 50U) &&
              (Protocol_GetU16LE(&f->body[7]) == 70U));
    }
}

/* -------------------------------------------------------------------------- */
/* 4. CRC 错误必须被丢掉                                                       */
/* -------------------------------------------------------------------------- */
static void test_crc_reject(void)
{
    Parser_t p;
    uint8_t bad[sizeof(V_REPORT_COLOR)];
    uint8_t done = 0U;
    const Frame_t *f = NULL;

    dbg_printf("[4] CRC 错误丢帧\r\n");

    memcpy(bad, V_REPORT_COLOR, sizeof(bad));
    bad[12] ^= 0xFFU;                       /* 破坏正文 */ 

    Protocol_ParserInit(&p);
    for (uint16_t i = 0U; i < sizeof(bad); i++) {
        if (Protocol_PushByte(&p, bad[i]) != 0U) {
            done = 1U;
            break;
        }
    }
    f = Protocol_GetFrame(&p);
    check("坏帧被识别出来 crc_ok == 0",
          (done != 0U) && (f != NULL) && (f->crc_ok == 0U));
    check("坏帧计数 err_crc == 1", p.err_crc == 1U);
}

/* -------------------------------------------------------------------------- */
/* 5. 帧前有垃圾字节也要能重新同步                                              */
/* -------------------------------------------------------------------------- */
static void test_resync(void)
{
    Parser_t p;
    static const uint8_t junk[] = {0x00, 0xFF, 0xAA, 0xAA, 0x55, 0xCA, 0xAC};
    uint8_t done = 0U;
    const Frame_t *f;

    dbg_printf("[5] 垃圾字节后重新同步\r\n");

    Protocol_ParserInit(&p);
    for (uint16_t i = 0U; i < sizeof(junk); i++) {
        (void)Protocol_PushByte(&p, junk[i]);
    }
    for (uint16_t i = 0U; i < sizeof(V_REQ_DETECT); i++) {
        if (Protocol_PushByte(&p, V_REQ_DETECT[i]) != 0U) {
            done = 1U;
            break;
        }
    }
    f = Protocol_GetFrame(&p);
    check("垃圾后仍能解析出 0x12",
          (done != 0U) && (f != NULL) && (f->crc_ok != 0U) &&
          (f->cmd == MAIX_CMD_REQUEST_DETECT));
}

/* -------------------------------------------------------------------------- */
/* 6. 有效范围判断                                                             */
/* -------------------------------------------------------------------------- */
static void test_range(void)
{
    dbg_printf("[6] 有效范围判断 (中心点 160~480, 80~240)\r\n");

    check("正中 (0,0,640,320) -> 在范围内",
          Vision_IsInValidRange(0U, 0U, 640U, 320U) == 1U);
    check("x=300 y=140 w=60 h=60 -> 在范围内",
          Vision_IsInValidRange(300U, 140U, 60U, 60U) == 1U);
    check("x=100 y=140 w=60 h=60 (cx=130) -> 超范围",
          Vision_IsInValidRange(100U, 140U, 60U, 60U) == 0U);
    check("x=300 y=40 w=60 h=60 (cy=70) -> 超范围",
          Vision_IsInValidRange(300U, 40U, 60U, 60U) == 0U);
    check("边界 cx=160 cy=80 -> 在范围内",
          Vision_IsInValidRange(160U, 80U, 0U, 0U) == 1U);
    check("中心点计算 cx=320 cy=160",
          (Vision_IsInValidRange(320U, 160U, 0U, 0U) == 1U));
}

/* -------------------------------------------------------------------------- */
/* 7. 二维码字符串解析                                                         */
/* -------------------------------------------------------------------------- */
static void test_qr(void)
{
    uint8_t b = 0U, t = 0U, s = 0U;

    dbg_printf("[7] 二维码解析\r\n");

    check("\"213\" -> 2/1/3",
          (GM65_ParseString("213", &b, &t, &s) == 1U) &&
          (b == 2U) && (t == 1U) && (s == 3U));
    check("\"112\" -> 1/1/2",
          (GM65_ParseString("112", &b, &t, &s) == 1U) &&
          (b == 1U) && (t == 1U) && (s == 2U));
    check("带前后缀 \"QR:331\\r\" -> 3/3/1",
          (GM65_ParseString("QR:331\r", &b, &t, &s) == 1U) &&
          (b == 3U) && (t == 3U) && (s == 1U));
    check("位数不足 \"12\" -> 失败",
          GM65_ParseString("12", &b, &t, &s) == 0U);
    check("越界 \"412\" -> 失败",
          GM65_ParseString("412", &b, &t, &s) == 0U);
}

/* -------------------------------------------------------------------------- */
/* 入口                                                                        */
/* -------------------------------------------------------------------------- */
uint16_t SelfTest_Run(void)
{
    s_pass = 0U;
    s_fail = 0U;

    dbg_printf("\r\n******** 自检开始 %s ********\r\n", SELFTEST_VERSION_STR);

    test_crc();
    test_build();
    test_parse();
    test_crc_reject();
    test_resync();
    test_range();
    test_qr();

    dbg_printf("******** 自检结果: %d 项通过, %d 项失败 ********\r\n",
               (int)s_pass, (int)s_fail);
    if (s_fail == 0U) {
        dbg_printf("******** 全部通过, 可以开始跑任务 ********\r\n\r\n");
    } else {
        dbg_printf("******** 有失败项, 请检查 !! ********\r\n\r\n");
    }
    return s_fail;
}
