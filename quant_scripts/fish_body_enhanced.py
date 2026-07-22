#!/usr/bin/env python3
"""
鱼身增强版 · 多维度融合系统 v2.0
融合多维度评分+三层共振+鱼身模式识别
"""

import subprocess, json, re, sys, os, time
from datetime import datetime

WESTOCK_CMD = "npx -y westock-data-skillhub@1.0.3"

class C:
    G='\033[92m'; Y='\033[93m'; R='\033[91m'; C='\033[96m'; B='\033[1m'; N='\033[0m'
def c(t,color): return f"{color}{t}{C.N}"

def run(cmd, timeout=60):
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except: return ""

def parse_table(md):
    lines=[l.strip() for l in md.split('\n') if l.strip()]
    if not lines: return []
    hdr=None
    for i,ln in enumerate(lines):
        if ln.startswith('|') and '---' not in ln and any(k in ln for k in ['code','name','symbol','date','closePrice']):
            hdr=i; break
    if hdr is None: return []
    hdrs=[h.strip() for h in lines[hdr].split('|')[1:-1]]
    res=[]
    for ln in lines[hdr+2:]:
        if not ln.startswith('|'): continue
        v=[v.strip() for v in ln.split('|')[1:-1]]
        if len(v)==len(hdrs): res.append(dict(zip(hdrs,v)))
    return res

def sf(v):
    if v is None or v=='-' or v=='': return None
    try: return float(v)
    except: return None

# === 模块A: 大盘择时 ===
def get_market_temp():
    raw=run(f"{WESTOCK_CMD} kline sh000001 --period day --limit 60 2>/dev/null")
    rows=parse_table(raw)
    if not rows: return {"temp":50,"level":"未知","idx":"--"}
    closes=[float(r['last']) for r in rows]
    vols=[float(r['volume']) for r in rows]
    latest=closes[0]
    ma5=sum(closes[:5])/5 if len(closes)>=5 else latest
    ma10=sum(closes[:10])/10 if len(closes)>=10 else latest
    ma20=sum(closes[:20])/20 if len(closes)>=20 else latest
    score=50
    if ma5>ma10>ma20: score+=20
    elif ma5>ma10: score+=10
    else: score-=10
    if len(closes)>=10:
        ret=(closes[0]-closes[9])/closes[9]*100
        if ret>3: score+=15
        elif ret>0: score+=8
        elif ret<-3: score-=10
    if len(vols)>=20:
        v5=sum(vols[:5])/5; v20=sum(vols[:20])/20
        r=v5/v20 if v20>0 else 1
        if r>1.3: score+=10
        elif r>0.8: score+=5
    temp=max(0,min(100,score))
    if temp>=75: lv="偏热"
    elif temp>=55: lv="中性偏多"
    elif temp>=40: lv="中性"
    elif temp>=25: lv="偏冷"
    else: lv="冰点"
    return {"temp":temp,"level":lv,"idx":f"{latest:.2f}"}

# === 模块B: 多维度个股评分 ===
def score_stock_multi(code):
    tech=parse_table(run(f"{WESTOCK_CMD} technical {code} --group macd,rsi,kdj,boll,ma 2>/dev/null"))
    fund=parse_table(run(f"{WESTOCK_CMD} asfund {code} 2>/dev/null"))
    kline=parse_table(run(f"{WESTOCK_CMD} kline {code} --period day --limit 60 2>/dev/null"))
    tech=tech[0] if tech else {}
    fund=fund[0] if fund else {}
    if not kline: return {"score":0,"detail":{}}
    closes=[float(r['last']) for r in kline]
    vols=[float(r['volume']) for r in kline]
    close=closes[0]
    scores={}
    # 资金(35)
    fs=0
    if fund:
        mn=sf(fund.get('MainNetFlow',0)) or 0
        m5=sf(fund.get('MainNetFlow5D',0)) or 0
        m10=sf(fund.get('MainNetFlow10D',0)) or 0
        m20=sf(fund.get('MainNetFlow20D',0)) or 0
        jn=sf(fund.get('JumboNetFlow',0)) or 0
        if mn>0: fs+=8
        pos=sum(1 for v in [mn,m5,m10,m20] if v>0)
        fs+=pos*4
        if jn>0: fs+=5
    scores['fund']=min(fs,35)
    # 技术(35)
    ts=0
    if tech:
        dif=sf(tech.get('macd.DIF',0)) or 0
        dea=sf(tech.get('macd.DEA',0)) or 0
        macd=sf(tech.get('macd.MACD',0)) or 0
        rsi6=sf(tech.get('rsi.RSI_6',50)) or 50
        kk=sf(tech.get('kdj.KDJ_K',50)) or 50
        kd=sf(tech.get('kdj.KDJ_D',50)) or 50
        if dif>dea and macd>0: ts+=10
        elif dif>dea: ts+=6
        if 50<=rsi6<=70: ts+=8
        elif rsi6>70: ts+=4
        if kk>kd: ts+=4
        if 20<=kd<=80: ts+=3
        bu=sf(tech.get('boll.BOLL_UPPER',0)) or 0
        bl=sf(tech.get('boll.BOLL_LOWER',0)) or 0
        if bu>bl>0:
            bp=(close-bl)/(bu-bl)*100
            if 40<=bp<=70: ts+=6
            elif bp>80: ts+=2
            else: ts+=3
    scores['technical']=min(ts,35)
    # 趋势(30)
    trs=0
    if len(closes)>=20:
        ma5=sum(closes[:5])/5; ma10=sum(closes[:10])/10; ma20=sum(closes[:20])/20
        if ma5>ma10>ma20: trs+=12
        elif ma5>ma10: trs+=8
        elif ma5>ma20: trs+=5
        else: trs+=2
        if len(closes)>=10:
            ret=(closes[0]-closes[9])/closes[9]*100
            if ret>5: trs+=10
            elif ret>2: trs+=7
            elif ret>-2: trs+=4
            else: trs+=1
        if len(vols)>=10:
            v3=sum(vols[:3])/3; v710=sum(vols[3:10])/7 if len(vols)>=10 else 1
            vr=v3/v710 if v710>0 else 1
            if vr>1.3: trs+=8
            elif vr>0.8: trs+=5
    scores['trend']=min(trs,30)
    total=sum(scores.values())
    return {"score":min(100,max(0,int(total))),"detail":scores}

# === 模块C: 共振验证 ===
def verify_resonance(code):
    idx_tech=parse_table(run(f"{WESTOCK_CMD} technical sh000001 --group macd,rsi 2>/dev/null"))
    idx_tech=idx_tech[0] if idx_tech else {}
    idx_dif=sf(idx_tech.get('macd.DIF',0)) or 0
    idx_dea=sf(idx_tech.get('macd.DEA',0)) or 0
    idx_rsi=sf(idx_tech.get('rsi.RSI_6',50)) or 50
    if idx_dif>idx_dea and idx_rsi>50: idx_dir="up"; idx_sig="大盘向上"
    elif idx_dif<idx_dea and idx_rsi<50: idx_dir="down"; idx_sig="大盘向下"
    else: idx_dir="side"; idx_sig="大盘震荡"
    stk=score_stock_multi(code)
    if stk['score']>=65: stk_dir="up"; stk_sig="个股强势"
    elif stk['score']>=50: stk_dir="side"; stk_sig="个股中性"
    else: stk_dir="down"; stk_sig="个股弱势"
    dirs=[idx_dir,stk_dir]
    ups=dirs.count("up"); downs=dirs.count("down")
    if ups==2: resonance="共振向上"; rs=100
    elif ups==1 and downs==0: resonance="部分共振"; rs=70
    elif downs>=1: resonance="共振向下"; rs=20
    else: resonance="无共振"; rs=40
    return {"index":idx_sig,"stock":stk_sig,"resonance":resonance,"score":rs}

# === 模块D: 鱼身模式识别 ===
def detect_golden_breakout(code):
    """黄金起爆线检测：涨停→缩量→不破涨停均价线
    返回 True/False"""
    raw = run(f"{WESTOCK_CMD} kline {code} --period day --limit 60 2>/dev/null")
    rows = parse_table(raw)
    if not rows or len(rows) < 6:
        return False
    # 最近10天内找涨停日
    for i in range(min(10, len(rows))):
        try:
            r = rows[i]
            close = float(r['last'])
            open_p = float(r['open'])
            high = float(r['high'])
            low = float(r['low'])
            vol = float(r['volume'])
        except (ValueError, KeyError, TypeError):
            continue
        gain = (close - open_p) / open_p * 100
        if gain < 9.5:  # 非涨停跳过
            continue
        # 涨停日 → 计算均价线（最高+最低）/2
        avg_price = (high + low) / 2
        # 之后2~5天检查缩量回踩
        end = min(i + 6, len(rows))
        if end - i < 3:
            continue
        all_ok = True
        for j in range(i + 1, end):
            try:
                p_low = float(rows[j]['low'])
                p_vol = float(rows[j]['volume'])
            except (ValueError, KeyError, TypeError):
                continue
            # 缩量：量 <= 涨停日量的 0.8
            if p_vol > vol * 0.8:
                all_ok = False
                break
            # 不破均价线（容差 2%）
            if p_low < avg_price * 0.98:
                all_ok = False
                break
        if all_ok:
            return True
    return False


def detect_fish_patterns(tech, multi_score, resonance):
    signals=[]
    dif=sf(tech.get('macd.DIF',0)) or 0
    dea=sf(tech.get('macd.DEA',0)) or 0
    macd=sf(tech.get('macd.MACD',0)) or 0
    close=sf(tech.get('closePrice',0)) or 0
    ma5=sf(tech.get('ma.MA_5',0)) or 0
    ma10=sf(tech.get('ma.MA_10',0)) or 0
    ma20=sf(tech.get('ma.MA_20',0)) or 0
    ma60=sf(tech.get('ma.MA_60',0)) or 0
    kdj_j=sf(tech.get('kdj.KDJ_J',50)) or 50
    boll_mid=sf(tech.get('boll.BOLL_MID',0)) or 0
    name=tech.get('name','')
    code=tech.get('code',tech.get('symbol',''))
    mw=multi_score/100.0; rw=resonance.get('score',50)/100.0
    weight=lambda x: min(100,max(0,int(x*(0.6+0.2*mw+0.2*rw))))
    
    # 模式1: MACD空中加油
    if dif>0 and dea>0 and dif>=dea:
        ps=0; pr=[]
        ps+=25; pr.append("DIF/DEA在0轴上方")
        if dif>=dea: ps+=25; pr.append(f"DIF({dif:.2f})>=DEA({dea:.2f})金叉")
        if macd>0:
            if macd<0.15: ps+=30; pr.append(f"MACD柱{macd:.3f}刚翻红加油成功")
            else: ps+=15; pr.append(f"MACD柱{macd:.2f}>0但已走高")
        if close>ma5: ps+=10; pr.append(f"收盘{close}>MA5{ma5}")
        if ma20 and ma60 and ma20>ma60: ps+=5; pr.append("MA20>MA60多头排列")
        if kdj_j<85: ps+=5; pr.append(f"KDJ_J={kdj_j:.0f}未超买")
        fs=weight(ps)
        if fs>=55:
            signals.append({'code':code,'name':name,'pattern':'MACD空中加油',
                'raw_score':ps,'final_score':fs,'multi_score':multi_score,
                'resonance':resonance.get('resonance',''),'price':close,
                'reasons':pr,'stop_loss':f"{ma5*0.95:.2f}" if ma5 else "--",
                'target':f"{close*1.15:.2f}" if close else "--",'mode':1,'tag':''})
    
    # 模式2: 均线回踩
    if ma20 and ma60 and ma20>ma60:
        ps=0; pr=[]
        ps+=20; pr.append(f"MA20({ma20:.2f})>MA60({ma60:.2f})多头")
        if dif>0 and dea>0: ps+=15; pr.append("MACD在0轴上方")
        if ma10:
            dev=abs(close-ma10)/ma10*100
            if dev<5: ps+=25; pr.append(f"在MA10附近(偏离{dev:.1f}%)")
            elif dev<10: ps+=15; pr.append(f"偏离MA10约{dev:.1f}%")
        if ma5 and close>ma5: ps+=10; pr.append(f"收盘{close}>MA5{ma5}")
        if boll_mid and close>=boll_mid: ps+=5; pr.append("站在布林中轨上方")
        fs=weight(ps)
        if fs>=55:
            signals.append({'code':code,'name':name,'pattern':'均线回踩支撑',
                'raw_score':ps,'final_score':fs,'multi_score':multi_score,
                'resonance':resonance.get('resonance',''),'price':close,
                'reasons':pr,'stop_loss':f"{ma20*0.95:.2f}" if ma20 else "--",
                'target':f"{close*1.12:.2f}" if close else "--",'mode':2,'tag':''})
    
    # 模式3: 箱体突破
    if ma20 and ma60 and ma20>ma60:
        ps=0; pr=[]
        ps+=20; pr.append(f"MA20({ma20:.2f})>MA60({ma60:.2f})")
        if dif>dea and dif>0: ps+=20; pr.append(f"MACD金叉(DIF={dif:.2f})")
        if kdj_j>50: ps+=10; pr.append(f"KDJ向上(J={kdj_j:.0f})")
        if close>ma5: ps+=15; pr.append(f"收盘{close}>MA5{ma5}")
        fs=weight(ps)
        if fs>=55:
            signals.append({'code':code,'name':name,'pattern':'箱体突破',
                'raw_score':ps,'final_score':fs,'multi_score':multi_score,
                'resonance':resonance.get('resonance',''),'price':close,
                'reasons':pr,'stop_loss':f"{ma5*0.93:.2f}" if ma5 else "--",
                'target':f"{close*1.15:.2f}" if close else "--",'mode':3,'tag':''})
    
    return signals

# === 主流程 ===
def is_valid_stock(code):
    """过滤：非科创板、非创业板、非北交所、非ST"""
    # 科创板 sh688xxx / sh689xxx
    if code.startswith('sh688') or code.startswith('sh689'):
        return False
    # 创业板 sz300xxx / sz301xxx
    if code.startswith('sz30'):
        if len(code)>=7 and code[4:7] in ['000','001']:
            return False
    # 北交所 bj
    if code.startswith('bj'):
        return False
    return True

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--pool',default='core')
    p.add_argument('--mode',default='all')
    p.add_argument('--min-temp',type=int,default=40)
    args=p.parse_args()
    
    core=['sh603669','sh600400','sz002520']
    if args.pool=='core': pool=core
    elif args.pool=='all':
        pool=[]
        # 沪市主板 sh600000-sh605999，跳过688科创板
        for i in range(600000,606000):
            code=f"sh{i}"
            if is_valid_stock(code):
                pool.append(code)
        # 深市主板 sz000001-sz003999，跳过300创业板
        for i in range(1,4000):
            code=f"sz{i:06d}"
            if is_valid_stock(code):
                pool.append(code)
    else:
        try:
            with open(args.pool) as f:
                raw=[l.strip() for l in f if l.strip() and not l.startswith('#')]
            pool=[c for c in raw if is_valid_stock(c)]
            filtered=len(raw)-len(pool)
            if filtered>0:
                print(f"  ⚠️ 过滤了 {filtered} 只不符合条件的标的（创业板/科创板/北交所/ST）")
        except:
            pool=core
    
    print(f"\n{c('='*60,C.C)}")
    print(f"  鱼身增强版 · 多维度融合交易系统 v2.0")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{c('='*60,C.C)}")
    
    # 阶段1: 大盘
    print(f"\n{c('─'*50,C.C)}")
    print(f"  [阶段1] 大盘环境过滤")
    print(f"{c('─'*50,C.C)}")
    temp=get_market_temp()
    tc=C.G if temp['temp']>=55 else C.Y
    print(f"  上证指数: {temp['idx']}  温度: {c(str(temp['temp'])+'/100',tc)}  状态: {c(temp['level'],tc)}")
    if temp['temp']<args.min_temp:
        print(f"\n  {c('大盘温度低于阈值，不建议开仓',C.R)}")
        return
    print(f"  {c('大盘环境通过',C.G)}")
    
    # 阶段2: 扫描
    print(f"\n{c('─'*50,C.C)}")
    print(f"  [阶段2] 多维度评分 + 鱼身模式识别")
    print(f"  股票池: {len(pool)}只")
    print(f"{c('─'*50,C.C)}")
    
    all_sigs=[]; multis=[]
    for i in range(0,len(pool),3):
        batch=pool[i:i+3]
        cs=','.join(batch)
        tech_rows=parse_table(run(f"{WESTOCK_CMD} technical {cs} --group all 2>/dev/null"))
        for row in tech_rows:
            code=row.get('code',row.get('symbol',''))
            name=row.get('name','')
            if not code: continue
            # 过滤ST/*ST
            if 'ST' in name.upper() or '*ST' in name.upper():
                continue
            multi=score_stock_multi(code)
            multis.append({'code':code,'name':name,'score':multi['score']})
            res=verify_resonance(code)
            sigs=detect_fish_patterns(row,multi['score'],res)
            # 黄金起爆检测：仅对 MACD空中加油 信号
            for s in sigs:
                if s.get('mode') == 1 and s.get('final_score', 0) >= 55:
                    if detect_golden_breakout(code):
                        s['tag'] = '黄金起爆'
                s['resonance_detail']=res
                all_sigs.append(s)
            sc=C.G if multi['score']>=65 else (C.Y if multi['score']>=50 else C.N)
            det=" | ".join([f"{k}={v}" for k,v in multi['detail'].items()])
            pats=" ".join([s['pattern'] for s in sigs])
            print(f"  {code} {name:8s} 多维:{c(str(multi['score'])+'分',sc)} {det}  {pats}")
        time.sleep(0.3)
    
    if args.mode!='all':
        mm={'1':1,'2':2,'3':3}
        tm=mm.get(args.mode)
        if tm: all_sigs=[s for s in all_sigs if s.get('mode')==tm]
    all_sigs.sort(key=lambda x:x['final_score'],reverse=True)
    
    # 阶段3: 输出
    print(f"\n{c('='*60,C.C)}")
    print(f"  [阶段3] 最终交易信号 ({len(all_sigs)}个)")
    print(f"{c('='*60,C.C)}")
    
    if not all_sigs:
        print(f"\n  {c('当前无符合条件的融合信号',C.Y)}")
    else:
        for mid,mname,mcol in [(1,'MACD空中加油',C.G),(2,'均线回踩支撑',C.C),(3,'箱体突破',C.Y)]:
            ms=[s for s in all_sigs if s.get('mode')==mid]
            if not ms: continue
            print(f"\n{c('─'*40,mcol)}")
            print(f"  {mname}")
            print(f"{c('─'*40,mcol)}")
            for j,s in enumerate(ms,1):
                sc=C.G if s['final_score']>=80 else (C.Y if s['final_score']>=65 else C.N)
                res_sc=s.get('resonance_detail',{}).get('score',0)
                rc=C.G if res_sc>=70 else C.Y
                print(f"\n  #{j} {s['code']} {s['name']}  "
                      f"综合: {c(str(s['final_score'])+'分',sc)} "
                      f"(原始{s['raw_score']}+多维{s['multi_score']}+共振{res_sc})  "
                      f"现价: {s['price']:.2f}"
                      + (f"  {c('🔥黄金起爆',C.R)}" if s.get('tag') == '黄金起爆' else ""))
                for r in s['reasons']:
                    print(f"    {r}")
                print(f"    止损:{s['stop_loss']}  目标:{s['target']}")
                print(f"    共振:{c(s.get('resonance',''),rc)} | {s.get('resonance_detail',{}).get('index','')} | {s.get('resonance_detail',{}).get('stock','')}")
    
    # 核心标的
    core_sigs=[s for s in all_sigs if s['code'] in core]
    if core_sigs:
        print(f"\n{c('='*50,C.C)}")
        print(f"  核心标的融合信号")
        print(f"{c('='*50,C.C)}")
        for s in core_sigs:
            sc=C.G if s['final_score']>=80 else (C.Y if s['final_score']>=65 else C.N)
            res_sc=s.get('resonance_detail',{}).get('score',0)
            print(f"  {s['code']} {s['name']} {c(s['pattern'],sc)} "
                  f"最终{c(str(s['final_score'])+'分',sc)} "
                  f"(原始{s['raw_score']}+多维{s['multi_score']}+共振{res_sc})")
            for r in s['reasons']:
                print(f"    {r}")
    
    # 保存JSON
    os.makedirs('./outputs',exist_ok=True)
    out=f"./outputs/fish_body_enhanced_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    try:
        with open(out,'w') as f:
            json.dump({"market_temp":temp,"signals":all_sigs},f,ensure_ascii=False,indent=2)
        print(f"\n  报告保存: {out}")
    except: pass
    
    # === 生成Markdown报告并上传到多维度知识库 ===
    try:
        patterns={'1':'MACD空中加油','2':'均线回踩支撑','3':'箱体突破'}
        now=datetime.now()
        md=f"# 🐟 鱼身交易扫描报告\n\n"
        md+=f"**扫描时间**: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        md+=f"**大盘温度**: {temp.get('temp','?')}/100 {temp.get('level','?')}\n\n"
        md+=f"**扫描标的**: {len(pool)}只\n\n"
        md+=f"**信号数量**: {len(all_sigs)}个\n\n"
        md+="---\n\n"
        
        for pid,pname in [('1','MACD空中加油'),('2','均线回踩支撑'),('3','箱体突破')]:
            ps=[s for s in all_sigs if s.get('mode')==int(pid)]
            if not ps: continue
            md+=f"## {pname}\n\n"
            md+=f"| 代码 | 名称 | 综合评分 | 现价 | 止损 | 目标 | 共振 |\n"
            md+=f"|------|------|:-------:|:----:|:----:|:----:|:----:|\n"
            for s in sorted(ps,key=lambda x:x['final_score'],reverse=True):
                res=s.get('resonance_detail',{}).get('resonance','--')
                md+=f"| {s['code']} | {s['name']} | {s['final_score']}分 | {s['price']:.2f} | {s['stop_loss']} | {s['target']} | {res} |\n"
        
        # 核心标的详情
        core=['sh603669','sh600400','sz002520']
        core_sigs=[s for s in all_sigs if s['code'] in core]
        if core_sigs:
            md+="\n## 核心标的详情\n\n"
            for s in core_sigs:
                md+=f"### {s['code']} {s['name']}\n\n"
                sc=s['final_score']
                if sc>=80: level='🟢 强势'
                elif sc>=65: level='🟡 关注'
                else: level='⚪ 观察'
                md+=f"- **模式**: {s['pattern']} | **评分**: {sc}分 ({level})\n"
                md+=f"- **多维度评分**: {s.get('multi_score','?')}/100 | **共振**: {s.get('resonance_detail',{}).get('resonance','--')}\n"
                md+=f"- **现价**: {s['price']:.2f} | **止损**: {s['stop_loss']} | **目标**: {s['target']}\n"
                for r in s['reasons']:
                    md+=f"- ✅ {r}\n"
                md+="\n"
        
        md+="\n---\n> 📊 鱼身交易系统 v2.0 · 多维度融合版\n"
        
        md_file=f"./outputs/鱼身报告_{now.strftime('%Y%m%d_%H%M')}.md"
        with open(md_file,'w',encoding='utf-8') as f:
            f.write(md)
        print(f"  Markdown报告: {md_file}")
        
        # 上传到多维度知识库
        kb_id="RgPmCvOW2CgN3I-HVGEYfmBS_W0mkiYzHRuTGHP8_6o="
        folder_id="folder_7478204537267754"
        rename=f"鱼身报告_{now.strftime('%Y-%m-%d')}"
        upload_cmd=f"python3 upload_ima.py --file-path {md_file} --knowledge-base-id {kb_id} --folder-id {folder_id} --rename '{rename}' 2>/dev/null"
        upload_result=run(upload_cmd)
        if '成功' in upload_result or 'success' in upload_result.lower():
            print(f"  ✅ 已上传到「多维量化→多维度」文件夹")
        else:
            print(f"  ⚠️ 上传结果: {upload_result.strip()[:80]}")
    except Exception as e:
        print(f"  ⚠️ 报告生成/上传: {e}")
    
    print(f"\n{c('='*60,C.C)}")
    print(f"  完成  温度:{temp['temp']}/100 {temp['level']}")
    print(f"  扫描{len(pool)}只  信号{len(all_sigs)}个")
    print(f"  空中加油:{len([s for s in all_sigs if s.get('mode')==1])}个  "
          f"均线回踩:{len([s for s in all_sigs if s.get('mode')==2])}个  "
          f"箱体突破:{len([s for s in all_sigs if s.get('mode')==3])}个")
    print(f"{c('='*60,C.C)}")

if __name__=='__main__':
    main()