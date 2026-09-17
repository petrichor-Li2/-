/**
  ******************************************************************************
  * @file    syscalls.c
  * @brief   newlib 最小系统调用桩 (防止 vsnprintf 等函数链接时找不到 _sbrk/_write)
  ******************************************************************************
  */
#include <sys/stat.h>
#include <stdlib.h>
#include <errno.h>
#include <stdio.h>
#include <signal.h>
#include <time.h>
#include <sys/time.h>
#include <sys/times.h>

#undef errno
extern int errno;

extern int __io_putchar(int ch) __attribute__((weak));
extern int __io_getchar(void) __attribute__((weak));

register char *stack_ptr asm("sp");

char *__env[1] = {0};
char **environ = __env;

/* -------------------------------------------------------------------------- */
int _close(int file)
{
    (void)file;
    return -1;
}

int _fstat(int file, struct stat *st)
{
    (void)file;
    st->st_mode = S_IFCHR;
    return 0;
}

int _isatty(int file)
{
    (void)file;
    return 1;
}

int _lseek(int file, int ptr, int dir)
{
    (void)file; (void)ptr; (void)dir;
    return 0;
}

int _read(int file, char *ptr, int len)
{
    (void)file; (void)ptr; (void)len;
    return 0;
}

int _write(int file, char *ptr, int len)
{
    int i;

    if (__io_putchar != NULL) {
        for (i = 0; i < len; i++) {
            (void)__io_putchar(*ptr++);
        }
    }
    (void)file;
    return len;
}

int _getpid(void)
{
    return 1;
}

int _kill(int pid, int sig)
{
    (void)pid; (void)sig;
    errno = EINVAL;
    return -1;
}

void _exit(int status)
{
    (void)status;
    _kill(status, -1);
    while (1) {
    }
}

/* -------------------------------------------------------------------------- */
/* 堆: 从链接脚本的 _end 往上涨 (本工程基本不用 malloc)                        */
/* -------------------------------------------------------------------------- */
caddr_t _sbrk(int incr)
{
    extern char _end;
    static unsigned char *heap = NULL;
    unsigned char *prev_heap;

    if (heap == NULL) {
        heap = (unsigned char *)&_end;
    }
    prev_heap = heap;

    /* 堆撞到栈就返回失败 */
    if ((heap + incr) > (unsigned char *)stack_ptr) {
        errno = ENOMEM;
        return (caddr_t)-1;
    }

    heap += incr;
    return (caddr_t)prev_heap;
}

int _gettimeofday(struct timeval *tv, void *tz)
{
    (void)tv; (void)tz;
    errno = EINVAL;
    return -1;
}

int _times(struct tms *buf)
{
    (void)buf;
    return -1;
}

int _stat(const char *file, struct stat *st)
{
    (void)file;
    st->st_mode = S_IFCHR;
    return 0;
}
