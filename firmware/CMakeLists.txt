# =============================================================================
#  2026 广东省工科大学生实验综合技能竞赛 —— 赛项3 反恐排爆救援机器人
#  STM32F407VGT6 主控固件
#
#  构建:  cmake --preset Debug && cmake --build --preset Debug
#  或直接: cmake -B build/Debug -G Ninja -DCMAKE_BUILD_TYPE=Debug && cmake --build build/Debug
# =============================================================================
cmake_minimum_required(VERSION 3.22)

set(CMAKE_TOOLCHAIN_FILE "${CMAKE_CURRENT_SOURCE_DIR}/cmake/gcc-arm-none-eabi.cmake")

project(AntiTerrorRobot C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# 目标芯片 / HAL 配置
# ---------------------------------------------------------------------------
add_compile_definitions(
    USE_HAL_DRIVER
    STM32F407xx
)

# 板级自检: -DSELFTEST=ON 时上电先跑协议自检并通过串口打印结果
option(SELFTEST "上电运行协议自检" OFF)
if(SELFTEST)
    add_compile_definitions(SELFTEST_ENABLE=1)
    message(STATUS "已启用板级自检 SELFTEST_ENABLE=1")
endif()

set(LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/STM32F407VGTX_FLASH.ld")
set(STARTUP_FILE  "${CMAKE_SOURCE_DIR}/startup/startup_stm32f407xx.s")

# Cortex-M4F, 硬件浮点, 168MHz
set(MCU_FLAGS -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard)

add_compile_options(
    ${MCU_FLAGS}
    -Wall
    -fdata-sections
    -ffunction-sections
    -fno-strict-aliasing
)

add_link_options(
    ${MCU_FLAGS}
    -T${LINKER_SCRIPT}
    -specs=nano.specs
    -Wl,-Map=${CMAKE_PROJECT_NAME}.map,--cref
    -Wl,--gc-sections
    -Wl,--print-memory-usage
    -lc -lm
)

# ---------------------------------------------------------------------------
# 源文件
# ---------------------------------------------------------------------------
# --- 本工程代码 (Core) ---
set(APP_SOURCES
    Core/Src/main.c
    Core/Src/system_stm32f4xx.c
    Core/Src/stm32f4xx_it.c
    Core/Src/stm32f4xx_hal_msp.c
    Core/Src/protocol.c
    Core/Src/vision.c
    Core/Src/maix_link.c
    Core/Src/gm65.c
    Core/Src/bsp_led.c
    Core/Src/motion.c
    Core/Src/arm.c
    Core/Src/laser.c
    Core/Src/app_fsm.c
    Core/Src/debug.c
    Core/Src/syscalls.c
    Core/Src/selftest.c
)

# --- HAL 驱动 (只编译用得到的模块, 其余文件保留在 Drivers/ 备用) ---
set(HAL_SOURCES
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_cortex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_dma.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_dma_ex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_exti.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash_ex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash_ramfunc.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_gpio.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_iwdg.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr_ex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc_ex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim_ex.c
    Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_uart.c
)

add_executable(${CMAKE_PROJECT_NAME}
    ${APP_SOURCES}
    ${HAL_SOURCES}
    ${STARTUP_FILE}
)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Inc
    Drivers/STM32F4xx_HAL_Driver/Inc
    Drivers/STM32F4xx_HAL_Driver/Inc/Legacy
    Drivers/CMSIS/Device/ST/STM32F4xx/Include
    Drivers/CMSIS/Include
)

# ---------------------------------------------------------------------------
# 编译配置
# ---------------------------------------------------------------------------
target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE
    $<$<CONFIG:Debug>:-Og -g3 -gdwarf-2>
    $<$<CONFIG:Release>:-Os -g0>
    $<$<COMPILE_LANGUAGE:ASM>:-x assembler-with-cpp>
)

set_target_properties(${CMAKE_PROJECT_NAME} PROPERTIES
    OUTPUT_NAME "${CMAKE_PROJECT_NAME}"
    SUFFIX ".elf"
    LINK_DEPENDS "${LINKER_SCRIPT}"
)

# ---------------------------------------------------------------------------
# 生成 .hex / .bin / 打印尺寸
# ---------------------------------------------------------------------------
add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_PROJECT_NAME}.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
    COMMENT "生成 ${CMAKE_PROJECT_NAME}.hex / .bin"
)
