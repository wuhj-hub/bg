#!/usr/bin/env python3
"""六套信号仲裁器（signal_arbiter）—— B1 待办落地 2026-08-11

背景：体系有六套独立信号（猛兽/鱼身/武威/乾坤/反转/四维共振），各自输出标的，
冲突时无统一优先级 → 资金分配靠人工判断。

仲裁规则（优先级即权重）：
  P0  四维共振★★高置信(≥7分)      +3   证据链闭合（政策/资金/筹码/关联方四维独立同向）
  P0  猛兽 Setup≥60               +3   强度最高（领先股档）
  P1  猛兽 Setup≥50               +2
  P1  乾坤A级金股                  +2   资金强攻+业绩共振
  P1  鱼身 空中加油(final≥70)      +2   买点时机
  P2  猛兽 Setup≥40 / 伏击/RS_D/G点 +1
  P2  鱼身 回踩/突破               +1
  P2  双弦共振                     +1
  P3  四维★弱共振(4-6分)           +1
  反向：四维否决 → -3（强制降级观察）

分级：≥7 ★★★全信号共振(重仓候选≤15%) / 5-6 ★★多信号(标准仓≤10%) / 3-4 ★双信号(轻仓≤5%) / <3 观察

前置过滤：月线闸门（对TOP20逐只检查：PASS多头/WARN纠缠/BLOCK空头；BLOCK降级标注）

数据源（容错：缺失跳过）：
  四维 = outputs/四维共振_latest.json（全市场3032只）
  鱼身 = outputs/fish_body_latest.json / fish_body_enhanced_*.json
  猛兽 = quant_results beast.stdout 的Setup表（代码/名称/总分/伏击/RS_D/模式/高阳列）
  双弦 = pools/pool_YYYY-MM.json（entries）
  乾坤 = qiankun_a_latest.json（容错缺失）
  反转 = 暂无结构化输出（留接口）

用法: python3 signal_arbiter.py [--top 20]
输出: outputs/信号仲裁_{date}.md + outputs/信号仲裁_latest.json
"""
import json, os, re, subprocess, sys, time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "outputs"


def run(args, timeout=20):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def norm_cn(code):
    """代码归一为纯数字（sh600519 -> 600519）"""
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code


def load_legal_codes():
    """加载主板清单白名单代码集合（all_mainboard.csv 已剔 ST/*ST/退市）"""
    legal = set()
    for p in ("all_mainboard.csv", "/sandbox/workspace/all_mainboard.csv",
              "../all_mainboard.csv", "quant_scripts/all_mainboard.csv"):
        try:
            with open(p, encoding="utf-8-sig") as f:
                next(f, None)
                for ln in f:
                    code = ln.strip().split(",")[0].strip()
                    if code:
                        legal.add(code)
            if legal:
                return legal
        except Exception:
            continue
    return None


def load_json(paths):
    """按序尝试读取JSON，成功返回dict，全部失败返回None"""
    for p in paths:
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
    return None


def load_four_dim():
    d = load_json(["outputs/四维共振_latest.json", "四维共振_latest.json"])
    out = {}
    if not d:
        return out
    for s in d.get("stocks", []):
        code = s.get("code", "")
        if not code:
            continue
        full = ("sh" if code.startswith("6") else "sz") + code
        out[full] = {"total": s.get("total", 0), "level": s.get("level", ""),
                     "veto": s.get("veto", ""), "fund_tag": s.get("fund_tag", "")}
    return out


def load_fish():
    d = load_json(["outputs/fish_body_latest.json", "fish_body_latest.json",
                   "outputs/鱼身报告_latest.json"])
    out = {}
    if not d:
        return out
    for s in d.get("signals", []):
        code = s.get("code", "")
        if not code:
            continue
        pat = s.get("pattern", "")
        fin = s.get("final_score", 0)
        if code in out:  # 同股多模式：保留最高分，pattern合并
            if fin > out[code]["final"]:
                out[code]["final"] = fin
            if pat and pat not in out[code]["pattern"]:
                out[code]["pattern"] += "+" + pat
        else:
            out[code] = {"pattern": pat, "final": fin,
                         "resonance": s.get("resonance", "")}
    return out


def parse_setup_table(txt):
    """猛兽Setup表（空格对齐格式）：
    表头: 代码 名称 总分 VCP 均线 量能 VAD 突破 断层 强度 伏击 RS_D 基本 模式 高阳"""
    out = {}
    lines = txt.splitlines()
    header_idx = None
    for i, ln in enumerate(lines):
        if "代码" in ln and "名称" in ln and "总分" in ln:
            header_idx = i
            break
    if header_idx is None:
        return out
    header = [p for p in lines[header_idx].split() if p]
    # 数据行：以 sh/sz 代码开头（空格分隔）
    for ln in lines[header_idx + 2:]:
        parts = ln.split()
        if len(parts) < 5 or not re.match(r"^(sh|sz)\d{6}$", parts[0]):
            continue
        try:
            score = float(parts[2])
        except ValueError:
            continue
        row = dict(zip(header, parts))
        out[parts[0]] = {"setup": score, "fujie": row.get("伏击", ""), "rsd": row.get("RS_D", ""),
                         "gpoint": row.get("VCP", ""), "mode": row.get("模式", ""), "gaoyang": row.get("高阳", "")}
    return out


def load_beast():
    """猛兽：从 quant_results beast.stdout 提取 Setup 表"""
    d = load_json(["outputs/quant_results_latest.json", "quant_results_latest.json"])
    if not d:
        return {}
    be = d.get("beast") or {}
    return parse_setup_table(be.get("stdout", ""))


def load_shuangxian():
    """双弦月度池：优先 quant_results shuangxian.pool_data.entries，其次 pools/pool_YYYY-MM.json"""
    d = load_json(["outputs/quant_results_latest.json", "quant_results_latest.json"])
    if d:
        sx = d.get("shuangxian") or {}
        pd = sx.get("pool_data") or {}
        entries = pd.get("entries") or []
        if entries:
            out = {}
            for e in entries:
                code = e.get("code", "")
                if code:
                    out[code] = {"score": e.get("score", 0), "resonance": e.get("resonance", "")}
            return out
    today = datetime.now().strftime("%Y-%m")
    for ym in (today, "2026-08", "2026-07"):
        d2 = load_json([f"pools/pool_{ym}.json"])
        if d2 and d2.get("entries"):
            out = {}
            for e in d2["entries"]:
                code = e.get("code", "")
                if code:
                    out[code] = {"score": e.get("score", 0), "resonance": e.get("resonance", "")}
            return out
    return {}


def load_qiankun():
    d = load_json(["outputs/qiankun_a_latest.json", "qiankun_a_latest.json"])
    if not d:
        return {}
    out = {}
    for s in d.get("stocks", []) if isinstance(d, dict) else []:
        code = s.get("code", "")
        if code:
            out[("sh" if code.startswith("6") else "sz") + code] = {"grade": s.get("grade", "A")}
    return out


def load_wuwei():
    """武威月线精选池（月度频率·容错）：outputs/武威精选池_*.md，重仓+2/精选+1"""
    import glob
    files = sorted(glob.glob("outputs/武威精选池_*.md"))
    if not files:
        return {}
    txt = open(files[-1], encoding="utf-8").read()
    heavy = "重仓" in txt
    out = {}
    for m in re.finditer(r"((?:sh|sz)\d{6})", txt):
        out[m.group(1)] = 2 if heavy else 1
    return out


def load_reversal():
    """反转数值周线信号（周线频率·容错）：outputs/反转数值周线信号_*.md，F重仓+2/其他+1"""
    import glob
    files = sorted(glob.glob("outputs/反转数值周线信号_*.md"))
    if not files:
        return {}
    txt = open(files[-1], encoding="utf-8").read()
    out = {}
    cur_lv = 1
    for ln in txt.splitlines():
        if "重仓" in ln or "F" in ln:
            cur_lv = 2
        elif "标准" in ln:
            cur_lv = 1
        for m in re.finditer(r"((?:sh|sz)\d{6})", ln):
            out[m.group(1)] = cur_lv
    return out




# ═══════ 信号源注册表（P0-1 统一出口 · 2026-08-26）═══════
# 每个系统标注：权重 / 回测胜率 / 盈亏比 / 验证状态 / 频率 / 说明
# 胜率数据来源：历史回测（月线反转×武威G1×v2.1漏斗 / 反转多级别 / 5方法对比等）
SYSTEM_REGISTRY = {
    "四维共振":   {"weight": 3, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "证据链闭合（政策/资金/筹码/关联方），≥7分高置信，否决-3"},
    "猛兽Setup":  {"weight": 3, "winrate": "74.3%", "rr": "2.4", "verified": True, "freq": "日",
                   "note": "强度刻度，Setup≥60一档；三阶共振E方法回测（1500只×2批一致）"},
    "乾坤A级":    {"weight": 2, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "资金强攻+业绩共振"},
    "鱼身空中加油": {"weight": 2, "winrate": "65.8%", "rr": "2.74", "verified": True, "freq": "日",
                   "note": "买点时机；武威G1∩月线反转回测（336样本）"},
    "鱼身回踩/突破": {"weight": 1, "winrate": "65.8%", "rr": "2.74", "verified": True, "freq": "日",
                   "note": "均线回踩/箱体突破（箱体突破已加有效性三条件）"},
    "武威G1":     {"weight": 2, "winrate": "65.4%", "rr": "2.88", "verified": True, "freq": "月",
                   "note": "月线双阴/一阴缩量低吸；∩支撑≥5%回测280样本"},
    "双弦共振":    {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "方向系统；月度股池核心层score≥65入池"},
    "反转数值":    {"weight": 2, "winrate": "51.1%", "rr": "1.63", "verified": True, "freq": "周",
                   "note": "周线反转持4周最优（300只×5级别回测）；红柱环境过滤+4.6倍"},
    "月线反转":    {"weight": 1, "winrate": "54.8%", "rr": "2.08", "verified": True, "freq": "月",
                   "note": "趋势确认（24188样本）；平台突破/均线金叉/趋势确立"},
    "123/2B反转":  {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "斯波朗迪结构确认；123法则/2B假突破/ABC末端"},
    "RSV均":      {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "腰缠万贯144日RSV均；启动/持有/离场刻度"},
    "强势体系":    {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "突破买入+趋势止盈；未接入统一JSON（待接入）"},
    "西湖三重滤网":  {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "大周期找趋势小周期找买点；未接入统一JSON（待接入）"},
    "王者倍量柱":   {"weight": 1, "winrate": "—", "rr": "—", "verified": False, "freq": "日",
                   "note": "倍量突破信号；未接入统一JSON（待接入）"},
}
# 市场级环境信号（不参与个股打分，计入环境裁决）
MARKET_SIGNALS = {
    "见顶五维":   {"file": "outputs/top_signal_latest.json", "threshold": 3,
                   "note": "≥3维=顶部区域（强制离场档）"},
    "市场宽度":   {"file": "outputs/market_width_latest.json", "threshold": 25,
                   "note": "<25弱势；≥70强势"},
    "年线广度":   {"file": "outputs/yearline_breadth_latest.json", "threshold": 40,
                   "note": "站上年线占比；<40%为熊市结构"},
}


def load_123_2b():
    """123/2B反转信号（斯波朗迪L3结构确认）：buy+2 / risk+1 / abc+1"""
    d = load_json(["outputs/123_2b_latest.json", "123_2b_latest.json"])
    out = {}
    if not d:
        return out
    for k, pts in (("buy", 2), ("risk", 1), ("abc", 1)):
        for s in d.get(k, []):
            code = s.get("code", "") if isinstance(s, dict) else s
            if code:
                full = ("sh" if code.startswith("6") else "sz") + code
                out[full] = {"pts": pts, "tag": k}
    return out


def load_rsv():
    """RSV均信号（腰缠万贯）：launch启动+2 / hold持有+1 / exit离场-1"""
    d = load_json(["outputs/rsv_strength_latest.json", "rsv_strength_latest.json"])
    out = {}
    if not d:
        return out
    for k, pts in (("launch", 2), ("hold", 1), ("exit", -1)):
        for s in d.get(k, []):
            code = s.get("code", "") if isinstance(s, dict) else s
            if code:
                full = ("sh" if code.startswith("6") else "sz") + code
                out[full] = {"pts": pts, "tag": k}
    return out


def load_market_top():
    """见顶五维监测（市场级）：score≥3 → 顶部区域预警（强制离场档）"""
    d = load_json(["outputs/top_signal_latest.json", "top_signal_latest.json"])
    if not d:
        return None
    return {"score": d.get("score", 0), "level": d.get("level", ""),
            "date": d.get("date", ""), "advice": d.get("advice", "")}


def load_market_width():
    """市场宽度（市场级）：<25弱势 / ≥70强势"""
    d = load_json(["outputs/market_width_latest.json", "market_width_latest.json"])
    if not d:
        return None
    return {"score": d.get("score", 50), "level": d.get("level", ""), "date": d.get("date", "")}



def month_gate(code):
    """月线闸门：PASS(收盘>MA6>MA12) / WARN(收盘>MA6但MA6<MA12) / BLOCK(收盘<MA6)"""
    txt = run(["kline", code, "--period", "month", "--limit", "12"])
    closes = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and re.match(r"^\|\s*20\d{2}", s):  # 2026-08-13修复：原仅匹配2026开头，2025年月K被过滤致closes不足返回"?"
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 4 and parts[3]:
                try:
                    closes.append(float(parts[3]))
                except ValueError:
                    continue
    if len(closes) < 6:
        return "?"
    cur = closes[0]
    ma6 = sum(closes[:6]) / 6
    ma12 = sum(closes[:min(12, len(closes))]) / min(12, len(closes)) if len(closes) >= 10 else ma6
    if cur > ma6 > ma12:
        return "PASS"
    if cur > ma6:
        return "WARN"
    return "BLOCK"


def load_market_env():
    """加载大盘环境温度（L2宏观层，斯波朗迪：冲突时信逻辑）。
    读 quant_results_latest.json 三系统温度（鱼身/猛兽/双弦），取均值。
    返回 {temp, level, detail} 或 None（数据缺失不裁决）
    """
    for p in ("quant_results_latest.json", "outputs/quant_results_latest.json",
              "../outputs/quant_results_latest.json",
              "/sandbox/workspace/github_bg/outputs/quant_results_latest.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
            temps = []
            detail = {}
            # 鱼身
            fb = d.get("fishbody") or d.get("fish_body") or {}
            if isinstance(fb, dict) and fb.get("market_temp") is not None:
                t = fb["market_temp"]
                if isinstance(t, dict):
                    t = t.get("score") or t.get("temp")
                if t is not None:
                    temps.append(float(t))
                    detail["鱼身"] = round(float(t), 1)
            # 猛兽
            bs = d.get("beast") or {}
            if isinstance(bs, dict) and bs.get("safety_score") is not None:
                temps.append(float(bs["safety_score"]))
                detail["猛兽"] = round(float(bs["safety_score"]), 1)
            # 双弦
            sx = d.get("shuangxian") or {}
            if isinstance(sx, dict) and sx.get("temperature") is not None:
                temps.append(float(sx["temperature"]))
                detail["双弦"] = round(float(sx["temperature"]), 1)
            if temps:
                temp = sum(temps) / len(temps)
                level = ("冷市<40" if temp < 40 else "偏冷40-50" if temp < 50 else
                         "中性50-60" if temp < 60 else "偏暖60-70" if temp < 70 else "过热≥70")
                return {"temp": round(temp, 1), "level": level, "detail": detail}
        except Exception:
            continue
    return None


def apply_env_adjudication(ranked, env):
    """宏观-技术冲突裁决（斯波朗迪L4：L2与L3冲突→信L2）。
    冷市(<40)：所有信号降级一档；过热(≥70)：标注警戒。返回裁决日志行列表。
    """
    logs = []
    if not env:
        return logs
    t = env["temp"]
    for r in ranked:
        if t < 40:
            # 冷市：降级一档（★★★→★★→★→观察）
            lv = r["level"]
            if lv.startswith("★★★"):
                r["level"] = "★★" + lv[3:] + "·冷市降级"
            elif lv.startswith("★★"):
                r["level"] = "★" + lv[2:] + "·冷市降级"
            elif lv.startswith("★"):
                r["level"] = "观察·冷市降级"
            else:
                r["level"] = lv + "·冷市降级"
            r["env_note"] = "冷市降级"
        elif t >= 70:
            r["level"] = r["level"] + "·过热警戒"
            r["env_note"] = "过热警戒"
        else:
            r["env_note"] = "正常"
    logs.append(f"大盘温度 {t}（{env['level']}）→ " +
                ("全部信号降级一档（信L2逻辑，冷市不追）" if t < 40 else
                 "全部信号过热警戒（防高位接力）" if t >= 70 else
                 "环境正常，信号按原级执行"))
    return logs


def main():
    top_n = 20
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])

    four = load_four_dim()
    fish = load_fish()
    beast = load_beast()
    sx = load_shuangxian()
    qk = load_qiankun()
    wuwei = load_wuwei()
    reversal = load_reversal()
    t2b = load_123_2b()      # 123/2B反转（P0-1新增）
    rsv = load_rsv()          # RSV均（P0-1新增）
    mtop = load_market_top()  # 见顶五维（市场级·P0-1新增）
    mwidth = load_market_width()  # 市场宽度（市场级·P0-1新增）
    print(f"[INFO] 信号源: 四维{len(four)} 鱼身{len(fish)} 猛兽{len(beast)} 双弦{len(sx)} 乾坤{len(qk)} 武威{len(wuwei)} 反转{len(reversal)} 123/2B{len(t2b)} RSV{len(rsv)}", flush=True)

    # 汇总打分
    scores = {}
    for code, info in four.items():
        t = info["total"]
        if "否决" in info.get("level", ""):
            scores.setdefault(code, {"pts": 0, "src": []})["pts"] -= 3
            scores[code]["src"].append(f"四维否决{info.get('veto','')}")
        elif t >= 7:
            scores.setdefault(code, {"pts": 0, "src": []})["pts"] += 3
            scores[code]["src"].append(f"四维{t}分")
        elif t >= 4:
            scores.setdefault(code, {"pts": 0, "src": []})["pts"] += 1
            scores[code]["src"].append(f"四维{t}分")
    for code, info in fish.items():
        pts = 2 if ("加油" in info["pattern"] and info["final"] >= 70) else 1
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += pts
        scores[code]["src"].append(f"鱼身{info['pattern']}({info['final']})")
    for code, info in beast.items():
        s = info["setup"]
        pts = 3 if s >= 60 else (2 if s >= 50 else (1 if s >= 40 else 0))
        if pts:
            scores.setdefault(code, {"pts": 0, "src": []})["pts"] += pts
            scores[code]["src"].append(f"猛兽Setup{s:.0f}")
        for tag, kw in (("伏击", "伏击"), ("RS_D", "RS_D"), ("G点", "G点")):
            if kw in info.get("fujie", "") or kw in info.get("rsd", "") or kw in info.get("gpoint", ""):
                scores[code]["pts"] += 1
                scores[code]["src"].append(f"猛兽{kw}")
                break
    for code, info in sx.items():
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += 1
        scores[code]["src"].append(f"双弦共振({info.get('score', 0)})")
    for code, info in qk.items():
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += 2
        scores[code]["src"].append(f"乾坤{info.get('grade','A')}级")
    for code, pts in wuwei.items():  # 武威月线精选（2026-08-11接入）
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += pts
        scores[code]["src"].append(f"武威精选(+{pts})")
    for code, pts in reversal.items():  # 反转数值周线（2026-08-11接入）
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += pts
        scores[code]["src"].append(f"反转数值(+{pts})")
    for code, info in t2b.items():  # 123/2B反转（P0-1接入：buy+2/risk+1/abc+1）
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += info["pts"]
        scores[code]["src"].append(f"123/2B-{info['tag']}({info['pts']:+d})")
    for code, info in rsv.items():  # RSV均（P0-1接入：launch+2/hold+1/exit-1）
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += info["pts"]
        scores[code]["src"].append(f"RSV-{info['tag']}({info['pts']:+d})")

    # 分级
    ranked = []
    for code, v in scores.items():
        pts = v["pts"]
        if pts >= 7:
            lv = "★★★ 全信号共振"
        elif pts >= 5:
            lv = "★★ 多信号共振"
        elif pts >= 3:
            lv = "★ 双信号"
        else:
            lv = "观察"
        ranked.append({"code": code, "pts": pts, "level": lv, "src": v["src"]})
    ranked.sort(key=lambda x: (-x["pts"], x["code"]))

    # ST/退市兜底：按主板清单白名单过滤（清单已剔ST/*ST/退市）
    legal = load_legal_codes()
    if legal:
        before = len(ranked)
        ranked = [r for r in ranked if norm_cn(r["code"]) in legal]
        if len(ranked) < before:
            print(f"[ST过滤] 剔除 {before - len(ranked)} 只非清单标的（ST/退市/创业板等）")

    # 宏观-技术冲突裁决（斯波朗迪L2：大盘环境定权，冲突信逻辑）
    env = load_market_env()
    env_logs = apply_env_adjudication(ranked, env) if env else []
    if env:
        print(f"[环境裁决] 大盘温度 {env['temp']}（{env['level']}）→ {env_logs[0] if env_logs else '无调整'}")
    if mtop and mtop["score"] >= 3:
        for r in ranked:
            r["level"] = "观察·市场见顶降级"
            r["env_note"] = f"见顶五维{mtop['score']}/5"
        env_logs.append(f"⚠️ 见顶五维 {mtop['score']}/5（{mtop['level']}）→ 全部信号降级观察（强制离场档）")
        print(f"[市场顶预警] 五维 {mtop['score']}/5 → 全部降级观察")
    if mwidth and mwidth.get("score", 50) < 25:
        env_logs.append(f"⚠️ 市场宽度 {mwidth.get('score')}（弱势）→ 新开仓谨慎")
        print(f"[宽度预警] 市场宽度 {mwidth.get('score')} 弱势")

    # 月线闸门过滤（TOP N）
    for r in ranked[:top_n]:
        r["month"] = month_gate(r["code"])
        if r["month"] == "BLOCK":
            r["level"] = "观察" + "·月线空头降级"
        time.sleep(0.2)

    # 信号级风控卡（《专业投机原理》L5：无止损不进场 + 账户风险2%→仓位）
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "quant_scripts"))
        from signal_risk_card import risk_card_batch
        _cards = risk_card_batch([{"code": r["code"]} for r in ranked[:top_n]])
        _rc = {c["code"]: c for c in _cards}
        for r in ranked[:top_n]:
            r["risk"] = _rc.get(r["code"], {})
        _ok = sum(1 for c in _cards if c.get("status", "").startswith("✅"))
        _warn = sum(1 for c in _cards if c.get("status", "").startswith("⚠️"))
        _no = sum(1 for c in _cards if c.get("status", "").startswith("⛔"))
        print(f"[风控卡] TOP{len(_cards)}: ✅可执行{_ok} / ⚠️盈亏比不足{_warn} / ⛔无止损{_no}")
    except Exception as e:
        print(f"[WARN] 风控卡计算失败: {e}")

    today = datetime.now().strftime("%Y-%m-%d")
    # 今日操作清单（P0-1：唯一执行出口）
    operations = {"buy": [], "watch": [], "avoid": []}
    for r in ranked:
        rk = r.get("risk", {})
        rk_ok = rk.get("status", "").startswith("✅")
        if r["pts"] >= 5 and r.get("month", "?") != "BLOCK" and rk_ok:
            operations["buy"].append({"code": r["code"], "pts": r["pts"], "level": r["level"],
                                      "src": r["src"], "pos_pct": rk.get("pos_pct", "—")})
        elif r["pts"] >= 3 and r.get("month", "?") != "BLOCK":
            operations["watch"].append({"code": r["code"], "pts": r["pts"], "level": r["level"], "src": r["src"]})
        elif r["pts"] < 0 or r.get("month", "") == "BLOCK" or "否决" in "".join(r["src"]):
            operations["avoid"].append({"code": r["code"], "pts": r["pts"], "level": r["level"], "src": r["src"]})
    js = {"date": today, "env": env, "env_logs": env_logs, "operations": operations,
          "market_top": mtop, "market_width": mwidth,
          "sources": {"四维": len(four), "鱼身": len(fish), "猛兽": len(beast),
                                      "双弦": len(sx), "乾坤": len(qk), "武威": len(wuwei), "反转": len(reversal),
                                      "123_2b": len(t2b), "rsv": len(rsv)},
          "counts": {"★★★": sum(1 for r in ranked if r["level"].startswith("★★★")),
                     "★★": sum(1 for r in ranked if r["level"].startswith("★★")),
                     "★": sum(1 for r in ranked if r["level"].startswith("★")),
                     "观察": sum(1 for r in ranked if r["level"].startswith("观察"))},
          "ranked": ranked[:top_n]}
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "信号仲裁_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    n_src = len(four) + len(fish) + len(beast) + len(sx) + len(qk) + len(wuwei) + len(reversal) + len(t2b) + len(rsv)
    L = [f"# ⚖️ 全系统信号仲裁（统一出口） {today}", "",
         f"> 数据源：四维{len(four)} / 鱼身{len(fish)} / 猛兽{len(beast)} / 双弦{len(sx)} / 乾坤{len(qk)} / 武威{len(wuwei)} / 反转{len(reversal)} / 123-2B{len(t2b)} / RSV{len(rsv)}（共{n_src}条）",
         "> 仲裁权重：四维高置信+3｜猛兽Setup≥60+3/≥50+2｜乾坤A+2｜鱼身加油≥70+2｜伏击/RS_D/G点+1｜双弦共振+1｜123-2B买+2/RSV启动+2｜四维否决-3",
         "> 分级：≥7 ★★★全信号共振(≤15%) / 5-6 ★★(≤10%) / 3-4 ★(≤5%) / <3 观察；月线BLOCK强制降级", ""]
    if env:
        L.append("## 🏛️ 大盘环境裁决（L2宏观 · 斯波朗迪：冲突信逻辑）")
        L.append(f"- 大盘温度 **{env['temp']}**（{env['level']}）｜三系统：{' '.join(f'{k}={v}' for k, v in env.get('detail', {}).items())}")
        for lg in env_logs:
            L.append(f"- ⚖️ {lg}")
        L.append("")
    if mtop or mwidth:
        L.append("## 🌡️ 市场级信号")
        if mtop:
            mt_warn = " ⚠️ 顶部区域！全部信号降级观察" if mtop["score"] >= 3 else ""
            L.append(f"- 见顶五维：**{mtop['score']}/5**（{mtop['level']}）{mt_warn}")
        if mwidth:
            L.append(f"- 市场宽度：**{mwidth.get('score')}**（{mwidth.get('level', '')}）" +
                     (" ⚠️ 弱势，新开仓谨慎" if mwidth.get("score", 50) < 25 else ""))
        L.append("")
    L.append("## 仲裁结果 TOP{0}".format(min(top_n, len(ranked))))
    L.append("| 排名 | 代码 | 总分 | 分级 | 月线 | 信号来源 | 风控卡 |")
    L.append("|:----|:----|:----:|:----|:----:|:----|:----|")
    for i, r in enumerate(ranked[:top_n], 1):
        rk = r.get("risk", {})
        if rk.get("status", "").startswith("✅"):
            rk_txt = f"✅ {rk.get('rr','—')}x·仓位{rk.get('pos_pct','—')}%"
        elif rk.get("status", "").startswith("⚠️"):
            rk_txt = f"⚠️ 盈亏比{rk.get('rr','—')}"
        elif rk.get("status", "").startswith("⛔"):
            rk_txt = "⛔ 无止损"
        else:
            rk_txt = "—"
        L.append(f"| {i} | {r['code']} | **{r['pts']}** | {r['level']} | {r['month']} | {'；'.join(r['src'][:5])}{'…' if len(r['src']) > 5 else ''} | {rk_txt} |")
    L.append("")
    L.append("## 📋 今日操作清单（唯一执行出口）")
    L.append("### 🟢 买入候选（★★/★★★ 且 月线非空头 且 风控卡✅）")
    if operations["buy"]:
        for r in operations["buy"]:
            L.append(f"- **{r['code']}** {r['pts']}分 {r['level']}｜仓位≤{r['pos_pct']}%｜{'；'.join(r['src'][:4])}")
    else:
        L.append("- （今日无符合全部条件的买入候选）")
    L.append("### 🟡 观察池（★ 双信号）")
    if operations["watch"]:
        L.append("- " + "、".join(f"{r['code']}({r['pts']}分)" for r in operations["watch"][:15]))
    else:
        L.append("- （无）")
    L.append("### 🔴 规避/卖出（四维否决/月线空头/RSV离场）")
    if operations["avoid"]:
        L.append("- " + "、".join(f"{r['code']}({r['pts']}分)" for r in operations["avoid"][:10]))
    else:
        L.append("- （无）")
    L.append("")
    L.append("## 分级分布")
    L.append(f"- ★★★ 全信号共振: {js['counts']['★★★']} | ★★ 多信号: {js['counts']['★★']} | ★ 双信号: {js['counts']['★']} | 观察: {js['counts']['观察']}")
    L.append("")
    L.append("## 说明")
    L.append("- 仲裁优先级（冲突时资金分配）：四维证据链 > 猛兽强度 > 乾坤/鱼身买点 > 双弦/反转")
    L.append("- 武威（月度）与反转数值（周线）已接入，数据出现时自动参与打分")
    L.append("- 月线闸门对TOP标的逐只校验（BLOCK=月线空头强制降级）；四维否决(-3)即使其他信号强也只到观察")
    L.append("- 市场级信号（见顶五维≥3/市场宽度<25）强制降级全部信号——冲突时信环境（斯波朗迪L2）")
    L.append("")
    L.append("## 📚 信号源注册表（回测胜率/权重）")
    L.append("| 系统 | 权重 | 回测胜率 | 盈亏比 | 验证 | 频率 | 说明 |")
    L.append("|:----|:----:|:----:|:----:|:----:|:----:|:----|")
    for _name, _meta in SYSTEM_REGISTRY.items():
        _v = "✅" if _meta["verified"] else "❌"
        L.append(f"| {_name} | +{_meta['weight']} | {_meta['winrate']} | {_meta['rr']} | {_v} | {_meta['freq']} | {_meta['note']} |")
    L.append("")
    L.append("> ⚠️ 未回测验证的系统（❌）信号权重仅供参考，实盘应以 ✅ 系统为主链；接入新信号源前必须过 backtest_gate 回测门槛")
    md_path = os.path.join(OUT_DIR, f"信号仲裁_{today}.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"分布: ★★★{js['counts']['★★★']} ★★{js['counts']['★★']} ★{js['counts']['★']} 观察{js['counts']['观察']}")

    # E2 自选清单（2026-08-11）：★★★/★★/★ 代码清单，可直接导入交易软件
    try:
        watch = []
        for r in ranked:
            if r["level"].startswith("★") and r.get("month", "?") != "BLOCK":
                code = r["code"]
                watch.append(f"{code}  # {r['pts']}分 {r['level']}")
        with open(os.path.join(OUT_DIR, f"自选清单_{today}.txt"), "w", encoding="utf-8") as f:
            f.write(f"# 信号仲裁自选清单 {today}（导入交易软件用）\n")
            f.write("# 格式: 代码 # 总分 分级（月线BLOCK已剔除）\n")
            f.write("\n".join(watch) + "\n")
        print(f"[OK] 自选清单 {len(watch)} 只 → outputs/自选清单_{today}.txt")
    except Exception as e:
        print(f"[WARN] 自选清单失败: {e}")

    # V3 仲裁信号日志（2026-08-11）：累积 date,code,pts,level,month,src 供胜率分层
    try:
        log_path = os.path.join(OUT_DIR, "仲裁信号日志.csv")
        new = not os.path.exists(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            if new:
                f.write("date,code,pts,level,month,src\n")
            for r in ranked[:20]:
                f.write(f"{today},{r['code']},{r['pts']},{r['level']},{r.get('month','?')},{'|'.join(r['src'][:4])}\n")
        print(f"[OK] 仲裁日志累积 → outputs/仲裁信号日志.csv")
    except Exception as e:
        print(f"[WARN] 仲裁日志失败: {e}")


if __name__ == "__main__":
    main()
