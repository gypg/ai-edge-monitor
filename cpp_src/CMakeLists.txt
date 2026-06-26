cmake_minimum_required(VERSION 3.14)
project(ai_edge_native VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Options
option(ENABLE_NEON "Enable ARM NEON SIMD" OFF)
option(ENABLE_AVX2 "Enable x86 AVX2 SIMD" OFF)
option(BUILD_TESTS "Build unit tests" ON)
option(BUILD_PYTHON "Build pybind11 Python bindings" OFF)

# Source files
set(SOURCES
    system_info.cpp
    memory_monitor.cpp
    optimized_kernels.cpp
)

# Static library
add_library(ai_edge_native STATIC ${SOURCES})
target_include_directories(ai_edge_native PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# Platform-specific flags
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm")
    message(STATUS "ARM target detected")
    if(ENABLE_NEON)
        target_compile_options(ai_edge_native PRIVATE -mfpu=neon)
        target_compile_definitions(ai_edge_native PRIVATE AI_EDGE_HAS_NEON=1)
    endif()
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64")
    message(STATUS "x86_64 target detected")
    if(ENABLE_AVX2)
        target_compile_options(ai_edge_native PRIVATE -mavx2 -mfma)
        target_compile_definitions(ai_edge_native PRIVATE AI_EDGE_HAS_AVX2=1)
    endif()
endif()

# Install
install(TARGETS ai_edge_native ARCHIVE DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)

# Tests
if(BUILD_TESTS)
    add_subdirectory(tests)
endif()

# Python bindings
if(BUILD_PYTHON)
    add_subdirectory(pybind)
endif()
