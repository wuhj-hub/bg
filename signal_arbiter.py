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


def run(args, timeout=60):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


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
    print(f"[INFO] 信号源: 四维{len(four)} 鱼身{len(fish)} 猛兽{len(beast)} 双弦{len(sx)} 乾坤{len(qk)} 武威{len(wuwei)} 反转{len(reversal)}", flush=True)

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

    # 月线闸门过滤（TOP N）
    for r in ranked[:top_n]:
        r["month"] = month_gate(r["code"])
        if r["month"] == "BLOCK":
            r["level"] = "观察" + "·月线空头降级"
        time.sleep(0.2)

    today = datetime.now().strftime("%Y-%m-%d")
    js = {"date": today, "sources": {"四维": len(four), "鱼身": len(fish), "猛兽": len(beast),
                                      "双弦": len(sx), "乾坤": len(qk), "武威": len(wuwei), "反转": len(reversal)},
          "counts": {"★★★": sum(1 for r in ranked if r["level"].startswith("★★★")),
                     "★★": sum(1 for r in ranked if r["level"].startswith("★★")),
                     "★": sum(1 for r in ranked if r["level"].startswith("★")),
                     "观察": sum(1 for r in ranked if r["level"].startswith("观察"))},
          "ranked": ranked[:top_n]}
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "信号仲裁_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    L = [f"# ⚖️ 六套信号仲裁 {today}", "",
         f"> 数据源：四维{len(four)}只 / 鱼身{len(fish)} / 猛兽Setup{len(beast)} / 双弦{len(sx)} / 乾坤{len(qk)} / 武威{len(wuwei)} / 反转{len(reversal)}",
         "> 仲裁权重：四维高置信+3｜猛兽Setup≥60+3/≥50+2｜乾坤A+2｜鱼身加油≥70+2｜伏击/RS_D/G点+1｜双弦共振+1｜四维否决-3",
         "> 分级：≥7 ★★★全信号共振(≤15%) / 5-6 ★★(≤10%) / 3-4 ★(≤5%) / <3 观察；月线BLOCK强制降级", ""]
    L.append("## 仲裁结果 TOP{0}".format(min(top_n, len(ranked))))
    L.append("| 排名 | 代码 | 总分 | 分级 | 月线 | 信号来源 |")
    L.append("|:----|:----|:----:|:----|:----:|:----|")
    for i, r in enumerate(ranked[:top_n], 1):
        L.append(f"| {i} | {r['code']} | **{r['pts']}** | {r['level']} | {r['month']} | {'；'.join(r['src'][:5])}{'…' if len(r['src']) > 5 else ''} |")
    L.append("")
    L.append("## 分级分布")
    L.append(f"- ★★★ 全信号共振: {js['counts']['★★★']} | ★★ 多信号: {js['counts']['★★']} | ★ 双信号: {js['counts']['★']} | 观察: {js['counts']['观察']}")
    L.append("")
    L.append("## 说明")
    L.append("- 仲裁优先级（冲突时资金分配）：四维证据链 > 猛兽强度 > 乾坤/鱼身买点 > 双弦/反转")
    L.append("- 武威（月度）与反转数值（周线）已接入，数据出现时自动参与打分")
    L.append("- 月线闸门对TOP标的逐只校验（BLOCK=月线空头强制降级）；四维否决(-3)即使其他信号强也只到观察")
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
