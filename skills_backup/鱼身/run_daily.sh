#!/bin/bash
# 🐟 鱼身交易系统 · 每日定时扫描脚本
# 每天工作日8:00由 crontab 自动触发
# 使用扩大版股票池（~120只），结果上传到多维量化知识库

SCRIPT_DIR="/sandbox/workspace/skills/鱼身/scripts"
POOL_FILE="/sandbox/workspace/skills/鱼身/stock_pool.txt"
OUTPUT_DIR="/sandbox/workspace/outputs"
LOG_DIR="/sandbox/workspace/logs"
LOG_FILE="${LOG_DIR}/鱼身_每日扫描.log"

# 确保目录存在
mkdir -p "${OUTPUT_DIR}" "${LOG_DIR}"

# 写入日志头
echo "========================================" >> "${LOG_FILE}"
echo "🐟 鱼身每日扫描 $(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"
echo "========================================" >> "${LOG_FILE}"

# 检查是否为交易日（简单的日期检查 - 周六日不运行）
DOW=$(date '+%u')
if [ "${DOW}" -gt 5 ]; then
    echo "⏭️  非交易日（周${DOW}），跳过扫描" >> "${LOG_FILE}"
    exit 0
fi

# 运行扫描
echo "📡 开始扫描 (股票池: ${POOL_FILE})" >> "${LOG_FILE}"
cd /sandbox/workspace

python3 "${SCRIPT_DIR}/fish_body_enhanced.py" --pool "${POOL_FILE}" 2>&1 | tee -a "${LOG_FILE}"

SCAN_EXIT=${PIPESTATUS[0]}
if [ "${SCAN_EXIT}" -eq 0 ]; then
    echo "✅ 扫描完成 $(date '+%H:%M:%S')" >> "${LOG_FILE}"
else
    echo "❌ 扫描异常退出 (exit=${SCAN_EXIT}) $(date '+%H:%M:%S')" >> "${LOG_FILE}"
fi

echo "" >> "${LOG_FILE}"

# 保留最近30天日志
find "${LOG_DIR}" -name "鱼身_每日扫描.log" -mtime +30 -delete 2>/dev/null

exit ${SCAN_EXIT}