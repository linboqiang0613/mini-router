#!/bin/bash
# Mini-Router 生产环境启动脚本
# 连接 MySQL 数据库，配置从数据库加载

set -e

export MINI_ROUTER_ENV=prd
export MINI_ROUTER_DB_ACCESS="BEE_619589959"

# 可选：调整轮询间隔
# export MINI_ROUTER_GLOBAL_POLL_INTERVAL=120
# export MINI_ROUTER_TENANT_POLL_INTERVAL=10

echo "Starting mini-router in PRD mode (MySQL config)"
echo "Database: 1.94.232.185:3306/mini_router"

python -m mini_router.server --host 0.0.0.0 --port 8080