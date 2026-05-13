#!/bin/bash
# Mini-Router 开发环境启动脚本 (数据库模式)
# 数据库模式：配置从 MySQL 数据库加载
# 使用 --env=dev 选择 config/envs_dev.yaml 作为数据库连接配置

set -e

export MINI_ROUTER_DB_ACCESS="BEE_619589959"

echo "Starting mini-router in DEV mode (MySQL config)"
echo "Database: localhost:3306/mini_router"
echo "Env config: config/envs_dev.yaml"

python -m mini_router.server --host 0.0.0.0 --port 8080 --env dev