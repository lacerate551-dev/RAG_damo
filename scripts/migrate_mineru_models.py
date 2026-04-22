#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MinerU 模型迁移脚本

将 HuggingFace 缓存中的 MinerU 模型迁移到项目 models/ 目录
"""

import os
import shutil
import json
from pathlib import Path

# 项目根目录（脚本在 scripts/ 目录下，需要回到上级）
PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models" / "mineru"

# 当前配置文件路径
USER_CONFIG = Path.home() / "mineru.json"

def read_current_config():
    """读取当前配置"""
    if not USER_CONFIG.exists():
        print(f"❌ 配置文件不存在: {USER_CONFIG}")
        return None

    with open(USER_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)

def migrate_models():
    """迁移模型文件"""
    print("=" * 60)
    print("MinerU 模型迁移工具")
    print("=" * 60)

    # 读取当前配置
    config = read_current_config()
    if not config:
        return False

    models_dir_config = config.get('models-dir', {})
    if not models_dir_config:
        print("❌ 配置文件中没有 models-dir 配置")
        return False

    print(f"\n📂 当前模型路径:")
    for model_type, model_path in models_dir_config.items():
        print(f"  {model_type}: {model_path}")

    # 创建目标目录
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # 迁移每个模型
    new_config = {}
    for model_type, src_path in models_dir_config.items():
        src_path = Path(src_path)

        if not src_path.exists():
            print(f"\n⚠️  源路径不存在，跳过: {src_path}")
            continue

        # 目标路径
        dst_path = MODELS_DIR / model_type

        print(f"\n📦 迁移 {model_type} 模型...")
        print(f"  源: {src_path}")
        print(f"  目标: {dst_path}")

        # 检查目标是否已存在
        if dst_path.exists():
            print(f"  ⚠️  目标已存在，是否覆盖？(y/n): ", end='')
            choice = input().strip().lower()
            if choice != 'y':
                print(f"  ⏭️  跳过")
                new_config[model_type] = str(dst_path.absolute())
                continue
            else:
                shutil.rmtree(dst_path)

        # 复制模型文件
        try:
            shutil.copytree(src_path, dst_path)
            print(f"  ✅ 迁移成功")
            new_config[model_type] = str(dst_path.absolute())
        except Exception as e:
            print(f"  ❌ 迁移失败: {e}")
            return False

    if not new_config:
        print("\n❌ 没有成功迁移任何模型")
        return False

    # 更新配置文件
    print(f"\n📝 更新配置文件...")

    # 更新用户目录配置
    config['models-dir'] = new_config
    with open(USER_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print(f"  ✅ 已更新: {USER_CONFIG}")

    # 创建项目配置文件（使用相对路径）
    project_config_path = PROJECT_ROOT / "mineru.json"
    project_config = {
        "models-dir": {
            model_type: f"models/mineru/{model_type}"
            for model_type in new_config.keys()
        },
        "config_version": config.get("config_version", "1.3.1")
    }

    with open(project_config_path, 'w', encoding='utf-8') as f:
        json.dump(project_config, f, indent=4, ensure_ascii=False)
    print(f"  ✅ 已创建: {project_config_path}")

    # 显示新配置
    print(f"\n✅ 迁移完成！新的模型路径:")
    for model_type, model_path in new_config.items():
        print(f"  {model_type}: {model_path}")

    # 计算模型大小
    total_size = 0
    for model_type in new_config.keys():
        model_path = MODELS_DIR / model_type
        if model_path.exists():
            size = sum(f.stat().st_size for f in model_path.rglob('*') if f.is_file())
            total_size += size
            print(f"  {model_type} 大小: {size / 1024 / 1024:.1f} MB")

    print(f"\n📊 总大小: {total_size / 1024 / 1024:.1f} MB ({total_size / 1024 / 1024 / 1024:.2f} GB)")

    return True

def verify_migration():
    """验证迁移结果"""
    print("\n" + "=" * 60)
    print("验证迁移结果")
    print("=" * 60)

    # 检查项目配置文件
    project_config_path = PROJECT_ROOT / "mineru.json"
    if not project_config_path.exists():
        print("❌ 项目配置文件不存在")
        return False

    with open(project_config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    models_dir_config = config.get('models-dir', {})

    all_ok = True
    for model_type, model_path in models_dir_config.items():
        model_path = Path(model_path)
        if model_path.exists():
            print(f"✅ {model_type}: {model_path}")
        else:
            print(f"❌ {model_type}: {model_path} (不存在)")
            all_ok = False

    return all_ok

if __name__ == "__main__":
    import sys

    # Windows 控制台编码
    if sys.platform == 'win32':
        import locale
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')

    success = migrate_models()

    if success:
        verify_migration()
        print("\n🎉 迁移完成！现在可以删除 HuggingFace 缓存中的模型以节省空间。")
        print(f"\n💡 提示：")
        print(f"  1. 项目配置文件: {PROJECT_ROOT / 'mineru.json'}")
        print(f"  2. 模型目录: {MODELS_DIR}")
        print(f"  3. 环境变量: MINERU_MODEL_SOURCE=local")
    else:
        print("\n❌ 迁移失败")
        sys.exit(1)
