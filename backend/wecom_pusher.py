#!/usr/bin/env python3
"""
企业微信 Webhook 推送引擎 v1.0
=================================
读取 AI 教务管家数据 → 构建 Markdown 消息 → 通过群机器人 Webhook 推送到企业微信群。

完全不依赖企业管理员审批——任何人只要有群机器人 Webhook URL 即可使用。

用法:
    # 实际推送
    python3 wecom_pusher.py

    # 测试（只打印消息，不发送）
    python3 wecom_pusher.py --dry-run

    # 指定数据文件
    python3 wecom_pusher.py --data ~/.hermes/data/xiaomai/data_20260620.json

    # 使用 AI 生成更智能的推送文案
    python3 wecom_pusher.py --ai-summary

    # 发送到指定 Webhook URL（覆盖配置文件）
    python3 wecom_pusher.py --webhook https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

环境变量:
    DEEPSEEK_API_KEY  用于 AI 总结生成（--ai-summary 时必需）
"""

import json
import os
import re
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# ── 路径配置 ──────────────────────────────────────────────
HOME = Path.home()
SCRIPT_DIR = HOME / ".hermes" / "scripts"
CONFIG_FILE = SCRIPT_DIR / "wecom_config.json"
DATA_DIR = HOME / ".hermes" / "data" / "xiaomai"
OBSIDIAN_INBOX = HOME / "Documents" / "Obsidian Vault" / "00-Inbox"
LOG_DIR = HOME / ".hermes" / "logs" / "wecom"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# WeCom Markdown 消息限制（企业微信群机器人）
WECOM_MD_MAX_LENGTH = 4096


# ── 配置加载 ──────────────────────────────────────────────

def load_config() -> dict:
    """加载配置文件，不存在则返回默认配置"""
    defaults = {
        "webhook_urls": [],
        "schedule": {
            "cron_expression": "30 9 * * *",
            "description": "每天早上 9:30（AI 教务日报 9:00 之后）"
        },
        "templates": {
            "class_warning": {
                "title": "🔴 课时不足预警",
                "threshold": 10,
                "emoji": "🔴",
                "template": "**{phone_masked}** | {course} | {class_name} | **{remaining}节** | 到期 {expiry}"
            },
            "expiry_warning": {
                "title": "🟡 已到期未消课",
                "emoji": "🟡",
                "template": "**{phone_masked}** | {remaining}节剩余 | 到期 {expiry}"
            },
            "no_class_warning": {
                "title": "⚠️ 未选班学员",
                "emoji": "⚠️",
                "template": "**{phone_masked}** | {course} | {remaining}节剩余"
            }
        },
        "message_header": "## 🧠 AI教务提醒",
        "message_footer": "> 由 AI教务管家 自动推送 | 下次推送：明天 9:30",
        "max_items_per_section": 10,
        "send_timeout": 10,
        "retry_count": 2,
        "retry_delay": 3,
    }

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                user_config = json.load(f)
            # 深度合并（简单实现）
            for key, value in user_config.items():
                if key in defaults and isinstance(defaults[key], dict) and isinstance(value, dict):
                    defaults[key].update(value)
                else:
                    defaults[key] = value
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 配置文件读取失败，使用默认配置: {e}", file=sys.stderr)

    return defaults


# ── 数据加载 ──────────────────────────────────────────────

def find_latest_data() -> Optional[Path]:
    """找到最新的 xiaomai 数据 JSON 文件"""
    if not DATA_DIR.exists():
        return None
    files = sorted(DATA_DIR.glob("data_*.json"), reverse=True)
    return files[0] if files else None


def load_student_data(data_path: Optional[str] = None) -> dict:
    """加载学员数据，优先 JSON，fallback 到 Obsidian 日报解析"""
    # 1. 尝试 JSON 数据文件
    json_path = Path(data_path) if data_path else find_latest_data()
    if json_path and json_path.exists():
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            print(f"📂 已加载数据: {json_path.name} ({len(data.get('students', []))} 名学员)", file=sys.stderr)
            return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ JSON 数据读取失败: {e}", file=sys.stderr)

    # 2. Fallback: 解析 Obsidian 日报
    print("📂 回退到 Obsidian 日报解析...", file=sys.stderr)
    return parse_obsidian_report()


def parse_obsidian_report() -> dict:
    """从 Obsidian 日报 Markdown 解析学员数据"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = OBSIDIAN_INBOX / f"🧠 AI教务日报 {today}.md"

    if not report_path.exists():
        print(f"⚠️ 日报不存在: {report_path}", file=sys.stderr)
        return {"students": [], "finance": {}}

    with open(report_path, "r") as f:
        content = f.read()

    students = []
    # 解析课时预警表格
    in_warning = False
    for line in content.split("\n"):
        if "课时不足预警" in line:
            in_warning = True
            continue
        if in_warning and line.startswith("| ") and "节" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 5:
                phone = parts[0].replace("****", "0000").replace("*", "")
                course = parts[1]
                class_name = parts[2]
                remaining_match = re.search(r"(\d+)节", parts[3])
                remaining = int(remaining_match.group(1)) if remaining_match else 0
                expiry = parts[5] if len(parts) > 5 else ""
                students.append({
                    "phone": phone,
                    "course": course,
                    "class": class_name,
                    "remaining": remaining,
                    "expiry": expiry,
                    "paid": 0,
                    "total_value": 0,
                    "total_lessons": 0,
                })
        if in_warning and line.startswith("---"):
            in_warning = False

    print(f"📂 从日报解析出 {len(students)} 名预警学员", file=sys.stderr)
    return {"students": students, "finance": {}}


# ── 消息构建 ──────────────────────────────────────────────

def mask_phone(phone: str) -> str:
    """脱敏手机号: 138****1234"""
    if len(phone) >= 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


def build_warning_section(students: list, config: dict) -> str:
    """构建课时不足预警段落"""
    tmpl = config["templates"]["class_warning"]
    threshold = tmpl.get("threshold", 10)
    max_items = config.get("max_items_per_section", 10)

    # 筛选并去重（同一手机号只取课时最少的）
    low_students = [s for s in students if 0 < s.get("remaining", 999) <= threshold]
    seen_phones = {}
    for s in low_students:
        phone = s.get("phone", "")
        if phone not in seen_phones or s["remaining"] < seen_phones[phone]["remaining"]:
            seen_phones[phone] = s
    low_students = sorted(seen_phones.values(), key=lambda x: x.get("remaining", 999))[:max_items]

    if not low_students:
        return ""

    lines = [f"## {tmpl['title']}", ""]
    for s in low_students:
        try:
            line = tmpl["template"].format(
                phone_masked=mask_phone(s.get("phone", "")),
                course=s.get("course", ""),
                class_name=s.get("class", "")[:15],
                remaining=s.get("remaining", 0),
                expiry=s.get("expiry", "无"),
            )
        except KeyError:
            line = f"**{mask_phone(s.get('phone', ''))}** | {s.get('course', '')} | {s.get('remaining', 0)}节"
        lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def build_expiry_section(students: list, today_str: str, config: dict) -> str:
    """构建到期未消课段落"""
    tmpl = config["templates"]["expiry_warning"]
    max_items = config.get("max_items_per_section", 10)

    expired = [
        s for s in students
        if s.get("expiry") and s["expiry"] < today_str and s.get("remaining", 0) > 0
    ]
    # 去重
    seen_phones = {}
    for s in expired:
        phone = s.get("phone", "")
        if phone not in seen_phones:
            seen_phones[phone] = s
    expired = list(seen_phones.values())[:max_items]

    if not expired:
        return ""

    lines = [f"## {tmpl['title']}", ""]
    for s in expired:
        try:
            line = tmpl["template"].format(
                phone_masked=mask_phone(s.get("phone", "")),
                remaining=s.get("remaining", 0),
                expiry=s.get("expiry", "无"),
            )
        except KeyError:
            line = f"**{mask_phone(s.get('phone', ''))}** | {s.get('remaining', 0)}节剩余 | 到期 {s.get('expiry', '')}"
        lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def build_no_class_section(students: list, config: dict) -> str:
    """构建未选班学员段落"""
    tmpl = config["templates"]["no_class_warning"]
    max_items = config.get("max_items_per_section", 10)

    no_class = [
        s for s in students
        if "未选班" in s.get("class", "") and s.get("remaining", 0) > 0
    ]
    seen_phones = {}
    for s in no_class:
        phone = s.get("phone", "")
        if phone not in seen_phones:
            seen_phones[phone] = s
    no_class = list(seen_phones.values())[:max_items]

    if not no_class:
        return ""

    lines = [f"## {tmpl['title']}", ""]
    for s in no_class:
        try:
            line = tmpl["template"].format(
                phone_masked=mask_phone(s.get("phone", "")),
                course=s.get("course", ""),
                remaining=s.get("remaining", 0),
            )
        except KeyError:
            line = f"**{mask_phone(s.get('phone', ''))}** | {s.get('course', '')} | {s.get('remaining', 0)}节"
        lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def build_ai_summary(students: list, today_str: str) -> str:
    """使用 DeepSeek API 生成智能推送文案"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return "> 💡 设置 DEEPSEEK_API_KEY 环境变量可启用 AI 智能文案"

    # 汇总数据
    low_lesson = [s for s in students if 0 < s.get("remaining", 999) <= 10]
    expired = [s for s in students if s.get("expiry") and s["expiry"] < today_str and s.get("remaining", 0) > 0]
    no_class = [s for s in students if "未选班" in s.get("class", "") and s.get("remaining", 0) > 0]

    context = f"""日期: {today_str}
课时不足(≤10节): {len(low_lesson)}人
已到期未消课: {len(expired)}人
未选班: {len(no_class)}人
总学员: {len(students)}人"""

    prompt = f"""你是体培机构的AI教务助手。请根据以下数据，生成一段简短有力的企业微信推送文案（Markdown格式）。

数据概要:
{context}

要求:
1. 用简洁的语气，不要太AI腔
2. 给出明确的行动建议（联系家长续费/安排试课等）
3. 突出紧迫感但不能制造焦虑
4. 控制在150字以内
5. 使用适当的emoji增强可读性

直接输出Markdown文案，不要任何开头结尾说明。"""

    try:
        req = Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 300,
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"].strip()
        return f"> 🤖 AI建议：{text}"
    except Exception as e:
        return f"> ⚠️ AI总结生成失败: {e}"


def build_message(students: list, config: dict, today_str: str, use_ai: bool = False) -> str:
    """构建完整的 Markdown 推送消息"""
    parts = [config.get("message_header", "## 🧠 AI教务提醒"), ""]

    # 统计摘要
    low_count = len([s for s in students if 0 < s.get("remaining", 999) <= 10])
    expired = [s for s in students if s.get("expiry") and s["expiry"] < today_str and s.get("remaining", 0) > 0]
    no_class = [s for s in students if "未选班" in s.get("class", "") and s.get("remaining", 0) > 0]

    summary = f"📊 今日概况: 课时预警 **{low_count}** 人 | 已到期 **{len(expired)}** 人 | 未选班 **{len(no_class)}** 人"
    parts.append(summary)
    parts.append("")

    # 各预警段落
    warning = build_warning_section(students, config)
    if warning:
        parts.append(warning)

    expiry = build_expiry_section(students, today_str, config)
    if expiry:
        parts.append(expiry)

    no_class_section = build_no_class_section(students, config)
    if no_class_section:
        parts.append(no_class_section)

    # AI 总结
    if use_ai:
        ai_text = build_ai_summary(students, today_str)
        parts.append(ai_text)
    else:
        # 简单自动建议
        suggestions = []
        if low_count > 0:
            suggestions.append(f"1. **续费跟进** 🔴：{low_count} 人课时不足，建议今天联系家长")
        if expired:
            suggestions.append(f"2. **到期处理** 🟡：{len(expired)} 人已到期，建议发送续费优惠")
        if no_class:
            suggestions.append(f"3. **排班安排**：{len(no_class)} 人未选班，尽快安排试课分班")
        if suggestions:
            parts.append("---")
            parts.append("")
            parts.extend(suggestions)
            parts.append("")

    parts.append("")
    parts.append(config.get("message_footer", "> 由 AI教务管家 自动推送"))

    message = "\n".join(parts)

    # 截断超长消息
    if len(message) > WECOM_MD_MAX_LENGTH:
        cutoff = WECOM_MD_MAX_LENGTH - 100
        message = message[:cutoff] + "\n\n> ⚠️ 消息过长已截断，完整信息请查看 Obsidian 日报"

    return message


# ── Webhook 发送 ──────────────────────────────────────────

def send_webhook(webhook_url: str, message: str, timeout: int = 10) -> bool:
    """发送 Markdown 消息到企业微信群机器人"""
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {
            "content": message,
        },
    }, ensure_ascii=False).encode("utf-8")

    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        if result.get("errcode") == 0:
            return True
        else:
            print(f"  ❌ Webhook 返回错误: {result}", file=sys.stderr)
            return False
    except HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        print(f"  ❌ HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except URLError as e:
        print(f"  ❌ 网络错误: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ❌ 发送异常: {e}", file=sys.stderr)
        return False


def push_to_all(message: str, webhook_urls: list, config: dict) -> dict:
    """推送到所有 Webhook URL"""
    results = {"success": [], "failed": []}
    timeout = config.get("send_timeout", 10)
    retry_count = config.get("retry_count", 2)
    retry_delay = config.get("retry_delay", 3)

    for i, url in enumerate(webhook_urls):
        # 脱敏显示
        masked_url = re.sub(r"key=[a-zA-Z0-9\-]+", "key=***", url)
        print(f"📤 [{i+1}/{len(webhook_urls)}] 发送到: {masked_url}", file=sys.stderr)

        success = False
        for attempt in range(1 + retry_count):
            if attempt > 0:
                print(f"  🔄 重试 {attempt}/{retry_count}...", file=sys.stderr)
                time.sleep(retry_delay)
            if send_webhook(url, message, timeout):
                success = True
                break

        if success:
            results["success"].append(masked_url)
            print(f"  ✅ 发送成功", file=sys.stderr)
        else:
            results["failed"].append(masked_url)
            print(f"  ❌ 发送失败（已重试{retry_count}次）", file=sys.stderr)

    return results


# ── 日志 ──────────────────────────────────────────────────

def write_log(message: str, results: dict):
    """记录推送日志"""
    log_file = LOG_DIR / f"push_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "message_preview": message[:200],
        "message_length": len(message),
        "results": results,
    }
    with open(log_file, "w") as f:
        json.dump(log_entry, f, ensure_ascii=False, indent=2)
    print(f"📝 日志已保存: {log_file}", file=sys.stderr)


# ── 主流程 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="企业微信 Webhook 推送引擎 - AI 教务管家数据推送",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                     # 正常推送
  %(prog)s --dry-run           # 测试：只打印，不发送
  %(prog)s --ai-summary        # 使用 DeepSeek 生成 AI 总结
  %(prog)s --webhook URL       # 覆盖配置，发送到指定 Webhook
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="测试模式：打印消息但不发送")
    parser.add_argument("--ai-summary", action="store_true", help="使用 DeepSeek API 生成 AI 总结文案")
    parser.add_argument("--data", type=str, help="指定数据 JSON 文件路径")
    parser.add_argument("--webhook", type=str, action="append", help="指定 Webhook URL（可多次使用）")
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="配置文件路径")
    args = parser.parse_args()

    # 加载配置
    config = load_config()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Webhook URLs
    webhook_urls = args.webhook if args.webhook else config.get("webhook_urls", [])
    if not webhook_urls and not args.dry_run:
        print("❌ 错误：未配置 Webhook URL。请在配置文件中设置或在命令行指定 --webhook", file=sys.stderr)
        sys.exit(1)

    # 加载数据
    data = load_student_data(args.data)
    students = data.get("students", [])

    if not students:
        print("❌ 没有学员数据，退出", file=sys.stderr)
        sys.exit(1)

    # 构建消息
    print("📝 构建推送消息...", file=sys.stderr)
    message = build_message(students, config, today_str, use_ai=args.ai_summary)

    print(f"📏 消息长度: {len(message)} 字符", file=sys.stderr)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("🧪 DRY RUN - 以下是将要发送的消息：")
        print("=" * 60)
        print(message)
        print("=" * 60)
        print(f"📋 目标 Webhook 数量: {len(webhook_urls)}")
        print("=" * 60)
        return

    # 发送
    print(f"🚀 开始推送到 {len(webhook_urls)} 个群...", file=sys.stderr)
    results = push_to_all(message, webhook_urls, config)

    # 汇总
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"📊 推送完成: ✅ {len(results['success'])}  | ❌ {len(results['failed'])}", file=sys.stderr)
    if results["failed"]:
        print(f"失败列表: {results['failed']}", file=sys.stderr)

    write_log(message, results)


if __name__ == "__main__":
    main()
