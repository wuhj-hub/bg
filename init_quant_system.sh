#!/usr/bin/env bash
# ============================================================
# init_quant_system.sh —— A股量化体系一键初始化（workbuddy/沙箱通用）
# ============================================================
# 功能: 环境检查 → 拉取仓库 → 配置凭证 → 安装依赖 → 数据校验 → 技能恢复
# 用法: bash init_quant_system.sh [--token GITHUB_TOKEN] [--ima-client ID] [--ima-key KEY]
#      或通过环境变量 GITHUB_TOKEN / IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY 传入
# ============================================================
set -u

# ---------- 参数 ----------
WORK="${WORK_DIR:-/sandbox/workspace}"
REPO_URL="https://github.com/wuhj-hub/bg.git"
REPO_NAME="bg"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
IMA_CID="${IMA_OPENAPI_CLIENTID:-}"
IMA_KEY="${IMA_OPENAPI_APIKEY:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --token) GITHUB_TOKEN="$2"; shift 2;;
    --ima-client) IMA_CID="$2"; shift 2;;
    --ima-key) IMA_KEY="$2"; shift 2;;
    *) shift;;
  esac
done

echo "=============================================="
echo "🏛️ A股量化体系初始化 v3.0"
echo "工作目录: $WORK"
echo "=============================================="

# ---------- 1. 环境检查 ----------
echo ""
echo "[1/6] 环境检查"
MISSING=""
for cmd in python3 git; do
  if command -v $cmd >/dev/null 2>&1; then echo "  ✅ $cmd: $($cmd --version 2>&1 | head -1)"; else echo "  ❌ $cmd 缺失"; MISSING="$MISSING $cmd"; fi
done
if command -v node >/dev/null 2>&1; then echo "  ✅ node: $(node --version 2>&1)"; else echo "  ⚠️ node 缺失（westock npx 需要，GitHub Actions 自带）"; fi

# ---------- 2. 拉取仓库 ----------
echo ""
echo "[2/6] 拉取主仓库 ($REPO_NAME)"
mkdir -p "$WORK"
if [ -d "$WORK/$REPO_NAME/.git" ]; then
  echo "  仓库已存在，更新..."
  (cd "$WORK/$REPO_NAME" && git pull --rebase origin main 2>/dev/null || echo "  ⚠️ pull 失败（可忽略）")
else
  timeout 90 git clone --depth 1 "$REPO_URL" "$WORK/$REPO_NAME" 2>&1 | tail -1 || echo "  ⚠️ clone 超时/失败（脚本均可直接从GitHub API拉取，不阻塞）"
fi
[ -d "$WORK/$REPO_NAME/.git" ] && echo "  ✅ 仓库就绪" || echo "  ⚠️ 仓库未就绪（不影响后续：脚本走GitHub API）"

# ---------- 3. 配置凭证 ----------
echo ""
echo "[3/6] 凭证配置"
ENV_FILE="$WORK/.env"
IMA_FILE="$WORK/.env.ima"
if [ -z "$GITHUB_TOKEN" ] && [ -f "$ENV_FILE" ]; then
  GITHUB_TOKEN=$(grep '^GITHUB_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
fi
if [ -z "$GITHUB_TOKEN" ]; then
  echo "  ⚠️ 未提供 GITHUB_TOKEN（可留空，部分 GitHub API 功能受限）"
else
  echo "GITHUB_TOKEN=$GITHUB_TOKEN" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "  ✅ GitHub Token 已保存 (.env)"
fi
if [ -z "$IMA_CID" ] || [ -z "$IMA_KEY" ]; then
  if [ -f "$IMA_FILE" ]; then
    IMA_CID=$(grep '^IMA_OPENAPI_CLIENTID=' "$IMA_FILE" | cut -d= -f2-)
    IMA_KEY=$(grep '^IMA_OPENAPI_APIKEY=' "$IMA_FILE" | cut -d= -f2-)
  fi
fi
if [ -z "$IMA_CID" ] || [ -z "$IMA_KEY" ]; then
  echo "  ⚠️ 未提供 IMA 凭证（知识库上传不可用，报告生成/推送不受影响）"
else
  echo "IMA_OPENAPI_CLIENTID=$IMA_CID" > "$IMA_FILE"
  echo "IMA_OPENAPI_APIKEY=$IMA_KEY" >> "$IMA_FILE"
  chmod 600 "$IMA_FILE"
  echo "  ✅ IMA 凭证已保存 (.env.ima)"
fi

# ---------- 4. 依赖 ----------
echo ""
echo "[4/6] Python 依赖"
pip install -q pandas numpy pynacl 2>/dev/null || pip3 install -q pandas numpy pynacl 2>/dev/null || echo "  ⚠️ pip 安装失败（GitHub Actions 已自带 pandas/numpy）"
python3 -c "import pandas, numpy" 2>/dev/null && echo "  ✅ pandas+numpy" || echo "  ⚠️ pandas/numpy 不可用"
echo "  预热 westock（首次会下载包，约30秒）..."
npx -y westock-data-skillhub@1.0.3 hot board --limit 3 >/dev/null 2>&1 && echo "  ✅ westock 可用" || echo "  ⚠️ westock 预热失败（重试或检查网络）"

# ---------- 5. 数据校验 ----------
echo ""
echo "[5/6] 核心数据校验"
if [ ! -f "$WORK/all_mainboard.csv" ] && [ -n "$GITHUB_TOKEN" ]; then
  echo "  拉取 all_mainboard.csv ..."
  curl -s --max-time 60 -H "Authorization: token $GITHUB_TOKEN" \
    "https://api.github.com/repos/wuhj-hub/bg/contents/all_mainboard.csv" | \
    python3 -c "import json,sys,base64; d=json.load(sys.stdin); open('$WORK/all_mainboard.csv','wb').write(base64.b64decode(d['content']))" 2>/dev/null || true
fi
[ -f "$WORK/all_mainboard.csv" ] && echo "  ✅ all_mainboard.csv ($(wc -l < "$WORK/all_mainboard.csv") 行)" || echo "  ⚠️ all_mainboard.csv 缺失（手动拉取或运行 gen_mainboard.py）"
if [ ! -f "$WORK/hs300.csv" ] && [ -n "$GITHUB_TOKEN" ]; then
  curl -s --max-time 60 -H "Authorization: token $GITHUB_TOKEN" \
    "https://api.github.com/repos/wuhj-hub/bg/contents/quant_scripts/hs300.csv" | \
    python3 -c "import json,sys,base64; d=json.load(sys.stdin); open('$WORK/hs300.csv','wb').write(base64.b64decode(d['content']))" 2>/dev/null || true
fi
[ -f "$WORK/hs300.csv" ] && echo "  ✅ hs300.csv ($(wc -l < "$WORK/hs300.csv") 行)" || echo "  ⚠️ hs300.csv 缺失（回测用）"

# ---------- 6. 技能恢复（从 GitHub skills_backup） ----------
echo ""
echo "[6/6] 自建技能恢复（skills_backup → /root/.skills）"
SKILLS_DIR="${SKILLS_DIR:-/root/.skills}"
SELF_SKILLS="复盘报告 猛兽体系 盘前市场报告 双弦投资系统 双弦投资系统-月度股池 鱼身 wangbei-report wuwei-report xihu-report bo-duan-sao-miao duo-wei-du fish-body-trading 强势体系 个人23策略股票分析技能"
mkdir -p "$SKILLS_DIR"
RESTORED=0
if [ -n "$GITHUB_TOKEN" ]; then
  for skill in $SELF_SKILLS; do
    [ -f "$SKILLS_DIR/$skill/SKILL.md" ] && continue
    mkdir -p "$SKILLS_DIR/$skill/scripts"
    # SKILL.md
    curl -s --max-time 30 -H "Authorization: token $GITHUB_TOKEN" \
      "https://api.github.com/repos/wuhj-hub/bg/contents/skills_backup/$skill/SKILL.md" | \
      python3 -c "import json,sys,base64; d=json.load(sys.stdin); open('$SKILLS_DIR/$skill/SKILL.md','wb').write(base64.b64decode(d['content']))" 2>/dev/null && RESTORED=$((RESTORED+1))
    # scripts（列表拉取）
    curl -s --max-time 30 -H "Authorization: token $GITHUB_TOKEN" \
      "https://api.github.com/repos/wuhj-hub/bg/contents/skills_backup/$skill/scripts" | \
      python3 -c "
import json,sys,base64,urllib.request
try:
    d=json.load(sys.stdin)
    for f in d:
        if f.get('type')=='file' and f['name'].endswith('.py'):
            r=urllib.request.Request(f['download_url'])
            c=urllib.request.urlopen(r,timeout=20).read()
            open('$SKILLS_DIR/$skill/scripts/'+f['name'],'wb').write(c)
except Exception: pass
" 2>/dev/null || true
  done
fi
echo "  ✅ 恢复 $RESTORED 个技能 SKILL.md（其余已存在或跳过）"

# ---------- 完成 ----------
echo ""
echo "=============================================="
echo "✅ 初始化完成！"
echo "下一步操作:"
echo "  1. 校验一致性:  cd $WORK && python3 bg/quant_scripts/guard.py status"
echo "  2. 出盘前报告:  触发「盘前市场报告」技能（08:00-09:00）"
echo "  3. 股池扫描:    python3 bg/quant_scripts/caige_pool.py"
echo "  4. 每日自动:    GitHub Actions 15:30 全盘量化（无需本地）"
echo "=============================================="
