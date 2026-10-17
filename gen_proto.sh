#!/usr/bin/env bash

# 生成 python proto 绑定文件

uv run -m grpc_tools.protoc \
    -I./doubaoime_asr \
    --python_out=./doubaoime_asr \
    --pyi_out=./doubaoime_asr \
    ./doubaoime_asr/asr.proto