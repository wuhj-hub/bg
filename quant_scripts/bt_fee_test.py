#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扣费压力测试：C6 vs C1 vs 跌破MA5 vs T10，看交易成本后的净收益"""
import json
import numpy as np
d=json.load(open("outputs/wangzhe_combo_bt.json"))
ma=json.load(open("outputs/wangzhe_ma_exit_bt.json"))
print("=== 组合（未扣费 / 扣0.2%双边 / 扣0.3%冒险）===")
print(f"{'策略':<30}{'平均':>9}{'持有':>7}{'扣0.2%':>10}{'扣0.3%':>10}{'年化(扣0.2%)':>14}")
for c in d["combos"]:
    a=c["avg"]; dys=c["days"]
    n02=a-0.002; n03=a-0.003
    ann=(1+n02)**(240/max(dys,1))-1
    print(f"{c['name']:<30}{a*100:>+8.2f}%{dys:>7.1f}{n02*100:>+9.2f}%{n03*100:>+9.2f}%{ann*100:>+13.1f}%")
print("\n=== 单一均线规则（未扣费 / 扣0.2%）===")
print(f"{'规则':<26}{'平均':>9}{'持有':>7}{'扣0.2%':>10}{'年化(扣0.2%)':>14}")
for r in ma["rules"]:
    a=r["avg"]; dys=r["days_mean"]
    n02=a-0.002
    ann=(1+n02)**(240/max(dys,1))-1
    print(f"{r['name']:<26}{a*100:>+8.2f}%{dys:>7.1f}{n02*100:>+9.2f}%{ann*100:>+13.1f}%")
