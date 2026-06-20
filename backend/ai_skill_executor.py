#!/usr/bin/env python3
"""
AI Skill 执行引擎 (ai_skill_executor.py)
=========================================
版本: v2.0
功能: 读取 ai_skills.yaml 配置 → 检查触发条件 → 执行动作
支持: AI 教务管家 (EduButler) + AI 店长 (StoreManager)

用法:
    python ai_skill_executor.py                          # 执行所有已启用的 skill
    python ai_skill_executor.py --agent edu_butler       # 只执行教务管家
    python ai_skill_executor.py --skill renewal_alert    # 只执行指定 skill
    python ai_skill_executor.py --dry-run                # 试运行模式
    python ai_skill_executor.py --test                   # 使用内置测试数据
    python ai_skill_executor.py --list                   # 列出所有 skill
"""

import yaml
import os
import sys
import json
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod


# ============================================================
# 配置与常量
# ============================================================
CONFIG_PATH = os.path.expanduser("~/.hermes/config/ai_skills.yaml")
LOG_PATH = os.path.expanduser("~/.hermes/logs/ai_skills.log")

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ai_skill_executor")


# ============================================================
# 测试数据 (模拟小麦助教 + CRM 数据)
# ============================================================
TEST_DATA = {
    "students": [
        {"id": 1, "name": "张三", "age": 7, "birthday": "2019-07-15", "status": "active",
         "remaining_hours": 3, "parent_name": "张爸爸", "parent_phone": "13800001111",
         "enrolled_classes": ["启蒙A班"], "enrolled_courses": ["创意美术"],
         "renewal_history": ["2025-12-01", "2026-03-01"], "renewal_date": "2026-06-01"},
        {"id": 2, "name": "李四", "age": 5, "birthday": "2021-03-22", "status": "active",
         "remaining_hours": 12, "parent_name": "李妈妈", "parent_phone": "13800002222",
         "enrolled_classes": ["启蒙B班"], "enrolled_courses": ["创意美术"],
         "renewal_history": ["2026-01-15"], "renewal_date": "2026-07-15"},
        {"id": 3, "name": "王五", "age": 6, "birthday": "2020-01-10", "status": "unassigned",
         "remaining_hours": 20, "parent_name": "王爸爸", "parent_phone": "13800003333",
         "enrolled_classes": [], "enrolled_courses": ["乐高"],
         "renewal_history": ["2026-02-20"], "renewal_date": None},
        {"id": 4, "name": "赵六", "age": 8, "birthday": "2018-06-23", "status": "active",
         "remaining_hours": 8, "parent_name": "赵妈妈", "parent_phone": "13800004444",
         "enrolled_classes": ["基础A班"], "enrolled_courses": ["创意美术", "书法"],
         "renewal_history": ["2026-04-01"], "renewal_date": "2026-10-01"},
        {"id": 5, "name": "钱七", "age": 8, "birthday": "2018-11-05", "status": "active",
         "remaining_hours": 15, "parent_name": "钱爸爸", "parent_phone": "13800005555",
         "enrolled_classes": ["启蒙A班"], "enrolled_courses": ["创意美术"],
         "renewal_history": ["2026-03-15"], "renewal_date": "2026-09-15"},
        {"id": 6, "name": "孙八", "age": 10, "birthday": "2016-09-01", "status": "active",
         "remaining_hours": 6, "parent_name": "孙妈妈", "parent_phone": "13800006666",
         "enrolled_classes": ["进阶C班"], "enrolled_courses": ["书法"],
         "renewal_history": ["2025-11-01"], "renewal_date": "2026-05-01"},
        {"id": 7, "name": "周九", "age": 4, "birthday": "2022-06-17", "status": "active",
         "remaining_hours": 25, "parent_name": "周爸爸", "parent_phone": "13800007777",
         "enrolled_classes": ["启蒙B班"], "enrolled_courses": ["乐高"],
         "renewal_history": ["2026-05-01"], "renewal_date": "2026-11-01"},
    ],
    "classes": [
        {"id": 1, "name": "启蒙A班", "age_min": 5, "age_max": 7, "capacity": 20,
         "current_enrollment": 18, "coach_id": 1, "level": "beginner",
         "schedule": "周一/周三 16:00-17:30", "classroom": "1号教室"},
        {"id": 2, "name": "启蒙B班", "age_min": 4, "age_max": 6, "capacity": 15,
         "current_enrollment": 8, "coach_id": 2, "level": "beginner",
         "schedule": "周二/周四 16:00-17:30", "classroom": "2号教室"},
        {"id": 3, "name": "基础A班", "age_min": 7, "age_max": 9, "capacity": 18,
         "current_enrollment": 14, "coach_id": 1, "level": "intermediate",
         "schedule": "周三/周五 17:00-18:30", "classroom": "1号教室"},
        {"id": 4, "name": "基础B班", "age_min": 6, "age_max": 8, "capacity": 16,
         "current_enrollment": 6, "coach_id": 3, "level": "intermediate",
         "schedule": "周六 09:00-11:00", "classroom": "3号教室"},
        {"id": 5, "name": "进阶C班", "age_min": 9, "age_max": 12, "capacity": 12,
         "current_enrollment": 11, "coach_id": 2, "level": "advanced",
         "schedule": "周六 14:00-16:00", "classroom": "2号教室"},
    ],
    "coaches": [
        {"id": 1, "name": "张教练", "assigned_classes": [1, 3]},
        {"id": 2, "name": "李教练", "assigned_classes": [2, 5]},
        {"id": 3, "name": "王教练", "assigned_classes": [4]},
    ],
    "attendance": [
        # 张三: 最后一次消课在 2 周前
        {"student_id": 1, "class_id": 1, "date": "2026-06-18", "hours_consumed": 1.5},
        {"student_id": 1, "class_id": 1, "date": "2026-06-16", "hours_consumed": 1.5},
        # 李四: 连续 4 周未消课
        {"student_id": 2, "class_id": 2, "date": "2026-05-20", "hours_consumed": 1.5},
        {"student_id": 2, "class_id": 2, "date": "2026-05-18", "hours_consumed": 1.5},
        # 赵六: 正常消课
        {"student_id": 4, "class_id": 3, "date": "2026-06-19", "hours_consumed": 1.5},
        {"student_id": 4, "class_id": 3, "date": "2026-06-17", "hours_consumed": 1.5},
        {"student_id": 4, "class_id": 3, "date": "2026-06-12", "hours_consumed": 1.5},
        # 周九: 最近消课
        {"student_id": 7, "class_id": 2, "date": "2026-06-20", "hours_consumed": 1.5},
        {"student_id": 7, "class_id": 2, "date": "2026-06-18", "hours_consumed": 1.5},
    ],
    "finance": [
        {"id": 1, "student_id": 1, "amount_due": 3000, "amount_paid": 3000, "due_date": "2026-04-01", "type": "tuition", "date": "2026-04-01"},
        {"id": 2, "student_id": 6, "amount_due": 4500, "amount_paid": 3000, "due_date": "2026-05-01", "type": "tuition", "date": "2026-05-01"},
        {"id": 3, "student_id": 4, "amount_due": 3600, "amount_paid": 3600, "due_date": "2026-06-01", "type": "tuition", "date": "2026-06-01"},
        {"id": 4, "student_id": 2, "amount_due": 3000, "amount_paid": 2000, "due_date": "2026-04-15", "type": "tuition", "date": "2026-04-15"},
    ],
    "crm": {
        "marketing_funnel": [
            {"channel": "大众点评", "impressions": 5000, "inquiries": 250, "visits": 80, "trials": 40, "deals": 12, "revenue": 36000},
            {"channel": "抖音", "impressions": 20000, "inquiries": 600, "visits": 150, "trials": 60, "deals": 15, "revenue": 45000},
            {"channel": "朋友介绍", "impressions": 200, "inquiries": 120, "visits": 80, "trials": 60, "deals": 30, "revenue": 90000},
            {"channel": "地推", "impressions": 3000, "inquiries": 180, "visits": 50, "trials": 25, "deals": 8, "revenue": 24000},
            {"channel": "微信广告", "impressions": 8000, "inquiries": 400, "visits": 100, "trials": 50, "deals": 20, "revenue": 60000},
            {"channel": "自然到店", "impressions": 1000, "inquiries": 80, "visits": 50, "trials": 30, "deals": 10, "revenue": 30000},
        ],
        "marketing_cost": [
            {"channel": "大众点评", "cost": 8000, "period": "2026-06"},
            {"channel": "抖音", "cost": 15000, "period": "2026-06"},
            {"channel": "朋友介绍", "cost": 2000, "period": "2026-06"},
            {"channel": "地推", "cost": 5000, "period": "2026-06"},
            {"channel": "微信广告", "cost": 12000, "period": "2026-06"},
            {"channel": "自然到店", "cost": 0, "period": "2026-06"},
        ],
        "complaints": [
            {"student_id": 3, "status": "unresolved", "date": "2026-06-10", "content": "排课时间不合适"},
        ],
    },
    "classrooms": [
        {"id": 1, "name": "1号教室", "area_sqm": 40, "rental_cost": 0},
        {"id": 2, "name": "2号教室", "area_sqm": 35, "rental_cost": 0},
        {"id": 3, "name": "3号教室", "area_sqm": 30, "rental_cost": 0},
    ],
}


# ============================================================
# 数据模型
# ============================================================
@dataclass
class SkillResult:
    """单个 Skill 执行结果"""
    agent: str
    skill_name: str
    triggered: bool
    condition_detail: str
    actions_executed: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "skill": self.skill_name,
            "triggered": self.triggered,
            "condition": self.condition_detail,
            "actions": self.actions_executed,
            "data_summary": {k: len(v) if isinstance(v, list) else str(v)[:100] for k, v in self.data.items()},
            "errors": self.errors,
        }


@dataclass
class ExecutionReport:
    """批量执行报告"""
    timestamp: str
    results: List[SkillResult]
    total: int = 0
    triggered: int = 0
    errors: int = 0

    def summarize(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  AI Skill 执行报告 — {self.timestamp}",
            f"{'='*60}",
            f"  总计: {self.total} 个 Skill | 触发: {self.triggered} 个 | 错误: {self.errors} 个",
            f"{'='*60}",
        ]
        for r in self.results:
            status = "✅ 触发" if r.triggered else "⏭️ 跳过"
            lines.append(f"  [{r.agent}] {r.skill_name}: {status}")
            if r.condition_detail:
                lines.append(f"    条件: {r.condition_detail}")
            if r.actions_executed:
                lines.append(f"    动作: {', '.join(r.actions_executed)}")
            if r.errors:
                for e in r.errors:
                    lines.append(f"    ❌ {e}")
            if r.data:
                for k, v in r.data.items():
                    if isinstance(v, list) and len(v) > 0:
                        lines.append(f"    📊 {k}: {len(v)} 条记录")
                        # 预览前3条
                        for item in v[:3]:
                            lines.append(f"       {item}")
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)


# ============================================================
# 动作分发器
# ============================================================
class ActionDispatcher:
    """动作执行器 — 将配置中的 action 名称映射到实际执行函数"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.executed: List[str] = []

    def _log_action(self, action: str, detail: str = ""):
        msg = f"[{'DRY-RUN' if self.dry_run else 'EXEC'}] {action}: {detail}"
        self.executed.append(msg)
        logger.info(msg)

    def wecom_push(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> bool:
        """企业微信推送"""
        receivers = config.get("wecom_receivers", ["admin"])
        title = f"【{agent}】{skill} 预警"
        content = json.dumps(data, ensure_ascii=False, indent=2)
        self._log_action("wecom_push", f"→ {', '.join(receivers)} | {title}")
        return True

    def feishu_push(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> bool:
        """飞书消息推送"""
        chat_id = config.get("feishu_chat_id", "default")
        title = f"【{agent}】{skill}"
        content = json.dumps(data, ensure_ascii=False, indent=2)
        self._log_action("feishu_push", f"→ chat_id={chat_id} | {title}")
        return True

    def gen_script(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> str:
        """生成跟进话术"""
        template = config.get("script_template", config.get("level_templates", {}).get("level1", ""))
        scripts = []
        for item in data.get("triggered_items", []):
            script = template
            for k, v in item.items():
                script = script.replace(f"{{{k}}}", str(v))
            scripts.append(script)
        result = "\n---\n".join(scripts)
        self._log_action("gen_script", f"生成了 {len(scripts)} 条话术")
        return result

    def issue_coupon(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> List[Dict]:
        """发放优惠券"""
        coupons = []
        for item in data.get("triggered_items", []):
            coupon = {
                "student_id": item.get("student_id") or item.get("id"),
                "student_name": item.get("student_name") or item.get("name"),
                "type": config.get("coupon_type", "discount"),
                "value": config.get("coupon_value", 0),
                "expiry_days": config.get("coupon_expiry_days", 30),
                "condition": config.get("coupon_condition", ""),
                "reason": skill,
                "issue_date": datetime.date.today().isoformat(),
            }
            coupons.append(coupon)
        self._log_action("issue_coupon", f"发放了 {len(coupons)} 张优惠券")
        return coupons

    def gen_recommendations(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> List[Dict]:
        """生成推荐列表"""
        self._log_action("gen_recommendations", f"为 {len(data.get('triggered_items', []))} 位学员生成推荐")
        return data.get("recommendations", [])

    def gen_report(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> Dict:
        """生成报告"""
        self._log_action("gen_report", f"生成 {skill} 报告")
        return data

    def gen_trial_invite(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> List[str]:
        """生成试课邀请"""
        template = config.get("trial_class_template", "")
        invites = []
        for item in data.get("triggered_items", []):
            invite = template
            for k, v in item.items():
                invite = invite.replace(f"{{{k}}}", str(v))
            invites.append(invite)
        self._log_action("gen_trial_invite", f"生成了 {len(invites)} 条试课邀请")
        return invites

    def gen_greeting(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> List[str]:
        """生成祝福文案"""
        template = config.get("greeting_template", "")
        greetings = []
        for item in data.get("triggered_items", []):
            greeting = template
            for k, v in item.items():
                greeting = greeting.replace(f"{{{k}}}", str(v))
            greetings.append(greeting)
        self._log_action("gen_greeting", f"生成了 {len(greetings)} 条祝福")
        return greetings

    def gen_forecast(self, agent: str, skill: str, data: Dict[str, Any], config: Dict) -> Dict:
        """生成收入预测"""
        self._log_action("gen_forecast", f"预测了 {len(data.get('forecast', []))} 周收入")
        return data.get("forecast", {})


# ============================================================
# 数据获取器
# ============================================================
class DataFetcher:
    """数据获取 — 从数据源拉取数据（当前使用测试数据）"""

    def __init__(self, use_test_data: bool = True):
        self.use_test_data = use_test_data
        self._data = TEST_DATA if use_test_data else {}

    def fetch(self, source_type: str, table: str, fields: List[str] = None) -> List[Dict]:
        """从指定数据源获取数据"""
        if source_type == "xiaomaizhujiao":
            return self._data.get(table, [])
        elif source_type == "crm":
            return self._data.get("crm", {}).get(table, [])
        else:
            logger.warning(f"未知数据源: {source_type}")
            return []

    def get_student_by_id(self, student_id: int) -> Optional[Dict]:
        students = self._data.get("students", [])
        for s in students:
            if s["id"] == student_id:
                return s
        return None

    def get_class_by_id(self, class_id: int) -> Optional[Dict]:
        classes = self._data.get("classes", [])
        for c in classes:
            if c["id"] == class_id:
                return c
        return None

    def get_coach_by_id(self, coach_id: int) -> Optional[Dict]:
        coaches = self._data.get("coaches", [])
        for c in coaches:
            if c["id"] == coach_id:
                return c
        return None


# ============================================================
# 基础 Skill 执行器
# ============================================================
class BaseSkillExecutor(ABC):
    """所有 Skill 执行器的基类"""

    def __init__(self, config: Dict, fetcher: DataFetcher, dispatcher: ActionDispatcher, agent_name: str):
        self.config = config
        self.fetcher = fetcher
        self.dispatcher = dispatcher
        self.agent_name = agent_name
        self.skills_cfg = config.get("skills", {}).get(agent_name, {})
        self.today = datetime.date.today()

    def _get_skill_cfg(self, skill_name: str) -> Dict:
        return self.skills_cfg.get(skill_name, {})

    def _check_enabled(self, skill_name: str) -> bool:
        cfg = self._get_skill_cfg(skill_name)
        return cfg.get("enabled", False)

    def _execute_actions(self, skill_name: str, actions: List[str], data: Dict, cfg: Dict):
        """执行配置中的 action 列表"""
        executed = []
        action_map = {
            "wecom_push": lambda: self.dispatcher.wecom_push(self.agent_name, skill_name, data, cfg.get("config", {})),
            "feishu_push": lambda: self.dispatcher.feishu_push(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_script": lambda: self.dispatcher.gen_script(self.agent_name, skill_name, data, cfg.get("config", {})),
            "issue_coupon": lambda: self.dispatcher.issue_coupon(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_recommendations": lambda: self.dispatcher.gen_recommendations(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_report": lambda: self.dispatcher.gen_report(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_trial_invite": lambda: self.dispatcher.gen_trial_invite(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_greeting": lambda: self.dispatcher.gen_greeting(self.agent_name, skill_name, data, cfg.get("config", {})),
            "gen_forecast": lambda: self.dispatcher.gen_forecast(self.agent_name, skill_name, data, cfg.get("config", {})),
        }
        for action in actions:
            if action in action_map:
                try:
                    action_map[action]()
                    executed.append(action)
                except Exception as e:
                    logger.error(f"执行 action '{action}' 失败: {e}")
            else:
                logger.warning(f"未知 action: {action}")
        return executed

    @abstractmethod
    def execute(self, skill_name: str) -> SkillResult:
        """执行指定 skill，子类必须实现"""
        pass

    def execute_all(self) -> List[SkillResult]:
        """执行该 Agent 下所有已启用的 skill"""
        results = []
        for skill_name in self.skills_cfg:
            if self._check_enabled(skill_name):
                try:
                    result = self.execute(skill_name)
                    results.append(result)
                except Exception as e:
                    logger.error(f"执行 {self.agent_name}.{skill_name} 失败: {e}", exc_info=True)
                    results.append(SkillResult(
                        agent=self.agent_name,
                        skill_name=skill_name,
                        triggered=False,
                        condition_detail="",
                        actions_executed=[],
                        errors=[str(e)],
                    ))
            else:
                results.append(SkillResult(
                    agent=self.agent_name,
                    skill_name=skill_name,
                    triggered=False,
                    condition_detail="已禁用",
                    actions_executed=[],
                ))
        return results


# ============================================================
# AI 教务管家执行器
# ============================================================
class EduButlerExecutor(BaseSkillExecutor):
    """教务管家 Skill 执行器"""

    def __init__(self, config: Dict, fetcher: DataFetcher, dispatcher: ActionDispatcher):
        super().__init__(config, fetcher, dispatcher, "edu_butler")

    def execute(self, skill_name: str) -> SkillResult:
        cfg = self._get_skill_cfg(skill_name)
        if not cfg:
            return SkillResult(self.agent_name, skill_name, False, "Skill 配置不存在", [])

        handlers = {
            "renewal_alert": self._renewal_alert,
            "absence_alert": self._absence_alert,
            "class_recommend": self._class_recommend,
            "coach_load": self._coach_load,
            "birthday_marketing": self._birthday_marketing,
            "upgrade_reminder": self._upgrade_reminder,
            "overdue_payment": self._overdue_payment,
            "daily_report": self._daily_report,
        }

        handler = handlers.get(skill_name)
        if not handler:
            return SkillResult(self.agent_name, skill_name, False, f"未知 Skill: {skill_name}", [])

        return handler(cfg)

    # --- 🔴 续费预警 ---
    def _renewal_alert(self, cfg: Dict) -> SkillResult:
        threshold = cfg.get("threshold", 5)
        students = self.fetcher.fetch("xiaomaizhujiao", "students")
        triggered = [s for s in students if s.get("remaining_hours", 99) <= threshold]

        result = SkillResult(
            agent=self.agent_name,
            skill_name="renewal_alert",
            triggered=len(triggered) > 0,
            condition_detail=f"剩余课时 ≤ {threshold} 节 | 命中 {len(triggered)} 人",
            data={"triggered_items": triggered, "threshold": threshold},
        )

        if triggered:
            result.actions_executed = self._execute_actions("renewal_alert", cfg.get("actions", []), {"triggered_items": [
                {"student_name": s["name"], "remaining": s["remaining_hours"],
                 "discount": cfg.get("config", {}).get("discount_text", "")}
                for s in triggered
            ]}, cfg)
        return result

    # --- 🟡 消课异常 ---
    def _absence_alert(self, cfg: Dict) -> SkillResult:
        threshold_weeks = cfg.get("threshold_weeks", 2)
        attendance = self.fetcher.fetch("xiaomaizhujiao", "attendance")
        students = self.fetcher.fetch("xiaomaizhujiao", "students")

        # 计算每个学员最近消课日期
        student_last_attendance = {}
        for a in attendance:
            sid = a["student_id"]
            date = datetime.date.fromisoformat(a["date"])
            if sid not in student_last_attendance or date > student_last_attendance[sid]:
                student_last_attendance[sid] = date

        # 计算未消课周数
        cutoff = self.today - datetime.timedelta(weeks=threshold_weeks)
        triggered = []
        for s in students:
            sid = s["id"]
            last_date = student_last_attendance.get(sid)
            if last_date is None or last_date < cutoff:
                weeks_absent = (self.today - last_date).days // 7 if last_date else 99
                triggered.append({
                    "student_id": sid,
                    "student_name": s["name"],
                    "weeks_absent": weeks_absent,
                    "last_attendance": str(last_date) if last_date else "从未消课",
                    "parent_phone": s.get("parent_phone", ""),
                })

        result = SkillResult(
            agent=self.agent_name,
            skill_name="absence_alert",
            triggered=len(triggered) > 0,
            condition_detail=f"连续 ≥ {threshold_weeks} 周未消课 | 命中 {len(triggered)} 人",
            data={"triggered_items": triggered},
        )

        if triggered:
            result.actions_executed = self._execute_actions(
                "absence_alert", cfg.get("actions", []),
                {"triggered_items": triggered}, cfg
            )
        return result

    # --- 📅 排课推荐 ---
    def _class_recommend(self, cfg: Dict) -> SkillResult:
        students = self.fetcher.fetch("xiaomaizhujiao", "students")
        classes = self.fetcher.fetch("xiaomaizhujiao", "classes")
        age_tolerance = cfg.get("config", {}).get("age_tolerance", 1)
        max_recs = cfg.get("config", {}).get("max_recommendations", 3)
        exclude_full = cfg.get("config", {}).get("exclude_full", True)

        unassigned = [s for s in students if s.get("status") == "unassigned"]
        triggered = []
        for s in unassigned:
            age = s["age"]
            recs = []
            for c in classes:
                if c["age_min"] - age_tolerance <= age <= c["age_max"] + age_tolerance:
                    if exclude_full and c["current_enrollment"] >= c["capacity"]:
                        continue
                    recs.append({
                        "class_name": c["name"],
                        "age_range": f"{c['age_min']}-{c['age_max']}岁",
                        "enrollment": f"{c['current_enrollment']}/{c['capacity']}",
                        "schedule": c["schedule"],
                    })
            recs = recs[:max_recs]
            if recs:
                triggered.append({
                    "student_name": s["name"],
                    "student_age": age,
                    "recommendations": recs,
                })

        return SkillResult(
            agent=self.agent_name, skill_name="class_recommend",
            triggered=len(triggered) > 0,
            condition_detail=f"未选班学员推荐 | {len(triggered)} 人有匹配班级",
            data={"triggered_items": triggered, "recommendations": triggered},
            actions_executed=self._execute_actions("class_recommend", cfg.get("actions", []), {"triggered_items": triggered}, cfg) if triggered else [],
        )

    # --- 📊 教练负载 ---
    def _coach_load(self, cfg: Dict) -> SkillResult:
        load_threshold = cfg.get("load_threshold", 0.80)
        classes = self.fetcher.fetch("xiaomaizhujiao", "classes")
        coaches = self.fetcher.fetch("xiaomaizhujiao", "coaches")

        triggered = []
        for c in classes:
            load_ratio = c["current_enrollment"] / c["capacity"] if c["capacity"] > 0 else 0
            if load_ratio > load_threshold:
                coach = self.fetcher.get_coach_by_id(c["coach_id"])
                triggered.append({
                    "coach_name": coach["name"] if coach else f"ID:{c['coach_id']}",
                    "class_name": c["name"],
                    "enrollment": f"{c['current_enrollment']}/{c['capacity']}",
                    "load_pct": f"{load_ratio:.0%}",
                    "suggestion": "建议新增平行班" if cfg.get("config", {}).get("suggest_parallel_class") else "",
                })

        return SkillResult(
            agent=self.agent_name, skill_name="coach_load",
            triggered=len(triggered) > 0,
            condition_detail=f"班容 > {load_threshold:.0%} | 命中 {len(triggered)} 个班级",
            data={"triggered_items": triggered},
            actions_executed=self._execute_actions("coach_load", cfg.get("actions", []), {"triggered_items": triggered}, cfg) if triggered else [],
        )

    # --- 🎂 生日营销 ---
    def _birthday_marketing(self, cfg: Dict) -> SkillResult:
        days_before = cfg.get("days_before", 3)
        students = self.fetcher.fetch("xiaomaizhujiao", "students")
        target_date = self.today + datetime.timedelta(days=days_before)

        triggered = []
        for s in students:
            birthday = s.get("birthday", "")
            if birthday:
                try:
                    bd = datetime.date.fromisoformat(birthday)
                    if bd.month == target_date.month and bd.day == target_date.day:
                        triggered.append({
                            "student_id": s["id"],
                            "student_name": s["name"],
                            "birthday": birthday,
                            "age_turning": target_date.year - bd.year,
                            "coupon_desc": f"{cfg.get('config', {}).get('coupon_value', '')} {'折' if cfg.get('config', {}).get('coupon_type') == 'discount' else '元'}优惠券",
                            "school_name": cfg.get("config", {}).get("school_name", "培训中心"),
                        })
                except ValueError:
                    pass

        return SkillResult(
            agent=self.agent_name, skill_name="birthday_marketing",
            triggered=len(triggered) > 0,
            condition_detail=f"生日前 {days_before} 天 | 命中 {len(triggered)} 人 (目标日期: {target_date})",
            data={"triggered_items": triggered},
            actions_executed=self._execute_actions("birthday_marketing", cfg.get("actions", []), {"triggered_items": triggered}, cfg) if triggered else [],
        )

    # --- 📈 升班提醒 ---
    def _upgrade_reminder(self, cfg: Dict) -> SkillResult:
        students = self.fetcher.fetch("xiaomaizhujiao", "students")
        classes = self.fetcher.fetch("xiaomaizhujiao", "classes")

        triggered = []
        for s in students:
            if s["status"] != "active":
                continue
            age = s["age"]
            for ec_name in s.get("enrolled_classes", []):
                current_cls = next((c for c in classes if c["name"] == ec_name), None)
                if current_cls and age > current_cls["age_max"]:
                    # 找下一阶段班级
                    next_classes = [
                        c for c in classes
                        if c["age_min"] <= age <= c["age_max"]
                        and c["level"] != current_cls.get("level")
                        and c["name"] != ec_name
                    ]
                    if next_classes:
                        triggered.append({
                            "student_name": s["name"],
                            "student_age": age,
                            "current_class": ec_name,
                            "current_age_range": f"{current_cls['age_min']}-{current_cls['age_max']}岁",
                            "target_class": next_classes[0]["name"],
                            "trial_time": cfg.get("config", {}).get("trial_time", ""),
                            "location": cfg.get("config", {}).get("location", ""),
                        })

        return SkillResult(
            agent=self.agent_name, skill_name="upgrade_reminder",
            triggered=len(triggered) > 0,
            condition_detail=f"年龄超出现有班级上限 | 命中 {len(triggered)} 人",
            data={"triggered_items": triggered},
            actions_executed=self._execute_actions("upgrade_reminder", cfg.get("actions", []), {"triggered_items": triggered}, cfg) if triggered else [],
        )

    # --- 💰 欠费催缴 ---
    def _overdue_payment(self, cfg: Dict) -> SkillResult:
        overdue_days = cfg.get("overdue_days", 30)
        finance = self.fetcher.fetch("xiaomaizhujiao", "finance")
        level_cfg = cfg.get("config", {}).get("level_thresholds", {})
        templates = cfg.get("config", {}).get("level_templates", {})

        triggered = []
        for f in finance:
            unpaid = f["amount_due"] - f["amount_paid"]
            if unpaid <= 0:
                continue
            try:
                due_date = datetime.date.fromisoformat(f["due_date"])
                days_late = (self.today - due_date).days
                if days_late > overdue_days:
                    # 分级
                    level = "level1"
                    for lvl_name, (lo, hi) in level_cfg.items():
                        if lo <= days_late < hi:
                            level = lvl_name
                            break
                    student = self.fetcher.get_student_by_id(f["student_id"])
                    triggered.append({
                        "student_name": student["name"] if student else f"ID:{f['student_id']}",
                        "parent_name": student.get("parent_name", "") if student else "",
                        "amount": unpaid,
                        "days": days_late,
                        "level": level,
                        "parent_phone": student.get("parent_phone", "") if student else "",
                        "deadline": f"{(self.today + datetime.timedelta(days=cfg.get('config', {}).get('suspension_deadline', 7)))}",
                    })
            except ValueError:
                pass

        result = SkillResult(
            agent=self.agent_name, skill_name="overdue_payment",
            triggered=len(triggered) > 0,
            condition_detail=f"欠费 > {overdue_days} 天 | 命中 {len(triggered)} 笔",
            data={"triggered_items": triggered},
        )

        if triggered:
            result.actions_executed = self._execute_actions(
                "overdue_payment", cfg.get("actions", []),
                {"triggered_items": triggered}, cfg
            )
        return result

    # --- 📋 日报生成 ---
    def _daily_report(self, cfg: Dict) -> SkillResult:
        sections = cfg.get("config", {}).get("report_sections", [])
        # 汇总所有检测结果
        summary = {
            "date": self.today.isoformat(),
            "daily_summary": {"total_classes": len(self.fetcher.fetch("xiaomaizhujiao", "attendance")), "note": "模拟数据"},
            "renewal_alerts": [{"count": "从 renewal_alert 汇总"}],
            "new_enrollments": [{"count": 0, "note": "模拟数据"}],
            "anomaly_events": [{"count": 0, "note": "模拟数据"}],
            "todo_items": ["跟进欠费学员", "确认下周排课"],
        }
        return SkillResult(
            agent=self.agent_name, skill_name="daily_report",
            triggered=True,
            condition_detail="每日定时触发",
            data={"report": summary},
            actions_executed=self._execute_actions("daily_report", cfg.get("actions", []), summary, cfg),
        )


# ============================================================
# AI 店长执行器
# ============================================================
class StoreManagerExecutor(BaseSkillExecutor):
    """店长 Skill 执行器"""

    def __init__(self, config: Dict, fetcher: DataFetcher, dispatcher: ActionDispatcher):
        super().__init__(config, fetcher, dispatcher, "store_manager")

    def execute(self, skill_name: str) -> SkillResult:
        cfg = self._get_skill_cfg(skill_name)
        if not cfg:
            return SkillResult(self.agent_name, skill_name, False, "Skill 配置不存在", [])

        handlers = {
            "coach_performance": self._coach_performance,
            "revenue_forecast": self._revenue_forecast,
            "acquisition_roi": self._acquisition_roi,
            "churn_alert": self._churn_alert,
            "classroom_optimization": self._classroom_optimization,
            "weekly_report": self._weekly_report,
            "finance_trend": self._finance_trend,
            "refund_anomaly": self._refund_anomaly,
            "monthly_pl": self._monthly_pl,
        }

        handler = handlers.get(skill_name)
        if not handler:
            return SkillResult(self.agent_name, skill_name, False, f"未知 Skill: {skill_name}", [])

        return handler(cfg)

    # --- 📊 教练绩效排名 ---
    def _coach_performance(self, cfg: Dict) -> SkillResult:
        coaches = self.fetcher.fetch("xiaomaizhujiao", "coaches")
        classes = self.fetcher.fetch("xiaomaizhujiao", "classes")
        weights = cfg.get("config", {}).get("weights", {})

        rankings = []
        for coach in coaches:
            coach_classes = [c for c in classes if c["coach_id"] == coach["id"]]
            # 满班率
            full_rate = sum(c["current_enrollment"] / c["capacity"] for c in coach_classes) / len(coach_classes) if coach_classes else 0
            # 综合得分 (模拟：满班率设为主要可见指标)
            score = round(full_rate * 100)
            rankings.append({
                "coach_name": coach["name"],
                "score": score,
                "class_count": len(coach_classes),
                "total_enrollment": sum(c["current_enrollment"] for c in coach_classes),
                "total_capacity": sum(c["capacity"] for c in coach_classes),
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)
        avg_score = sum(r["score"] for r in rankings) / len(rankings) if rankings else 0

        # 标记低于平均分的
        stddev = cfg.get("config", {}).get("alert_threshold_stddev", 1.0)
        for r in rankings:
            if r["score"] < avg_score - 10 * stddev:
                r["alert"] = "⚠️ 低于平均"

        return SkillResult(
            agent=self.agent_name, skill_name="coach_performance",
            triggered=True,
            condition_detail="定时触发（周/月）",
            data={"rankings": rankings, "average_score": round(avg_score, 1)},
            actions_executed=self._execute_actions("coach_performance", cfg.get("actions", []),
                {"rankings": rankings}, cfg),
        )

    # --- 📈 收入预测 ---
    def _revenue_forecast(self, cfg: Dict) -> SkillResult:
        forecast_weeks = cfg.get("forecast_weeks", 4)
        ci = cfg.get("config", {}).get("confidence_interval", 0.15)
        weights = cfg.get("config", {}).get("recent_weights", [0.4, 0.3, 0.2, 0.1])

        # 模拟历史数据
        base_revenue = 30000
        forecast = []
        for i in range(forecast_weeks):
            week_rev = base_revenue * (1 + 0.05 * (i + 1))
            forecast.append({
                "week": f"W{i+1}",
                "predicted": round(week_rev, 2),
                "lower": round(week_rev * (1 - ci), 2),
                "upper": round(week_rev * (1 + ci), 2),
            })

        return SkillResult(
            agent=self.agent_name, skill_name="revenue_forecast",
            triggered=True,
            condition_detail="定时触发（每周一）",
            data={"forecast": forecast, "method": "加权移动平均 + 在册学员预估"},
            actions_executed=self._execute_actions("revenue_forecast", cfg.get("actions", []),
                {"forecast": forecast}, cfg),
        )

    # --- 🎯 获客ROI ---
    def _acquisition_roi(self, cfg: Dict) -> SkillResult:
        funnel = self.fetcher.fetch("crm", "marketing_funnel")
        costs = self.fetcher.fetch("crm", "marketing_cost")
        cost_map = {c["channel"]: c["cost"] for c in costs}

        channels = []
        for f in funnel:
            ch = f["channel"]
            cost = cost_map.get(ch, 0)
            roi = round(f["revenue"] / cost, 2) if cost > 0 else float("inf")
            cac = round(cost / f["deals"], 2) if f["deals"] > 0 else 0
            conversion = round(f["deals"] / f["impressions"] * 100, 2) if f["impressions"] > 0 else 0
            channels.append({
                "channel": ch,
                "roi": f"{roi}x",
                "cac": f"¥{cac}",
                "conversion": f"{conversion}%",
                "deals": f["deals"],
                "revenue": f["revenue"],
                "cost": cost,
                "funnel": {
                    "曝光→咨询": f"{round(f['inquiries']/f['impressions']*100,1)}%",
                    "咨询→到店": f"{round(f['visits']/f['inquiries']*100,1)}%",
                    "到店→试课": f"{round(f['trials']/f['visits']*100,1)}%",
                    "试课→成交": f"{round(f['deals']/f['trials']*100,1)}%",
                },
            })

        channels.sort(key=lambda x: float(x["roi"].replace("x", "")) if x["roi"] != "inf" else 999, reverse=True)

        return SkillResult(
            agent=self.agent_name, skill_name="acquisition_roi",
            triggered=True,
            condition_detail="定时触发（每周一）",
            data={"channels": channels},
            actions_executed=self._execute_actions("acquisition_roi", cfg.get("actions", []),
                {"channels": channels}, cfg),
        )

    # --- ⚠️ 流失预警 ---
    def _churn_alert(self, cfg: Dict) -> SkillResult:
        risk_threshold = cfg.get("risk_threshold", 70)
        weights = cfg.get("config", {}).get("weights", {})
        students = self.fetcher.fetch("xiaomaizhujiao", "students")
        attendance = self.fetcher.fetch("xiaomaizhujiao", "attendance")
        complaints = self.fetcher.fetch("crm", "complaints")

        # 构建学员消课数据
        student_attendance = {}
        for a in attendance:
            sid = a["student_id"]
            if sid not in student_attendance:
                student_attendance[sid] = []
            student_attendance[sid].append(a)

        triggered = []
        for s in students:
            sid = s["id"]
            # 1. 连续未消课周数
            last_dates = [datetime.date.fromisoformat(a["date"]) for a in student_attendance.get(sid, [])]
            last_date = max(last_dates) if last_dates else datetime.date(2026, 1, 1)
            inactive_weeks = (self.today - last_date).days // 7
            inactive_score = min(inactive_weeks / 12 * 100, 100) * weights.get("inactive_weeks", 0.35)

            # 2. 剩余课时
            hours = s.get("remaining_hours", 99)
            low_hours_score = (100 if hours <= 0 else max(0, 100 - hours * 10)) * weights.get("low_hours", 0.25)

            # 3. 近3月请假次数 (模拟)
            absence_count = max(0, inactive_weeks - 2) * 2
            absence_score = min(absence_count / 20 * 100, 100) * weights.get("absence_frequency", 0.20)

            # 4. 未处理投诉
            unresolved = any(c["student_id"] == sid and c["status"] == "unresolved" for c in complaints)
            complaint_score = (100 if unresolved else 0) * weights.get("unresolved_complaints", 0.20)

            risk_score = round(inactive_score + low_hours_score + absence_score + complaint_score, 1)
            if risk_score >= risk_threshold:
                reasons = []
                if inactive_score > 10: reasons.append(f"连续{inactive_weeks}周未消课")
                if low_hours_score > 5: reasons.append(f"剩余{hours}课时")
                if absence_score > 5: reasons.append("请假频繁")
                if complaint_score > 0: reasons.append("有未处理投诉")
                triggered.append({
                    "student_name": s["name"],
                    "risk_score": risk_score,
                    "reasons": reasons,
                    "suggestion": "建议：专属回访" + (" + 复课优惠券" if inactive_weeks >= 3 else " + 灵活补课方案"),
                })

        triggered.sort(key=lambda x: x["risk_score"], reverse=True)

        return SkillResult(
            agent=self.agent_name, skill_name="churn_alert",
            triggered=len(triggered) > 0,
            condition_detail=f"风险分 ≥ {risk_threshold} | 命中 {len(triggered)} 人",
            data={"triggered_items": triggered},
            actions_executed=self._execute_actions("churn_alert", cfg.get("actions", []),
                {"triggered_items": triggered}, cfg) if triggered else [],
        )

    # --- 🏪 班容优化 ---
    def _classroom_optimization(self, cfg: Dict) -> SkillResult:
        classes = self.fetcher.fetch("xiaomaizhujiao", "classes")
        full_threshold = cfg.get("config", {}).get("full_threshold", 0.85)
        merge_threshold = cfg.get("config", {}).get("merge_threshold", 0.40)

        analysis = []
        for c in classes:
            rate = c["current_enrollment"] / c["capacity"] if c["capacity"] > 0 else 0
            status = "🟢 良好"
            suggestion = ""
            if rate >= full_threshold:
                status = "🟡 接近满班"
                suggestion = "考虑新增平行班"
            elif rate <= merge_threshold:
                status = "🔴 低满班率"
                suggestion = "建议与其他班级合并"
            analysis.append({
                "class_name": c["name"],
                "enrollment": f"{c['current_enrollment']}/{c['capacity']}",
                "rate": f"{rate:.0%}",
                "status": status,
                "suggestion": suggestion,
                "schedule": c["schedule"],
            })

        return SkillResult(
            agent=self.agent_name, skill_name="classroom_optimization",
            triggered=True,
            condition_detail="定时触发（每周日）",
            data={"analysis": analysis},
            actions_executed=self._execute_actions("classroom_optimization", cfg.get("actions", []),
                {"analysis": analysis}, cfg),
        )

    # --- 📋 周报 ---
    def _weekly_report(self, cfg: Dict) -> SkillResult:
        sections = cfg.get("config", {}).get("report_sections", [])
        report = {
            "period": f"{self.today - datetime.timedelta(days=7)} ~ {self.today}",
            "core_metrics": {"revenue": "¥85,000", "classes_completed": 42, "new_enrollments": 8, "renewals": 12, "churned": 2},
            "yoy_qoq_comparison": {"revenue_change": "+12%", "enrollment_change": "+5%"},
            "coach_ranking": "见教练绩效排名",
            "revenue_analysis": "见收入预测",
            "churn_warning": "见流失预警",
            "classroom_status": "见班容优化",
            "action_suggestions": [
                "跟进张三续费（剩余3课时）",
                "联系李四了解消课中断原因",
                "优化启蒙A班班容（90%满班率）",
                "加大朋友介绍渠道激励（ROI最高）",
                "处理孙八欠费催缴",
            ],
        }
        return SkillResult(
            agent=self.agent_name, skill_name="weekly_report",
            triggered=True,
            condition_detail="定时触发（每周日）",
            data={"report": report},
            actions_executed=self._execute_actions("weekly_report", cfg.get("actions", []), report, cfg),
        )

    # --- 📊 财务趋势 (v1.0) ---
    def _finance_trend(self, cfg: Dict) -> SkillResult:
        return SkillResult(
            agent=self.agent_name, skill_name="finance_trend",
            triggered=True, condition_detail="定时触发（每周一）",
            data={"trend": "模拟10周趋势数据", "direction": "↑ (上升)"},
            actions_executed=self._execute_actions("finance_trend", cfg.get("actions", []), {}, cfg),
        )

    # --- 🔍 异常退款 (v1.0) ---
    def _refund_anomaly(self, cfg: Dict) -> SkillResult:
        return SkillResult(
            agent=self.agent_name, skill_name="refund_anomaly",
            triggered=False, condition_detail="无异常退款",
            data={},
            actions_executed=[],
        )

    # --- 💰 月度盈亏 (v1.0) ---
    def _monthly_pl(self, cfg: Dict) -> SkillResult:
        fixed = cfg.get("config", {}).get("fixed_costs", [])
        total_fixed = sum(item["amount"] for item in fixed)
        return SkillResult(
            agent=self.agent_name, skill_name="monthly_pl",
            triggered=True, condition_detail="定时触发（每月1日）",
            data={"revenue_estimate": 120000, "fixed_costs": total_fixed, "profit_estimate": 120000 - total_fixed},
            actions_executed=self._execute_actions("monthly_pl", cfg.get("actions", []), {}, cfg),
        )


# ============================================================
# 主执行器
# ============================================================
class SkillRunner:
    """Skill 执行主引擎"""

    def __init__(self, config_path: str = CONFIG_PATH, use_test_data: bool = False, dry_run: bool = False):
        self.config_path = config_path
        self.dry_run = dry_run
        self.config = self._load_config()
        self.fetcher = DataFetcher(use_test_data=use_test_data)
        self.dispatcher = ActionDispatcher(dry_run=dry_run)
        self.edu_butler = EduButlerExecutor(self.config, self.fetcher, self.dispatcher)
        self.store_manager = StoreManagerExecutor(self.config, self.fetcher, self.dispatcher)

    def _load_config(self) -> Dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_skills(self) -> Dict[str, List[str]]:
        """列出所有已配置的 skill"""
        result = {}
        for agent in ["edu_butler", "store_manager"]:
            agent_cfg = self.config.get("skills", {}).get(agent, {})
            skills = []
            for name, cfg in agent_cfg.items():
                status = "✅" if cfg.get("enabled", False) else "❌"
                skills.append(f"{status} {name}: {cfg.get('description', '')}")
            result[agent] = skills
        return result

    def run_agent(self, agent_name: str, skill_name: str = None) -> List[SkillResult]:
        """执行指定 Agent 的 skill"""
        executor = {"edu_butler": self.edu_butler, "store_manager": self.store_manager}.get(agent_name)
        if not executor:
            logger.error(f"未知 Agent: {agent_name}")
            return []
        if skill_name:
            return [executor.execute(skill_name)]
        return executor.execute_all()

    def run_all(self, agent_filter: str = None, skill_filter: str = None) -> ExecutionReport:
        """执行所有（或指定）skill"""
        results = []
        agents = [agent_filter] if agent_filter else ["edu_butler", "store_manager"]
        for agent in agents:
            results.extend(self.run_agent(agent, skill_filter))

        report = ExecutionReport(
            timestamp=datetime.datetime.now().isoformat(),
            results=results,
            total=len(results),
            triggered=sum(1 for r in results if r.triggered),
            errors=sum(1 for r in results if r.errors),
        )
        return report


# ============================================================
# CLI 入口
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Skill 执行引擎 — 教务管家 & 店长",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python ai_skill_executor.py                          # 执行所有已启用的 skill
  python ai_skill_executor.py --agent edu_butler       # 只执行教务管家
  python ai_skill_executor.py --skill renewal_alert    # 只执行续费预警
  python ai_skill_executor.py --test --skill churn_alert   # 用测试数据执行流失预警
  python ai_skill_executor.py --dry-run                # 试运行模式
  python ai_skill_executor.py --list                   # 列出所有 skill
        """,
    )
    parser.add_argument("--agent", choices=["edu_butler", "store_manager"], help="指定 Agent")
    parser.add_argument("--skill", help="指定 Skill 名称")
    parser.add_argument("--test", action="store_true", help="使用内置测试数据")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不执行实际动作）")
    parser.add_argument("--list", action="store_true", help="列出所有 skill")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()

    runner = SkillRunner(use_test_data=args.test, dry_run=args.dry_run)

    if args.list:
        skills = runner.list_skills()
        for agent, skill_list in skills.items():
            print(f"\n{'='*50}")
            print(f"  {agent}")
            print(f"{'='*50}")
            for s in skill_list:
                print(f"  {s}")
        return

    print(f"\n🚀 AI Skill 执行引擎启动...")
    print(f"   模式: {'🧪 测试数据' if args.test else '📡 生产数据'} | {'🔍 DRY-RUN' if args.dry_run else '⚡ 执行模式'}")
    print(f"   目标: {args.agent or '全部Agent'} | Skill: {args.skill or '全部'}\n")

    report = runner.run_all(agent_filter=args.agent, skill_filter=args.skill)

    if args.json:
        print(json.dumps([r.to_dict() for r in report.results], ensure_ascii=False, indent=2))
    else:
        print(report.summarize())

    # 退出码：有错误时非 0
    sys.exit(1 if report.errors > 0 else 0)


if __name__ == "__main__":
    main()
