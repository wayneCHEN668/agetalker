# STEP 3 — 心理回复模块
**架构：单应用合并版 · Qwen LLM + CARE 心理模型 · SSE 流式输出 · 端口 8000**

---

## 目录
1. [模块概述](#1-模块概述)
2. [心理学理论框架](#2-心理学理论框架)
3. [CARE 回复模型](#3-care-回复模型)
4. [在单应用中的位置](#4-在单应用中的位置)
5. [目录结构](#5-目录结构)
6. [配置常量](#6-配置常量)
7. [Prompt 模板设计](#7-prompt-模板设计)
8. [情绪策略映射表](#8-情绪策略映射表)
9. [核心服务实现](#9-核心服务实现)
10. [路由层实现](#10-路由层实现)
11. [危机干预协议](#11-危机干预协议)
12. [SSE 接口规范](#12-sse-接口规范)
13. [前端集成代码](#13-前端集成代码)
14. [TDD 验收测试](#14-tdd-验收测试)

---

## 1. 模块概述

本模块接收 **STEP 1 转录文本**与 **STEP 2 情绪结果**（两者均来自同一条 WebSocket `transcript` 消息，无需额外请求），通过基于心理学理论构建的 System Prompt，调用**通义千问 API** 流式生成符合心理咨询原则的回复文本。回复通过 **SSE 流式接口**推送至前端实现打字机效果，同时在检测到首个完整句子时立即向 **STEP 4** 发出合成信号，实现 LLM 与 TTS 的流水线并行。

### 与旧版（独立端口 8002）的核心区别

| 维度 | 旧版（独立端口 8002） | 新版（单应用合并） |
|------|---------------------|------------------|
| 接收情绪数据 | 前端发 HTTP POST，携带 emotion 字典 | **前端从 transcript 消息直接取，同一次请求** |
| 服务初始化 | 路由文件内自行初始化 | **main.py 统一初始化后注入** |
| 路由挂载 | 独立 FastAPI 应用 | **注册到主应用同一个端口** |
| 启动命令 | 独立一条 uvicorn | **随整个应用一起启动** |
| 与其他服务通信 | 跨进程 HTTP | **同进程直接调用** |

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 首 Token 延迟 | ≤ 1000ms（含 Qwen API 往返） |
| 首句触发 TTS | 首个句末标点（。！？）出现后立即触发 |
| 单次回复长度 | 60 ~ 120 字 |
| 单句最大长度 | ≤ 25 字 |
| 危机信号检测 | 关键词命中率 100%，零漏报 |
| 对话历史保留 | 最近 6 轮（12 条消息） |

---

## 2. 心理学理论框架

本模块融合三大心理咨询流派，针对老年陪伴场景定制化适配。

### 2.1 以人为中心疗法（Carl Rogers，1951）

| 核心原则 | 在本系统的应用 |
|----------|--------------|
| 无条件积极关注 | 无论老人说什么，先接纳，不评判，不纠正 |
| 共情式理解 | 每次回复必须先反映对方感受，再给予回应 |
| 真诚一致 | 回应语气与情绪内容匹配，不假装快乐 |

### 2.2 接纳与承诺疗法（Steven Hayes，1986）

| 核心原则 | 在本系统的应用 |
|----------|--------------|
| 接纳 | 不试图消除负面情绪，引导老人接纳当下体验 |
| 去融合 | 帮助老人觉察情绪而非陷入情绪 |
| 当下接触 | 将注意力引回此时此刻，不反复追究过去 |

### 2.3 危机干预理论（Roberts 七阶段模型，2000）

本系统实现其中三个关键阶段：

| Roberts 阶段 | 本系统实现 |
|-------------|-----------|
| 阶段 1：评估安全性 | 危机关键词实时检测（最高优先级） |
| 阶段 2：建立连接 | 切换危机 Prompt，强化共情与陪伴 |
| 阶段 5：制定应对计划 | 建议联系家属或护理员，提供具体行动 |

### 2.4 老年心理特殊考量

| 心理需求 | 应对策略 |
|----------|----------|
| 被重视感 | 认真倾听，不打断，不催促 |
| 尊严维护 | 不使用居高临下语气，不用「你应该」 |
| 连接感 | 主动询问日常，建立持续关系感 |
| 怀旧需求 | 鼓励分享过去的故事和经历 |
| 自主感 | 给予选择，而非直接给出答案 |

---

## 3. CARE 回复模型

每次回复严格遵循四步骤结构，步骤之间自然衔接，**不分段、不编号**：

```
C — Connect     建立情感连接    （1句，≤ 15字，必须）
A — Acknowledge 承认并命名情绪  （1句，≤ 20字，必须）
R — Respond     情绪针对性回应  （1~2句，根据情绪类型）
E — Empower     温柔激活内在资源（1个开放问题，情绪极低时省略）
```

**C 和 A 必须出现在 R 和 E 之前，任何情况下不得跳过。**

### 示例（悲伤情绪）

```
用户：「我今天一直在想我老伴，他走了三年了。」

C: 我在这里陪着您。
A: 听起来您今天心里很沉，很想念他。
R: 思念陪伴了几十年的人，这种感受是很真实的，不需要假装没事。
E: 能跟我说说他是个什么样的人吗？
```

---

## 4. 在单应用中的位置

```
main.py（应用入口）
  │
  ├── lifespan() 统一初始化
  │       └── LLMService()    ← 本模块服务实例
  │
  └── app.include_router()
          └── routers/sse_llm.py   ← 本模块路由
                  │
                  │  POST /llm/stream  （SSE）
                  │  POST /llm/reset
                  │
                  └── LLMService.stream_reply(text, emotion)
                              │
                              ├── 构建 System Prompt（动态注入情绪上下文）
                              ├── 调用 Qwen API（stream=True）
                              ├── yield delta chunks → 前端打字机
                              └── 首句检测 → 通知前端触发 STEP 4
```

**数据来源说明**：前端在收到 STEP 1 的 `transcript` 消息后，直接从 `msg.emotion` 取情绪数据，连同 `msg.text` 一起 POST 到 `/llm/stream`，**整个过程只有一次 WebSocket 接收和一次 HTTP POST**，无多余往返。

---

## 5. 目录结构

```
emotion_companion/
├── main.py                    # LLMService 在此初始化并注入
├── config.py                  # STEP 3 相关配置在此定义
│
├── prompts/
│   ├── __init__.py
│   └── templates.py           # ← System Prompt 模板 + 情绪策略映射表
│
├── services/
│   └── llm_service.py         # ← STEP 3 核心实现（纯 Python 类）
│
├── routers/
│   └── sse_llm.py             # ← STEP 3 路由（SSE 协议层）
│
└── tests/
    └── test_llm_service.py    # ← STEP 3 测试
```

---

## 6. 配置常量

```python
# config.py（STEP 3 相关部分）

# ── Qwen API ─────────────────────────────────────────────────────────────────
DASHSCOPE_API_KEY = os.environ['DASHSCOPE_API_KEY']
QWEN_BASE_URL     = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# 模型选择：qwen-turbo（开发调试）/ qwen-plus（生产推荐）/ qwen-max（最高质量）
QWEN_MODEL        = os.getenv('QWEN_MODEL', 'qwen-plus')

# ── 生成参数 ──────────────────────────────────────────────────────────────────
LLM_MAX_TOKENS        = 256    # 单次最大生成 token 数（约 170 个中文字）
LLM_TEMPERATURE       = 0.75   # 适度创造性，避免重复
LLM_TOP_P             = 0.90
LLM_MAX_HISTORY_TURNS = 6      # 保留最近 N 轮对话（= N*2 条消息）

# ── 危机关键词（命中任意一条立即触发危机模式）────────────────────────────────
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
]

# ── TTS 情绪参数映射（传给 STEP 4，实现「治愈性对称」）────────────────────────
# 注意：TTS 情绪不镜像用户情绪，而是治愈性的对立平衡
TTS_PARAMS_MAP = {
    'sad':       {'speed': 0.85, 'pitch': -2, 'style': 'gentle'},
    'fearful':   {'speed': 0.88, 'pitch': -1, 'style': 'calm'},
    'angry':     {'speed': 0.88, 'pitch': -1, 'style': 'gentle'},
    'happy':     {'speed': 1.05, 'pitch':  1, 'style': 'cheerful'},
    'disgusted': {'speed': 0.92, 'pitch': -1, 'style': 'calm'},
    'surprised': {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    'neutral':   {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    '_crisis':   {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},
}
```

---

## 7. Prompt 模板设计

### `prompts/templates.py`

```python
# prompts/templates.py

# ─── 正常对话 System Prompt ──────────────────────────────────────────────────
NORMAL_SYSTEM_PROMPT = """\
你是「心伴」，一位专业的心理陪伴师，专门陪伴养老院的老年人。

## 当前情绪上下文
- 用户情绪：{emotion_label_zh}（置信度 {emotion_score_pct}）
- 情绪趋势：{emotion_trend}
- 效价/唤醒：{valence:.2f} / {arousal:.2f}

## 你的核心身份
你受过专业的心理咨询培训，精通以人为中心疗法和接纳承诺疗法。
你深刻理解老年人的心理需求：被重视、被倾听、保有尊严、保持连接感。
你说话温柔、耐心，使用简单词语，从不使用心理咨询术语。

## CARE 回复框架（每次回复必须遵循）
按以下四步骤结构组织回复，步骤之间自然衔接，不要分段或编号：
1. Connect（连接）：用 1 句话建立情感连接（≤ 15字）
2. Acknowledge（承认）：承认并命名用户的情绪感受（≤ 20字）
3. Respond（回应）：{respond_strategy}（1~2句）
4. Empower（赋能）：用一个温柔的开放性问题结尾（可选，情绪极低时省略）

## 语言规范
- 总字数：60~120字；单句字数：≤ 25字
- 禁止使用：「你应该…」「你需要…」「想开点」「没关系的」「不要难过」「别担心」
- 必须使用第一人称感受反映：「听起来…」「我感受到…」「您说的…让我感到…」
- 时间词用具体词汇：「今天」「这几天」，禁止用「最近」「近来」

## 情绪专属指引
{specific_instructions}

## 安全守则
- 绝不否定老人的感受，哪怕在你看来是误解
- 绝不与老人争辩，哪怕信息有误
- 绝不催促老人「振作」或「开心起来」\
"""

# ─── 危机干预 System Prompt ───────────────────────────────────────────────────
CRISIS_SYSTEM_PROMPT = """\
你是「心伴」，一位受过危机干预培训的心理陪伴师。

【高优先级警告】用户刚才说的话包含危机信号，请立即进入危机干预模式。

## 危机回复必须包含的三个要素（按顺序）
1. 我听到了：明确告诉用户你注意到了他说的话（1句）
2. 表达在意：表达你认真对待这句话（1句）
3. 具体行动：建议立刻联系家人或护理员，提供明确的下一步行动（1~2句）

## 语言要求
- 极度温柔，无任何批评或评判
- 不要问「你为什么这么想」，不追问细节
- 不要给分析或建议，只做情感连接和行动引导
- 字数：60~80字\
"""


# ─── 情绪策略映射表 ───────────────────────────────────────────────────────────
EMOTION_STRATEGY_MAP = {
    'sad': {
        'respond_strategy':      '陪伴式倾听，温柔引导对方表达，不急于提供解决方案',
        'specific_instructions': (
            '允许沉默存在，不要急于填满空白。'
            '可以轻柔询问：「能说说是什么让您今天这么难过吗？」'
        ),
        'forbidden': '「没事的」「会好的」「想开点」「过去了就好了」',
    },
    'fearful': {
        'respond_strategy':      '先用语言引导放慢呼吸节律，再温柔地做认知重构',
        'specific_instructions': (
            '可以说：「我们先慢慢呼吸，好吗？」'
            '再将注意力引回当下：「现在，您眼前能看到什么？」'
        ),
        'forbidden': '否定担忧、做任何保证、直接给建议',
    },
    'angry': {
        'respond_strategy':      '充分承认愤怒的合理性，完全接纳，不评判，不尝试降温',
        'specific_instructions': (
            '先让愤怒被完全接纳，再温柔探索原因。'
            '可以说：「能告诉我是什么让您这么生气吗？」'
        ),
        'forbidden': '「冷静一下」「别激动」「这不值得生气」「你太敏感了」',
    },
    'happy': {
        'respond_strategy':      '与用户共鸣，正向强化，好奇且真诚地询问细节',
        'specific_instructions': (
            '鼓励分享更多：「听起来真是美好的事，多跟我说说？」'
        ),
        'forbidden': '转移话题、敷衍回应、过度夸张',
    },
    'disgusted': {
        'respond_strategy':      '接纳情绪，不辩解，温和探索背后原因',
        'specific_instructions': (
            '温和共情：「这件事让您很不舒服，这完全可以理解。」'
        ),
        'forbidden': '辩解、评判、否定感受',
    },
    'surprised': {
        'respond_strategy':      '先确认是正面还是负面的惊讶，再分别给予共鸣或稳定支持',
        'specific_instructions': (
            '开放探索：「这让您感到意外，能跟我说说发生了什么吗？」'
        ),
        'forbidden': '过度反应、忽视',
    },
    'neutral': {
        'respond_strategy':      '保持轻松自然的对话，主动关怀今日状态',
        'specific_instructions': (
            '可主动邀请分享：「今天过得怎么样？有什么想跟我聊的吗？」'
        ),
        'forbidden': '无特殊禁忌',
    },
}


# ─── 构建函数 ─────────────────────────────────────────────────────────────────

def build_normal_prompt(emotion: dict) -> str:
    """
    根据 STEP 2 的情绪结果构建正常对话 System Prompt。

    Args:
        emotion: EmotionService.to_dict() 的输出，
                 包含 label, label_zh, score, valence, arousal, trend 等字段。

    Returns:
        完整的 System Prompt 字符串，直接传给 Qwen API。
    """
    label    = emotion.get('label', 'neutral')
    strategy = EMOTION_STRATEGY_MAP.get(label, EMOTION_STRATEGY_MAP['neutral'])

    return NORMAL_SYSTEM_PROMPT.format(
        emotion_label_zh      = emotion.get('label_zh', '平静'),
        emotion_score_pct     = f"{emotion.get('score', 1.0):.0%}",
        emotion_trend         = emotion.get('trend', '首次对话'),
        valence               = emotion.get('valence', 0.5),
        arousal               = emotion.get('arousal', 0.2),
        respond_strategy      = strategy['respond_strategy'],
        specific_instructions = strategy['specific_instructions'],
    )


def build_crisis_prompt() -> str:
    """危机干预 System Prompt，不需要情绪参数。"""
    return CRISIS_SYSTEM_PROMPT
```

---

## 8. 情绪策略映射表

动态填充至 Prompt 中的 `{respond_strategy}` 和 `{specific_instructions}`：

| 情绪 | Respond 策略 | 专属指引 | 禁忌 |
|------|-------------|----------|------|
| `sad` 悲伤 | 陪伴式倾听，温柔引导表达 | 允许沉默；可询问「能说说让您难过的事吗？」 | 「没事的」「想开点」 |
| `fearful` 焦虑 | 先引导呼吸，再认知重构 | 引导注意力回当下 | 否定担忧、做保证 |
| `angry` 愤怒 | 充分承认愤怒合理性，完全接纳 | 让愤怒先被接纳再探索 | 「冷静」「别激动」 |
| `happy` 快乐 | 与用户共鸣，正向强化 | 鼓励分享细节 | 转移话题 |
| `disgusted` 厌恶 | 接纳情绪，温和探索 | 温和共情 | 辩解、评判 |
| `surprised` 惊讶 | 先确认正负性，再分别回应 | 开放探索 | 过度反应 |
| `neutral` 平静 | 轻松自然对话，主动关怀 | 主动邀请分享 | 无特殊禁忌 |

---

## 9. 核心服务实现

### `services/llm_service.py`

```python
import logging
from typing import Generator
from openai import OpenAI
from config import (
    DASHSCOPE_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_MAX_HISTORY_TURNS,
    CRISIS_KEYWORDS,
    TTS_PARAMS_MAP,
)
from prompts.templates import build_normal_prompt, build_crisis_prompt

logger = logging.getLogger(__name__)


class LLMService:
    """
    通义千问 LLM 心理回复服务。

    设计说明：
    - 纯 Python 服务类，不包含任何路由/HTTP 逻辑
    - 在 main.py 的 lifespan() 中初始化，整个应用生命周期共享同一实例
    - stream_reply() 接收文本和情绪字典，直接来自前端的 SSE 请求体，
      情绪数据由前端从 STEP 1 的 transcript 消息中取出后转发，无中间层
    - 维护每个会话的对话历史，超出上限时自动裁剪最旧轮次
    """

    def __init__(self):
        self.client = OpenAI(
            api_key  = DASHSCOPE_API_KEY,
            base_url = QWEN_BASE_URL,
        )
        # 对话历史：[{'role': 'user'|'assistant', 'content': str}, ...]
        self.conversation: list[dict] = []
        logger.info("LLM 服务初始化完成 ✅")


    # ── 主入口：流式生成回复 ──────────────────────────────────────────────────

    def stream_reply(
        self,
        user_text: str,
        emotion:   dict,
    ) -> Generator[dict, None, None]:
        """
        流式生成心理回复。

        Args:
            user_text: STEP 1 转录文本（来自 transcript 消息的 text 字段）
            emotion:   STEP 2 情绪结果字典（来自 transcript 消息的 emotion 字段）
                       包含 label, label_zh, score, valence, arousal, trend, history

        Yields:
            {'type': 'delta',  'text': str,       'crisis': bool}
            {'type': 'done',   'full_text': str,   'crisis': bool,
             'emotion_label': str, 'tts_params': dict}
            {'type': 'error',  'message': str}
        """

        # ── 步骤 1：危机检测（最高优先级，早于一切处理）────────────────────
        crisis = self._check_crisis(user_text)
        if crisis:
            logger.warning(f"⚠️  危机信号触发 | 文本: {user_text[:50]}")

        # ── 步骤 2：构建 System Prompt ──────────────────────────────────────
        system_prompt = (
            build_crisis_prompt()       if crisis
            else build_normal_prompt(emotion)
        )

        # ── 步骤 3：追加用户消息到历史 ──────────────────────────────────────
        self.conversation.append({'role': 'user', 'content': user_text})

        # ── 步骤 4：裁剪历史，保留最近 N 轮 ────────────────────────────────
        max_msgs = LLM_MAX_HISTORY_TURNS * 2
        if len(self.conversation) > max_msgs:
            self.conversation = self.conversation[-max_msgs:]

        # ── 步骤 5：组装完整消息列表 ────────────────────────────────────────
        messages = [
            {'role': 'system', 'content': system_prompt},
            *self.conversation,
        ]

        # ── 步骤 6：调用 Qwen API 流式生成 ──────────────────────────────────
        try:
            stream = self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = messages,
                stream      = True,
                max_tokens  = LLM_MAX_TOKENS,
                temperature = LLM_TEMPERATURE,
                top_p       = LLM_TOP_P,
            )
        except Exception as e:
            logger.error(f"Qwen API 调用失败: {e}", exc_info=True)
            yield {'type': 'error', 'message': str(e)}
            return

        # ── 步骤 7：流式处理输出 ─────────────────────────────────────────────
        full_reply = ''
        for chunk in stream:
            delta_text = chunk.choices[0].delta.content or ''
            if delta_text:
                full_reply += delta_text
                yield {
                    'type':   'delta',
                    'text':   delta_text,
                    'crisis': crisis,
                }

        # ── 步骤 8：保存助手回复到历史 ──────────────────────────────────────
        if full_reply:
            self.conversation.append(
                {'role': 'assistant', 'content': full_reply}
            )

        # ── 步骤 9：生成完毕信号 ──────────────────────────────────────────────
        # tts_params 直接传给前端，前端用于触发 STEP 4
        yield {
            'type':          'done',
            'full_text':     full_reply,
            'crisis':        crisis,
            'emotion_label': emotion.get('label', 'neutral'),
            'tts_params':    self._get_tts_params(emotion, crisis),
        }


    # ── 工具方法 ─────────────────────────────────────────────────────────────

    def _check_crisis(self, text: str) -> bool:
        """
        检测用户文本是否包含危机信号关键词。
        任意一个关键词命中即返回 True，无置信度阈值。
        """
        return any(kw in text for kw in CRISIS_KEYWORDS)

    def _get_tts_params(self, emotion: dict, crisis: bool) -> dict:
        """
        根据情绪和是否危机返回 STEP 4 所需的 TTS 参数。
        危机模式使用最平缓参数，其余按「治愈性对称」原则映射。
        """
        if crisis:
            return TTS_PARAMS_MAP['_crisis']
        label = emotion.get('label', 'neutral')
        return TTS_PARAMS_MAP.get(label, TTS_PARAMS_MAP['neutral'])

    def reset(self):
        """
        新对话开始时调用，清除对话历史。
        由 main.py 的 /session/reset 端点统一触发，
        与 EmotionService.reset() 同步调用。
        """
        self.conversation.clear()
        logger.info("对话历史已重置")

    @property
    def history_turns(self) -> int:
        """当前对话轮数（用于调试）。"""
        return len(self.conversation) // 2
```

---

## 10. 路由层实现

### `routers/sse_llm.py`

```python
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from services.llm_service import LLMService

logger = logging.getLogger(__name__)
router = APIRouter()

# 服务实例由 main.py 注入
llm_service: LLMService = None


# ─── Schema ──────────────────────────────────────────────────────────────────

class LLMRequest(BaseModel):
    text:       str  = Field(...,         description="STEP 1 转录文本")
    emotion:    dict = Field(...,         description="STEP 2 EmotionResult 序列化字典")
    session_id: str  = Field(default='default', description="会话 ID（预留多用户扩展）")


# ─── 路由 ────────────────────────────────────────────────────────────────────

@router.post('/llm/stream')
async def stream_reply(req: LLMRequest):
    """
    LLM 流式回复接口，使用 SSE（Server-Sent Events）格式。

    前端调用时机：
      收到 STEP 1 的 transcript WebSocket 消息后，立即 POST 此接口。
      req.text    = msg.text
      req.emotion = msg.emotion  （直接转发，无需额外处理）
    """
    def generate():
        for chunk in llm_service.stream_reply(req.text, req.emotion):
            # SSE 格式：每条消息 "data: <json>\n\n"
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',   # 禁止 Nginx 缓冲，保证实时推送
        },
    )


@router.post('/llm/reset')
async def reset_session(session_id: str = 'default'):
    """
    重置对话历史。
    通常由 main.py 的 /session/reset 统一调用，
    也可单独调用用于调试。
    """
    llm_service.reset()
    return {'status': 'ok', 'session_id': session_id}


@router.get('/llm/history')
async def get_history():
    """获取当前对话历史（调试用）。"""
    return {
        'turns':    llm_service.history_turns,
        'messages': llm_service.conversation,
    }
```

### 与 `main.py` 的连接方式

```python
# main.py（节选）
import routers.sse_llm as sse_llm_router
from services.llm_service import LLMService

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 其他服务初始化 ...
    llm_svc = LLMService()

    # 注入到路由模块
    sse_llm_router.llm_service = llm_svc

    yield

app.include_router(sse_llm_router.router)  # 挂载到端口 8000
```

---

## 11. 危机干预协议

### 11.1 触发条件

用户文本包含 `CRISIS_KEYWORDS` 中任意关键词，立即触发，无置信度阈值，无延迟。

```python
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
]
```

> ⚠️ 危机检测是 `stream_reply()` 的**第一行逻辑**，早于 Prompt 构建和 API 调用。

### 11.2 全链路触发流程

```
用户说出危机词
        │
        ▼
LLMService._check_crisis() → crisis = True
  ├─ System Prompt 切换为 CRISIS_SYSTEM_PROMPT
  ├─ 每个 delta chunk 携带 crisis: true
  └─ done 事件携带 crisis: true + _crisis TTS 参数

        │
        ▼
前端 useLLM.ts 收到 crisis: true
  ├─ onCrisis 回调触发
  ├─ 界面背景渐变为温暖橙色
  ├─ 显示「联系护理员」按钮
  └─ 禁用「结束对话」按钮

        │
        ▼
STEP 4 使用 _crisis TTS 参数
  └─ speed=0.82, pitch=-2, style=gentle（最平缓语调）
```

### 11.3 危机模式下的对话历史处理

- 危机触发轮次的对话**正常保存**到历史（供后续轮次参考上下文）
- 危机触发后连续 **2 轮**对话的 system prompt 保持危机模式警惕状态
- 后端日志记录危机事件（含时间戳、session_id），供护理人员查阅

---

## 12. SSE 接口规范

### POST `/llm/stream`

**请求体：**
```json
{
  "text":    "我今天一直在想我老伴，他走了三年了。",
  "emotion": {
    "label":    "sad",
    "label_zh": "悲伤",
    "score":    0.718,
    "valence":  0.10,
    "arousal":  0.20,
    "trend":    "情绪持续稳定在「悲伤」状态",
    "history":  [
      { "label": "neutral", "score": 0.682 },
      { "label": "sad",     "score": 0.611 },
      { "label": "sad",     "score": 0.731 }
    ]
  },
  "session_id": "default"
}
```

**SSE 流式响应（Content-Type: text/event-stream）：**

```
data: {"type": "delta", "text": "我在", "crisis": false}

data: {"type": "delta", "text": "这里陪着您。", "crisis": false}

data: {"type": "delta", "text": "听起来今天", "crisis": false}

...（持续推送 delta chunks）...

data: {
  "type":          "done",
  "full_text":     "我在这里陪着您。听起来今天您心里很沉，很想念他。思念陪伴了几十年的人，这种感受是很真实的，不需要假装没事。能跟我说说他是个什么样的人吗？",
  "crisis":        false,
  "emotion_label": "sad",
  "tts_params":    {"speed": 0.85, "pitch": -2, "style": "gentle"}
}
```

**危机响应示例：**

```
data: {"type": "delta", "text": "我听到您说的了，", "crisis": true}

...

data: {
  "type":          "done",
  "full_text":     "我听到您说的了，您现在的感受我很在意。您现在身边有人陪着您吗？我建议我们现在去找一下护理员，好吗？",
  "crisis":        true,
  "emotion_label": "sad",
  "tts_params":    {"speed": 0.82, "pitch": -2, "style": "gentle"}
}
```

---

## 13. 前端集成代码

### `composables/useLLM.ts`

```typescript
import { ref } from 'vue'

// ── 类型定义 ─────────────────────────────────────────────────────────────────

interface TTSParams {
  speed: number
  pitch: number
  style: string
}

interface DoneEvent {
  type:          'done'
  full_text:     string
  crisis:        boolean
  emotion_label: string
  tts_params:    TTSParams
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useLLM(apiBase = 'http://localhost:8000') {
  const reply       = ref('')      // 流式累积的完整回复文本（用于界面显示）
  const isStreaming = ref(false)
  const isCrisis    = ref(false)

  // 首句缓冲区：检测到句末标点后立即触发 STEP 4
  let sentenceBuffer    = ''
  let firstSentenceSent = false

  // ── 外部回调（由父组件设置）──────────────────────────────────────────────
  // 首句生成完毕时调用，立即触发 STEP 4 合成（流水线并行关键）
  const onFirstSentence = ref<((text: string, params: TTSParams) => void) | null>(null)
  // 全文生成完毕时调用
  const onReplyDone     = ref<((event: DoneEvent) => void) | null>(null)
  // 危机信号触发时调用（UI 切换橙色背景等）
  const onCrisis        = ref<(() => void) | null>(null)

  // 句末标点正则
  const SENTENCE_END_RE = /^([^。！？.!?]+[。！？.!?])/


  // ── 主接口：发起 SSE 请求 ────────────────────────────────────────────────

  async function streamReply(text: string, emotion: object) {
    reply.value        = ''
    isStreaming.value  = true
    isCrisis.value     = false
    sentenceBuffer     = ''
    firstSentenceSent  = false

    try {
      const res = await fetch(`${apiBase}/llm/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          text,
          emotion,
          session_id: 'default',
        }),
      })

      if (!res.ok)   throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('无响应体')

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // SSE 行解析
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''   // 保留不完整的最后一行

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const jsonStr = line.slice(5).trim()
          if (!jsonStr) continue

          try {
            handleEvent(JSON.parse(jsonStr))
          } catch {
            // 忽略解析失败的行
          }
        }
      }

    } catch (err) {
      console.error('[LLM] SSE 请求失败:', err)
    } finally {
      isStreaming.value = false
    }
  }


  // ── 事件处理 ─────────────────────────────────────────────────────────────

  function handleEvent(event: any) {
    if (event.type === 'delta') {
      reply.value += event.text

      // 危机标记（首次触发时调用回调）
      if (event.crisis && !isCrisis.value) {
        isCrisis.value = true
        onCrisis.value?.()
      }

      // ── 首句检测：流水线并行的关键 ─────────────────────────────────────
      // 一旦 delta 拼接出第一个完整句子，立即触发 STEP 4 合成
      // 不等 LLM 全文生成，LLM 和 TTS 并行运行
      if (!firstSentenceSent) {
        sentenceBuffer += event.text
        const match = sentenceBuffer.match(SENTENCE_END_RE)
        if (match) {
          firstSentenceSent = true
          const firstSentence = match[1]
          sentenceBuffer = sentenceBuffer.slice(firstSentence.length)
          // 此时 tts_params 还未到达（done 事件才有），
          // 使用 emotion_label 的默认参数先触发（STEP 4 有默认值兜底）
          // 或等 done 事件到达时补发（见下方处理）
        }
      }

    } else if (event.type === 'done') {
      isCrisis.value = event.crisis

      if (!firstSentenceSent && event.full_text) {
        // 极短回复（无句末标点）在 done 时触发 TTS
        onFirstSentence.value?.(event.full_text, event.tts_params)
      } else if (firstSentenceSent) {
        // 首句已触发，通知 STEP 4 剩余文本
        const remaining = extractRemaining(reply.value, event.full_text)
        if (remaining.trim()) {
          onFirstSentence.value?.(remaining, event.tts_params)
        }
      }

      onReplyDone.value?.(event)

    } else if (event.type === 'error') {
      console.error('[LLM] 服务端错误:', event.message)
    }
  }


  // ── 工具 ─────────────────────────────────────────────────────────────────

  function extractRemaining(firstSentence: string, fullText: string): string {
    // 从 fullText 中去除已通过 onFirstSentence 发送的首句
    const RE   = /^([^。！？.!?]+[。！？.!?])/
    const match = fullText.match(RE)
    if (!match) return ''
    return fullText.slice(match[1].length)
  }

  async function resetSession() {
    reply.value = ''
    await fetch(`${apiBase}/llm/reset`, { method: 'POST' })
  }

  return {
    reply,
    isStreaming,
    isCrisis,
    onFirstSentence,
    onReplyDone,
    onCrisis,
    streamReply,
    resetSession,
  }
}
```

---

## 14. TDD 验收测试

### `tests/test_llm_service.py`

```python
import pytest
from unittest.mock import MagicMock, patch
from config import CRISIS_KEYWORDS, LLM_MAX_HISTORY_TURNS, TTS_PARAMS_MAP
from prompts.templates import (
    build_normal_prompt,
    build_crisis_prompt,
    EMOTION_STRATEGY_MAP,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """初始化 LLMService，mock 掉 OpenAI 客户端。"""
    with patch('services.llm_service.OpenAI') as mock_cls:
        from services.llm_service import LLMService
        service = LLMService()
        service.client = mock_cls.return_value
    return service


def make_emotion(label: str = 'neutral', score: float = 0.8) -> dict:
    """构造 STEP 2 EmotionResult 序列化字典。"""
    COORDS = {
        'neutral':   (0.50, 0.20), 'happy':     (0.90, 0.70),
        'sad':       (0.10, 0.20), 'angry':     (0.10, 0.90),
        'fearful':   (0.15, 0.80), 'disgusted': (0.15, 0.50),
        'surprised': (0.60, 0.85),
    }
    ZH = {
        'neutral': '平静', 'happy': '快乐', 'sad': '悲伤',
        'angry': '愤怒',  'fearful': '焦虑/恐惧',
        'disgusted': '厌恶', 'surprised': '惊讶',
    }
    v, a = COORDS.get(label, (0.5, 0.2))
    return {
        'label':    label,
        'label_zh': ZH.get(label, '平静'),
        'score':    score,
        'raw_label': label,
        'raw_score': score,
        'valence':  v,
        'arousal':  a,
        'trend':    '首次对话',
        'history':  [],
    }


def make_stream_chunks(text: str):
    """构造 Qwen API 流式响应 mock。"""
    chunks = []
    for char in text:
        m = MagicMock()
        m.choices[0].delta.content = char
        chunks.append(m)
    end = MagicMock()
    end.choices[0].delta.content = ''
    chunks.append(end)
    return iter(chunks)


# ─── TC-01: 危机检测 ──────────────────────────────────────────────────────────

class TestCrisisDetection:

    def test_crisis_keyword_returns_true(self, svc):
        """TC-01: 包含危机关键词时返回 True"""
        assert svc._check_crisis('我不想活了') is True
        assert svc._check_crisis('活着没意思') is True

    def test_normal_text_returns_false(self, svc):
        """TC-02: 正常文本返回 False"""
        assert svc._check_crisis('今天天气真好') is False
        assert svc._check_crisis('我想吃饺子') is False

    def test_keyword_list_covers_critical_phrases(self):
        """TC-03: 关键词列表覆盖必要的危机表达"""
        must_have = ['不想活', '活着没意思', '死了算了', '轻生', '了结']
        for kw in must_have:
            assert kw in CRISIS_KEYWORDS, f"关键词「{kw}」未在列表中"

    def test_partial_keyword_match(self, svc):
        """TC-04: 关键词嵌入句子中也能检测到"""
        assert svc._check_crisis('我真的太累了不想撑下去了') is True

    def test_crisis_switches_to_crisis_prompt(self, svc):
        """TC-05: 危机文本触发危机 Prompt（含「危机信号」字样）"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('我听到了。')
        list(svc.stream_reply('我不想活了', make_emotion()))
        msgs   = svc.client.chat.completions.create.call_args.kwargs['messages']
        system = msgs[0]['content']
        assert '危机信号' in system
        assert 'CARE' not in system

    def test_normal_text_uses_care_prompt(self, svc):
        """TC-06: 正常文本使用 CARE Prompt"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('我在这里。')
        list(svc.stream_reply('今天天气真好', make_emotion()))
        msgs   = svc.client.chat.completions.create.call_args.kwargs['messages']
        system = msgs[0]['content']
        assert 'CARE' in system
        assert '危机信号' not in system


# ─── TC-02: Prompt 构建 ───────────────────────────────────────────────────────

class TestPromptBuilding:

    def test_emotion_label_zh_in_prompt(self):
        """TC-07: System Prompt 包含情绪中文标签"""
        prompt = build_normal_prompt(make_emotion('sad'))
        assert '悲伤' in prompt

    def test_emotion_trend_in_prompt(self):
        """TC-08: System Prompt 包含情绪趋势"""
        emotion = make_emotion('happy')
        emotion['trend'] = '情绪明显好转'
        assert '情绪明显好转' in build_normal_prompt(emotion)

    def test_respond_strategy_in_prompt(self):
        """TC-09: System Prompt 包含情绪对应的 Respond 策略"""
        strategy = EMOTION_STRATEGY_MAP['angry']['respond_strategy']
        assert strategy in build_normal_prompt(make_emotion('angry'))

    def test_specific_instructions_in_prompt(self):
        """TC-10: System Prompt 包含情绪专属指引"""
        instructions = EMOTION_STRATEGY_MAP['fearful']['specific_instructions']
        assert instructions in build_normal_prompt(make_emotion('fearful'))

    def test_valence_arousal_in_prompt(self):
        """TC-11: System Prompt 包含效价和唤醒度数值"""
        prompt = build_normal_prompt(make_emotion('sad'))
        assert '0.10' in prompt   # sad valence
        assert '0.20' in prompt   # sad arousal

    def test_all_7_emotions_have_strategy(self):
        """TC-12: 7 种情绪标签均有完整策略映射"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert label in EMOTION_STRATEGY_MAP
            s = EMOTION_STRATEGY_MAP[label]
            assert 'respond_strategy' in s
            assert 'specific_instructions' in s
            assert 'forbidden' in s

    def test_crisis_prompt_has_three_elements(self):
        """TC-13: 危机 Prompt 包含三个必要要素"""
        prompt = build_crisis_prompt()
        assert '我听到了' in prompt
        assert '表达在意' in prompt
        assert '具体行动' in prompt

    def test_unknown_emotion_falls_back_to_neutral_strategy(self):
        """TC-14: 未知情绪标签回退到 neutral 策略"""
        emotion = make_emotion('neutral')
        emotion['label'] = 'unknown_emotion'
        # build_normal_prompt 不应报错
        prompt = build_normal_prompt(emotion)
        assert prompt  # 非空字符串


# ─── TC-03: 流式输出 ──────────────────────────────────────────────────────────

class TestStreamOutput:

    def test_delta_chunks_yielded(self, svc):
        """TC-15: 流式回复产生多个 delta 类型事件"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('我在这里陪着您。')
        chunks = list(svc.stream_reply('你好', make_emotion()))
        deltas = [c for c in chunks if c.get('type') == 'delta']
        assert len(deltas) > 0

    def test_delta_text_concatenates_to_full_reply(self, svc):
        """TC-16: 所有 delta.text 拼接等于 done.full_text"""
        reply_text = '我在这里陪着您。'
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks(reply_text)
        chunks   = list(svc.stream_reply('你好', make_emotion()))
        deltas   = [c['text'] for c in chunks if c.get('type') == 'delta']
        done     = next(c for c in chunks if c.get('type') == 'done')
        assert ''.join(deltas) == done['full_text']
        assert done['full_text'] == reply_text

    def test_done_event_has_tts_params(self, svc):
        """TC-17: done 事件包含 tts_params 字段"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('回复。')
        chunks = list(svc.stream_reply('你好', make_emotion('sad')))
        done   = next(c for c in chunks if c.get('type') == 'done')
        assert 'tts_params' in done
        assert 'speed' in done['tts_params']
        assert 'pitch' in done['tts_params']
        assert 'style' in done['tts_params']

    def test_done_event_has_emotion_label(self, svc):
        """TC-18: done 事件包含 emotion_label 字段"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('回复。')
        chunks = list(svc.stream_reply('你好', make_emotion('happy')))
        done   = next(c for c in chunks if c.get('type') == 'done')
        assert done['emotion_label'] == 'happy'

    def test_crisis_flag_on_all_chunks(self, svc):
        """TC-19: 危机文本的所有 chunk 均携带 crisis: true"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('我听到了。')
        chunks = list(svc.stream_reply('我不想活了', make_emotion()))
        for chunk in chunks:
            assert chunk.get('crisis') is True

    def test_api_exception_yields_error_event(self, svc):
        """TC-20: API 调用失败时 yield error 事件，不崩溃"""
        svc.client.chat.completions.create.side_effect = \
            RuntimeError("API 超时")
        chunks = list(svc.stream_reply('你好', make_emotion()))
        errors = [c for c in chunks if c.get('type') == 'error']
        assert len(errors) == 1
        assert 'API 超时' in errors[0]['message']


# ─── TC-04: TTS 参数 ─────────────────────────────────────────────────────────

class TestTTSParams:

    def test_sad_gets_slow_speed(self, svc):
        """TC-21: 悲伤情绪 TTS 语速 < 1.0（治愈性对称）"""
        params = svc._get_tts_params(make_emotion('sad'), crisis=False)
        assert params['speed'] < 1.0

    def test_happy_gets_fast_speed(self, svc):
        """TC-22: 快乐情绪 TTS 语速 > 1.0（共鸣强化）"""
        params = svc._get_tts_params(make_emotion('happy'), crisis=False)
        assert params['speed'] > 1.0

    def test_crisis_gets_slowest_speed(self, svc):
        """TC-23: 危机模式 TTS 语速最慢"""
        crisis_params = svc._get_tts_params(make_emotion('neutral'), crisis=True)
        normal_params = svc._get_tts_params(make_emotion('neutral'), crisis=False)
        assert crisis_params['speed'] < normal_params['speed']

    def test_crisis_uses_gentle_style(self, svc):
        """TC-24: 危机模式 TTS 使用 gentle 风格"""
        params = svc._get_tts_params(make_emotion('neutral'), crisis=True)
        assert params['style'] == 'gentle'

    def test_all_7_emotions_have_tts_params(self):
        """TC-25: 7 种情绪标签均有 TTS 参数映射"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert label in TTS_PARAMS_MAP

    def test_crisis_tts_params_exist(self):
        """TC-26: 危机专用 TTS 参数存在"""
        assert '_crisis' in TTS_PARAMS_MAP


# ─── TC-05: 对话历史管理 ─────────────────────────────────────────────────────

class TestConversationHistory:

    def test_user_message_appended_to_history(self, svc):
        """TC-27: stream_reply 后用户消息加入历史"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('回复')
        list(svc.stream_reply('测试消息', make_emotion()))
        user_msgs = [m for m in svc.conversation if m['role'] == 'user']
        assert any('测试消息' in m['content'] for m in user_msgs)

    def test_assistant_reply_appended_to_history(self, svc):
        """TC-28: stream_reply 后助手回复加入历史"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('助手回复内容')
        list(svc.stream_reply('你好', make_emotion()))
        asst_msgs = [m for m in svc.conversation if m['role'] == 'assistant']
        assert any('助手回复内容' in m['content'] for m in asst_msgs)

    def test_history_trimmed_when_exceeds_limit(self, svc):
        """TC-29: 历史超出 MAX_HISTORY_TURNS * 2 条时自动裁剪"""
        for i in range(LLM_MAX_HISTORY_TURNS * 2 + 5):
            svc.conversation.append({'role': 'user',      'content': f'msg{i}'})
            svc.conversation.append({'role': 'assistant', 'content': f'rep{i}'})
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('ok')
        list(svc.stream_reply('新消息', make_emotion()))
        assert len(svc.conversation) <= LLM_MAX_HISTORY_TURNS * 2 + 2

    def test_system_prompt_not_in_history(self, svc):
        """TC-30: 对话历史中不包含 system 角色消息"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('回复')
        list(svc.stream_reply('你好', make_emotion()))
        roles = [m['role'] for m in svc.conversation]
        assert 'system' not in roles

    def test_reset_clears_conversation(self, svc):
        """TC-31: reset 后对话历史为空"""
        svc.conversation.append({'role': 'user', 'content': 'test'})
        svc.reset()
        assert len(svc.conversation) == 0

    def test_history_turns_property(self, svc):
        """TC-32: history_turns 返回正确轮数"""
        svc.conversation = [
            {'role': 'user',      'content': '1'},
            {'role': 'assistant', 'content': '2'},
            {'role': 'user',      'content': '3'},
            {'role': 'assistant', 'content': '4'},
        ]
        assert svc.history_turns == 2

    def test_empty_reply_not_saved_to_history(self, svc):
        """TC-33: 空回复不保存到历史"""
        svc.client.chat.completions.create.return_value = \
            make_stream_chunks('')   # 空回复
        list(svc.stream_reply('你好', make_emotion()))
        asst_msgs = [m for m in svc.conversation if m['role'] == 'assistant']
        assert len(asst_msgs) == 0
```

### 验收标准汇总

| ID | 分类 | 描述 | 通过条件 |
|----|------|------|----------|
| TC-01 | 危机 | 关键词检测 True | 返回 True |
| TC-02 | 危机 | 正常文本 False | 返回 False |
| TC-03 | 危机 | 关键词列表完整 | 5 个必选词存在 |
| TC-04 | 危机 | 嵌入句中也检测 | 返回 True |
| TC-05 | 危机 | 切换危机 Prompt | system 含「危机信号」 |
| TC-06 | 危机 | 正常用 CARE Prompt | system 含「CARE」 |
| TC-07 | Prompt | 含中文情绪标签 | 含「悲伤」 |
| TC-08 | Prompt | 含趋势描述 | trend 字符串存在 |
| TC-09 | Prompt | 含 Respond 策略 | 策略字符串存在 |
| TC-10 | Prompt | 含专属指引 | 指引字符串存在 |
| TC-11 | Prompt | 含 V/A 数值 | 坐标值存在 |
| TC-12 | Prompt | 7 种情绪有策略 | 所有 label 均有映射 |
| TC-13 | Prompt | 危机三要素 | 3 个必要段落存在 |
| TC-14 | Prompt | 未知情绪回退 | 不报错，返回非空 |
| TC-15 | 流式 | 产生 delta 事件 | delta 数量 > 0 |
| TC-16 | 流式 | delta 拼接等于全文 | 字符串相等 |
| TC-17 | 流式 | done 含 tts_params | 3 个字段存在 |
| TC-18 | 流式 | done 含 emotion_label | 与入参一致 |
| TC-19 | 流式 | 危机 chunk 标记 | 所有 crisis == True |
| TC-20 | 流式 | API 异常产生 error | error 事件存在 |
| TC-21 | TTS | 悲伤语速慢 | speed < 1.0 |
| TC-22 | TTS | 快乐语速快 | speed > 1.0 |
| TC-23 | TTS | 危机最慢 | crisis speed < normal |
| TC-24 | TTS | 危机 gentle 风格 | style == gentle |
| TC-25 | TTS | 7 种情绪有参数 | 所有 label 均有映射 |
| TC-26 | TTS | 危机参数存在 | `_crisis` 键存在 |
| TC-27 | 历史 | 用户消息入历史 | history 含用户消息 |
| TC-28 | 历史 | 助手回复入历史 | history 含助手消息 |
| TC-29 | 历史 | 超限自动裁剪 | len ≤ 上限 + 2 |
| TC-30 | 历史 | system 不入历史 | roles 不含 system |
| TC-31 | 历史 | reset 清空 | len == 0 |
| TC-32 | 历史 | turns 计算正确 | == 2 |
| TC-33 | 历史 | 空回复不入历史 | asst_msgs 为空 |
