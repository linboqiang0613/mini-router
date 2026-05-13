#!/bin/bash
# Mini-Router 开发环境启动脚本
# 使用 YAML 配置，不连接数据库

set -e

export MINI_ROUTER_ENV=dev

echo "Starting mini-router in DEV mode (YAML config)"
echo "Config: config/config_dev.yaml"

python -m mini_router.server --host 0.0.0.0 --port 8080