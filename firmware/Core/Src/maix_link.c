/**
  ******************************************************************************
  * @file    maix_link.c
  * @brief   STM32 <-> MaixCAM 链路 (USART2)
  *
  *  接收: DMA 循环模式(256B) + 空闲中断 + DMA 半满/全满中断
  *        -> 数据搬进软件环形缓冲 -> 主循环逐字节喂给协议解析器
  *  发送: 一次性 HAL_UART_Transmit 发出整帧
  ******************************************************************************
  */
#include "maix_link.h"
#include "protocol.h"
#include "vision.h"
#include "main.h"
#include <string.h>

/* -------------------------------------------------------------------------- */
/* 缓冲与状态                                                                  */
/* -------------------------------------------------------------------------- */
static uint8_t  s_dma_buf[MAIX_DMA_BUF_SIZE];
static volatile uint16_t s_dma_old_pos;      /* 上次已搬运到的 DMA 位置 */

static uint8_t  s_ring[MAIX_RX_RING_SIZE];
static volatile uint16_t s_ring_head;
static volatile uint16_t s_ring_tail;

static Parser_t s_parser;
static uint8_t  s_tx_buf[MAIX_MAX_BODY_LEN + 12U];

volatile uint32_t g_maix_tx_frames = 0U;
volatile uint32_t g_maix_rx_frames = 0U;
volatile uint32_t g_maix_crc_err    = 0U;
volatile uint32_t g_maix_overflow   = 0U;

/* -------------------------------------------------------------------------- */
/* 环形缓冲                                                                    */
/* -------------------------------------------------------------------------- */
static void ring_push(const uint8_t *src, uint16_t n)
{
    for (uint16_t i = 0U; i < n; i++) {
        uint16_t next = (uint16_t)((s_ring_head + 1U) & (MAIX_RX_RING_SIZE - 1U));
        if (next == s_ring_tail) {
            g_maix_overflow++;               /* 缓冲满, 丢新数据 */
            return;
        }
        s_ring[s_ring_head] = src[i];
        s_ring_head = next;
    }
}

/* -------------------------------------------------------------------------- */
/* 把 DMA 缓冲区里"新到"的字节搬进环形缓冲 (IRQ 上下文调用)                    */
/* -------------------------------------------------------------------------- */
static void drain_dma(void)
{
    uint16_t pos;
    uint16_t old;

    if (huart2.hdmarx == NULL) {
        return;
    }

    pos = (uint16_t)(MAIX_DMA_BUF_SIZE - __HAL_DMA_GET_COUNTER(huart2.hdmarx));
    old = s_dma_old_pos;

    if (pos == old) {
        return;
    }

    if (pos > old) {
        ring_push(&s_dma_buf[old], (uint16_t)(pos - old));
    } else {
        /* DMA 指针绕回: 分两段搬 */
        ring_push(&s_dma_buf[old], (uint16_t)(MAIX_DMA_BUF_SIZE - old));
        if (pos > 0U) {
            ring_push(&s_dma_buf[0], pos);
        }
    }
    s_dma_old_pos = pos;
}

/* -------------------------------------------------------------------------- */
/* 初始化                                                                      */
/* -------------------------------------------------------------------------- */
void MaixLink_StartRx(void)
{
    (void)HAL_UART_DMAStop(&huart2);
    s_dma_old_pos = 0U;
    (void)HAL_UART_Receive_DMA(&huart2, s_dma_buf, MAIX_DMA_BUF_SIZE);
    __HAL_UART_CLEAR_IDLEFLAG(&huart2);
    __HAL_UART_ENABLE_IT(&huart2, UART_IT_IDLE);
}

void MaixLink_Flush(void)
{
    __disable_irq();
    s_ring_head = 0U;
    s_ring_tail = 0U;
    s_dma_old_pos = 0U;
    Protocol_ParserInit(&s_parser);
    memset(s_dma_buf, 0, sizeof(s_dma_buf));
    __enable_irq();
}

void MaixLink_Init(void)
{
    g_maix_tx_frames = 0U;
    g_maix_rx_frames = 0U;
    g_maix_crc_err   = 0U;
    g_maix_overflow  = 0U;

    MaixLink_Flush();
    MaixLink_StartRx();
}

void MaixLink_OnIdleIrq(void)
{
    drain_dma();
}

void MaixLink_OnDmaEvent(void)
{
    drain_dma();
}

void MaixLink_OnError(void)
{
    /* DMA/USART 出错后重新武装接收, 不能卡死在这里 */
    MaixLink_StartRx();
}

/* -------------------------------------------------------------------------- */
/* 主循环: 解析环形缓冲                                                        */
/* -------------------------------------------------------------------------- */
void MaixLink_Process(void)
{
    while (s_ring_tail != s_ring_head) {
        uint8_t byte = s_ring[s_ring_tail];
        s_ring_tail = (uint16_t)((s_ring_tail + 1U) & (MAIX_RX_RING_SIZE - 1U));

        if (Protocol_PushByte(&s_parser, byte) != 0U) {
            const Frame_t *f = Protocol_GetFrame(&s_parser);

            if (f == NULL) {
                continue;
            }
            if (f->crc_ok == 0U) {
                g_maix_crc_err++;            /* CRC 失败: 丢帧, 等状态机重试 */
                continue;
            }
            g_maix_rx_frames++;
            Vision_OnFrame(f->cmd, f->body, f->body_len);
        }
    }
}

/* -------------------------------------------------------------------------- */
/* 发送                                                                        */
/* -------------------------------------------------------------------------- */
void Maix_SendCmd(uint8_t cmd, const uint8_t *body, uint8_t body_len)
{
    uint16_t n = Protocol_BuildFrame(s_tx_buf, MAIX_FLAG_REQUEST, cmd, body, body_len);

    if (n == 0U) {
        return;
    }
    /* 一帧最多 18 字节, 115200 下 <2ms; 100ms 超时足够 */
    if (HAL_UART_Transmit(&huart2, s_tx_buf, n, 100U) == HAL_OK) {
        g_maix_tx_frames++;
    }
}

void Maix_SendModeColor(void)
{
    Maix_SendCmd(MAIX_CMD_SET_MODE_COLOR, NULL, 0U);
}

void Maix_SendModeShape(void)
{
    Maix_SendCmd(MAIX_CMD_SET_MODE_SHAPE, NULL, 0U);
}

void Maix_SendReqDetect(void)
{
    Maix_SendCmd(MAIX_CMD_REQUEST_DETECT, NULL, 0U);
}
