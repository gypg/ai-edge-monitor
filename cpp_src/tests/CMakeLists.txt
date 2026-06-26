# Tests — simple assert-based runner, no external dependencies.
add_executable(test_ai_edge test_main.cpp)
target_link_libraries(test_ai_edge PRIVATE ai_edge_native)

# Memory diagnostics test runner (for Valgrind)
add_executable(test_runner
    test_main.cpp
    test_leak_detector_cpp.cpp
    test_gpu_tracker_cpp.cpp
)
target_link_libraries(test_runner PRIVATE ai_edge_native)
target_include_directories(test_runner PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
)
target_compile_options(test_runner PRIVATE -g -O0)
if(NOT CMAKE_CXX_COMPILER_ID MATCHES "MSVC")
    target_link_options(test_runner PRIVATE -g)
endif()

# Register with CTest so `ctest --test-dir build` works.
enable_testing()
add_test(NAME ai_edge_tests COMMAND test_ai_edge)
add_test(NAME memory_diagnostics_tests COMMAND test_runner)
