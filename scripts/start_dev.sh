#!/bin/bash
# Mini-Router 开发环境启动脚本 (YAML 模式)
# YAML 模式：配置从 config.yaml 加载，不连接数据库
# 使用 --config=config.yaml 启用 YAML 模式

set -e

echo "Starting mini-router in DEV mode (YAML config)"
echo "Config: config.yaml"

python -m mini_router.server --host 0.0.0.0 --port 8080 --config config.yaml