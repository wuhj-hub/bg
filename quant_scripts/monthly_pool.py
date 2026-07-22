"""
双弦投资系统 - 月度股池模块 (monthly_pool.py)
==============================================
功能：保留本月10元以下的共振及低吸结果作为月度股池，在推送中体现

设计原则：
- 轻量级：纯JSON持久化，零外部依赖
- 非侵入：不修改原系统核心逻辑，作为后处理注入
- 自动滚月：月度自动切换，历史按月归档
"""

import json
import os
from datetime import datetime, date
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 月度股池存储目录
POOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pools")
# 价格上限（与系统MAX_PRICE=10一致）
MAX_PRICE = 10.0
# 推送到月度股池的共振最低要求：≥ +1（偏多及以上）
MIN_RESONANCE_SCORE = 1


# ============================================================
# 数据结构
# ============================================================

class PoolEntry:
    """月度股池单条记录"""

    def __init__(self, code: str, name: str, price: float, signal_type: str,
                 date_str: str, score: float = 0, resonance_label: str = "",
                 sector: str = "", reason: str = ""):
        self.code = code           # 股票代码 eg. sh600519
        self.name = name           # 股票名称
        self.price = price         # 触发时价格
        self.signal_type = signal_type  # "共振" 或 "低吸"
        self.date_str = date_str   # 触发日期 YYYY-MM-DD
        self.score = score         # 三维综合评分
        self.resonance_label = resonance_label  # 共振标签
        self.sector = sector       # 所属板块
        self.reason = reason       # 触发原因简述

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "signal_type": self.signal_type,
            "date_str": self.date_str,
            "score": self.score,
            "resonance_label": self.resonance_label,
            "sector": self.sector,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PoolEntry":
        return cls(
            code=d["code"],
            name=d["name"],
            price=d["price"],
            signal_type=d["signal_type"],
            date_str=d["date_str"],
            score=d.get("score", 0),
            resonance_label=d.get("resonance_label", ""),
            sector=d.get("sector", ""),
            reason=d.get("reason", ""),
        )

    def __repr__(self):
        return f"[{self.signal_type}] {self.code} {self.name} @{self.price} ({self.date_str})"


# ============================================================
# 月度股池管理器
# ============================================================

class MonthlyPool:
    """
    月度股池管理器

    用法：
        pool = MonthlyPool()
        pool.add_resonance_stock(...)  # 添加共振股
        pool.add_dip_stock(...)        # 添加低吸股
        pool.save()                    # 保存到文件
        report = pool.format_report()  # 生成推送用文本
    """

    def __init__(self, base_dir: str = POOL_DIR):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

        self.today = date.today()
        self.year_month = self.today.strftime("%Y-%m")
        self.pool_file = os.path.join(base_dir, f"pool_{self.year_month}.json")
        self.entries: list[PoolEntry] = []
        self._load()

    # ---- 文件读写 ----

    def _load(self):
        """从JSON文件加载本月已有记录"""
        if os.path.exists(self.pool_file):
            try:
                with open(self.pool_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entries = [PoolEntry.from_dict(e) for e in data.get("entries", [])]
            except (json.JSONDecodeError, KeyError):
                self.entries = []
        else:
            self.entries = []

    def save(self):
        """保存到JSON文件"""
        data = {
            "year_month": self.year_month,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }
        # 按评分降序排列
        data["entries"].sort(key=lambda x: x["score"], reverse=True)
        with open(self.pool_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    @staticmethod
    def get_all_monthly_files(base_dir: str = POOL_DIR) -> list[str]:
        """获取所有历史月度股池文件（按月份倒序）"""
        if not os.path.exists(base_dir):
            return []
        files = [f for f in os.listdir(base_dir) if f.startswith("pool_") and f.endswith(".json")]
        files.sort(reverse=True)
        return [os.path.join(base_dir, f) for f in files]

    # ---- 添加记录 ----

    def _code_exists(self, code: str) -> Optional[PoolEntry]:
        """检查股票是否已在池中"""
        for entry in self.entries:
            if entry.code == code:
                return entry
        return None

    def add_resonance_stock(self, code: str, name: str, price: float,
                            score: float, resonance_label: str,
                            sector: str = "", reason: str = ""):
        """
        添加共振信号股票（AND门控通过 + 共振≥+1 + 价格≤10元）

        返回: True=新增, False=已存在（会更新评分）
        """
        if price > MAX_PRICE:
            return False

        existing = self._code_exists(code)
        today_str = self.today.isoformat()

        entry = PoolEntry(
            code=code, name=name, price=price,
            signal_type="共振", date_str=today_str,
            score=score, resonance_label=resonance_label,
            sector=sector, reason=reason or f"共振{resonance_label}",
        )

        if existing:
            # 已有则更新（保留更早日期，更新评分）
            existing.score = max(existing.score, score)
            existing.resonance_label = resonance_label
            existing.price = price
            existing.reason = reason or f"共振{resonance_label}"
            return False
        else:
            self.entries.append(entry)
            return True

    def add_dip_stock(self, code: str, name: str, price: float,
                      score: float = 0, sector: str = "", reason: str = ""):
        """
        添加低吸信号股票（MACD底背离买点 + 价格≤10元）

        返回: True=新增, False=已存在
        """
        if price > MAX_PRICE:
            return False

        existing = self._code_exists(code)
        today_str = self.today.isoformat()

        entry = PoolEntry(
            code=code, name=name, price=price,
            signal_type="低吸", date_str=today_str,
            score=score, sector=sector,
            reason=reason or "MACD底背离买点",
        )

        if existing:
            if existing.signal_type == "共振":
                # 如果已在池且是共振信号，保留共振（优先级更高）
                return False
            existing.score = max(existing.score, score)
            existing.price = price
            return False
        else:
            self.entries.append(entry)
            return True

    # ---- 查询 ----

    def get_resonance_stocks(self) -> list[PoolEntry]:
        """获取本月所有共振股（按评分降序）"""
        return sorted(
            [e for e in self.entries if e.signal_type == "共振"],
            key=lambda x: x.score, reverse=True
        )

    def get_dip_stocks(self) -> list[PoolEntry]:
        """获取本月所有低吸股（按评分降序）"""
        return sorted(
            [e for e in self.entries if e.signal_type == "低吸"],
            key=lambda x: x.score, reverse=True
        )

    def get_all_stocks(self) -> list[PoolEntry]:
        """获取全部月度股池（按评分降序，共振优先）"""
        return sorted(
            self.entries,
            key=lambda x: (0 if x.signal_type == "共振" else 1, -x.score)
        )

    def get_stats(self) -> dict:
        """获取月度统计"""
        total = len(self.entries)
        resonance_count = len(self.get_resonance_stocks())
        dip_count = len(self.get_dip_stocks())
        avg_score = sum(e.score for e in self.entries) / total if total > 0 else 0
        return {
            "year_month": self.year_month,
            "total": total,
            "resonance_count": resonance_count,
            "dip_count": dip_count,
            "avg_score": round(avg_score, 1),
            "date_range": self._get_date_range(),
        }

    def _get_date_range(self) -> str:
        dates = sorted(set(e.date_str for e in self.entries))
        if not dates:
            return "暂无"
        return f"{dates[0]} ~ {dates[-1]}"

    # ---- 报告生成 ----

    def format_report(self, max_items: int = 20) -> str:
        """
        生成月度股池推送文本（纯文本，适配PushPlus/Server酱）

        Args:
            max_items: 最多展示条目数

        Returns:
            格式化后的文本段落
        """
        stats = self.get_stats()
        if stats["total"] == 0:
            return ""

        lines = []
        lines.append("━" * 30)
        lines.append(f"📋 本月股池 ({stats['year_month']})")
        lines.append(f"总计 {stats['total']} 只 | 共振 {stats['resonance_count']} 只 | "
                      f"低吸 {stats['dip_count']} 只 | 均分 {stats['avg_score']}")
        lines.append(f"数据范围: {stats['date_range']}")
        lines.append("━" * 30)

        # 共振股（优先展示）
        resonance = self.get_resonance_stocks()
        if resonance:
            lines.append(f"\n▶ 共振股 ({len(resonance)}只, 价格≤{MAX_PRICE}元):")
            for i, entry in enumerate(resonance[:max_items], 1):
                lines.append(
                    f"  {i}. {entry.code} {entry.name} "
                    f"@{entry.price} | 评分{entry.score} | {entry.resonance_label}"
                )
                if entry.reason:
                    lines.append(f"     {entry.reason}")

        # 低吸股
        dip = self.get_dip_stocks()
        if dip:
            lines.append(f"\n▶ 低吸股 ({len(dip)}只, 价格≤{MAX_PRICE}元):")
            for i, entry in enumerate(dip[:max_items], 1):
                lines.append(
                    f"  {i}. {entry.code} {entry.name} "
                    f"@{entry.price} | 评分{entry.score}"
                )
                if entry.reason:
                    lines.append(f"     {entry.reason}")

        lines.append("━" * 30)
        return "\n".join(lines)


# ============================================================
# 快捷集成函数
# ============================================================

def add_daily_results(resonance_stocks: list[dict] = None,
                      dip_stocks: list[dict] = None,
                      base_dir: str = POOL_DIR) -> dict:
    """
    每日运行结束后调用，将当日共振/低吸结果加入月度股池

    Args:
        resonance_stocks: 共振股列表，每项含 {code, name, price, score, resonance_label, sector, reason}
        dip_stocks: 低吸股列表，每项含 {code, name, price, score, sector, reason}
        base_dir: 存储目录

    Returns:
        save() 返回的完整数据
    """
    pool = MonthlyPool(base_dir=base_dir)

    if resonance_stocks:
        for s in resonance_stocks:
            pool.add_resonance_stock(
                code=s["code"], name=s["name"], price=s["price"],
                score=s.get("score", 0),
                resonance_label=s.get("resonance_label", ""),
                sector=s.get("sector", ""),
                reason=s.get("reason", ""),
            )

    if dip_stocks:
        for s in dip_stocks:
            pool.add_dip_stock(
                code=s["code"], name=s["name"], price=s["price"],
                score=s.get("score", 0),
                sector=s.get("sector", ""),
                reason=s.get("reason", ""),
            )

    return pool.save()


def get_monthly_pool_report(base_dir: str = POOL_DIR) -> str:
    """获取月度股池报告文本（供推送调用）"""
    pool = MonthlyPool(base_dir=base_dir)
    return pool.format_report()


# ============================================================
# 命令行入口（调试/手动运行）
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        # python3 monthly_pool.py report
        print(get_monthly_pool_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        # python3 monthly_pool.py stats
        pool = MonthlyPool()
        stats = pool.get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print(pool.format_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        # python3 monthly_pool.py list
        files = MonthlyPool.get_all_monthly_files()
        print("历史月度股池文件:")
        for f in files:
            size = os.path.getsize(f)
            print(f"  {os.path.basename(f)} ({size} bytes)")
    else:
        print("用法: python3 monthly_pool.py [report|stats|list]")