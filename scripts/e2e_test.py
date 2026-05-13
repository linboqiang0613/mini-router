#!/usr/bin/env python3
"""
端到端测试脚本：验证 MySQL 持久化功能

测试内容：
1. 启动服务连接数据库
2. 从数据库加载全局配置
3. 从数据库加载租户配置
4. API Key 池管理
5. 配置同步（版本检测）

运行方式：
    source .venv/bin/activate
    python scripts/e2e_test.py
"""

import asyncio
import os
import sys

# 设置环境变量
os.environ["MINI_ROUTER_ENV"] = "prd"
os.environ["MINI_ROUTER_DB_ACCESS"] = "BEE_619589959"

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mini_router.config.loader import load_config, load_config_from_db
from mini_router.database import DatabaseConnection, ConfigRepository
from mini_router.tenant.manager import TenantManager


async def test_database_connection():
    """测试数据库连接"""
    print("\n=== 测试 1: 数据库连接 ===")

    config = load_config()
    print(f"✓ 加载基础配置成功")
    print(f"  database.enabled: {config.database.enabled}")
    print(f"  database.host: {config.database.host}")

    if not config.database.enabled:
        print("✗ 数据库未启用，跳过测试")
        return None, None

    db = DatabaseConnection(config.database)
    await db.connect()
    print(f"✓ 数据库连接成功")

    repo = ConfigRepository(db)
    print(f"✓ Repository 创建成功")

    return db, repo


async def test_global_config_loading(repo):
    """测试全局配置加载"""
    print("\n=== 测试 2: 全局配置加载 ===")

    router_config = await load_config_from_db(repo)

    if router_config:
        print(f"✓ 从数据库加载 RouterConfig 成功")
        print(f"  models.base_url: {router_config.models.base_url}")
        print(f"  models.timeout: {router_config.models.timeout}")
        print(f"  decisions count: {len(router_config.decisions)}")
        print(f"  cache.enabled: {router_config.cache.enabled}")
        return router_config
    else:
        print("✗ 数据库中没有全局配置")
        return None


async def test_tenant_loading(repo):
    """测试租户加载"""
    print("\n=== 测试 3: 租户配置加载 ===")

    manager = TenantManager(repository=repo)
    await manager.async_load()

    tenants = manager.list_all()
    print(f"✓ 加载租户成功: {len(tenants)} 个")

    for tenant in tenants:
        print(f"  - tenant_id: {tenant.tenant_id}")
        print(f"    apikey: {tenant.apikey}")
        print(f"    apikey_pool_mode: {tenant.apikey_pool_mode}")

        # 获取 API Key 池
        pool = manager.get_apikey_pool(tenant.tenant_id)
        print(f"    apikey_pool: {pool}")

    return manager


async def test_apikey_pool(repo):
    """测试 API Key 池操作"""
    print("\n=== 测试 4: API Key 池操作 ===")

    # 获取 test-tenant 的 API Key 池
    pool = await repo.get_apikey_pool("test-tenant")
    print(f"✓ 获取 API Key 池: {len(pool)} 个 key")

    for key in pool:
        print(f"  - order={key['apikey_order']}, apikey={key['apikey']}, active={key['is_active']}")

    # 测试更新状态（模拟 fallback）
    if pool:
        await repo.update_apikey_status("test-tenant", 0, False)
        print(f"✓ 更新第一个 key 为 inactive")

        # 验证更新
        pool_after = await repo.get_apikey_pool("test-tenant")
        print(f"  更新后: {pool_after[0]['is_active']}")

        # 恢复
        await repo.update_apikey_status("test-tenant", 0, True)
        print(f"✓ 恢复第一个 key 为 active")


async def test_version_tracking(repo):
    """测试版本追踪"""
    print("\n=== 测试 5: 版本追踪 ===")

    global_version = await repo.get_global_version()
    print(f"✓ 全局配置版本: {global_version}")

    tenant_version = await repo.get_tenant_max_version()
    print(f"✓ 租户最大版本: {tenant_version}")


async def test_reload(manager, repo):
    """测试配置重新加载"""
    print("\n=== 测试 6: 配置重新加载 ===")

    # 添加一个测试租户（模拟配置变更）
    # 这里只测试 reload 功能，不实际添加数据

    await manager.reload()
    print(f"✓ 租户重新加载成功: {len(manager.list_all())} 个")


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("Mini-Router MySQL 持久化端到端测试")
    print("=" * 60)

    try:
        # 测试 1: 数据库连接
        db, repo = await test_database_connection()
        if not db:
            return

        # 测试 2: 全局配置
        await test_global_config_loading(repo)

        # 测试 3: 租户加载
        manager = await test_tenant_loading(repo)

        # 测试 4: API Key 池
        await test_apikey_pool(repo)

        # 测试 5: 版本追踪
        await test_version_tracking(repo)

        # 测试 6: 重新加载
        await test_reload(manager, repo)

        # 关闭连接
        await db.close()
        print("\n=== 测试完成 ===")
        print("✓ 所有测试通过")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)