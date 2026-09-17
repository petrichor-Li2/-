#[[
  GCC ARM Embedded toolchain file  (STM32CubeCLT / STM32CubeIDE style)

  若你的工具链不在下列位置，可用 -DARM_TOOLCHAIN_DIR=<bin 目录> 覆盖，
  或直接把 arm-none-eabi-gcc 加入系统 PATH。
]]

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

#
# 在常见安装位置自动寻找 xPack / STM32CubeCLT 工具链
#
if(NOT DEFINED ARM_TOOLCHAIN_DIR)
  foreach(_cand
      "D:/STM32CubeCLT_1.18.0/GNU-tools-for-STM32/bin"
      "C:/ST/STM32CubeCLT_1.18.0/GNU-tools-for-STM32/bin"
      "$ENV{LOCALAPPDATA}/Programs/xpack-arm-none-eabi-gcc"
      "C:/Program Files (x86)/Arm GNU Toolchain arm-none-eabi"
      "C:/Program Files/Arm GNU Toolchain arm-none-eabi")
    if(EXISTS "${_cand}/arm-none-eabi-gcc.exe")
      set(ARM_TOOLCHAIN_DIR "${_cand}")
      break()
    endif()
  endforeach()
endif()

if(DEFINED ARM_TOOLCHAIN_DIR)
  set(_ARM_PREFIX "${ARM_TOOLCHAIN_DIR}/arm-none-eabi-")
  message(STATUS "使用 ARM 工具链目录: ${ARM_TOOLCHAIN_DIR}")
else()
  set(_ARM_PREFIX "arm-none-eabi-")
  message(STATUS "使用 PATH 中的 arm-none-eabi-* 工具")
endif()

# Windows 上必须给出带 .exe 的完整路径, CMake 才不会说"不是完整路径"
set(_ARM_EXE "")
if(CMAKE_HOST_WIN32 AND EXISTS "${_ARM_PREFIX}gcc.exe")
  set(_ARM_EXE ".exe")
endif()

set(CMAKE_C_COMPILER   "${_ARM_PREFIX}gcc${_ARM_EXE}")
set(CMAKE_ASM_COMPILER "${_ARM_PREFIX}gcc${_ARM_EXE}")
set(CMAKE_CXX_COMPILER "${_ARM_PREFIX}g++${_ARM_EXE}")

set(CMAKE_OBJCOPY "${_ARM_PREFIX}objcopy${_ARM_EXE}" CACHE INTERNAL "")
set(CMAKE_SIZE    "${_ARM_PREFIX}size${_ARM_EXE}"    CACHE INTERNAL "")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

set(CMAKE_EXECUTABLE_SUFFIX ".elf")
