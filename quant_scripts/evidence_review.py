#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_review.py —— AI链标的 evidence 月度复核工作单生成器 (v1.0, 2026-09-05)
================================================================================
用途：每月对所有 *_pool.json（AI链30只 + 固态电池10只等）标的做 evidence（证据等级）复核。
背景：evidence 决定宁静守护层的"证据铁律"（无 strong/medium 则信号强制降一档），
      且 pool 内字段必须人工维护——公告/投关/研报会随时间改变标的证据状态。

用法：
  python3 evidence_review.py                 # 默认输出 outputs/evidence_review_{date}.md
  python3 evidence_review.py --out /path     # 指定输出目录
  python3 evidence_review.py --days 45       # 自定义"待复核"阈值(默认45天)

输出：按 优先级(过期>待复核>正常) × 子链 分组的复核工作单 md，
      每只列出：当前证据 / 上次核验 / 依据 / 待查关键词 / 建议动作。

SOP（每月1号）：
  1. 跑本脚本生成工作单 → PushPlus/微信查看
  2. 对 🟡/🔴 标的检索：巨潮公告(大单/长协/定点/量产/认证) > 投关记录表 > 互动易 > 券商研报
  3. 确认后手工更新对应 *_pool.json 的 evidence / evidence_note / evidence_date 三项
  4. 推送 GitHub（evidence 是唯一人工字段，guard/仲裁全自动引用）
"""
import json, os, sys
from datetime import datetime, date

_DIR = os.path.dirname(os.path.abspath(__file__))
def _all_pools():
    """同目录所有 *_pool.json（多池合并）"""
    files = sorted(os.path.join(_DIR, fn) for fn in os.listdir(_DIR) if fn.endswith("_pool.json"))
    return files or [os.path.join(_DIR, "ai_chain_pool.json")]

# 升级路径建议（weak→medium→strong 需要什么证据）
UPGRADE_HINT = {
    "strong": "已最强，无需升级；仅确认无新增利空(立案/质押爆雷/替代技术量产)可维持",
    "medium": "升级strong需：公司公告大单/长协/定点/量产交付/认证通过，或投关记录表/互动易亲口确认产能客户良率",
    "weak":   "升级medium需：券商深度研报(含盈利预测)或权威财经媒体(财联社/上证报)报道；升级strong需再找到公司级公告/投关确认",
}
# 每类证据对应优先检索源
EVIDENCE_SRC = {
    "strong": "✅ 已是strong：维护性复查（公告有无新大单/认证延期/客户变更）",
    "medium": "🔍 查公司公告(巨潮)是否有 订单/长协/定点/量产/认证 措辞 → 有则升strong；无则维持medium",
    "weak":   "⚠️ 弱证据：查投关记录表/互动易官方回复/券商深度研报 → 有实质内容升medium，仍无则考虑移出池或标注观察",
}


def norm_date(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def search_kw(info):
    """生成待查关键词"""
    base = [info.get("segment", ""), info.get("note", "")]
    kws = ["订单", "量产", "定点", "认证", "扩产"]
    return base + kws


def main():
    out_dir = "outputs"
    days = 45
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out_dir = argv[i + 1]
        if a == "--days" and i + 1 < len(argv):
            days = int(argv[i + 1])

    stocks = []
    for _pf in _all_pools():
        try:
            stocks.extend(json.load(open(_pf, encoding="utf-8"))["stocks"])
        except Exception as e:
            print(f"[evidence] 读取池 {_pf} 失败: {e}")
    today = date.today()
    L = []
    A = L.append
    A(f"# 🔍 AI链 evidence 月度复核工作单 · {today}")
    A("")
    A(f"> 池内 {len(stocks)} 只主板卡位链标的 · 阈值：> {days} 天未核验 = 🟡待复核，> {days * 2} 天 = 🔴过期")
    A("> SOP：对 🟡/🔴 标的检索 公告(巨潮) > 投关记录表 > 互动易 > 券商研报 → 更新对应 *_pool.json 的 evidence/evidence_note/evidence_date")
    A("")
    # 分组：优先级排序
    def prio(s):
        ed = norm_date(s.get("evidence_date"))
        if not ed:
            return 0  # 无日期最优先
        gap = (today - ed).days
        if gap > days * 2:
            return 0
        if gap > days:
            return 1
        return 2
    by_chain = {}
    for s in stocks:
        by_chain.setdefault(s.get("chain", "未分类"), []).append(s)
    total_y = total_r = 0
    for chain, items in sorted(by_chain.items()):
        A(f"## {chain}（{len(items)}只）")
        A("")
        A("| 代码 | 名称 | 环节 | 证据 | 上次核验 | 状态 | 建议动作 |")
        A("|---|---|---|---|---|---|---|")
        for s in sorted(items, key=lambda x: (prio(x), x["code"])):
            ed = norm_date(s.get("evidence_date"))
            ev = s.get("evidence", "medium")
            if not ed:
                st, mark = "🔴 无日期", 0
            else:
                gap = (today - ed).days
                if gap > days * 2:
                    st, mark = f"🔴 过期{gap}天", 0
                elif gap > days:
                    st, mark = f"🟡 {gap}天未核", 1
                else:
                    st, mark = f"✅ {gap}天前", 2
            total_r += mark == 0
            total_y += mark == 1
            action = UPGRADE_HINT.get(ev, "查公告确认是否有升级证据")
            A(f"| {s['code']} | {s['name']} | {s['segment']} | {ev} | {s.get('evidence_date','—')} | {st} | {action} |")
        A("")
    A("---")
    A("")
    A("## 📋 逐只检索指引（按优先级从上到下）")
    A("")
    for chain, items in sorted(by_chain.items()):
        for s in sorted(items, key=lambda x: (prio(x), x["code"])):
            ed = norm_date(s.get("evidence_date"))
            gap = (today - ed).days if ed else 999
            if gap <= days:
                continue  # 正常的不展开
            ev = s.get("evidence", "medium")
            kw = " / ".join(str(x) for x in search_kw(s) if x)
            A(f"### {'🔴' if gap > days*2 else '🟡'} {s['code']} {s['name']}（{chain}·{s['segment']}）")
            A(f"- 当前证据：**{ev}**｜上次核验：{s.get('evidence_date','—')}｜依据：{s.get('evidence_note','—')}")
            A(f"- {EVIDENCE_SRC.get(ev, '')}")
            A(f"- 待查关键词：{kw}")
            A("")
    A(f"---")
    A("")
    A(f"**汇总：🔴 过期/无日期 {total_r} 只 ｜ 🟡 待复核 {total_y} 只 ｜ ✅ 正常 {len(stocks) - total_r - total_y} 只**")
    A("")
    A("> 维护提示：evidence 是宁静守护层的唯一人工字段。升级/降级后同步推送 GitHub（guard/仲裁/盘前③.4/复盘③.9 全自动引用）。")
    os.makedirs(out_dir, exist_ok=True)
    fname = os.path.join(out_dir, f"evidence_review_{today}.md")
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[OK] 复核工作单已生成: {fname}")
    print(f"[汇总] 池内 {len(stocks)} 只 | 🔴过期/无日期 {total_r} | 🟡待复核 {total_y} | ✅正常 {len(stocks)-total_r-total_y}")


if __name__ == "__main__":
    main()
