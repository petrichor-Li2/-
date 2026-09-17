/**
  ******************************************************************************
  * @file    gm65.c
  * @brief   GM65 二维码读取 (USART1, 9600 8N1, 逐字节中断)
  *
  *  GM65 主动吐字符串, 以 CR/LF 结束, 例如 "213\r\n"
  ******************************************************************************
  */
#include "gm65.h"
#include "app_config.h"
#include "main.h"
#include "maix_link.h"

uint8_t qr_bomb_color   = QR_PLACEHOLDER_BOMB_COLOR;
uint8_t qr_target_color = QR_PLACEHOLDER_TARGET_COLOR;
uint8_t qr_rescue_shape = QR_PLACEHOLDER_RESCUE_SHAPE;
uint8_t qr_done         = QR_DONE_NONE;

static char    s_line[GM65_RX_BUF_SIZE];
static volatile uint8_t s_len;
static volatile uint8_t s_line_ready;
static uint8_t s_rx_byte;

/* -------------------------------------------------------------------------- */
void GM65_Reset(void)
{
    __disable_irq();
    s_len = 0U;
    s_line_ready = 0U;
    qr_done = QR_DONE_NONE;
    __enable_irq();
}

void GM65_Init(void)
{
    s_len = 0U;
    s_line_ready = 0U;
    s_rx_byte = 0U;
    (void)HAL_UART_Receive_IT(&huart1, &s_rx_byte, 1U);
}

uint8_t GM65_HasLine(void)
{
    return s_line_ready;
}

/* -------------------------------------------------------------------------- */
/* 中断里调用: 每收一个字节                                                      */
/* -------------------------------------------------------------------------- */
void GM65_OnRxByte(uint8_t byte)
{
    if ((byte == (uint8_t)'\r') || (byte == (uint8_t)'\n')) {
        if ((s_len > 0U) && (s_line_ready == 0U)) {
            s_line[s_len] = '\0';
            s_line_ready = 1U;               /* 交给主循环解析 */
        }
        return;
    }

    if (s_line_ready != 0U) {
        return;                              /* 上一行还没处理, 先丢掉 */
    }

    if (s_len < (GM65_RX_BUF_SIZE - 1U)) {
        s_line[s_len] = (char)byte;
        s_len++;
    } else {
        s_len = 0U;                          /* 太长: 丢弃重新来 */
    }
}

/* -------------------------------------------------------------------------- */
/* 主循环里调用: 有一整行就解析                                                 */
/* -------------------------------------------------------------------------- */
void GM65_Process(void)
{
    char    buf[GM65_RX_BUF_SIZE];
    uint8_t bomb = 0U, target = 0U, shape = 0U;

    if (s_line_ready == 0U) {
        return;
    }

    __disable_irq();
    for (uint8_t i = 0U; i < GM65_RX_BUF_SIZE; i++) {
        buf[i] = s_line[i];
        if (s_line[i] == '\0') {
            break;
        }
    }
    buf[GM65_RX_BUF_SIZE - 1U] = '\0';
    s_len = 0U;
    s_line_ready = 0U;
    __enable_irq();

    if (GM65_ParseString(buf, &bomb, &target, &shape) != 0U) {
        qr_bomb_color   = bomb;
        qr_target_color = target;
        qr_rescue_shape = shape;
        qr_done = QR_DONE_REAL;
    }
}

/* -------------------------------------------------------------------------- */
/* 解析三位数字                                                                */
/*   第1位 排爆物颜色 1/2/3                                                    */
/*   第2位 反恐靶颜色 1/2/3                                                    */
/*   第3位 救援目标形状 1/2/3                                                  */
/* -------------------------------------------------------------------------- */
uint8_t GM65_ParseString(const char *s, uint8_t *bomb_color,
                         uint8_t *target_color, uint8_t *rescue_shape)
{
    uint8_t digits[3];
    uint8_t n = 0U;

    if (s == NULL) {
        return 0U;
    }

    while ((*s != '\0') && (n < 3U)) {
        if ((*s >= '1') && (*s <= '3')) {
            digits[n] = (uint8_t)(*s - '0');
            n++;
        } else if ((*s == '0') || (*s == '4') || (*s == '5') ||
                   (*s == '6') || (*s == '7') || (*s == '8') || (*s == '9')) {
            return 0U;                       /* 出现了非法数字 */
        }
        /* 其它字符 (前后缀/空白) 直接跳过 */
        s++;
    }

    if (n != 3U) {
        return 0U;
    }

    if (bomb_color != NULL)   { *bomb_color = digits[0]; }
    if (target_color != NULL) { *target_color = digits[1]; }
    if (rescue_shape != NULL) { *rescue_shape = digits[2]; }
    return 1U;
}

/* -------------------------------------------------------------------------- */
/* 读码失败时用占位值 (app_config.h 里的宏)                                     */
/* -------------------------------------------------------------------------- */
void GM65_LoadPlaceholder(void)
{
    qr_bomb_color   = QR_PLACEHOLDER_BOMB_COLOR;
    qr_target_color = QR_PLACEHOLDER_TARGET_COLOR;
    qr_rescue_shape = QR_PLACEHOLDER_RESCUE_SHAPE;
    qr_done = QR_DONE_PLACEHOLDER;
}

/* -------------------------------------------------------------------------- */
/* HAL 回调 (整个工程只允许定义一次)                                            */
/* -------------------------------------------------------------------------- */
/* 接收完成: USART1 是 GM65 的单字节; USART2 是 DMA 缓冲绕回一圈 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        GM65_OnRxByte(s_rx_byte);
        (void)HAL_UART_Receive_IT(&huart1, &s_rx_byte, 1U);   /* 重新武装 */
    } else if (huart->Instance == USART2) {
        MaixLink_OnDmaEvent();
    }
}

/* DMA 半满 (用 ReceiveToIdle_DMA 时才有; 这里留着是为了以后切换方便) */
void HAL_UART_RxHalfCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART2) {
        MaixLink_OnDmaEvent();
    }
}

/* USART 出错 (溢出/噪声/帧错误): MaixCAM 这条链路重新武装, 不能卡死 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        (void)HAL_UART_Receive_IT(&huart1, &s_rx_byte, 1U);
    } else if (huart->Instance == USART2) {
        MaixLink_OnError();
    }
}
