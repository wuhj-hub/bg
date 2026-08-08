"""
双弦投资系统 - 月度股池模块 (monthly_pool.py) v2.4
==============================================
功能：保留本月10元以下的共振及低吸结果作为月度股池
v2.4 新增：股池轮动跟踪(新增/删除标记) + 跨月对比 + 轮动报告

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

POOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pools")
MAX_PRICE = 10.0
MIN_RESONANCE_SCORE = 1


# ============================================================
# 数据结构
# ============================================================

class PoolEntry:
    """月度股池单条记录 (v2.4 新增轮动跟踪字段)"""

    def __init__(self, code: str, name: str, price: float, signal_type: str,
                 date_str: str, score: float = 0, resonance_label: str = "",
                 sector: str = "", reason: str = "",
                 is_new: bool = True):
        self.code = code
        self.name = name
        self.price = price
        self.signal_type = signal_type  # "共振" 或 "低吸"
        self.date_str = date_str        # 首次触发日期
        self.score = score
        self.resonance_label = resonance_label
        self.sector = sector
        self.reason = reason
        self.is_new = is_new            # ★ 新增：是否为本次新增

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
            "is_new": self.is_new,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PoolEntry":
        return cls(
            code=d["code"], name=d["name"], price=d["price"],
            signal_type=d["signal_type"], date_str=d["date_str"],
            score=d.get("score", 0),
            resonance_label=d.get("resonance_label", ""),
            sector=d.get("sector", ""),
            reason=d.get("reason", ""),
            is_new=d.get("is_new", False),  # 从文件加载时默认为旧
        )

    def __repr__(self):
        tag = "🆕" if self.is_new else "  "
        return f"{tag}[{self.signal_type}] {self.code} {self.name} @{self.price}"


# ============================================================
# 月度股池管理器
# ============================================================

class MonthlyPool:
    """月度股池管理器 (v2.4 新增轮动报告)"""

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
        if os.path.exists(self.pool_file):
            try:
                with open(self.pool_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entries = [PoolEntry.from_dict(e) for e in data.get("entries", [])]
                # 加载后全部标记为"旧"（is_new=False），由add方法重新标记新增
                for e in self.entries:
                    e.is_new = False
            except (json.JSONDecodeError, KeyError):
                self.entries = []
        else:
            self.entries = []

    def save(self):
        data = {
            "year_month": self.year_month,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }
        data["entries"].sort(key=lambda x: x["score"], reverse=True)
        with open(self.pool_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    @staticmethod
    def get_all_monthly_files(base_dir: str = POOL_DIR) -> list[str]:
        if not os.path.exists(base_dir):
            return []
        files = [f for f in os.listdir(base_dir) if f.startswith("pool_") and f.endswith(".json")]
        files.sort(reverse=True)
        return [os.path.join(base_dir, f) for f in files]

    @staticmethod
    def load_month(year_month: str, base_dir: str = POOL_DIR) -> list:
        """加载指定月份的股池条目"""
        filepath = os.path.join(base_dir, f"pool_{year_month}.json")
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("entries", [])
        except:
            return []

    # ---- 添加记录 ----

    def _code_exists(self, code: str) -> Optional[PoolEntry]:
        for entry in self.entries:
            if entry.code == code:
                return entry
        return None

    def add_resonance_stock(self, code: str, name: str, price: float,
                            score: float, resonance_label: str,
                            sector: str = "", reason: str = ""):
        if price > MAX_PRICE:
            return False

        existing = self._code_exists(code)
        today_str = self.today.isoformat()

        if existing:
            existing.score = max(existing.score, score)
            existing.resonance_label = resonance_label
            existing.price = price
            existing.reason = reason or f"共振{resonance_label}"
            existing.is_new = False  # 已存在，非新增
            return False
        else:
            entry = PoolEntry(
                code=code, name=name, price=price,
                signal_type="共振", date_str=today_str,
                score=score, resonance_label=resonance_label,
                sector=sector, reason=reason or f"共振{resonance_label}",
                is_new=True,  # ★ 标记为新增
            )
            self.entries.append(entry)
            return True

    def add_dip_stock(self, code: str, name: str, price: float,
                      score: float = 0, sector: str = "", reason: str = ""):
        if price > MAX_PRICE:
            return False

        existing = self._code_exists(code)
        today_str = self.today.isoformat()

        if existing:
            if existing.signal_type == "共振":
                return False
            existing.score = max(existing.score, score)
            existing.price = price
            existing.is_new = False
            return False
        else:
            entry = PoolEntry(
                code=code, name=name, price=price,
                signal_type="低吸", date_str=today_str,
                score=score, sector=sector,
                reason=reason or "MACD底背离买点",
                is_new=True,
            )
            self.entries.append(entry)
            return True

    # ---- 查询 ----

    def get_resonance_stocks(self) -> list[PoolEntry]:
        return sorted(
            [e for e in self.entries if e.signal_type == "共振"],
            key=lambda x: x.score, reverse=True
        )

    def get_dip_stocks(self) -> list[PoolEntry]:
        return sorted(
            [e for e in self.entries if e.signal_type == "低吸"],
            key=lambda x: x.score, reverse=True
        )

    def get_all_stocks(self) -> list[PoolEntry]:
        return sorted(
            self.entries,
            key=lambda x: (0 if x.signal_type == "共振" else 1, -x.score)
        )

    def get_new_stocks(self) -> list[PoolEntry]:
        """获取本次新增的股票"""
        return [e for e in self.entries if e.is_new]

    def get_stats(self) -> dict:
        total = len(self.entries)
        resonance_count = len(self.get_resonance_stocks())
        dip_count = len(self.get_dip_stocks())
        avg_score = sum(e.score for e in self.entries) / total if total > 0 else 0
        new_count = len(self.get_new_stocks())
        return {
            "year_month": self.year_month,
            "total": total,
            "resonance_count": resonance_count,
            "dip_count": dip_count,
            "avg_score": round(avg_score, 1),
            "new_count": new_count,
            "date_range": self._get_date_range(),
        }

    def _get_date_range(self) -> str:
        dates = sorted(set(e.date_str for e in self.entries))
        if not dates:
            return "暂无"
        return f"{dates[0]} ~ {dates[-1]}"

    # ---- 跨月轮动对比 (★ 新增) ----

    def get_rotation_report(self) -> dict:
        """
        生成月度轮动报告
        返回: {current_month, prev_month, new_entries, removed_entries, stats}
        """
        current_codes = set(e.code for e in self.entries)

        # 找上月股池
        year, month = self.year_month.split("-")
        prev_y, prev_m = int(year), int(month) - 1
        if prev_m == 0:
            prev_y -= 1
            prev_m = 12
        prev_key = f"{prev_y:04d}-{prev_m:02d}"
        prev_entries = self.load_month(prev_key, self.base_dir)
        prev_codes = set(e["code"] for e in prev_entries)

        # 新增股：本月有但上月没有
        new_codes = current_codes - prev_codes
        new_stocks = [e for e in self.entries if e.code in new_codes]

        # 移除股：上月有但本月没有
        removed_codes = prev_codes - current_codes
        removed_stocks = [e for e in prev_entries if e["code"] in removed_codes]

        return {
            "current_month": self.year_month,
            "prev_month": prev_key if prev_entries else None,
            "new_stocks": [(e.code, e.name, e.signal_type) for e in new_stocks],
            "removed_stocks": [(e["code"], e["name"], e["signal_type"]) for e in removed_stocks],
            "new_count": len(new_stocks),
            "removed_count": len(removed_stocks),
        }

    # ---- 报告生成 ----

    def format_rotation_report(self) -> str:
        """生成轮动报告文本"""
        rotation = self.get_rotation_report()
        stats = self.get_stats()

        lines = []
        lines.append("━" * 35)
        lines.append(f"🔄 股池轮动报告 ({stats['year_month']})")
        lines.append("━" * 35)

        # 本月概况
        lines.append(f"\n📊 本月概况: {stats['total']}只 | "
                     f"共振{stats['resonance_count']} | "
                     f"低吸{stats['dip_count']} | "
                     f"新增{stats['new_count']} | "
                     f"均分{stats['avg_score']}")
        lines.append(f"   数据范围: {stats['date_range']}")

        # 新增股
        if rotation["new_stocks"]:
            lines.append(f"\n🆕 本月新增 ({rotation['new_count']}只):")
            for code, name, stype in rotation["new_stocks"]:
                icon = "🟢" if stype == "共振" else "📉"
                lines.append(f"   {icon} {code} {name} ({stype})")
        else:
            lines.append(f"\n🆕 本月新增: 无")

        # 移除股
        if rotation["removed_stocks"]:
            lines.append(f"\n🗑️ 较上月移除 ({rotation['removed_count']}只):")
            for code, name, stype in rotation["removed_stocks"]:
                lines.append(f"   ❌ {code} {name} ({stype})")
        else:
            lines.append(f"\n🗑️ 较上月移除: 无")

        # 轮动率
        if rotation["prev_month"]:
            prev_total = len(rotation["removed_stocks"]) + len(
                [e for e in MonthlyPool.load_month(stats["year_month"], self.base_dir)
                 if e["code"] in set(e2.code for e2 in self.entries)])
            total_prev_month = len(MonthlyPool.load_month(rotation["prev_month"], self.base_dir))
            if total_prev_month > 0:
                turnover = rotation["new_count"] / total_prev_month * 100
                lines.append(f"\n📈 轮动率: {turnover:.0f}% "
                             f"(本月新增{rotation['new_count']} / 上月{total_prev_month}只)")
        else:
            lines.append(f"\n📈 轮动率: 上月无数据，首次运行")

        lines.append("━" * 35)
        return "\n".join(lines)

    def format_report(self, max_items: int = 20) -> str:
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

        resonance = self.get_resonance_stocks()
        if resonance:
            lines.append(f"\n▶ 共振股 ({len(resonance)}只, 价格≤{MAX_PRICE}元):")
            for i, entry in enumerate(resonance[:max_items], 1):
                tag = " 🆕" if entry.is_new else ""
                lines.append(
                    f"  {i}. {entry.code} {entry.name} "
                    f"@{entry.price} | 评分{entry.score} | {entry.resonance_label}{tag}"
                )
                if entry.reason:
                    lines.append(f"     {entry.reason}")

        dip = self.get_dip_stocks()
        if dip:
            lines.append(f"\n▶ 低吸股 ({len(dip)}只, 价格≤{MAX_PRICE}元):")
            for i, entry in enumerate(dip[:max_items], 1):
                tag = " 🆕" if entry.is_new else ""
                lines.append(
                    f"  {i}. {entry.code} {entry.name} "
                    f"@{entry.price} | 评分{entry.score}{tag}"
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
    pool = MonthlyPool(base_dir=base_dir)
    return pool.format_report()


def get_rotation_report(base_dir: str = POOL_DIR) -> str:
    """获取轮动报告文本（供推送/命令行调用）"""
    pool = MonthlyPool(base_dir=base_dir)
    return pool.format_rotation_report()


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(get_monthly_pool_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "rotation":
        print(get_rotation_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        pool = MonthlyPool()
        s = pool.get_stats()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print("用法: python3 monthly_pool.py [report|rotation|stats]")
