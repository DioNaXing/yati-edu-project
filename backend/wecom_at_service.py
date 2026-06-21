#!/usr/bin/env python3
"""
企业微信 AT 团队接入服务 v1.0
================================
接收企微消息 → 路由到 AT 团队 Agent → 回复

架构:
  用户(企微) → POST /api/wecom/callback → 解密XML → Agent路由 → 回复

部署:
  添加到 yati-edu-project/backend/
  作为 FastAPI 子路由挂载到主服务

依赖:
  pip3 install pycryptodome
"""

import json
import hashlib
import time
import struct
import socket
import base64
import logging
from typing import Optional, Dict, Any
from Crypto.Cipher import AES
from xml.etree import ElementTree as ET

log = logging.getLogger("wecom")

# ============================================================
# 企微消息加解密 (WeCom XML → JSON → XML)
# ============================================================

class WXBizMsgCrypt:
    """企业微信消息加解密"""
    
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        
    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """URL验证（配置回调URL时企微会调用）"""
        sort_list = sorted([self.token, timestamp, nonce, echostr])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        if sha1 != msg_signature:
            raise ValueError("签名验证失败")
        return self._decrypt(echostr)
    
    def decrypt_msg(self, xml_body: str, msg_signature: str, timestamp: str, nonce: str) -> ET.Element:
        """解密消息XML"""
        root = ET.fromstring(xml_body)
        encrypt = root.find("Encrypt").text
        # 验证签名
        sort_list = sorted([self.token, timestamp, nonce, encrypt])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        if sha1 != msg_signature:
            raise ValueError("消息签名验证失败")
        # 解密
        plain = self._decrypt(encrypt)
        return ET.fromstring(plain)
    
    def encrypt_msg(self, reply_xml: str, nonce: str, timestamp: str = None) -> str:
        """加密回复"""
        if timestamp is None:
            timestamp = str(int(time.time()))
        encrypted = self._encrypt(reply_xml)
        signature = hashlib.sha1(
            "".join(sorted([self.token, timestamp, nonce, encrypted])).encode()
        ).hexdigest()
        return f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
    
    def _decrypt(self, text: str) -> str:
        raw = base64.b64decode(text)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        plain = cipher.decrypt(raw)
        # 去掉 PKCS7 padding
        pad = plain[-1]
        content = plain[16:-pad]
        # 解析: random(16) + msg_len(4) + msg + corp_id
        msg_len = socket.ntohl(struct.unpack("I", content[:4])[0])
        result = content[4:4+msg_len].decode("utf-8")
        # 去掉尾部 corp_id
        if result.endswith(self.corp_id):
            result = result[:-len(self.corp_id)]
        return result
    
    def _encrypt(self, text: str) -> str:
        random_bytes = base64.b64decode("abcdefghijklmnopqrstuvwxyz")[:16]  # not truly random
        msg_bytes = text.encode("utf-8")
        corp_bytes = self.corp_id.encode("utf-8")
        
        # random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.pack("!I", len(msg_bytes))
        raw = random_bytes + msg_len + msg_bytes + corp_bytes
        
        # PKCS7 padding
        block_size = 32
        pad = block_size - len(raw) % block_size
        raw += bytes([pad] * pad)
        
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = cipher.encrypt(raw)
        return base64.b64encode(encrypted).decode()


# ============================================================
# AT 团队路由引擎
# ============================================================

AT_AGENTS = {
    "edu_butler": {
        "name": "AI教务管家",
        "desc": "续费预警/消课异常/排课推荐/教练负载/日报",
        "model": "deepseek-v4-pro",
        "system_prompt": """你是亚体少儿运动馆的AI教务管家(called "小亚")。
职责: 课时查询、续费提醒、排课咨询、学员档案、未消课预警。
回复风格: 温暖亲切，用表情符号，一次性给全信息。
当前数据连接: SQLite(468学员,17课时包,46缴费)"""
    },
    "store_manager": {
        "name": "AI店长",
        "desc": "教练绩效/收入预测/周报/盈亏预估/趋势分析",
        "model": "gpt-5.5",
        "system_prompt": """你是亚体少儿运动馆的AI店长(called "亚店长")。
职责: 财务分析、教练绩效、收入预测、周报月报、经营决策建议。
回复风格: 专业数据驱动，附带关键指标，给出可执行建议。"""
    },
    "director": {
        "name": "GPT-5.5总监",
        "desc": "战略决策/架构评审/复盘/变现评估",
        "model": "gpt-5.5",
        "system_prompt": """你是亚体教务系统总监。负责架构决策、系统复盘、变现评估、战略对齐。
目标: 3年800万 → 体育幼儿园。回复: 简洁直接，带优先级标注。"""
    },
    "coding_worker": {
        "name": "Coding Worker",
        "desc": "代码生成/调试/架构设计",
        "model": "gpt-5.5",
        "system_prompt": """你是亚体教务系统的Coding Worker。负责代码生成、调试、架构设计。
技术栈: Python/FastAPI/SQLite/React/微信小程序。回复: 带代码示例。"""
    },
}

def route_message(user_text: str, user_id: str) -> Dict[str, Any]:
    """根据消息内容路由到对应的 AT Agent"""
    text_lower = user_text.lower()
    
    # 关键词匹配
    routes = [
        (["续费", "课时", "预警", "排课", "消课", "学员", "查询", "档案", "还剩", "到期",
          "上课", "请假", "试课", "班级", "教练"], "edu_butler"),
        (["财务", "收入", "利润", "周报", "月报", "绩效", "报表", "成本", "盈亏",
          "薪资", "工资", "支出", "毛利", "预算"], "store_manager"),
        (["架构", "复盘", "战略", "规划", "目标", "变现", "评估", "路线图",
          "800万", "幼儿园", "体育"], "director"),
        (["代码", "bug", "报错", "修复", "部署", "docker", "API", "数据库",
          "功能", "开发", "写一个", "帮我做"], "coding_worker"),
    ]
    
    for keywords, agent_id in routes:
        if any(kw in text_lower for kw in keywords):
            return {"agent_id": agent_id, "agent": AT_AGENTS[agent_id]}
    
    # 默认 → AI教务管家
    return {"agent_id": "edu_butler", "agent": AT_AGENTS["edu_butler"]}

# ============================================================
# FastAPI 端点
# ============================================================

# 这个文件被 yati_edu_core.py import
# 注册路由: app.include_router(wecom_router, prefix="/api/wecom")

from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, Response

wecom_router = APIRouter(tags=["企业微信"])

# 配置（从环境变量读取）
import os
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_APP_SECRET = os.getenv("WECOM_APP_SECRET", "")

# One API token
ONE_API_TOKEN = os.getenv("ONE_API_TOKEN", "5zrc9Aiu23OA76of63Ea44726c044B9fB342C9cE3Cc42a0")

_wecom_crypt = None

def get_crypt():
    global _wecom_crypt
    if _wecom_crypt is None:
        if not all([WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID]):
            raise RuntimeError("企微配置未设置: WECOM_TOKEN/WECOM_ENCODING_AES_KEY/WECOM_CORP_ID")
        _wecom_crypt = WXBizMsgCrypt(WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID)
    return _wecom_crypt


@wecom_router.get("/callback")
async def wecom_verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """企微回调URL验证（GET请求，配置回调时触发）"""
    try:
        crypt = get_crypt()
        decrypted = crypt.verify_url(msg_signature, timestamp, nonce, echostr)
        return PlainTextResponse(decrypted)
    except Exception as e:
        log.error(f"URL验证失败: {e}")
        return PlainTextResponse("error", status_code=403)


@wecom_router.post("/callback")
async def wecom_receive_message(request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """接收企微消息 → 路由AT Agent → 回复"""
    try:
        body = await request.body()
        crypt = get_crypt()
        
        # 解密消息
        xml_root = crypt.decrypt_msg(body.decode(), msg_signature, timestamp, nonce)
        
        msg_type = xml_root.find("MsgType").text
        from_user = xml_root.find("FromUserName").text
        to_user = xml_root.find("ToUserName").text
        content = xml_root.find("Content").text if msg_type == "text" else ""
        
        log.info(f"企微消息: from={from_user} type={msg_type} content={content[:100]}")
        
        # 路由到 AT Agent
        result = route_message(content, from_user)
        agent = result["agent"]
        
        # 调用 One API 获取回复
        reply_text = await call_agent(
            agent_id=result["agent_id"],
            system_prompt=agent["system_prompt"],
            user_message=content,
            model=agent["model"],
        )
        
        # 构造回复 XML
        reply_xml = f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{reply_text}]]></Content>
</xml>"""
        
        # 加密回复
        encrypted = crypt.encrypt_msg(reply_xml, nonce, timestamp)
        return Response(content=encrypted, media_type="application/xml")
        
    except Exception as e:
        log.error(f"消息处理失败: {e}", exc_info=True)
        return PlainTextResponse("success")  # 企微要求返回success，否则会重试


async def call_agent(agent_id: str, system_prompt: str, user_message: str, model: str) -> str:
    """通过 One API 调用 AI Agent"""
    import httpx
    
    ONE_API_BASE = os.getenv("ONE_API_BASE_URL", "http://localhost:3001/v1")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{ONE_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {ONE_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "max_tokens": 800,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            else:
                log.error(f"Agent调用失败: {data}")
                return f"[{agent_id}] 暂时无法回复，请稍后再试"
        except Exception as e:
            log.error(f"Agent网络错误: {e}")
            return f"[{agent_id}] 网络异常，请稍后再试"


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    # 测试路由
    tests = [
        "我还有多少课时",
        "这个月收入多少",
        "系统架构复盘",
        "帮我写一个排课接口",
        "你好",
    ]
    for t in tests:
        r = route_message(t, "test_user")
        print(f"  {t[:30]:30s} → {r['agent']['name']}")
    
    # 快速启动测试
    import uvicorn
    uvicorn.run("wecom_at_service:wecom_router", host="0.0.0.0", port=8001, reload=True)
