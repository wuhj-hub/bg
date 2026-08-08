#!/usr/bin/env python3
"""
统一过滤规则 — filter_rules.py
================================
所有系统的统一过滤入口，替代散落在各脚本中的硬编码过滤逻辑。

v3.0 升级：新增「创业板精选」子池（市值TOP50），解决过去5年80%牛股在创业板的问题。

用法：
    from filter_rules import is_tradable, FilterLevel
    
    # 判断股票是否可交易
    result = is_tradable("300750")  # → {"allowed": True, "pool": "创业板精选", "reason": ""}
    result = is_tradable("688001")  # → {"allowed": False, "pool": "科创板-排除", "reason": "科创板暂不开放"}
"""

# ==================== 过滤等级 ====================

class FilterLevel:
    """过滤等级（从严格到宽松）"""
    MAINBOARD_ONLY = "主板only"        # 原规则：仅沪深主板
    MAINBOARD_PLUS_CHINEXT = "主板+创业板精选"  # 新规则：主板+创业板TOP50
    ALL_EXCEPT_ST = "全A(除ST)"        # 最宽松
    
    # 当前使用的过滤等级（可配置）
    CURRENT = MAINBOARD_PLUS_CHINEXT


# ==================== 创业板精选TOP50 ====================

# 基于2026年7月市值排序的前50只创业板股票
CHINEXT_TOP50 = {
    # 新能源/电池
    "300750": "宁德时代", "300014": "亿纬锂能", "300274": "阳光电源",
    "300457": "赢合科技", "300450": "先导智能", "300568": "星源材质",
    "300207": "欣旺达",
    
    # 医药/医疗
    "300760": "迈瑞医疗", "300015": "爱尔眼科", "300122": "智飞生物",
    "300142": "沃森生物", "300347": "泰格医药", "300529": "健帆生物",
    "300759": "康龙化成", "300832": "新产业", "300896": "爱美客",
    "300601": "康泰生物",
    
    # AI算力/光模块/芯片 (过去5年涨幅最大赛道, 必须纳入)
    "300308": "中际旭创", "300502": "新易盛", "300394": "天孚通信",
    "300476": "胜宏科技", "300463": "沪电股份", "300661": "圣邦股份",
    "300782": "卓胜微", "300433": "蓝思科技",
    
    # 互联网金融/科技
    "300059": "东方财富", "300124": "汇川技术", "300316": "晶盛机电",
    "300413": "芒果超媒", "300418": "昆仑万维", "300624": "万兴科技",
    "300033": "同花顺",
    
    # 消费/其他
    "300888": "稳健医疗", "300957": "贝泰妮", "300979": "华利集团",
    "300274": "阳光电源", "300751": "迈为股份",
    
    # 工业/制造
    "300124": "汇川技术", "300450": "先导智能", "300316": "晶盛机电",
    "300724": "捷佳伟创", "300124": "汇川技术",
    
    # 汽车产业链
    "300750": "宁德时代", "300014": "亿纬锂能", "300124": "汇川技术",
    
    # 补充剩余
    "300122": "智飞生物", "300284": "苏交科", "300236": "上海新阳",
    "300567": "精测电子", "300604": "长川科技", "300623": "捷捷微电",
    "300666": "江丰电子", "300672": "国科微",
}


# ==================== 过滤函数 ====================

# 永久排除的前缀
PERMANENT_EXCLUDE_PREFIXES = ("688", "8", "43", "83", "87")  # 科创板+北交所永久排除
ST_SUBSTRINGS = ("ST", "*ST")


def is_st(code: str, name: str = "") -> bool:
    """是否为ST股"""
    if any(s in code.upper() for s in ST_SUBSTRINGS):
        return True
    if any(s in name.upper() for s in ST_SUBSTRINGS):
        return True
    return False


def is_mainboard(code: str) -> bool:
    """沪深主板：60xxxx 或 00xxxx"""
    return code.startswith(("60", "00"))


def is_chinext(code: str) -> bool:
    """创业板：300xxx 或 301xxx"""
    return code.startswith(("300", "301"))


def is_kcb(code: str) -> bool:
    """科创板：688xxx"""
    return code.startswith("688")


def is_chinext_elite(code: str) -> bool:
    """是否在创业板精选TOP50中"""
    return code in CHINEXT_TOP50


def is_tradable(code: str, name: str = "", 
                level: str = None) -> dict:
    """
    统一入口：判断股票是否可交易
    
    Args:
        code: 6位股票代码
        name: 股票名称（用于ST判断）
        level: 过滤等级（默认使用FilterLevel.CURRENT）
    
    Returns:
        {"allowed": bool, "pool": str, "reason": str}
    """
    if level is None:
        level = FilterLevel.CURRENT
    
    code = code.strip()
    
    # === 永久排除（任何等级都适用）===
    if code.startswith(PERMANENT_EXCLUDE_PREFIXES):
        return {"allowed": False, "pool": "永久排除", 
                "reason": f"科创板/北交所({code[0]}xxx)不在交易范围内"}
    
    if is_st(code, name):
        return {"allowed": False, "pool": "ST排除", 
                "reason": "ST/*ST股不在交易范围内"}
    
    # === 按等级过滤 ===
    if level == FilterLevel.MAINBOARD_ONLY:
        if is_mainboard(code):
            return {"allowed": True, "pool": "主板", "reason": ""}
        else:
            pool_name = "创业板" if is_chinext(code) else "其他"
            return {"allowed": False, "pool": f"{pool_name}-排除", 
                    "reason": f"主板only模式下{pool_name}股不交易"}
    
    elif level == FilterLevel.MAINBOARD_PLUS_CHINEXT:
        if is_mainboard(code):
            return {"allowed": True, "pool": "主板", "reason": ""}
        elif is_chinext(code) and is_chinext_elite(code):
            return {"allowed": True, "pool": "创业板精选", 
                    "reason": f"创业板精选TOP50: {CHINEXT_TOP50.get(code, '')}"}
        elif is_chinext(code):
            return {"allowed": False, "pool": "创业板-非精选", 
                    "reason": "非创业板精选TOP50，暂不交易"}
        else:
            return {"allowed": False, "pool": "其他", "reason": "无法识别的板块"}
    
    elif level == FilterLevel.ALL_EXCEPT_ST:
        return {"allowed": True, "pool": "全A(除ST)", "reason": ""}
    
    return {"allowed": False, "pool": "未知", "reason": f"未知过滤等级: {level}"}


def get_pool_description(code: str) -> str:
    """获取股票所属池的描述"""
    result = is_tradable(code)
    if result["allowed"]:
        return f"✅ {result['pool']}"
    else:
        return f"🚫 {result['pool']}: {result['reason']}"


# ==================== 快速测试 ====================
if __name__ == "__main__":
    test_codes = [
        "600095",  # 湘财股份 → 主板 ✅
        "601138",  # 工业富联 → 主板 ✅
        "300750",  # 宁德时代 → 创业板精选 ✅
        "300308",  # 中际旭创 → 创业板精选 ✅ (之前被排除!)
        "300502",  # 新易盛 → 创业板精选 ✅ (之前被排除!)
        "688001",  # 华兴源创 → 科创板 🚫
        "002596",  # 海南瑞泽 → 主板 ✅
        "300999",  # 金龙鱼 → 创业板非精选 🚫
    ]
    
    print("过滤规则测试 (等级: 主板+创业板精选):")
    print("=" * 60)
    for code in test_codes:
        result = is_tradable(code)
        mark = "✅" if result["allowed"] else "🚫"
        print(f"  {mark} {code}: {result['pool']}")
        if result["reason"]:
            print(f"     原因: {result['reason']}")
