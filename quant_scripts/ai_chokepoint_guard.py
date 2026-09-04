#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_chokepoint_guard.py —— 宁静AI卡位守护层 (v1.0.0, 2026-09-04)
定位: signal_arbiter 的横向"题材质地裁决层", 只在 AI链标的池内生效。
规则(对齐 serenity三件套_A股落地包):
  卡位分 = pool.base(0-80: 不可替代+供给紧+政策) + relabel未定价分(0-20, 按120日涨幅自动)
  ├─ 卡位分 ≥80 → pts +1   (题材确认: 卡位强+未充分relabel)
  ├─ 卡位分 <60 → pts -1   (题材劣质: 卡位弱或已过度relabel)
  ├─ evidence 非 strong/medium → 强制降一档 (证据铁律: 叙事强订单弱=降权)
  ├─ 不在池内 → 不干预 (宁静层只对AI链标的生效)
  └─ 罚分项(微盘/质押/解禁/杀猪盘) → 由 trade_guard risk 层处理, 不重复
用法: python3 ai_chokepoint_guard.py <仲裁latest.json>   # 独立回放
      from ai_chokepoint_guard import apply_chokepoint_guard  # 接入仲裁
"""
import json, os, subprocess, sys

POOL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_chain_pool.json")

def _norm(code):
    code = str(code).strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code

def load_pool(path=None):
    p = path or POOL_PATH
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        idx = {}
        for s in d.get("stocks", []):
            idx[_norm(s["code"])] = s
        return idx, d.get("relabel_scoring", ""), d.get("guard_rules", "")
    except Exception as e:
        print(f"[宁静守护] 读取池失败: {e}")
        return {}, "", ""

def fetch_chg120(code):
    """近120交易日区间涨幅(%). 失败返回 None. 自动补 sh/sz 前缀."""
    code = str(code).strip().lower()
    if not code.startswith(("sh", "sz", "bj")):
        code = ("sh" if code.startswith(("6", "9")) else "sz") + code
    try:
        r = subprocess.run(["npx", "westock-data-skillhub@1.0.3", "kline", code,
                            "--limit", "130"], capture_output=True, text=True, timeout=90)
        out = r.stdout
        if "执行失败" in out or "数据为空" in out or r.returncode != 0:
            return None
        rows = []
        for blk in out.split("\n\n"):
            lines = [l for l in blk.splitlines() if l.strip()]
            if not lines or not lines[0].startswith("|"):
                continue
            hdr = [h.strip() for h in lines[0].strip("|").split("|")]
            for l in lines[2:]:
                vals = [v.strip() for v in l.strip("|").split("|")]
                if len(vals) == len(hdr):
                    rows.append(dict(zip(hdr, vals)))
        if len(rows) < 2:
            return None
        cur = float(rows[0]["last"])
        # 找120根前(即索引120, 存在才用)
        base = None
        for i in (120, 60, 20):
            if len(rows) > i:
                base = float(rows[i]["last"])
                break
        if not base or base <= 0:
            return None
        return (cur / base - 1) * 100
    except Exception:
        return None

def relabel_score(chg120):
    """未定价分(0-20): 涨幅越大=relabel越充分=分越低. chg120=None(数据缺失)返回None→不裁决"""
    if chg120 is None:
        return None
    if chg120 < 30: return 18
    if chg120 < 60: return 14
    if chg120 < 100: return 10
    if chg120 < 200: return 6
    return 2

def downgrade_level(level):
    """级别降一档: ★★★→★★ / ★★→★ / ★→观察 / 观察→观察(不动)"""
    lv = str(level)
    if lv.startswith("★★★"): return lv.replace("★★★", "★★", 1)
    if lv.startswith("★★"): return lv.replace("★★", "★", 1)
    if lv.startswith("★"): return lv.replace("★", "观察", 1)
    return lv  # 观察及特殊降级态不再降

def apply_chokepoint_guard(ranked, pool_path=None, skip_fetch=False, chg_cache=None):
    """
    对 ranked(list[dict] 含 code/pts/level/src) 施加宁静卡位裁决。
    返回 (ranked, logs)。仅在池内标的上生效; 所有异常不阻断主流程。
    """
    pool, _, _ = load_pool(pool_path)
    if not pool:
        return ranked, []
    logs = []
    chg_cache = chg_cache if chg_cache is not None else {}
    for r in ranked:
        c = _norm(r.get("code", ""))
        info = pool.get(c)
        if not info:
            continue
        # 1) 卡位分
        chg = chg_cache.get(c)
        if chg is None and not skip_fetch:
            chg = fetch_chg120(c)
            chg_cache[c] = chg
        rs = relabel_score(chg)
        cp_score = int(info.get("base", 50)) + rs if rs is not None else None
        # 2) 证据等级
        ev = str(info.get("evidence", "medium")).lower()
        ev_ok = ev in ("strong", "medium")
        name = info.get("name", c)
        chain = info.get("chain", "")
        coef = float(info.get("coef", 1.0))
        upstream = coef >= 0.78  # 上游层(材料/制程/设备/器件)才适用卡位阈值判定; 下游(模块/集成)信号自决
        # 3) 裁决: 上游层 ±1; 下游层仅证据铁律
        if upstream and cp_score is not None:
            if cp_score >= 80:
                r["pts"] = int(r.get("pts", 0)) + 1
                r["src"].append(f"宁静卡位{cp_score}(题材确认)")
                logs.append(f"🔗 {name}({c}) 宁静卡位{cp_score}≥80 → pts+1（{chain}·{info.get('segment','')}）")
            elif cp_score < 60:
                r["pts"] = int(r.get("pts", 0)) - 1
                r["src"].append(f"宁静卡位{cp_score}(题材劣质)")
                logs.append(f"🔗 {name}({c}) 宁静卡位{cp_score}<60 → pts-1（{chain}·{info.get('segment','')}）")
            else:
                logs.append(f"🔗 {name}({c}) 宁静卡位{cp_score}（60-79中性，信号自决）")
        elif upstream and cp_score is None:
            logs.append(f"🔗 {name}({c}) 行情缺失→不裁决（数据铁律）")
        elif not upstream and cp_score is not None:
            logs.append(f"🔗 {name}({c}) 卡位{cp_score}（{info.get('tier','')}层，信号自决）")
        if not ev_ok:
            old = r.get("level", "观察")
            new = downgrade_level(old)
            if new != old:
                r["level"] = new
                r["env_note"] = f"宁静证据铁律:无强/中证据"
                r["src"].append("宁静证据弱→降级")
                logs.append(f"🔗 {name}({c}) 证据仅'{ev}' → 强制降一档 {old}→{new}（证据铁律）")
        # 4) 备注字段
        r.setdefault("chokepoint", {})["score"] = cp_score
        r["chokepoint"]["evidence"] = ev
        r["chokepoint"]["chain"] = chain
        r["chokepoint"]["tier"] = info.get("tier", "")
        r["chokepoint"]["coef"] = coef
        if chg is not None:
            r["chokepoint"]["chg120"] = f"{chg:+.0f}%"
    if logs:
        print(f"[宁静守护] {len(logs)} 条AI链标的裁决 → " + " | ".join(logs[:4]) + (" …" if len(logs) > 4 else ""))
    return ranked, logs

def replay(json_path):
    """独立回放: 读 信号仲裁_latest.json 的 ranked, 展示守护层前后对比"""
    with open(json_path, encoding="utf-8") as f:
        js = json.load(f)
    ranked = list(js.get("ranked", []))
    print(f"回放: {json_path} — ranked {len(ranked)} 条")
    # 找出池内标的的当前状态
    pool, _, _ = load_pool()
    hit = [r for r in ranked if _norm(r.get("code", "")) in pool]
    print(f"池内命中: {len(hit)} 条 →")
    for r in hit:
        info = pool[_norm(r["code"])]
        print(f"  {r['code']} {info['name']}: pts={r['pts']} {r['level']} | {info['segment']} ev={info['evidence']} base={info['base']}")
    print("\n--- 施加守护层 ---")
    ranked2, logs = apply_chokepoint_guard(ranked)
    print("\n".join(logs) if logs else "(无调整)")
    print("\n--- 调整后池内标的 ---")
    for r in ranked2:
        if _norm(r.get("code", "")) in pool:
            ck = r.get("chokepoint", {})
            print(f"  {r['code']} {pool[_norm(r['code'])]['name']}: pts={r['pts']} {r['level']} | 卡位{ck.get('score')} ev={ck.get('evidence')} chg120={ck.get('chg120')}")

def daily_watch(four_dim_path=None, out_dir=None, date_str=None):
    """
    AI卡位每日观察清单: 池内30只主板AI链标的 × 四维共振状态 → 卡位分/信号分层
    输入: 四维共振_latest.json (全市场扫描, 池内标的的共振状态)
    输出: 按卡位分排序的观察清单 (卡位分 由 base + relabel120日涨幅 计算)
    """
    pool, _, _ = load_pool()
    if not pool:
        return []
    four = {}
    if four_dim_path and os.path.exists(four_dim_path):
        try:
            d = json.load(open(four_dim_path, encoding="utf-8"))
            for s in d.get("stocks", []):
                four[_norm(s.get("code", ""))] = s
        except Exception as e:
            print(f"[宁静守护] 读四维共振失败: {e}")
    rows = []
    for code, info in pool.items():
        chg = fetch_chg120(code)
        rs = relabel_score(chg)
        cp = int(info.get("base", 50)) + rs if rs is not None else None
        f = four.get(code, {})
        rows.append({
            "code": code, "name": info.get("name", ""),
            "chain": info.get("chain", ""), "segment": info.get("segment", ""),
            "tier": info.get("tier", ""), "coef": info.get("coef", 1.0),
            "base": info.get("base", 50), "relabel": rs, "chokepoint": cp,
            "evidence": info.get("evidence", ""),
            "four_dim_total": f.get("total", 0), "four_dim_level": f.get("level", "无共振"),
            "chg120": f"{chg:+.0f}%" if chg is not None else "N/A",
            "note": info.get("note", ""), "evidence_note": info.get("evidence_note", "")
        })
    rows.sort(key=lambda x: (-(x["chokepoint"] if x["chokepoint"] is not None else 0), -x["four_dim_total"]))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        today = date_str or __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        with open(os.path.join(out_dir, f"ai_chokepoint_watch_{today}.json"), "w", encoding="utf-8") as f:
            json.dump({"date": today, "rows": rows}, f, ensure_ascii=False, indent=1)
        # md 摘要
        L = [f"# 🔗 AI卡位每日观察 {today}", "",
             f"> 池内 {len(rows)} 只主板AI链标的 · 卡位分=base(不可替代/供给/政策)+relabel(120日涨幅) · 证据铁律:无强/中证据降级", ""]
        L.append("| 代码 | 名称 | 子链 | 环节 | 卡位分 | 四维信号 | 证据 | 120日 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in rows[:25]:
            sig = f"{r['four_dim_total']}·{r['four_dim_level']}" if r["four_dim_total"] > 0 else "—"
            ck = r['chokepoint'] if r['chokepoint'] is not None else "N/A"
            L.append(f"| {r['code']} | {r['name']} | {r['chain']} | {r['segment']} | **{ck}** | {sig} | {r['evidence']} | {r['chg120']} |")
        with open(os.path.join(out_dir, f"ai_chokepoint_watch_{today}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        print(f"[宁静守护] 观察清单已写: {os.path.join(out_dir, f'ai_chokepoint_watch_{today}.json')}")
    return rows

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--daily":
            four = sys.argv[2] if len(sys.argv) > 2 else "四维共振_latest.json"
            out = sys.argv[3] if len(sys.argv) > 3 else "outputs"
            dstr = None
            if "--date" in sys.argv:
                dstr = sys.argv[sys.argv.index("--date") + 1]
            daily_watch(four, out, dstr)
        else:
            replay(sys.argv[1])
    else:
        print("用法: python3 ai_chokepoint_guard.py <信号仲裁_latest.json>  |  --daily [四维共振.json] [out_dir] [--date YYYY-MM-DD]")
