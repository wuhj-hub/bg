#!/bin/bash
# ============================================================
# skills 沙箱备份/恢复工具（解决沙箱周期性重置问题）
# ============================================================
# 备份:  将 /root/.skills 下自建skill的关键资产 → github_bg/skills_backup/
# 恢复:  从 skills_backup/ 恢复到 /root/.skills/
#
# 备份内容: SKILL.md + scripts/*.py + references/* + pools/*.json
# 排除:    outputs/缓存、__pycache__、*.pyc
# ============================================================
SKILLS_DIR="/root/.skills"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/skills_backup"
SELF_SKILLS="复盘报告 猛兽体系 盘前市场报告 双弦投资系统 双弦投资系统-月度股池 鱼身 wangbei-report wuwei-report xihu-report bo-duan-sao-miao duo-wei-du fish-body-trading 强势体系 个人23策略股票分析技能"

cmd="${1:-backup}"

if [ "$cmd" = "backup" ]; then
    mkdir -p "$BACKUP_DIR"
    echo "📦 备份自建skill → $BACKUP_DIR"
    for name in $SELF_SKILLS; do
        src="$SKILLS_DIR/$name"
        [ -d "$src" ] || continue
        dst="$BACKUP_DIR/$name"
        rm -rf "$dst"
        mkdir -p "$dst"
        # SKILL.md
        [ -f "$src/SKILL.md" ] && cp "$src/SKILL.md" "$dst/"
        # scripts（仅.py）
        if [ -d "$src/scripts" ]; then
            mkdir -p "$dst/scripts"
            cp "$src/scripts/"*.py "$dst/scripts/" 2>/dev/null
        fi
        # references
        if [ -d "$src/references" ]; then
            cp -r "$src/references" "$dst/" 2>/dev/null
        fi
        # pools（双弦月度股池）
        if [ -d "$src/pools" ]; then
            mkdir -p "$dst/pools"
            cp "$src/pools/"*.json "$dst/pools/" 2>/dev/null
        fi
        # 顶层其他配置文件（stock_pool等）
        cp "$src/"*.txt "$src/"*.csv "$dst/" 2>/dev/null
        echo "  ✅ $name ($(du -sh "$dst" 2>/dev/null | cut -f1))"
    done
    echo "✅ 备份完成 → $BACKUP_DIR"
    echo "   提交: cd github_bg && git add skills_backup && git commit -m 'skills备份' && git push"

elif [ "$cmd" = "restore" ]; then
    echo "♻️  从 $BACKUP_DIR 恢复自建skill → $SKILLS_DIR"
    for d in "$BACKUP_DIR"/*/; do
        name="$(basename "$d")"
        [ "$name" = "$(basename "$BACKUP_DIR")" ] && continue
        mkdir -p "$SKILLS_DIR/$name"
        cp -r "$d/." "$SKILLS_DIR/$name/" 2>/dev/null
        echo "  ✅ $name"
    done
    echo "✅ 恢复完成（SKILL.md + scripts + references + pools）"

else
    echo "用法: $0 [backup|restore]"
fi
