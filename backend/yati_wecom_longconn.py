#!/usr/bin/env python3
"""
企业微信智能机器人 — API 长连接客户端
=========================================
文档: https://developer.work.weixin.qq.com/document/path/100178

连接方式: WebSocket 长连接
- 接收: wss://qyapi.weixin.qq.com/cgi-bin/ws/bot
- 发送: POST https://qyapi.weixin.qq.com/cgi-bin/bot/send

错误码 853000 = botid 或 secret 无效
"""

import asyncio
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime

import httpx
import websockets

# ── 配置 ──────────────────────────────────────────────
BOT_ID = os.getenv("WECOM_BOT_ID", "")
BOT_SECRET = os.getenv("WECOM_BOT_SECRET", "")

# 调试模式：打印详细日志
DEBUG = os.getenv("WECOM_DEBUG", "0") == "1"

WS_URL = f"wss://qyapi.weixin.qq.com/cgi-bin/ws/bot?bot_id={BOT_ID}&bot_secret={BOT_SECRET}"
SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/bot/send"

# 重连配置
MAX_RECONNECT_DELAY = 60
INITIAL_RECONNECT_DELAY = 2


def log(level: str, msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def mask(s: str) -> str:
    """脱敏显示"""
    if len(s) <= 8:
        return "***"
    return f"{s[:6]}...{s[-4:]}"


async def send_message(chat_id: str, content: str, msg_id: str = "") -> dict:
    """发送消息到群聊/私聊"""
    payload = {
        "chatid": chat_id,
        "msgtype": "text",
        "text": {"content": content},
    }
    if msg_id:
        payload["msgid"] = msg_id  # 回复时带上原消息 ID

    params = {"bot_id": BOT_ID, "bot_secret": BOT_SECRET}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(SEND_URL, params=params, json=payload)
        data = resp.json()
        if data.get("errcode") != 0:
            log("ERROR", f"发送失败: {data}")
        return data


async def handle_message(msg: dict):
    """处理收到的消息"""
    msg_type = msg.get("msgtype", "")
    chat_id = msg.get("chatid", "")
    msg_id = msg.get("msgid", "")
    from_user = msg.get("from", {}).get("alias", "unknown")

    if msg_type == "text":
        text = msg.get("text", {}).get("content", "")
        log("MSG", f"收到 [{from_user}]: {text[:80]}")

        # ── AT Agent 路由 ────────────────────────
        reply = await route_message(text, from_user)
        if reply:
            await send_message(chat_id, reply, msg_id)

    elif msg_type == "event":
        event_type = msg.get("event", {}).get("event_type", "")
        log("EVENT", f"事件: {event_type}")
    else:
        log("MSG", f"未知类型: {msg_type}")


async def route_message(text: str, from_user: str) -> str:
    """消息路由 — 关键词匹配 Agent 或默认回复"""
    text_lower = text.lower().strip()

    # 教务管家 — 课时/课程/学员
    if any(kw in text_lower for kw in ["课时", "课程", "学员", "上课", "消课", "请假"]):
        return f"📚 [教务管家] 收到，正在处理...\n(from {from_user})"

    # AI 店长 — 销售/转化/活动
    if any(kw in text_lower for kw in ["销售", "转化", "活动", "报名", "体验", "到店"]):
        return f"🏪 [AI店长] 收到，正在分析...\n(from {from_user})"

    # 总监 — 数据/报表/KPI
    if any(kw in text_lower for kw in ["数据", "报表", "kpi", "营收", "分析", "月报"]):
        return f"🎯 [总监] 收到，正在生成报告...\n(from {from_user})"

    # 帮助
    if text_lower in ["帮助", "help", "?"]:
        return (
            "🤖 **亚体 AI 助手**\n"
            "- 教务问题 → 直接问（课时/消课/请假）\n"
            "- 销售数据 → 问营收/转化/活动\n"
            "- 报表 → 问月报/年报/KPI"
        )

    # 默认
    return f"收到：{text[:100]}"


async def connect_ws():
    """WebSocket 长连接主循环（自动重连）"""
    reconnect_delay = INITIAL_RECONNECT_DELAY

    while True:
        try:
            log("INFO", f"正在连接 WebSocket... bot_id={mask(BOT_ID)}")
            log("DEBUG", f"URL: wss://qyapi.weixin.qq.com/cgi-bin/ws/bot?bot_id={mask(BOT_ID)}&bot_secret=***")

            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**20,
            ) as ws:
                log("INFO", "✅ WebSocket 连接成功！")
                reconnect_delay = INITIAL_RECONNECT_DELAY  # 重置重连延迟

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if DEBUG:
                            log("DEBUG", f"原始消息: {json.dumps(msg, ensure_ascii=False)[:200]}")

                        # 优先检查错误
                        if msg.get("errcode") and msg.get("errcode") != 0:
                            log("ERROR", f"服务端错误: {msg}")
                            continue

                        await handle_message(msg)

                    except json.JSONDecodeError:
                        log("WARN", f"无效 JSON: {raw[:100]}")
                    except Exception as e:
                        log("ERROR", f"处理消息异常: {e}")
                        traceback.print_exc()

        except websockets.exceptions.InvalidStatus as e:
            log("FATAL", f"连接被拒绝 (HTTP {e.response.status_code}): {e}")
            # 853000 等不可恢复错误，需要检查 bot_id/secret
            time.sleep(30)

        except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError) as e:
            log("WARN", f"连接断开: {e}")
            log("INFO", f"{reconnect_delay}s 后重连...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

        except asyncio.CancelledError:
            log("INFO", "收到退出信号")
            break

        except Exception as e:
            log("ERROR", f"未预期异常: {e}")
            traceback.print_exc()
            await asyncio.sleep(10)


def main():
    if not BOT_ID or not BOT_SECRET:
        log("FATAL", "❌ 缺少 WECOM_BOT_ID 或 WECOM_BOT_SECRET 环境变量")
        sys.exit(1)

    log("INFO", f"启动企微长连接客户端: bot_id={mask(BOT_ID)}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 优雅退出
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown(loop)))
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(connect_ws())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        log("INFO", "客户端已退出")


async def shutdown(loop):
    log("INFO", "正在优雅退出...")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


if __name__ == "__main__":
    main()
