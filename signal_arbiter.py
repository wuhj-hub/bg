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


def load_liangxue():
    """量学扫描信号（黑马王子三部曲·2026-08-30接入）：
    读 outputs/liangxue_latest.json，PASS(≥85)标的。
    返回 {code: {score, has_mid}} —— 100分(黄金柱+倍量+多共振)+3 / 85-99分+2"""
    import glob
    files = sorted(glob.glob("outputs/liangxue_latest.json"))
    if not files:
        return {}
    try:
        d = json.load(open(files[-1], encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for s in d.get("signals", []):
        if s.get("level") != "PASS" or not s.get("ok"):
            continue
        code = norm_cn(s.get("code", ""))
        if not code:
            continue
        sig_types = [x.get("type", "") for x in s.get("signals", [])]
        has_mid = any("中继" in t for t in sig_types)
        out[code] = {"score": s.get("score", 0), "has_mid": has_mid,
                     "name": s.get("name", ""), "sigs": sig_types}
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
    lx = load_liangxue()  # 量学（黑马王子，2026-08-30接入）
    print(f"[INFO] 信号源: 四维{len(four)} 鱼身{len(fish)} 猛兽{len(beast)} 双弦{len(sx)} 乾坤{len(qk)} 武威{len(wuwei)} 反转{len(reversal)} 量学{len(lx)}", flush=True)

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
    for code, info in lx.items():  # 量学（黑马王子·2026-08-30接入）：100分+3/85-99+2，中继黄金柱+1
        pts = 3 if info["score"] >= 100 else 2
        if info.get("has_mid"):
            pts += 1  # 中继黄金柱（最安全买点）加成
        scores.setdefault(code, {"pts": 0, "src": []})["pts"] += pts
        sig_note = "黄金柱·中继" if info.get("has_mid") else (f"量学{info['score']}分")
        scores[code]["src"].append(f"量学({sig_note})+{pts}")

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

    # RSG 强势标注（2026-08-27：RSV体系周线RS偏离52周均线>50‰=强势侧；仅标注，不强制过滤）
    try:
        _rsg_map = {}
        for _p in ("outputs/rsv_strength_latest.json", "rsv_strength_latest.json"):
            if os.path.exists(_p):
                _d = json.load(open(_p, encoding="utf-8"))
                for _r in (_d.get("launch", []) + _d.get("hold", []) + _d.get("exit", [])):
                    if _r.get("code"):
                        _rsg_map[_r["code"]] = _r.get("rsg_dev")
                break
        for r in ranked[:top_n]:
            r["rsg_dev"] = _rsg_map.get(r["code"])
        _n = sum(1 for r in ranked[:top_n] if (r.get("rsg_dev") or 0) > 50)
        print(f"[RSG标注] TOP{top_n}: {_n} 只在强势池(周RS偏离>50‰)")
    except Exception as e:
        print(f"[WARN] RSG标注失败: {e}")

    today = datetime.now().strftime("%Y-%m-%d")
    js = {"date": today, "env": env, "env_logs": env_logs,
          "sources": {"四维": len(four), "鱼身": len(fish), "猛兽": len(beast),
                                      "双弦": len(sx), "乾坤": len(qk), "武威": len(wuwei), "反转": len(reversal)},
          "counts": {"★★★": sum(1 for r in ranked if r["level"].startswith("★★★")),
                     "★★": sum(1 for r in ranked if r["level"].startswith("★★")),
                     "★": sum(1 for r in ranked if r["level"].startswith("★")),
                     "观察": sum(1 for r in ranked if r["level"].startswith("观察"))},
          "ranked": ranked[:top_n]}
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "信号仲裁_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    # 仲裁信号源日志累积（2026-08-28 P1：供月度权重校准——按信号源统计胜率）
    # 字段: date,code,pts,level,src,rsg_dev；同(date,code)去重，仅累积不删除
    try:
        import csv as _csv
        os.makedirs("logs", exist_ok=True)
        log_path = "logs/arbiter_signals_log.csv"
        new_rows = []
        for r in ranked[:top_n]:
            new_rows.append({"date": today, "code": r["code"], "pts": r["pts"],
                             "level": r["level"], "src": "|".join(r["src"][:5]),
                             "rsg_dev": r.get("rsg_dev", "")})
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                seen = {(row["date"], row["code"]) for row in _csv.DictReader(f)}
        else:
            seen = set()
        fresh = [row for row in new_rows if (row["date"], row["code"]) not in seen]
        if fresh:
            with open(log_path, "a", encoding="utf-8", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=["date", "code", "pts", "level", "src", "rsg_dev"])
                if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
                    w.writeheader()
                w.writerows(fresh)
            print(f"[日志] 仲裁信号累积 {len(fresh)} 条 → {log_path}")
    except Exception as e:
        print(f"[WARN] 仲裁日志写入失败: {e}")

    L = [f"# ⚖️ 六套信号仲裁 {today}", "",
         f"> 数据源：四维{len(four)}只 / 鱼身{len(fish)} / 猛兽Setup{len(beast)} / 双弦{len(sx)} / 乾坤{len(qk)} / 武威{len(wuwei)} / 反转{len(reversal)}",
         "> 仲裁权重：四维高置信+3｜猛兽Setup≥60+3/≥50+2｜乾坤A+2｜鱼身加油≥70+2｜伏击/RS_D/G点+1｜双弦共振+1｜四维否决-3",
         "> 分级：≥7 ★★★全信号共振(≤15%) / 5-6 ★★(≤10%) / 3-4 ★(≤5%) / <3 观察；月线BLOCK强制降级", ""]
    if env:
        L.append("## 🏛️ 大盘环境裁决（L2宏观 · 斯波朗迪：冲突信逻辑）")
        L.append(f"- 大盘温度 **{env['temp']}**（{env['level']}）｜三系统：{' '.join(f'{k}={v}' for k, v in env.get('detail', {}).items())}")
        for lg in env_logs:
            L.append(f"- ⚖️ {lg}")
        L.append("")
    L.append("## 仲裁结果 TOP{0}".format(min(top_n, len(ranked))))
    L.append("| 排名 | 代码 | 总分 | 分级 | 月线 | RSG | 信号来源 | 风控卡 |")
    L.append("|:----|:----|:----:|:----|:----:|:----:|:----|:----|")
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
        _rd = r.get("rsg_dev")
        _rsg_txt = "🟢强势" if (_rd is not None and _rd > 50) else ("🟡偏离" if _rd is not None and _rd > 0 else "⚪弱势")
        L.append(f"| {i} | {r['code']} | **{r['pts']}** | {r['level']} | {r['month']} | {_rsg_txt} | {'；'.join(r['src'][:5])}{'…' if len(r['src']) > 5 else ''} | {rk_txt} |")
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
