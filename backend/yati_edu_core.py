#!/usr/bin/env python3
"""
亚体教务系统 v1.0 — 核心后端框架
===================================
FastAPI + SQLite + 排课引擎 + AI 增强

用法:
    # 初始化数据库
    python yati_edu_core.py --init

    # 导入小麦助教数据
    python yati_edu_core.py --import-xiaomai ~/.hermes/data/xiaomai/data_latest.json

    # 启动 API 服务
    python yati_edu_core.py --serve

    # 启动服务（开发模式）
    uvicorn yati_edu_core:app --host 0.0.0.0 --port 8000 --reload

依赖:
    pip install fastapi uvicorn sqlalchemy pydantic

💰 变现点：本文件 = 亚体教务系统核心，可独立部署或打包为 SaaS
📦 打包节点：整个 backend/ 目录 + SQLite 数据库 = 一次部署
"""

import argparse
import json
import os
import re
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Union
from contextlib import asynccontextmanager

# ── FastAPI ────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ── SQLAlchemy ─────────────────────────────────────────
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, ForeignKey,
    CheckConstraint, UniqueConstraint, Index, event
)
from sqlalchemy.orm import (
    DeclarativeBase, Session, sessionmaker, Mapped, mapped_column, relationship
)
from sqlalchemy.sql import func

# ══════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════

BASE_DIR = Path.home() / "yati-edu"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "yati_edu.db"
BACKUP_DIR = Path.home() / ".hermes" / "data" / "yati_edu" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ══════════════════════════════════════════════════════════
# SQLAlchemy 模型（ORM 映射，与 SQL schema 一致）
# ══════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    gender: Mapped[str] = mapped_column(String(4), default="")
    birthday: Mapped[str] = mapped_column(String(10), default="")
    parent_name: Mapped[str] = mapped_column(String(100), default="")
    parent_phone: Mapped[str] = mapped_column(String(20), default="")
    wechat_unionid: Mapped[str] = mapped_column(String(64), default="")
    school: Mapped[str] = mapped_column(String(100), default="")
    grade: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    source: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    enrollments = relationship("Enrollment", back_populates="student", lazy="selectin")
    credits = relationship("LessonCredit", back_populates="student", lazy="selectin")
    payments = relationship("Payment", back_populates="student", lazy="selectin")

    __table_args__ = (
        Index("idx_students_phone", "phone"),
        Index("idx_students_status", "status"),
        Index("idx_students_name", "name"),
    )


class Coach(Base):
    __tablename__ = "coaches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    wechat_unionid: Mapped[str] = mapped_column(String(64), default="")
    specialties: Mapped[str] = mapped_column(String(200), default="")
    max_daily_slots: Mapped[int] = mapped_column(default=6)
    max_consecutive: Mapped[int] = mapped_column(default=3)
    prefer_morning: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")
    hire_date: Mapped[str] = mapped_column(String(10), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    schedules = relationship("ClassSchedule", back_populates="coach", lazy="selectin")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), default="📚")
    color: Mapped[str] = mapped_column(String(20), default="#1890ff")
    duration_min: Mapped[int] = mapped_column(default=60)
    max_students: Mapped[int] = mapped_column(default=8)
    price_per_lesson: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(default=8)
    location: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class ClassSchedule(Base):
    __tablename__ = "class_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    coach_id: Mapped[int] = mapped_column(ForeignKey("coaches.id"), nullable=False)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), nullable=False)
    class_name: Mapped[str] = mapped_column(String(100), nullable=False)
    day_of_week: Mapped[int] = mapped_column(nullable=False)
    time_start: Mapped[str] = mapped_column(String(10), nullable=False)
    time_end: Mapped[str] = mapped_column(String(10), nullable=False)
    semester: Mapped[str] = mapped_column(String(20), default="regular")
    max_students: Mapped[int] = mapped_column(default=8)
    current_students: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    coach = relationship("Coach", back_populates="schedules", foreign_keys=[coach_id], primaryjoin="ClassSchedule.coach_id == Coach.id")
    enrollments = relationship("Enrollment", back_populates="schedule", lazy="selectin")

    __table_args__ = (
        Index("idx_schedules_coach", "coach_id"),
        Index("idx_schedules_day", "day_of_week"),
        Index("idx_schedules_course", "course_id"),
    )


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("class_schedules.id"), nullable=False)
    enrolled_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str] = mapped_column(Text, default="")

    student = relationship("Student", back_populates="enrollments", foreign_keys=[student_id])
    schedule = relationship("ClassSchedule", back_populates="enrollments", foreign_keys=[schedule_id])

    __table_args__ = (
        UniqueConstraint("student_id", "schedule_id"),
        Index("idx_enrollments_student", "student_id"),
        Index("idx_enrollments_schedule", "schedule_id"),
    )


class LessonCredit(Base):
    __tablename__ = "lesson_credits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    package_name: Mapped[str] = mapped_column(String(100), default="")
    total_lessons: Mapped[int] = mapped_column(nullable=False)
    consumed: Mapped[int] = mapped_column(default=0)
    remaining: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[float] = mapped_column(default=0.0)
    total_price: Mapped[float] = mapped_column(nullable=False)
    paid_amount: Mapped[float] = mapped_column(default=0.0)
    expiry_date: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    source_order_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    student = relationship("Student", back_populates="credits", foreign_keys=[student_id])

    __table_args__ = (
        CheckConstraint("consumed <= total_lessons"),
        Index("idx_credits_student", "student_id"),
        Index("idx_credits_expiry", "expiry_date"),
        Index("idx_credits_status", "status"),
    )


class Attendance(Base):
    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("class_schedules.id"), nullable=False)
    credit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lesson_credits.id"), nullable=True)
    check_in_time: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    check_method: Mapped[str] = mapped_column(String(20), default="manual")
    check_coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("coaches.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="present")
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    __table_args__ = (
        Index("idx_attendance_student", "student_id"),
        Index("idx_attendance_schedule", "schedule_id"),
        Index("idx_attendance_date", "check_in_time"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    credit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lesson_credits.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # charge / refund
    amount: Mapped[float] = mapped_column(nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="")
    transaction_id: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="completed")
    remark: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(50), default="")
    paid_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    created_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    student = relationship("Student", back_populates="payments", foreign_keys=[student_id])

    __table_args__ = (
        Index("idx_payments_student", "student_id"),
        Index("idx_payments_date", "paid_at"),
        Index("idx_payments_type", "type"),
    )


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(30), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ══════════════════════════════════════════════════════════
# Pydantic Schema（API 请求/响应）
# ══════════════════════════════════════════════════════════

class StudentCreate(BaseModel):
    name: str
    phone: str
    parent_name: str = ""
    parent_phone: str = ""
    school: str = ""
    grade: str = ""
    notes: str = ""
    source: str = ""

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    school: Optional[str] = None
    grade: Optional[str] = None
    notes: Optional[str] = None

class CoachCreate(BaseModel):
    name: str
    phone: str
    specialties: str = ""
    max_daily_slots: int = 6
    max_consecutive: int = 3
    prefer_morning: bool = True

class CourseCreate(BaseModel):
    name: str
    emoji: str = "📚"
    duration_min: int = 60
    max_students: int = 8
    price_per_lesson: float = 0.0

class ScheduleCreate(BaseModel):
    course_id: int
    coach_id: int
    classroom_id: int
    class_name: str
    day_of_week: int
    time_start: str
    time_end: str
    max_students: int = 8
    start_date: str
    end_date: str = ""
    semester: str = "regular"

class ScheduleAutoArrange(BaseModel):
    semester: str = "regular"
    start_date: str
    end_date: str
    time_slots: list[dict] = []
    project_demand: dict[str, int] = {}
    classrooms: int = 5
    coach_constraints: dict = {}

class CheckInRequest(BaseModel):
    student_id: int
    schedule_id: int
    check_method: str = "manual"
    check_coach_id: Optional[int] = None

class CreditCreate(BaseModel):
    student_id: int
    course_id: int
    package_name: str = ""
    total_lessons: int
    total_price: float
    paid_amount: float = 0.0
    expiry_date: str = ""

class PaymentCreate(BaseModel):
    student_id: int
    credit_id: Optional[int] = None
    type: str  # charge / refund
    amount: float
    method: str = ""
    transaction_id: str = ""
    remark: str = ""
    operator: str = ""

class NotifyRequest(BaseModel):
    channel: str = "wecom"  # wecom / sms
    target: str = ""        # 手机号 或 企业微信webhook URL
    title: str = ""
    content: str = ""

class APIResponse(BaseModel):
    code: int = 0
    data: Union[dict, list, None] = None
    message: str = "ok"


# ══════════════════════════════════════════════════════════
# 数据库初始化
# ══════════════════════════════════════════════════════════

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """启用 WAL 模式 + 外键约束"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_database():
    """创建所有表 + 默认数据"""
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # 默认教室
        if db.query(Classroom).count() == 0:
            for name, cap, loc in [
                ("场地A", 8, "室内主场地"),
                ("场地B", 8, "室内副场地"),
                ("场地C", 8, "室内小场地"),
                ("场地D", 8, "户外-跑道区"),
                ("场地E", 8, "户外-综合区"),
            ]:
                db.add(Classroom(name=name, capacity=cap, location=loc))

        # 默认课程
        if db.query(Course).count() == 0:
            default_courses = [
                ("体能训练课", "💪", "#f5222d", 60, 8, 46.8),
                ("跳绳", "🏃", "#52c41a", 60, 8, 46.8),
                ("田径", "🏃", "#fa8c16", 60, 8, 46.8),
                ("增高", "📈", "#1890ff", 60, 8, 58.0),
            ]
            for name, emoji, color, dur, max_s, price in default_courses:
                db.add(Course(name=name, emoji=emoji, color=color, duration_min=dur, max_students=max_s, price_per_lesson=price))

        # 默认系统配置
        defaults = {
            "org_name": "亚体少儿运动馆体育",
            "lesson_warning_threshold": "10",
            "version": "1.0.0",
        }
        for k, v in defaults.items():
            if not db.query(SystemConfig).filter(SystemConfig.key == k).first():
                db.add(SystemConfig(key=k, value=v))

        db.commit()

    print(f"✅ 数据库初始化完成: {DB_PATH}")
    print(f"   WAL 模式已启用 | 外键约束已开启")


# ══════════════════════════════════════════════════════════
# 排课引擎（移植自 schedule_optimizer.py）
# ══════════════════════════════════════════════════════════

class ScheduleEngine:
    """AI 增强排课引擎 — 贪心 + 约束满足"""

    def __init__(self, config: dict):
        self.config = config
        self.time_slots = config.get("time_slots", [])
        self.project_demand = config.get("project_demand", {})
        self.classrooms = config.get("classrooms", 5)
        self.coach_constraints = config.get("coach_constraints", {})
        self.max_consecutive = self.coach_constraints.get("max_consecutive", 3)
        self.warnings = []

    def _load_coaches(self, db: Session) -> list[dict]:
        coaches = db.query(Coach).filter(Coach.status == "active").all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "specialties": [s.strip() for s in c.specialties.split(",") if s.strip()],
                "max_slots": c.max_daily_slots,
                "max_consecutive": c.max_consecutive,
                "prefer_morning": bool(c.prefer_morning),
            }
            for c in coaches
        ]

    def _load_courses(self, db: Session) -> dict[int, dict]:
        courses = db.query(Course).filter(Course.status == "active").all()
        return {c.id: {"name": c.name, "emoji": c.emoji, "color": c.color} for c in courses}

    def optimize(self, db: Session) -> dict:
        """执行排课优化，返回结果字典"""
        coaches_data = self._load_coaches(db)
        courses_data = self._load_courses(db)

        if not self.time_slots:
            self.time_slots = [
                {"start": "09:00", "end": "10:00", "period": "morning"},
                {"start": "10:00", "end": "11:00", "period": "morning"},
                {"start": "11:00", "end": "12:00", "period": "morning"},
                {"start": "16:00", "end": "17:00", "period": "afternoon"},
                {"start": "17:00", "end": "18:00", "period": "afternoon"},
                {"start": "18:00", "end": "19:00", "period": "afternoon"},
            ]

        n_slots = len(self.time_slots)
        schedule = [[None for _ in range(self.classrooms)] for _ in range(n_slots)]

        # 教练状态追踪
        coach_slots = {c["name"]: 0 for c in coaches_data}
        coach_consecutive = {c["name"]: 0 for c in coaches_data}
        coach_last_slot = {c["name"]: -1 for c in coaches_data}
        coach_projects = {c["name"]: set(c["specialties"]) for c in coaches_data}
        coach_prefer = {c["name"]: c.get("prefer_morning", True) for c in coaches_data}

        # 构建待排课列表（按课程名匹配 project_demand）
        pending = []
        course_name_map = {v["name"]: k for k, v in courses_data.items()}
        for proj_name, count in self.project_demand.items():
            for i in range(count):
                pending.append({"course_name": proj_name, "index": i})

        for slot_idx, slot in enumerate(self.time_slots):
            period = slot.get("period", "morning")
            available = [
                c["name"] for c in coaches_data
                if coach_slots[c["name"]] < c.get("max_slots", 6)
                and coach_consecutive[c["name"]] < self.max_consecutive
            ]

            if not available:
                self.warnings.append(f"⚠️ {slot['start']}-{slot['end']} 无可用教练")
                continue

            for room in range(self.classrooms):
                if not pending:
                    break

                best_score, best_coach, best_pi, best_cname = -9999, None, None, None

                for pi, pj in enumerate(pending):
                    for coach_name in available:
                        # 教练能否教此项目
                        if pj["course_name"] not in coach_projects.get(coach_name, set()):
                            continue
                        # 已在本时段排课
                        already = [schedule[slot_idx][r]["coach"] for r in range(room) if schedule[slot_idx][r]]
                        if coach_name in already:
                            continue

                        score = 0.0
                        if (period == "morning" and coach_prefer.get(coach_name, True)) or \
                           (period == "afternoon" and not coach_prefer.get(coach_name, True)):
                            score += 2
                        if coach_last_slot[coach_name] == slot_idx - 1:
                            score += 3
                        if coach_consecutive[coach_name] >= self.max_consecutive - 1:
                            score -= 5
                        remaining_slots = coaches_data[0].get("max_slots", 6) - coach_slots[coach_name]
                        score += remaining_slots * 0.3

                        if score > best_score:
                            best_score = score
                            best_coach = coach_name
                            best_pi = pi
                            best_cname = pj["course_name"]

                if best_coach is None or best_score < -500:
                    self.warnings.append(f"⚠️ {slot['start']}-{slot['end']} 教室{room+1}: 无合适教练")
                    continue

                schedule[slot_idx][room] = {
                    "course": best_cname,
                    "coach": best_coach,
                }

                coach_slots[best_coach] += 1
                coach_consecutive[best_coach] += 1
                coach_last_slot[best_coach] = slot_idx

                for cn in coach_slots:
                    if cn != best_coach and coach_last_slot[cn] != slot_idx:
                        coach_consecutive[cn] = 0

                pending.pop(best_pi)
                available = [a for a in available if a != best_coach]

        # 统计
        assigned = {}
        for row in schedule:
            for cell in row:
                if cell:
                    assigned[cell["course"]] = assigned.get(cell["course"], 0) + 1

        unassigned = []
        remaining_count = {}
        for p in pending:
            remaining_count[p["course_name"]] = remaining_count.get(p["course_name"], 0) + 1
        for cn, count in remaining_count.items():
            unassigned.append({"course": cn, "count": count})
            self.warnings.append(f"⚠️ {cn} 还有 {count} 节未排入")

        return {
            "success": len(pending) == 0,
            "schedule": [
                {
                    "slot": f"{s['start']}-{s['end']}",
                    "period": s.get("period", ""),
                    "rooms": [
                        {
                            "room": f"教室{ri+1}",
                            "course": cell["course"] if cell else None,
                            "coach": cell["coach"] if cell else None,
                        }
                        for ri, cell in enumerate(row)
                    ],
                }
                for si, (s, row) in enumerate(zip(self.time_slots, schedule))
            ],
            "stats": {
                "total_classes": sum(assigned.values()),
                "max_capacity": n_slots * self.classrooms,
                "coach_workload": {
                    c["name"]: {
                        "assigned": coach_slots[c["name"]],
                        "max": c.get("max_slots", 6),
                        "utilization": f"{round(coach_slots[c['name']] / max(c.get('max_slots', 6), 1) * 100)}%",
                    }
                    for c in coaches_data
                },
                "project_assigned": assigned,
                "project_demand": self.project_demand,
            },
            "unassigned": unassigned,
            "warnings": self.warnings,
        }


# ══════════════════════════════════════════════════════════
# 数据导入引擎（小麦助教 → 亚体少儿运动馆）
# ══════════════════════════════════════════════════════════

def parse_class_info(class_str: str) -> dict:
    """
    解析班级名如 "胖虎周六10点班" → {coach: "胖虎", day: 6, time: "10:00"}
    """
    result = {"coach": "", "day_of_week": -1, "time": "", "class_name": class_str}
    if not class_str or class_str == "未选班":
        return result

    day_map = {"周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 0}

    # 尝试匹配 "教练名+星期+时间+班"
    for day_cn, day_num in day_map.items():
        if day_cn in class_str:
            result["day_of_week"] = day_num
            parts = class_str.split(day_cn)
            if parts:
                result["coach"] = parts[0].strip()
            if len(parts) > 1:
                time_part = parts[1]
                tm = re.search(r"(\d{1,2})点", time_part)
                if tm:
                    hour = int(tm.group(1))
                    result["time"] = f"{hour:02d}:00"
            break

    return result


def import_xiaomai_data(json_path: str, dry_run: bool = False):
    """从小麦助教 JSON 导入数据到 亚体少儿运动馆数据库"""
    print(f"📂 读取数据: {json_path}")
    with open(json_path, "r") as f:
        raw = json.load(f)

    students_raw = raw.get("students", [])
    finance_raw = raw.get("finance", {})
    print(f"   学员记录: {len(students_raw)} 条")
    print(f"   财务记录: {len(finance_raw)} 周")

    if dry_run:
        print("\n🔍 DRY RUN — 仅分析，不写入数据库\n")
        _dry_run_analysis(students_raw, finance_raw)
        return

    db = SessionLocal()
    try:
        # 1. 确保基础数据（课程 + 教室）
        existing_courses = {c.name: c for c in db.query(Course).all()}
        existing_classrooms = {c.name: c for c in db.query(Classroom).all()}
        if not existing_classrooms:
            raise RuntimeError("数据库未初始化，请先运行 --init")

        stats = {"students_new": 0, "students_existing": 0, "credits": 0, "payments": 0, "schedules": 0}
        _enrolled = set()  # 追踪已创建的报班关系，避免同批次重复

        # 2. 逐条处理学员
        phone_seen = set()
        for s_raw in students_raw:
            phone = s_raw["phone"]
            course_name = s_raw["course"].replace("\ue80f", "").strip()
            class_str = s_raw["class"]
            total_lessons = s_raw.get("total_lessons", 0)
            remaining = s_raw.get("remaining", 0)
            paid = s_raw.get("paid", 0)
            total_value = s_raw.get("total_value", 0)
            expiry = s_raw.get("expiry", "")

            # 2a. 创建/获取学员（手机号去重）
            if phone in phone_seen:
                student = db.query(Student).filter(Student.phone == phone).first()
            else:
                student = db.query(Student).filter(Student.phone == phone).first()
                if not student:
                    student = Student(name=f"学员{phone[-4:]}", phone=phone)
                    db.add(student)
                    db.flush()
                    stats["students_new"] += 1
                else:
                    stats["students_existing"] += 1
                phone_seen.add(phone)

            # 2b. 创建/获取课程
            if course_name not in existing_courses:
                course = Course(name=course_name)
                db.add(course)
                db.flush()
                existing_courses[course_name] = course
                print(f"   ➕ 新建课程: {course_name}")
            course = existing_courses[course_name]

            # 2c. 创建课时包（仅当有有效课时数据）
            if total_lessons > 0:
                # 避免重复课时包（同一手机号+课程+到期日）
                existing_credit = db.query(LessonCredit).filter(
                    LessonCredit.student_id == student.id,
                    LessonCredit.course_id == course.id,
                ).first()

                if not existing_credit:
                    credit = LessonCredit(
                        student_id=student.id,
                        course_id=course.id,
                        package_name=f"{course_name}课时包",
                        total_lessons=total_lessons,
                        consumed=total_lessons - remaining if remaining < total_lessons else 0,
                        remaining=remaining,
                        unit_price=total_value / total_lessons if total_lessons > 0 else 0,
                        total_price=total_value,
                        paid_amount=paid,
                        expiry_date=expiry,
                        source_order_id=f"xiaomai-{phone}",
                    )
                    db.add(credit)
                    db.flush()
                    stats["credits"] += 1

                    # 2d. 创建收费记录
                    if paid > 0:
                        payment = Payment(
                            student_id=student.id,
                            credit_id=credit.id,
                            type="charge",
                            amount=paid,
                            method="imported",
                            status="completed",
                            remark=f"从小麦助教导入 + ¥{paid:,.2f}",
                            operator="system",
                            paid_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        db.add(payment)
                        stats["payments"] += 1

            # 2e. 创建排班记录（如果班级名有效）
            class_info = parse_class_info(class_str)
            if class_info["day_of_week"] >= 0 and class_info["coach"] and class_info["time"]:
                coach = db.query(Coach).filter(Coach.name.like(f"%{class_info['coach']}%")).first()
                if not coach:
                    coach = Coach(
                        name=class_info["coach"],
                        phone=f"1990000{stats['schedules']:04d}",
                        specialties=course_name,
                    )
                    db.add(coach)
                    db.flush()

                time_end_h = int(class_info["time"].split(":")[0]) + 1
                time_end = f"{time_end_h:02d}:00"

                classroom = list(existing_classrooms.values())[0]

                existing_schedule = db.query(ClassSchedule).filter(
                    ClassSchedule.class_name.like(f"%{class_info['coach']}%{class_info['time']}%"),
                ).first()

                if not existing_schedule:
                    schedule = ClassSchedule(
                        course_id=course.id,
                        coach_id=coach.id,
                        classroom_id=classroom.id,
                        class_name=f"{class_info['coach']}周{class_info['day_of_week']}{class_info['time']}班",
                        day_of_week=class_info["day_of_week"],
                        time_start=class_info["time"],
                        time_end=time_end,
                        start_date=datetime.now().strftime("%Y-%m-%d"),
                        status="active",
                    )
                    db.add(schedule)
                    db.flush()
                    stats["schedules"] += 1
                    existing_schedule = schedule

                # 创建报班关系
                enroll_key = (student.id, existing_schedule.id)
                if enroll_key not in _enrolled:
                    existing_enrollment = db.query(Enrollment).filter(
                        Enrollment.student_id == student.id,
                        Enrollment.schedule_id == existing_schedule.id,
                    ).first()
                    if not existing_enrollment:
                        enrollment = Enrollment(
                            student_id=student.id,
                            schedule_id=existing_schedule.id,
                        )
                        db.add(enrollment)
                        _enrolled.add(enroll_key)

        # 3. 导入财务数据
        for date_str, fin_data in finance_raw.items():
            if fin_data.get("collected", 0) > 0:
                # 找到该日期的学员收入汇总
                pass  # 财务数据按日期聚合，需要额外映射逻辑

        db.commit()
        print(f"\n✅ 导入完成:")
        print(f"   新增学员: {stats['students_new']} | 已有学员: {stats['students_existing']}")
        print(f"   课时包: {stats['credits']} | 收费记录: {stats['payments']}")
        print(f"   排课记录: {stats['schedules']}")

    except Exception as e:
        db.rollback()
        print(f"❌ 导入失败: {e}")
        raise
    finally:
        db.close()


def _dry_run_analysis(students: list, finance: dict):
    """导入前分析：展示数据概况 + 潜在问题"""
    print("📊 数据概况分析\n")

    # 课程分布
    courses = {}
    for s in students:
        c = s["course"].replace("\ue80f", "").strip()
        courses[c] = courses.get(c, 0) + 1
    print("课程分布:")
    for c, n in sorted(courses.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n} 人")

    # 班级状态
    no_class = [s for s in students if "未选班" in s.get("class", "")]
    low_lesson = [s for s in students if 0 < s.get("remaining", 0) <= 10]
    expired = [s for s in students if s.get("expiry") and s["expiry"] < datetime.now().strftime("%Y-%m-%d")]

    print(f"\n⚠️ 预警:")
    print(f"  未选班: {len(no_class)} 人")
    print(f"  课时不足(≤10): {len(low_lesson)} 人")
    print(f"  已到期未消: {len(expired)} 人")

    total_paid = sum(s.get("paid", 0) for s in students)
    total_value = sum(s.get("total_value", 0) for s in students)
    print(f"\n💰 财务概要:")
    print(f"  实收总额: ¥{total_paid:,.2f}")
    print(f"  应收总额: ¥{total_value:,.2f}")
    print(f"  待收款: ¥{total_value - total_paid:,.2f}")


# ══════════════════════════════════════════════════════════
# FastAPI 应用
# ══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时确保数据库存在"""
    if not DB_PATH.exists():
        print("⚠️ 数据库未初始化，仅 API 文档可用。运行 --init 初始化。")
    yield

app = FastAPI(
    title="亚体教务系统 v1.0",
    description="体培机构教务管理系统 — 学员/排课/签到/财务一站式",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── 系统 ────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "database": str(DB_PATH)}


@app.get("/api/backup")
def backup_db():
    """数据库备份下载"""
    if not DB_PATH.exists():
        raise HTTPException(404, "数据库不存在")
    backup_path = BACKUP_DIR / f"yati_edu_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    return FileResponse(backup_path, filename=backup_path.name, media_type="application/octet-stream")


# ── 学员管理 ────────────────────────────────────────

@app.get("/api/students")
def list_students(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
):
    query = db.query(Student)
    if search:
        query = query.filter(
            (Student.name.contains(search)) |
            (Student.phone.contains(search)) |
            (Student.parent_name.contains(search))
        )
    if status:
        query = query.filter(Student.status == status)
    if status is None or status == "":
        query = query.filter(Student.status != "deleted")

    total = query.count()
    items = query.order_by(Student.id.desc()).offset((page - 1) * size).limit(size).all()

    result = []
    for s in items:
        active_credits = [c for c in s.credits if c.status == "active"]
        total_lessons = sum(c.total_lessons for c in active_credits)
        remaining = sum(c.remaining for c in active_credits)
        pending = sum(c.total_price - c.paid_amount for c in active_credits)

        enrollments = []
        for e in s.enrollments:
            if e.status == "active" and e.schedule:
                sch = e.schedule
                enrollments.append({
                    "class_name": sch.class_name,
                    "day_of_week": sch.day_of_week,
                    "time": f"{sch.time_start}-{sch.time_end}",
                })

        result.append({
            "id": s.id,
            "name": s.name,
            "phone": _mask_phone(s.phone),
            "status": s.status,
            "total_lessons": total_lessons,
            "remaining": remaining,
            "enrollments": enrollments,
            "pending_payment": round(pending, 2),
            "source": s.source,
            "created_at": s.created_at,
        })

    return {"code": 0, "data": {"total": total, "page": page, "items": result}}


@app.get("/api/students/{student_id}")
def get_student(student_id: int, db: Session = Depends(get_db)):
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(404, "学员不存在")

    credits_data = []
    for c in s.credits:
        credits_data.append({
            "id": c.id,
            "course": _get_course_name(db, c.course_id),
            "package_name": c.package_name,
            "total_lessons": c.total_lessons,
            "consumed": c.consumed,
            "remaining": c.remaining,
            "total_price": c.total_price,
            "paid_amount": c.paid_amount,
            "expiry_date": c.expiry_date,
            "status": c.status,
        })

    payments_data = []
    for p in s.payments:
        payments_data.append({
            "id": p.id,
            "type": p.type,
            "amount": p.amount,
            "method": p.method,
            "status": p.status,
            "paid_at": p.paid_at,
            "remark": p.remark,
        })

    return {
        "code": 0,
        "data": {
            "id": s.id,
            "name": s.name,
            "phone": _mask_phone(s.phone),
            "parent_name": s.parent_name,
            "parent_phone": _mask_phone(s.parent_phone) if s.parent_phone else "",
            "school": s.school,
            "grade": s.grade,
            "notes": s.notes,
            "status": s.status,
            "source": s.source,
            "credits": credits_data,
            "payments": payments_data,
        },
    }


@app.post("/api/students")
def create_student(body: StudentCreate, db: Session = Depends(get_db)):
    existing = db.query(Student).filter(Student.phone == body.phone).first()
    if existing:
        raise HTTPException(409, f"手机号 {body.phone} 已存在 (学员ID: {existing.id})")

    student = Student(
        name=body.name,
        phone=body.phone,
        parent_name=body.parent_name,
        parent_phone=body.parent_phone or body.phone,
        school=body.school,
        grade=body.grade,
        notes=body.notes,
        source=body.source,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"code": 0, "data": {"id": student.id, "name": student.name}, "message": "学员创建成功"}


@app.put("/api/students/{student_id}")
def update_student(student_id: int, body: StudentUpdate, db: Session = Depends(get_db)):
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(404, "学员不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(s, key, value)
    s.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return {"code": 0, "message": "更新成功"}


@app.delete("/api/students/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(404, "学员不存在")
    s.status = "deleted"
    s.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return {"code": 0, "message": "已软删除"}


# ── 教练管理 ────────────────────────────────────────

@app.get("/api/coaches")
def list_coaches(db: Session = Depends(get_db)):
    coaches = db.query(Coach).filter(Coach.status == "active").all()
    return {
        "code": 0,
        "data": [
            {
                "id": c.id,
                "name": c.name,
                "phone": _mask_phone(c.phone),
                "specialties": c.specialties,
                "max_daily_slots": c.max_daily_slots,
                "prefer_morning": bool(c.prefer_morning),
                "schedule_count": len(c.schedules) if hasattr(c, 'schedules') else 0,
            }
            for c in coaches
        ],
    }


@app.post("/api/coaches")
def create_coach(body: CoachCreate, db: Session = Depends(get_db)):
    existing = db.query(Coach).filter(Coach.phone == body.phone).first()
    if existing:
        raise HTTPException(409, "手机号已存在")

    coach = Coach(
        name=body.name,
        phone=body.phone,
        specialties=body.specialties,
        max_daily_slots=body.max_daily_slots,
        max_consecutive=body.max_consecutive,
        prefer_morning=1 if body.prefer_morning else 0,
    )
    db.add(coach)
    db.commit()
    db.refresh(coach)
    return {"code": 0, "data": {"id": coach.id, "name": coach.name}}


# ── 课程管理 ────────────────────────────────────────

@app.get("/api/courses")
def list_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).filter(Course.status == "active").all()
    return {
        "code": 0,
        "data": [
            {"id": c.id, "name": c.name, "emoji": c.emoji, "color": c.color,
             "duration_min": c.duration_min, "max_students": c.max_students,
             "price_per_lesson": c.price_per_lesson}
            for c in courses
        ],
    }


@app.post("/api/courses")
def create_course(body: CourseCreate, db: Session = Depends(get_db)):
    existing = db.query(Course).filter(Course.name == body.name).first()
    if existing:
        raise HTTPException(409, "课程已存在")

    course = Course(**body.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"code": 0, "data": {"id": course.id, "name": course.name}}


# ── 排课管理 ────────────────────────────────────────

@app.get("/api/schedules")
def list_schedules(
    day_of_week: Optional[int] = Query(None),
    coach_id: Optional[int] = Query(None),
    semester: str = Query(""),
    db: Session = Depends(get_db),
):
    query = db.query(ClassSchedule).filter(ClassSchedule.status == "active")
    if day_of_week is not None:
        query = query.filter(ClassSchedule.day_of_week == day_of_week)
    if coach_id:
        query = query.filter(ClassSchedule.coach_id == coach_id)
    if semester:
        query = query.filter(ClassSchedule.semester == semester)

    schedules = query.order_by(ClassSchedule.day_of_week, ClassSchedule.time_start).all()
    return {
        "code": 0,
        "data": [
            {
                "id": s.id,
                "class_name": s.class_name,
                "course": _get_course_name(db, s.course_id),
                "coach": _get_coach_name(db, s.coach_id),
                "day_of_week": s.day_of_week,
                "time": f"{s.time_start}-{s.time_end}",
                "semester": s.semester,
                "students": s.current_students,
                "max_students": s.max_students,
                "start_date": s.start_date,
            }
            for s in schedules
        ],
    }


@app.post("/api/schedules")
def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    schedule = ClassSchedule(**body.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {"code": 0, "data": {"id": schedule.id, "class_name": schedule.class_name}}


@app.post("/api/schedules/auto-arrange")
def auto_arrange_schedules(body: ScheduleAutoArrange, db: Session = Depends(get_db)):
    """🤖 AI 自动排课"""
    config = {
        "time_slots": body.time_slots if body.time_slots else None,
        "project_demand": body.project_demand,
        "classrooms": body.classrooms,
        "coach_constraints": body.coach_constraints if body.coach_constraints else {"max_consecutive": 3},
    }
    engine = ScheduleEngine(config)
    result = engine.optimize(db)

    # 可选：保存到数据库
    save_to_db = True
    saved_count = 0
    if save_to_db and result["success"]:
        today = datetime.now().strftime("%Y-%m-%d")
        course_map = {c.name: c for c in db.query(Course).filter(Course.status == "active").all()}
        coach_map = {c.name: c for c in db.query(Coach).filter(Coach.status == "active").all()}
        classrooms = db.query(Classroom).filter(Classroom.status == "active").all()

        for slot_data in result["schedule"]:
            for ri, room_data in enumerate(slot_data["rooms"]):
                if not room_data["course"] or not room_data["coach"]:
                    continue
                course = course_map.get(room_data["course"])
                coach = coach_map.get(room_data["coach"])
                if not course or not coach or ri >= len(classrooms):
                    continue

                start, end = slot_data["slot"].split("-")
                schedule = ClassSchedule(
                    course_id=course.id,
                    coach_id=coach.id,
                    classroom_id=classrooms[ri].id,
                    class_name=f"{room_data['course']}{room_data['coach']}{start}班",
                    day_of_week=1,  # 默认周一，实际需根据排课周期设定
                    time_start=start,
                    time_end=end,
                    semester=body.semester,
                    start_date=body.start_date,
                    end_date=body.end_date,
                )
                db.add(schedule)
                saved_count += 1
        db.commit()

    result["saved_to_db"] = saved_count
    return {"code": 0, "data": result}


# ── 签到消课（核心）─────────────────────────────────

@app.post("/api/attendance/check-in")
def check_in(body: CheckInRequest, db: Session = Depends(get_db)):
    """签到 + 自动扣课时"""
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(404, "学员不存在")

    schedule = db.query(ClassSchedule).filter(ClassSchedule.id == body.schedule_id).first()
    if not schedule:
        raise HTTPException(404, "排课不存在")

    # 找到该学员在此课程下的活跃课时包（按到期日最近优先）
    active_credit = (
        db.query(LessonCredit)
        .filter(
            LessonCredit.student_id == body.student_id,
            LessonCredit.course_id == schedule.course_id,
            LessonCredit.status == "active",
            LessonCredit.remaining > 0,
        )
        .order_by(LessonCredit.expiry_date.desc())
        .first()
    )

    if not active_credit:
        raise HTTPException(400, "该学员在此课程下无可用课时，请先购课")

    # 扣课时
    active_credit.consumed += 1
    active_credit.remaining -= 1
    active_credit.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 课时用完则标记
    if active_credit.remaining <= 0:
        active_credit.status = "finished"

    # 写入签到记录
    attendance = Attendance(
        student_id=body.student_id,
        schedule_id=body.schedule_id,
        credit_id=active_credit.id,
        check_method=body.check_method,
        check_coach_id=body.check_coach_id,
        status="present",
        remark=f"签到消课 | 剩余 {active_credit.remaining} 节",
    )
    db.add(attendance)

    # 检查预警
    warning = None
    threshold_str = db.query(SystemConfig).filter(SystemConfig.key == "lesson_warning_threshold").first()
    threshold = int(threshold_str.value) if threshold_str else 10
    if active_credit.remaining <= threshold:
        warning = f"⚠️ 仅剩 {active_credit.remaining} 节课，建议续费"

    db.commit()

    return {
        "code": 0,
        "data": {
            "attendance_id": attendance.id,
            "student_name": student.name,
            "course": _get_course_name(db, schedule.course_id),
            "remaining_after": active_credit.remaining,
            "warning": warning,
        },
    }


@app.get("/api/attendance")
def list_attendance(
    student_id: Optional[int] = Query(None),
    schedule_id: Optional[int] = Query(None),
    days: int = Query(7),
    db: Session = Depends(get_db),
):
    query = db.query(Attendance)
    if student_id:
        query = query.filter(Attendance.student_id == student_id)
    if schedule_id:
        query = query.filter(Attendance.schedule_id == schedule_id)

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = query.filter(Attendance.check_in_time >= cutoff)

    records = query.order_by(Attendance.check_in_time.desc()).limit(100).all()
    return {
        "code": 0,
        "data": [
            {
                "id": a.id,
                "student_name": _get_student_name(db, a.student_id),
                "course": _get_course_name(db, _get_schedule_course(db, a.schedule_id)),
                "check_in_time": a.check_in_time,
                "check_method": a.check_method,
                "status": a.status,
            }
            for a in records
        ],
    }


@app.get("/api/attendance/stats")
def attendance_stats(days: int = Query(7), db: Session = Depends(get_db)):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = db.query(Attendance).filter(Attendance.check_in_time >= cutoff).all()

    total = len(records)
    by_date = {}
    for r in records:
        date_key = r.check_in_time[:10]
        by_date[date_key] = by_date.get(date_key, 0) + 1

    return {
        "code": 0,
        "data": {
            "period_days": days,
            "total_checkins": total,
            "daily_average": round(total / max(days, 1), 1),
            "by_date": by_date,
        },
    }


# ── 课时管理 ────────────────────────────────────────

@app.get("/api/credits")
def list_credits(
    student_id: Optional[int] = Query(None),
    status: str = Query("active"),
    db: Session = Depends(get_db),
):
    query = db.query(LessonCredit)
    if student_id:
        query = query.filter(LessonCredit.student_id == student_id)
    if status:
        query = query.filter(LessonCredit.status == status)

    credits = query.order_by(LessonCredit.expiry_date).all()
    return {
        "code": 0,
        "data": [
            {
                "id": c.id,
                "student_name": _get_student_name(db, c.student_id),
                "course": _get_course_name(db, c.course_id),
                "package_name": c.package_name,
                "total_lessons": c.total_lessons,
                "consumed": c.consumed,
                "remaining": c.remaining,
                "total_price": c.total_price,
                "paid_amount": c.paid_amount,
                "expiry_date": c.expiry_date,
                "status": c.status,
            }
            for c in credits
        ],
    }


@app.get("/api/credits/warning")
def credits_warning(db: Session = Depends(get_db)):
    """课时不足预警（≤10节）"""
    threshold_str = db.query(SystemConfig).filter(SystemConfig.key == "lesson_warning_threshold").first()
    threshold = int(threshold_str.value) if threshold_str else 10

    today = datetime.now().strftime("%Y-%m-%d")
    warnings = (
        db.query(LessonCredit)
        .filter(
            LessonCredit.status == "active",
            LessonCredit.remaining <= threshold,
            LessonCredit.remaining > 0,
        )
        .order_by(LessonCredit.remaining)
        .all()
    )

    # 已到期但仍有课时
    expired = (
        db.query(LessonCredit)
        .filter(
            LessonCredit.status == "active",
            LessonCredit.expiry_date < today,
            LessonCredit.expiry_date != "",
            LessonCredit.remaining > 0,
        )
        .all()
    )

    return {
        "code": 0,
        "data": {
            "low_lesson": [
                {
                    "student": _get_student_name(db, c.student_id),
                    "phone": _mask_phone(_get_student_phone(db, c.student_id)),
                    "course": _get_course_name(db, c.course_id),
                    "remaining": c.remaining,
                    "expiry": c.expiry_date,
                }
                for c in warnings
            ],
            "expired": [
                {
                    "student": _get_student_name(db, c.student_id),
                    "phone": _mask_phone(_get_student_phone(db, c.student_id)),
                    "course": _get_course_name(db, c.course_id),
                    "remaining": c.remaining,
                    "expiry": c.expiry_date,
                }
                for c in expired
            ],
            "low_count": len(warnings),
            "expired_count": len(expired),
        },
    }


@app.post("/api/credits")
def create_credit(body: CreditCreate, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(404, "学员不存在")

    credit = LessonCredit(
        student_id=body.student_id,
        course_id=body.course_id,
        package_name=body.package_name or f"{_get_course_name(db, body.course_id)}课时包",
        total_lessons=body.total_lessons,
        remaining=body.total_lessons,
        unit_price=body.total_price / body.total_lessons if body.total_lessons > 0 else 0,
        total_price=body.total_price,
        paid_amount=body.paid_amount,
        expiry_date=body.expiry_date,
    )
    db.add(credit)
    db.commit()
    db.refresh(credit)
    return {"code": 0, "data": {"id": credit.id, "remaining": credit.remaining}}


# ── 财务管理 ────────────────────────────────────────

@app.post("/api/payments")
def create_payment(body: PaymentCreate, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(404, "学员不存在")

    # 退费金额为负
    amount = body.amount if body.type == "charge" else -abs(body.amount)

    payment = Payment(
        student_id=body.student_id,
        credit_id=body.credit_id,
        type=body.type,
        amount=amount,
        method=body.method,
        transaction_id=body.transaction_id,
        remark=body.remark,
        operator=body.operator,
    )
    db.add(payment)

    # 如果关联了课时包，更新 paid_amount
    if body.credit_id and body.type == "charge":
        credit = db.query(LessonCredit).filter(LessonCredit.id == body.credit_id).first()
        if credit:
            credit.paid_amount += amount
            credit.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db.commit()
    db.refresh(payment)
    return {"code": 0, "data": {"id": payment.id, "amount": amount}}


@app.get("/api/payments/dashboard")
def payments_dashboard(
    period: str = Query("month"),
    date: str = Query(""),
    db: Session = Depends(get_db),
):
    """💰 财务看板"""
    if not date:
        date = datetime.now().strftime("%Y-%m")

    if period == "month":
        start_date = f"{date}-01"
        if date == datetime.now().strftime("%Y-%m"):
            end_date = datetime.now().strftime("%Y-%m-%d")
        else:
            year, month = date.split("-")
            if month == "12":
                end_date = f"{int(year)+1}-01-01"
            else:
                end_date = f"{year}-{int(month)+1:02d}-01"
    else:
        start_date = date
        end_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")

    payments = (
        db.query(Payment)
        .filter(Payment.paid_at >= start_date, Payment.paid_at < end_date, Payment.status == "completed")
        .all()
    )

    total_charge = sum(p.amount for p in payments if p.type == "charge")
    total_refund = sum(abs(p.amount) for p in payments if p.type == "refund")
    net_income = total_charge - total_refund

    new_students = (
        db.query(Student)
        .filter(Student.created_at >= start_date, Student.created_at < end_date)
        .count()
    )

    return {
        "code": 0,
        "data": {
            "period": f"{start_date} ~ {end_date}",
            "summary": {
                "total_charge": round(total_charge, 2),
                "total_refund": round(total_refund, 2),
                "net_income": round(net_income, 2),
                "new_students": new_students,
                "transaction_count": len(payments),
            },
        },
    }


@app.get("/api/payments/stats")
def payments_stats(
    period: str = Query("month"),
    date: str = Query(""),
    db: Session = Depends(get_db),
):
    """财务统计详细"""
    if not date:
        date = datetime.now().strftime("%Y-%m")

    if period == "month":
        year, month = date.split("-")
        start_date = f"{date}-01"
        if int(month) == 12:
            end_month, end_year = 1, int(year) + 1
        else:
            end_month, end_year = int(month) + 1, int(year)
        end_date = f"{end_year}-{end_month:02d}-01"
    else:
        start_date = date
        end_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    payments = (
        db.query(Payment)
        .filter(Payment.paid_at >= start_date, Payment.paid_at < end_date, Payment.status == "completed")
        .all()
    )

    daily = {}
    for p in payments:
        day = p.paid_at[:10]
        if day not in daily:
            daily[day] = {"charge": 0, "refund": 0}
        if p.type == "charge":
            daily[day]["charge"] += p.amount
        else:
            daily[day]["refund"] += abs(p.amount)

    return {
        "code": 0,
        "data": {
            "period": f"{start_date} ~ {end_date}",
            "daily_breakdown": [
                {"date": d, "charge": round(v["charge"], 2), "refund": round(v["refund"], 2),
                 "net": round(v["charge"] - v["refund"], 2)}
                for d, v in sorted(daily.items())
            ],
        },
    }


# ── 通知中心 ────────────────────────────────────────

@app.post("/api/notify/send")
def send_notification(body: NotifyRequest):
    """发送通知（企业微信 Webhook）"""
    # 此功能在 wecom_pusher.py 中已完整实现
    # 此处为接口桩，实际集成时调用 wecom_pusher 模块
    return {
        "code": 0,
        "data": {
            "channel": body.channel,
            "target": body.target[:30] + "..." if len(body.target) > 30 else body.target,
            "status": "queued",
            "message": f"通知已加入发送队列 ({body.channel})",
        },
    }


# ── 数据导入 ────────────────────────────────────────

@app.post("/api/import/xiaomai")
def api_import_xiaomai(file_path: str = Query(""), db: Session = Depends(get_db)):
    """从小麦助教 JSON 导入数据"""
    if not file_path:
        # 自动查找最新数据文件
        data_dir = Path.home() / ".hermes" / "data" / "xiaomai"
        files = sorted(data_dir.glob("data_*.json"), reverse=True)
        if not files:
            raise HTTPException(404, "未找到数据文件，请指定 file_path")
        file_path = str(files[0])

    try:
        import_xiaomai_data(file_path)
        return {"code": 0, "message": f"导入完成: {file_path}"}
    except Exception as e:
        raise HTTPException(500, f"导入失败: {e}")


# ── 数据导出 ────────────────────────────────────────

@app.get("/api/export/students")
def export_students(db: Session = Depends(get_db)):
    """导出学员数据 CSV"""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["姓名", "手机号", "家长姓名", "课程", "剩余课时", "到期日", "状态"])

    students = db.query(Student).filter(Student.status != "deleted").all()
    for s in students:
        credits = [c for c in s.credits if c.status == "active"]
        for c in credits:
            writer.writerow([
                s.name, s.phone, s.parent_name,
                _get_course_name(db, c.course_id),
                c.remaining, c.expiry_date, c.status,
            ])

    from fastapi.responses import StreamingResponse
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=students_{datetime.now().strftime('%Y%m%d')}.csv"},
    )


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════

def _mask_phone(phone: str) -> str:
    if phone and len(phone) >= 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone or ""


def _get_student_name(db: Session, student_id: int) -> str:
    student = db.query(Student).filter(Student.id == student_id).first()
    return student.name if student else f"学员#{student_id}"


def _get_student_phone(db: Session, student_id: int) -> str:
    student = db.query(Student).filter(Student.id == student_id).first()
    return student.phone if student else ""


def _get_course_name(db: Session, course_id: int) -> str:
    course = db.query(Course).filter(Course.id == course_id).first()
    return course.name if course else f"课程#{course_id}"


def _get_coach_name(db: Session, coach_id: int) -> str:
    coach = db.query(Coach).filter(Coach.id == coach_id).first()
    return coach.name if coach else f"教练#{coach_id}"


def _get_schedule_course(db: Session, schedule_id: int) -> int:
    schedule = db.query(ClassSchedule).filter(ClassSchedule.id == schedule_id).first()
    return schedule.course_id if schedule else 0


# ══════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="亚体教务系统 v1.0")
    parser.add_argument("--init", action="store_true", help="初始化数据库")
    parser.add_argument("--import-xiaomai", type=str, metavar="JSON", help="导入小麦助教数据")
    parser.add_argument("--dry-run", action="store_true", help="导入前试运行")
    parser.add_argument("--serve", action="store_true", help="启动 API 服务")
    parser.add_argument("--host", default="0.0.0.0", help="服务地址")
    parser.add_argument("--port", type=int, default=8000, help="服务端口")
    args = parser.parse_args()

    if args.init:
        init_database()
    elif args.import_xiaomai:
        import_xiaomai_data(args.import_xiaomai, dry_run=args.dry_run)
    elif args.serve:
        import uvicorn
        print(f"🚀 亚体教务系统 v1.0")
        print(f"   API 文档: http://{args.host}:{args.port}/docs")
        print(f"   数据库: {DB_PATH}")
        uvicorn.run("yati_edu_core:app", host=args.host, port=args.port, reload=True)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
