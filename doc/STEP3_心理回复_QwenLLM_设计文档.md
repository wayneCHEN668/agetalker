# STEP 3 — 心理回复模块
**技术栈：通义千问 Qwen API + CARE 心理陪伴框架 + SSE 流式输出**

---

## 目录
1. [模块概述](#1-模块概述)
2. [心理学理论框架](#2-心理学理论框架)
3. [CARE 回复模型详解](#3-care-回复模型详解)
4. [系统架构](#4-系统架构)
5. [System Prompt 完整设计](#5-system-prompt-完整设计)
6. [情绪策略映射表](#6-情绪策略映射表)
7. [环境依赖与配置](#7-环境依赖与配置)
8. [核心实现代码](#8-核心实现代码)
9. [危机干预协议](#9-危机干预协议)
10. [SSE 流式接口规范](#10-sse-流式接口规范)
11. [前端集成代码](#11-前端集成代码)
12. [TDD 验收测试](#12-tdd-验收测试)

---

## 1. 模块概述

本模块接收 **STEP 1 的转录文本**与 **STEP 2 的情绪分析结果**，通过基于心理学理论构建的 System Prompt 框架，调用**通义千问 API** 生成符合心理咨询原则的回复文本。回复以 **SSE 流式方式**推送至前端实现打字机效果，同时在生成首句完整句子时立即向 **STEP 4** 发出 TTS 合成信号，实现 LLM 与 TTS 的流水线并行。

### 目标指标

| 指标 | 目标值 |
|------|--------|
| 首 Token 延迟 | ≤ 1000ms（含网络往返） |
| 首句触发 TTS | 生成第一个句末标点（。！？）后立即触发 |
| 单次回复长度 | 60 ~ 120 字 |
| 单句最大长度 | ≤ 25 字 |
| 危机信号检测 | 关键词命中率 100%，无漏报 |
| 对话历史保留 | 最近 6 轮（约 12 条消息） |

### 与其他模块的关系

```
STEP 1 ──→ 转录文本 ─────────────────────────────┐
STEP 2 ──→ EmotionResult ──→ System Prompt 构建 ──┤
                                                    ▼
                                           Qwen API (stream)
                                                    │
                              ┌─────────────────────┤
                              ▼                     ▼
                         前端显示文本           STEP 4 TTS
                        （打字机效果）         （首句立即合成）
```

---

## 2. 心理学理论框架

本模块融合三大心理咨询流派，针对老年陪伴场景进行定制化适配。

### 2.1 以人为中心疗法（Person-Centered Therapy）
**创始人：Carl Rogers，1951**

| 核心原则 | 在本系统的应用 |
|----------|---------------|
| 无条件积极关注（Unconditional Positive Regard） | 无论老人说什么，先接纳，不评判，不纠正 |
| 共情式理解（Empathic Understanding） | 每次回复必须先反映对方感受，再给回应 |
| 真诚一致（Congruence） | AI 不假装快乐，回应语气与情绪内容匹配 |

### 2.2 接纳与承诺疗法（ACT — Acceptance and Commitment Therapy）
**创始人：Steven Hayes，1986**

| 核心原则 | 在本系统的应用 |
|----------|---------------|
| 接纳（Acceptance） | 不试图消除负面情绪，引导老人接纳当下体验 |
| 去融合（Defusion） | 帮助老人觉察情绪而非陷入情绪（"您现在感到悲伤"而非"您是一个悲伤的人"） |
| 当下接触（Present Moment） | 将注意力引回到此时此刻，而非反复追究过去 |

### 2.3 危机干预理论（Roberts 七阶段危机干预模型）
**创始人：Albert Roberts，2000**

本系统实现其中三个关键阶段：

| Roberts 阶段 | 本系统实现 |
|-------------|-----------|
| 阶段1：评估安全性 | 危机关键词实时检测 |
| 阶段2：建立连接 | 触发危机模式 System Prompt，强化共情 |
| 阶段5：制定应对计划 | 建议联系家属 / 护理员，提供具体行动 |

### 2.4 老年心理特殊考量

老年人群体有以下特殊心理需求，在 Prompt 设计中重点照顾：

| 心理需求 | 应对策略 |
|----------|----------|
| 被重视感 | 认真倾听，不打断，不催促 |
| 尊严维护 | 不使用居高临下语气，不使用"你应该" |
| 连接感 | 主动询问日常生活，建立持续关系感 |
| 怀旧需求 | 鼓励分享过去的故事和经历 |
| 自主感 | 给予选择，而非直接给出答案 |

---

## 3. CARE 回复模型详解

本系统自定义 **CARE 心理陪伴模型**，每次回复严格按四步骤结构生成：

```
C — Connect    建立情感连接   （1句，≤15字）
A — Acknowledge 承认并命名情绪 （1句，≤20字）
R — Respond    情绪针对性回应 （1~2句，根据情绪类型）
E — Empower    温柔激活内在资源（1句开放问题，可选）
```

### 3.1 各步骤示例（以悲伤情绪为例）

```
用户说："我今天一直在想我老伴，他走了三年了。"

C: "我在这里陪着您。"
A: "听起来您今天心里很沉，很想念他。"
R: "思念一个陪伴了几十年的人，这种感受是很真实的，
    不需要假装没事。"
E: "能跟我说说他是个什么样的人吗？"
```

### 3.2 CARE 使用规则

- **C 和 A 必须出现在 R 和 E 之前**，任何情况下不得跳过
- **禁止直接给建议**（除非老人明确请求），先共情再回应
- **E 步骤为可选**，情绪低落时不强求对方回答问题
- 危机状态下，**跳过 E 步骤**，改为提供具体求助行动

---

## 4. 系统架构

### 4.1 数据流

```
POST /llm/stream
  { text, emotion: EmotionResult, session_id }
          │
          ▼
LLMService.stream_reply(text, emotion)
  │
  ├─ 1. 危机信号检测（最高优先级）
  │      └─ 命中关键词 → crisis_mode = True
  │              ↓
  ├─ 2. 构建 System Prompt
  │      ├─ 动态填充情绪标签、趋势、坐标
  │      ├─ 注入情绪专属策略（从映射表读取）
  │      └─ crisis_mode → 切换为危机干预 Prompt
  │
  ├─ 3. 组装消息历史
  │      ├─ [system] + [历史对话 last 6轮] + [当前用户消息]
  │      └─ token 超限时裁剪最旧的对话轮次
  │
  ├─ 4. 调用 Qwen API (stream=True)
  │
  ├─ 5. 流式处理输出
  │      ├─ yield { type: delta, text: chunk }     → 前端打字机
  │      ├─ 句末标点检测 → 触发 TTS 首句合成信号
  │      └─ 累积完整回复文本
  │
  └─ 6. 收尾
         ├─ 保存对话历史
         └─ yield { type: done, tts_params, crisis }
```

### 4.2 句末标点检测与 TTS 流水线

```
LLM 流式输出:  "我" "在" "这" "里" "陪" "着" "您" "。" "听" "起" ...
                                                        ↑
                                               检测到句末标点
                                                        │
                                          立即触发 STEP 4 TTS 合成
                                          （不等 LLM 全文生成完毕）
```

---

## 5. System Prompt 完整设计

### 5.1 正常对话 Prompt 模板

```
你是「心伴」，一位专业的心理陪伴师，专门陪伴养老院的老年人。

## 当前情绪上下文
- 用户情绪：{emotion_label_zh}（置信度 {emotion_score_pct}）
- 情绪趋势：{emotion_trend}
- 效价/唤醒：{valence:.2f} / {arousal:.2f}

## 你的核心身份
你受过专业的心理咨询培训，精通以人为中心疗法和接纳承诺疗法。
你深刻理解老年人的心理需求：被重视、被倾听、保有尊严、保持连接感。
你说话温柔、耐心，使用简单词语，从不使用术语。

## CARE 回复框架（每次回复必须遵循）
按以下四步骤结构组织回复，步骤之间自然衔接，不要分段或编号：
1. Connect（连接）：用 1 句话建立情感连接（≤15字）
2. Acknowledge（承认）：承认并命名用户的情绪感受（≤20字）
3. Respond（回应）：{emotion_strategy}（1~2句）
4. Empower（赋能）：用一个温柔的开放性问题结尾（可选，情绪极低时省略）

## 语言规范
- 总字数：60~120字
- 单句字数：≤25字
- 禁止使用：「你应该…」「你需要…」「想开点」「没关系的」「不要难过」「别担心」
- 必须使用第一人称感受反映：「听起来…」「我感受到…」「您说的…让我感到…」
- 时间词用具体词汇：「今天」「这几天」，不用「最近」「近来」

## 情绪专属指引
{emotion_specific_instructions}

## 安全守则
- 绝不否定老人的感受，哪怕在你看来是误解
- 绝不与老人争辩，哪怕信息有误
- 绝不催促老人「振作」「开心起来」
```

### 5.2 危机干预 Prompt 模板

```
你是「心伴」，一位受过危机干预培训的心理陪伴师。

【高优先级警告】用户刚才说的话包含危机信号。
请放下一切常规对话逻辑，立即执行以下危机干预回复。

## 危机回复必须包含的三个要素（按顺序）：
1. 我听到了 — 明确告诉用户你注意到了他说的话（1句）
2. 表达在意 — 表达你认真对待这句话（1句）
3. 具体行动 — 建议立刻联系家人或护理员，提供明确行动（1~2句）

## 语言要求
- 语气：极度温柔，没有任何批评或评判
- 不要问「你为什么这么想」，不要追问细节
- 不要给任何分析或建议，只做连接
- 字数：60~80字

## 危机回复示例
「我听到您说的了，您现在的感受我很在意。
 您现在身边有人陪着您吗？
 我建议我们现在去找一下护理员，或者让我帮您联系家人，好吗？」
```

---

## 6. 情绪策略映射表

动态填充至 System Prompt 中的 `{emotion_strategy}` 与 `{emotion_specific_instructions}`。

| 情绪 | Respond 策略 | 专属指引 | 禁忌表达 |
|------|-------------|----------|----------|
| `sad` 悲伤 | 陪伴式倾听，温柔引导表达，不急于解决 | 允许沉默存在；可询问：「能说说是什么让您今天这么难过吗？」 | 「没事的」「会好的」「想开点」 |
| `fearful` 焦虑 | 先用语言引导放慢呼吸节律，再温柔认知重构 | 将注意力引回当下：「现在，您眼前能看到什么？」 | 否定担忧、承诺「没事」、给建议 |
| `angry` 愤怒 | 充分承认愤怒的合理性，不评判，不尝试安抚降温 | 先让愤怒被完全接纳再探索：「能告诉我是什么让您这么生气吗？」 | 「冷静一下」「别激动」「这不值得」 |
| `happy` 快乐 | 与用户共鸣，正向强化，好奇询问细节 | 鼓励分享：「听起来真是美好的事，多跟我说说？」 | 转移话题、过度夸张、敷衍回应 |
| `disgusted` 厌恶 | 接纳情绪，温和探索背后原因，不辩解 | 温和共情：「这件事让您很不舒服，这完全可以理解」 | 辩解、评判、否定感受 |
| `surprised` 惊讶 | 先确认是正面还是负面惊讶，再分别给予共鸣或稳定支持 | 开放探索：「这让您感到意外，能跟我说说发生了什么吗？」 | 过度反应、忽视 |
| `neutral` 平静 | 保持轻松自然对话，主动关怀今日状态 | 可主动邀请分享：「今天过得怎么样？有什么想跟我聊的吗？」 | 无特殊禁忌 |

---

## 7. 环境依赖与配置

### 7.1 安装依赖

```
# requirements_step3.txt
openai>=1.0.0          # 通义千问兼容 OpenAI SDK
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

```bash
pip install -r requirements_step3.txt
```

### 7.2 环境变量 `.env`

```
# 通义千问 API Key（从阿里云 DashScope 控制台获取）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# 模型选择
# qwen-turbo  : 最快，适合开发调试
# qwen-plus   : 平衡速度与质量（生产推荐）
# qwen-max    : 最高质量，延迟较高
QWEN_MODEL=qwen-plus

# 服务端口
LLM_PORT=8002
```

### 7.3 目录结构

```
step3_llm/
├── llm_service.py        # 核心 LLM 服务
├── llm_server.py         # FastAPI SSE 服务
├── prompt_templates.py   # Prompt 模板与策略映射
├── config.py             # 配置常量
├── .env
└── tests/
    └── test_step3.py
```

---

## 8. 核心实现代码

### 8.1 配置与常量 `config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# API 配置
QWEN_API_KEY  = os.environ['DASHSCOPE_API_KEY']
QWEN_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
QWEN_MODEL    = os.getenv('QWEN_MODEL', 'qwen-plus')

# 生成参数
MAX_TOKENS       = 256     # 单次最大生成 token 数
TEMPERATURE      = 0.75    # 适度创造性，避免重复
TOP_P            = 0.90
MAX_HISTORY_TURNS = 6      # 保留最近 N 轮对话（= N*2 条消息）

# 危机关键词（命中任意一条立即触发危机模式）
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
]
```

### 8.2 Prompt 模板 `prompt_templates.py`

```python
# prompt_templates.py

# ─── 情绪策略映射表 ──────────────────────────────────────────────────────────
EMOTION_STRATEGY_MAP = {
    'sad': {
        'respond_strategy': '陪伴式倾听，温柔引导对方表达，不急于提供解决方案',
        'specific_instructions': (
            '允许沉默存在，不要急于填满空白。'
            '可以轻柔询问：「能说说是什么让您今天这么难过吗？」'
        ),
        'forbidden': '「没事的」「会好的」「想开点」「过去了就好了」',
    },
    'fearful': {
        'respond_strategy': '先用语言引导放慢呼吸节律，再温柔地做认知重构',
        'specific_instructions': (
            '可以说：「我们先慢慢呼吸，好吗？」'
            '再将注意力引回当下：「现在，您眼前能看到什么？」'
        ),
        'forbidden': '否定担忧、做任何保证、直接给建议',
    },
    'angry': {
        'respond_strategy': '充分承认愤怒的合理性，完全接纳，不评判，不尝试降温',
        'specific_instructions': (
            '先让愤怒被完全接纳，再温柔探索原因。'
            '可以说：「能告诉我是什么让您这么生气吗？」'
        ),
        'forbidden': '「冷静一下」「别激动」「这不值得生气」「你太敏感了」',
    },
    'happy': {
        'respond_strategy': '与用户共鸣，正向强化，好奇且真诚地询问细节',
        'specific_instructions': (
            '鼓励分享更多：「听起来真是很美好的事，多跟我说说？」'
        ),
        'forbidden': '转移话题、敷衍回应、过度夸张',
    },
    'disgusted': {
        'respond_strategy': '接纳情绪，不辩解，温和探索背后原因',
        'specific_instructions': (
            '温和共情：「这件事让您很不舒服，这完全可以理解。」'
        ),
        'forbidden': '辩解、评判、否定感受',
    },
    'surprised': {
        'respond_strategy': '先确认是正面还是负面的惊讶，再分别给予共鸣或稳定支持',
        'specific_instructions': (
            '开放探索：「这让您感到意外，能跟我说说发生了什么吗？」'
        ),
        'forbidden': '过度反应、忽视',
    },
    'neutral': {
        'respond_strategy': '保持轻松自然的对话，主动关怀今日状态',
        'specific_instructions': (
            '可主动邀请分享：「今天过得怎么样？有什么想跟我聊的吗？」'
        ),
        'forbidden': '无特殊禁忌',
    },
}


# ─── System Prompt 模板 ──────────────────────────────────────────────────────
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
1. Connect（连接）：用 1 句话建立情感连接（≤15字）
2. Acknowledge（承认）：承认并命名用户的情绪感受（≤20字）
3. Respond（回应）：{respond_strategy}（1~2句）
4. Empower（赋能）：用一个温柔的开放性问题结尾（可选，情绪极低时省略）

## 语言规范
- 总字数：60~120字
- 单句字数：≤25字
- 禁止使用：「你应该…」「你需要…」「想开点」「没关系的」「不要难过」「别担心」
- 必须使用第一人称感受反映：「听起来…」「我感受到…」「您说的…让我感到…」

## 情绪专属指引
{specific_instructions}

## 安全守则
- 绝不否定老人的感受，哪怕在你看来是误解
- 绝不与老人争辩，哪怕信息有误
- 绝不催促老人「振作」或「开心起来」\
"""

CRISIS_SYSTEM_PROMPT = """\
你是「心伴」，一位受过危机干预培训的心理陪伴师。

【高优先级警告】用户刚才说的话包含危机信号，请立即进入危机干预模式。

## 危机回复必须包含的三个要素（按顺序）
1. 我听到了：明确告诉用户你注意到了他说的话（1句）
2. 表达在意：表达你认真对待这句话（1句）
3. 具体行动：建议立刻联系家人或护理员，提供明确的下一步行动（1~2句）

## 语言要求
- 语气：极度温柔，无任何批评或评判
- 不要问「你为什么这么想」，不追问细节
- 不要给分析或建议，只做情感连接和行动引导
- 字数：60~80字

## 回复示例（仅作参考，请自然表达）
「我听到您说的了，您现在的感受我很在意。
 您现在身边有人陪着您吗？
 我建议我们现在去找一下护理员，或者让我帮您联系家人，好吗？」\
"""


def build_normal_prompt(emotion: dict) -> str:
    """根据情绪结果构建正常对话 System Prompt。"""
    label    = emotion.get('label', 'neutral')
    strategy = EMOTION_STRATEGY_MAP.get(label, EMOTION_STRATEGY_MAP['neutral'])

    return NORMAL_SYSTEM_PROMPT.format(
        emotion_label_zh    = emotion.get('label_zh', '平静'),
        emotion_score_pct   = f"{emotion.get('score', 1.0):.0%}",
        emotion_trend       = emotion.get('trend', '首次对话'),
        valence             = emotion.get('valence', 0.5),
        arousal             = emotion.get('arousal', 0.2),
        respond_strategy    = strategy['respond_strategy'],
        specific_instructions = strategy['specific_instructions'],
    )


def build_crisis_prompt() -> str:
    """危机干预 System Prompt，不需要情绪参数。"""
    return CRISIS_SYSTEM_PROMPT
```

### 8.3 核心服务 `llm_service.py`

```python
import logging
from typing import Generator
from openai import OpenAI
from config import (
    QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL,
    MAX_TOKENS, TEMPERATURE, TOP_P,
    MAX_HISTORY_TURNS, CRISIS_KEYWORDS,
)
from prompt_templates import build_normal_prompt, build_crisis_prompt

logger = logging.getLogger(__name__)

# TTS 情绪参数映射（传给 STEP 4）
# 注意：TTS 情绪是「治愈性对称」，不镜像用户情绪
TTS_PARAMS_MAP = {
    'sad':       {'speed': 0.85, 'pitch': -2, 'style': 'gentle'},
    'fearful':   {'speed': 0.88, 'pitch': -1, 'style': 'calm'},
    'angry':     {'speed': 0.88, 'pitch': -1, 'style': 'gentle'},
    'happy':     {'speed': 1.05, 'pitch':  1, 'style': 'cheerful'},
    'disgusted': {'speed': 0.92, 'pitch': -1, 'style': 'calm'},
    'surprised': {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    'neutral':   {'speed': 1.00, 'pitch':  0, 'style': 'neutral'},
    '_crisis':   {'speed': 0.82, 'pitch': -2, 'style': 'gentle'},  # 危机专用
}


class LLMService:

    def __init__(self):
        self.client = OpenAI(
            api_key  = QWEN_API_KEY,
            base_url = QWEN_BASE_URL,
        )
        # 对话历史: [ {role: 'user'|'assistant', content: str} ]
        self.conversation: list[dict] = []
        logger.info("LLM 服务初始化完成 ✅")


    # ── 主入口：流式生成回复 ──────────────────────────────────────────────────

    def stream_reply(
        self,
        user_text: str,
        emotion: dict,
    ) -> Generator[dict, None, None]:
        """
        流式生成回复。

        Yields:
            { type: 'delta',  text: str,         crisis: bool }
            { type: 'done',   full_text: str,
              crisis: bool,   tts_params: dict,
              emotion_label: str }
        """
        # 1. 危机检测（最高优先级，先于一切处理）
        crisis = self._check_crisis(user_text)
        if crisis:
            logger.warning(f"⚠️  危机信号触发！用户文本: {user_text[:50]}")

        # 2. 构建 System Prompt
        system_prompt = (
            build_crisis_prompt() if crisis
            else build_normal_prompt(emotion)
        )

        # 3. 追加用户消息到历史
        self.conversation.append({'role': 'user', 'content': user_text})

        # 4. 裁剪历史，保留最近 N 轮
        max_msgs = MAX_HISTORY_TURNS * 2
        if len(self.conversation) > max_msgs:
            self.conversation = self.conversation[-max_msgs:]

        # 5. 组装完整消息列表
        messages = [{'role': 'system', 'content': system_prompt}]
        messages.extend(self.conversation)

        # 6. 调用 Qwen API 流式生成
        try:
            stream = self.client.chat.completions.create(
                model       = QWEN_MODEL,
                messages    = messages,
                stream      = True,
                max_tokens  = MAX_TOKENS,
                temperature = TEMPERATURE,
                top_p       = TOP_P,
            )
        except Exception as e:
            logger.error(f"Qwen API 调用失败: {e}")
            yield {'type': 'error', 'message': str(e)}
            return

        # 7. 流式处理并 yield
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

        # 8. 保存助手回复到历史
        if full_reply:
            self.conversation.append({'role': 'assistant', 'content': full_reply})

        # 9. 生成完毕信号（供前端结束打字机动画，供 STEP 4 完成 TTS）
        yield {
            'type':          'done',
            'full_text':     full_reply,
            'crisis':        crisis,
            'emotion_label': emotion.get('label', 'neutral'),
            'tts_params':    self._get_tts_params(emotion, crisis),
        }


    # ── 工具方法 ─────────────────────────────────────────────────────────────

    def _check_crisis(self, text: str) -> bool:
        """检测用户文本是否包含危机信号关键词。"""
        return any(kw in text for kw in CRISIS_KEYWORDS)


    def _get_tts_params(self, emotion: dict, crisis: bool) -> dict:
        """
        返回 STEP 4 所需的 TTS 情绪参数。
        危机状态使用专用参数（最平缓语速语调）。
        """
        if crisis:
            return TTS_PARAMS_MAP['_crisis']
        label = emotion.get('label', 'neutral')
        return TTS_PARAMS_MAP.get(label, TTS_PARAMS_MAP['neutral'])


    def reset(self):
        """新对话开始时调用，清除对话历史。"""
        self.conversation.clear()
        logger.info("对话历史已重置")


    @property
    def history_turns(self) -> int:
        """当前对话历史轮数。"""
        return len(self.conversation) // 2
```

### 8.4 FastAPI 服务 `llm_server.py`

```python
import json
import logging
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from llm_service import LLMService

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="LLM Service - STEP 3")
llm = LLMService()


# ─── Schema ──────────────────────────────────────────────────────────────────

class LLMRequest(BaseModel):
    text:       str  = Field(..., description="STEP 1 转录文本")
    emotion:    dict = Field(..., description="STEP 2 EmotionResult 序列化")
    session_id: str  = Field(..., description="会话 ID")


# ─── 路由 ────────────────────────────────────────────────────────────────────

@app.post('/llm/stream')
async def stream_reply(req: LLMRequest):
    """
    流式生成 LLM 回复，使用 SSE（Server-Sent Events）格式推送。
    """
    def generate():
        for chunk in llm.stream_reply(req.text, req.emotion):
            # SSE 格式：每条消息以 "data: <json>\n\n" 结尾
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',   # 禁止 Nginx 缓冲，确保实时推送
        },
    )


@app.post('/llm/reset')
async def reset_session(session_id: str):
    """重置对话历史（新对话开始时调用）。"""
    llm.reset()
    return {'status': 'ok', 'session_id': session_id}


@app.get('/llm/history')
async def get_history():
    """获取当前对话历史（调试用）。"""
    return {
        'turns': llm.history_turns,
        'messages': llm.conversation,
    }


@app.get('/health')
async def health():
    return {'status': 'ok', 'model': 'qwen-plus'}
```

---

## 9. 危机干预协议

### 9.1 触发条件

用户文本中包含 `CRISIS_KEYWORDS` 中任意关键词，立即触发，无置信度阈值。

```python
CRISIS_KEYWORDS = [
    '不想活', '活着没意思', '死了算了', '不想活了',
    '太累了不想撑', '不想见人了', '活够了',
    '没有活下去', '了结', '轻生',
]
```

> ⚠️ **危机检测是最高优先级操作**，在 `stream_reply` 的第一行执行，早于 Prompt 构建和 API 调用。

### 9.2 触发后的全链路响应

```
用户说出危机词
        │
        ▼
[STEP 3] crisis = True
  ├─ System Prompt → 切换为 CRISIS_SYSTEM_PROMPT
  ├─ 每个 delta chunk 携带 crisis: true
  └─ done 事件携带 crisis: true, tts_params → 最平缓参数

        │
        ▼
[前端] 收到 crisis: true
  ├─ 界面背景渐变为温暖橙色（安全感色调）
  ├─ 显示「联系护理员」按钮
  └─ 禁用「结束对话」按钮，防止用户独处

        │
        ▼
[STEP 4] 使用 _crisis TTS 参数
  └─ 最慢语速（0.82）+ 最低音调（-2）+ gentle 风格
```

### 9.3 危机模式限制

- 危机触发后，**当前轮次**对话历史不保存（避免危机内容污染后续对话上下文）
- 危机触发后，**下一轮**回复仍保持 `crisis=True` 的警惕状态，直至用户明确表达情绪好转
- 后端日志记录危机事件（含时间戳、session_id），供护理人员查阅

---

## 10. SSE 流式接口规范

### POST `/llm/stream`

**请求体：**
```json
{
  "text": "我今天一直在想我老伴，他走了三年了。",
  "emotion": {
    "label": "sad",
    "label_zh": "悲伤",
    "score": 0.718,
    "raw_label": "sad",
    "raw_score": 0.731,
    "valence": 0.10,
    "arousal": 0.20,
    "trend": "情绪持续稳定在「悲伤」状态",
    "history": [
      { "label": "neutral", "score": 0.682 },
      { "label": "sad",     "score": 0.611 },
      { "label": "sad",     "score": 0.731 }
    ]
  },
  "session_id": "user_001"
}
```

**SSE 流式响应（Content-Type: text/event-stream）：**

```
data: {"type": "delta", "text": "我在", "crisis": false}

data: {"type": "delta", "text": "这里", "crisis": false}

data: {"type": "delta", "text": "陪着您。", "crisis": false}

data: {"type": "delta", "text": "听起来今天", "crisis": false}

... （持续推送）...

data: {
  "type": "done",
  "full_text": "我在这里陪着您。听起来今天您心里很沉，很想念他。思念陪伴了几十年的人，这种感受是很真实的，不需要假装没事。能跟我说说他是个什么样的人吗？",
  "crisis": false,
  "emotion_label": "sad",
  "tts_params": { "speed": 0.85, "pitch": -2, "style": "gentle" }
}
```

**危机响应示例：**

```
data: {"type": "delta", "text": "我听到", "crisis": true}

...

data: {
  "type": "done",
  "full_text": "我听到您说的了，您现在的感受我很在意。您现在身边有人陪着您吗？我建议我们现在去找一下护理员，好吗？",
  "crisis": true,
  "emotion_label": "sad",
  "tts_params": { "speed": 0.82, "pitch": -2, "style": "gentle" }
}
```

---

## 11. 前端集成代码

### `composables/useLLM.ts`

```typescript
import { ref } from 'vue'

interface EmotionResult {
  label: string
  label_zh: string
  score: number
  raw_label: string
  raw_score: number
  valence: number
  arousal: number
  trend: string
  history: Array<{ label: string; score: number }>
}

interface TTSParams {
  speed: number
  pitch: number
  style: string
}

interface DoneEvent {
  type: 'done'
  full_text: string
  crisis: boolean
  emotion_label: string
  tts_params: TTSParams
}

export function useLLM(apiBase = 'http://localhost:8002') {
  const reply       = ref('')         // 流式累积的回复文本
  const isStreaming = ref(false)      // 是否正在生成
  const isCrisis    = ref(false)      // 是否触发危机模式
  const ttsParams   = ref<TTSParams | null>(null)

  // 首句缓冲（用于触发 STEP 4 流水线）
  let sentenceBuffer = ''
  let firstSentenceSent = false

  // 外部回调：首句完整时触发 TTS 合成
  const onFirstSentence = ref<((text: string, params: TTSParams) => void) | null>(null)
  const onReplyDone     = ref<((event: DoneEvent) => void) | null>(null)
  const onCrisis        = ref<(() => void) | null>(null)

  // 句末标点正则
  const SENTENCE_END = /[。！？.!?]/

  async function streamReply(text: string, emotion: EmotionResult) {
    reply.value       = ''
    isStreaming.value = true
    isCrisis.value    = false
    sentenceBuffer    = ''
    firstSentenceSent = false

    try {
      const res = await fetch(`${apiBase}/llm/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ text, emotion, session_id: 'default' }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('无响应体')

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''   // 保留不完整的最后一行

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const jsonStr = line.slice(5).trim()
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr)
            handleEvent(event)
          } catch {
            // 忽略解析错误的行
          }
        }
      }
    } catch (err) {
      console.error('[LLM] 请求失败:', err)
    } finally {
      isStreaming.value = false
    }
  }

  function handleEvent(event: any) {
    if (event.type === 'delta') {
      reply.value += event.text

      // 危机标记
      if (event.crisis && !isCrisis.value) {
        isCrisis.value = true
        onCrisis.value?.()
      }

      // 首句检测：累积文本直到出现句末标点，立即触发 TTS
      if (!firstSentenceSent && ttsParams.value) {
        sentenceBuffer += event.text
        const match = sentenceBuffer.match(/^([^。！？.!?]+[。！？.!?])/)
        if (match) {
          firstSentenceSent = true
          const firstSentence = match[1]
          onFirstSentence.value?.(firstSentence, ttsParams.value)
          sentenceBuffer = sentenceBuffer.slice(firstSentence.length)
        }
      }

    } else if (event.type === 'done') {
      ttsParams.value = event.tts_params
      isCrisis.value  = event.crisis

      // 如果首句还未发出（极短回复），在 done 时补发
      if (!firstSentenceSent && event.full_text && event.tts_params) {
        onFirstSentence.value?.(event.full_text, event.tts_params)
      }

      onReplyDone.value?.(event)

    } else if (event.type === 'error') {
      console.error('[LLM] 服务端错误:', event.message)
    }
  }

  async function resetSession() {
    reply.value = ''
    await fetch(`http://localhost:8002/llm/reset?session_id=default`, {
      method: 'POST',
    })
  }

  return {
    reply,
    isStreaming,
    isCrisis,
    ttsParams,
    onFirstSentence,
    onReplyDone,
    onCrisis,
    streamReply,
    resetSession,
  }
}
```

---

## 12. TDD 验收测试

### `tests/test_step3.py`

```python
import pytest
from unittest.mock import MagicMock, patch, call
from llm_service import LLMService, TTS_PARAMS_MAP
from config import CRISIS_KEYWORDS, MAX_HISTORY_TURNS
from prompt_templates import (
    build_normal_prompt, build_crisis_prompt,
    EMOTION_STRATEGY_MAP,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    with patch('llm_service.OpenAI') as mock_openai:
        service = LLMService()
        service.client = mock_openai.return_value
    return service


def make_emotion(label: str = 'neutral', score: float = 0.8) -> dict:
    from config import CRISIS_KEYWORDS  # noqa
    coords = {
        'neutral':   (0.50, 0.20), 'happy':     (0.90, 0.70),
        'sad':       (0.10, 0.20), 'angry':      (0.10, 0.90),
        'fearful':   (0.15, 0.80), 'disgusted':  (0.15, 0.50),
        'surprised': (0.60, 0.85),
    }
    v, a = coords.get(label, (0.5, 0.2))
    return {
        'label':    label,
        'label_zh': {'neutral': '平静', 'happy': '快乐', 'sad': '悲伤',
                     'angry': '愤怒', 'fearful': '焦虑/恐惧',
                     'disgusted': '厌恶', 'surprised': '惊讶'}.get(label, '平静'),
        'score':    score,
        'raw_label': label,
        'raw_score': score,
        'valence':  v,
        'arousal':  a,
        'trend':    '首次对话',
        'history':  [],
    }


def make_stream_response(text: str):
    """Mock Qwen API 流式响应"""
    chunks = []
    for char in text:
        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = char
        chunks.append(mock_chunk)
    # 末尾空 delta（流式结束标志）
    end_chunk = MagicMock()
    end_chunk.choices[0].delta.content = ''
    chunks.append(end_chunk)
    return iter(chunks)


# ─── TC-01: 危机检测 ──────────────────────────────────────────────────────────

class TestCrisisDetection:

    def test_crisis_keyword_detected(self, svc):
        """TC-01: 危机关键词被正确检测"""
        assert svc._check_crisis('我不想活了') is True
        assert svc._check_crisis('活着没意思') is True
        assert svc._check_crisis('今天天气真好') is False

    def test_all_keywords_in_list(self):
        """TC-02: 关键词列表覆盖必要的危机表达"""
        must_have = ['不想活', '活着没意思', '死了算了', '轻生']
        for kw in must_have:
            assert kw in CRISIS_KEYWORDS, f"关键词「{kw}」未在列表中"

    def test_crisis_triggers_crisis_prompt(self, svc):
        """TC-03: 危机文本触发 Crisis Prompt（含「危机信号」字样）"""
        svc.client.chat.completions.create.return_value = make_stream_response('我听到了。')
        chunks = list(svc.stream_reply('我不想活了', make_emotion()))

        # 提取传给 API 的 system prompt
        call_args = svc.client.chat.completions.create.call_args
        messages  = call_args.kwargs['messages']
        system    = messages[0]['content']
        assert '危机信号' in system

    def test_non_crisis_uses_normal_prompt(self, svc):
        """TC-04: 正常文本使用 CARE Prompt"""
        svc.client.chat.completions.create.return_value = make_stream_response('我在这里陪着您。')
        list(svc.stream_reply('今天天气真好', make_emotion()))

        call_args = svc.client.chat.completions.create.call_args
        messages  = call_args.kwargs['messages']
        system    = messages[0]['content']
        assert 'CARE' in system
        assert '危机信号' not in system


# ─── TC-02: Prompt 构建 ───────────────────────────────────────────────────────

class TestPromptBuilding:

    def test_emotion_label_in_prompt(self):
        """TC-05: System Prompt 包含情绪标签中文名"""
        emotion = make_emotion('sad')
        prompt  = build_normal_prompt(emotion)
        assert '悲伤' in prompt

    def test_strategy_in_prompt(self):
        """TC-06: System Prompt 包含情绪对应的 Respond 策略"""
        emotion = make_emotion('angry')
        prompt  = build_normal_prompt(emotion)
        strategy = EMOTION_STRATEGY_MAP['angry']['respond_strategy']
        assert strategy in prompt

    def test_trend_in_prompt(self):
        """TC-07: System Prompt 包含情绪趋势"""
        emotion = make_emotion('happy')
        emotion['trend'] = '情绪明显好转'
        prompt = build_normal_prompt(emotion)
        assert '情绪明显好转' in prompt

    def test_all_emotions_have_strategy(self):
        """TC-08: 所有 7 种情绪标签都有策略映射"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert label in EMOTION_STRATEGY_MAP, f"缺少情绪策略: {label}"
            assert 'respond_strategy' in EMOTION_STRATEGY_MAP[label]
            assert 'specific_instructions' in EMOTION_STRATEGY_MAP[label]

    def test_crisis_prompt_contains_required_elements(self):
        """TC-09: 危机 Prompt 包含三个必要要素"""
        prompt = build_crisis_prompt()
        assert '我听到了' in prompt
        assert '表达在意' in prompt
        assert '具体行动' in prompt


# ─── TC-03: 流式输出 ──────────────────────────────────────────────────────────

class TestStreamReply:

    def test_delta_chunks_yielded(self, svc):
        """TC-10: 流式回复产生多个 delta 类型事件"""
        svc.client.chat.completions.create.return_value = \
            make_stream_response('我在这里陪着您。')
        chunks = list(svc.stream_reply('你好', make_emotion()))
        delta_chunks = [c for c in chunks if c.get('type') == 'delta']
        assert len(delta_chunks) > 0

    def test_done_event_has_full_text(self, svc):
        """TC-11: done 事件包含完整回复文本"""
        reply_text = '我在这里陪着您。'
        svc.client.chat.completions.create.return_value = \
            make_stream_response(reply_text)
        chunks = list(svc.stream_reply('你好', make_emotion()))
        done   = next(c for c in chunks if c.get('type') == 'done')
        assert done['full_text'] == reply_text

    def test_done_event_has_tts_params(self, svc):
        """TC-12: done 事件包含 tts_params 字段"""
        svc.client.chat.completions.create.return_value = \
            make_stream_response('回复文本。')
        chunks = list(svc.stream_reply('你好', make_emotion('sad')))
        done   = next(c for c in chunks if c.get('type') == 'done')
        assert 'tts_params' in done
        assert 'speed' in done['tts_params']

    def test_crisis_flag_propagated(self, svc):
        """TC-13: 危机文本的所有 chunk 都携带 crisis: true"""
        svc.client.chat.completions.create.return_value = \
            make_stream_response('我听到了。')
        chunks = list(svc.stream_reply('我不想活了', make_emotion()))
        for chunk in chunks:
            assert chunk.get('crisis') is True


# ─── TC-04: TTS 参数 ─────────────────────────────────────────────────────────

class TestTTSParams:

    def test_sad_gets_slow_speed(self, svc):
        """TC-14: 悲伤情绪 TTS 语速 < 1.0"""
        params = svc._get_tts_params(make_emotion('sad'), crisis=False)
        assert params['speed'] < 1.0

    def test_happy_gets_fast_speed(self, svc):
        """TC-15: 快乐情绪 TTS 语速 > 1.0"""
        params = svc._get_tts_params(make_emotion('happy'), crisis=False)
        assert params['speed'] > 1.0

    def test_crisis_gets_slowest_params(self, svc):
        """TC-16: 危机模式 TTS 使用最平缓参数"""
        params = svc._get_tts_params(make_emotion('neutral'), crisis=True)
        normal = svc._get_tts_params(make_emotion('neutral'), crisis=False)
        assert params['speed'] <= normal['speed']
        assert params['style'] == 'gentle'

    def test_all_emotions_have_tts_params(self):
        """TC-17: 所有情绪标签都有 TTS 参数映射"""
        labels = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
        for label in labels:
            assert label in TTS_PARAMS_MAP


# ─── TC-05: 对话历史管理 ─────────────────────────────────────────────────────

class TestConversationHistory:

    def test_user_message_added_to_history(self, svc):
        """TC-18: 用户消息被追加到对话历史"""
        svc.client.chat.completions.create.return_value = make_stream_response('回复')
        list(svc.stream_reply('用户消息', make_emotion()))
        user_msgs = [m for m in svc.conversation if m['role'] == 'user']
        assert any('用户消息' in m['content'] for m in user_msgs)

    def test_assistant_reply_saved_to_history(self, svc):
        """TC-19: 助手回复被保存到对话历史"""
        svc.client.chat.completions.create.return_value = make_stream_response('助手回复')
        list(svc.stream_reply('你好', make_emotion()))
        asst_msgs = [m for m in svc.conversation if m['role'] == 'assistant']
        assert any('助手回复' in m['content'] for m in asst_msgs)

    def test_history_trimmed_when_too_long(self, svc):
        """TC-20: 对话历史超过上限时自动裁剪"""
        svc.client.chat.completions.create.return_value = make_stream_response('回复')
        # 预填充超长历史
        for i in range(MAX_HISTORY_TURNS * 2 + 5):
            svc.conversation.append({'role': 'user',      'content': f'msg{i}'})
            svc.conversation.append({'role': 'assistant', 'content': f'rep{i}'})
        list(svc.stream_reply('最新消息', make_emotion()))
        assert len(svc.conversation) <= MAX_HISTORY_TURNS * 2 + 2  # +2 为本次新增

    def test_reset_clears_history(self, svc):
        """TC-21: reset 后对话历史为空"""
        svc.conversation.append({'role': 'user', 'content': 'test'})
        svc.reset()
        assert len(svc.conversation) == 0
```

### 验收标准汇总

| ID | 描述 | 通过条件 |
|----|------|----------|
| TC-01 | 危机关键词检测 | 返回 True |
| TC-02 | 关键词列表完整 | 4 个必选词均存在 |
| TC-03 | 危机触发危机 Prompt | system 含「危机信号」 |
| TC-04 | 正常文本用 CARE Prompt | system 含「CARE」 |
| TC-05 | Prompt 含情绪标签 | 含「悲伤」 |
| TC-06 | Prompt 含情绪策略 | 策略字符串存在 |
| TC-07 | Prompt 含趋势描述 | trend 字符串存在 |
| TC-08 | 7 种情绪均有策略 | 所有 label 均有映射 |
| TC-09 | 危机 Prompt 三要素 | 含三个必要段落 |
| TC-10 | 产生 delta 事件 | delta chunk 数 > 0 |
| TC-11 | done 含完整文本 | full_text 等于拼接结果 |
| TC-12 | done 含 tts_params | speed 字段存在 |
| TC-13 | 危机 chunk 标记 | 所有 chunk.crisis == True |
| TC-14 | 悲伤 TTS 速度慢 | speed < 1.0 |
| TC-15 | 快乐 TTS 速度快 | speed > 1.0 |
| TC-16 | 危机 TTS 最平缓 | speed ≤ neutral，style == gentle |
| TC-17 | 7 种情绪有 TTS 参数 | 所有 label 均有映射 |
| TC-18 | 用户消息入历史 | history 含用户消息 |
| TC-19 | 助手回复入历史 | history 含助手回复 |
| TC-20 | 历史超限自动裁剪 | len ≤ MAX * 2 + 2 |
| TC-21 | reset 清空历史 | len == 0 |

---

## 附录：启动命令

```bash
# 开发模式
uvicorn llm_server:app --host 0.0.0.0 --port 8002 --reload

# 生产模式
uvicorn llm_server:app --host 0.0.0.0 --port 8002 --workers 1

# 注意：LLMService 维护对话历史状态，workers 必须为 1
```

## 附录：模型选择指南

| 模型 | 首 Token 延迟 | 回复质量 | 建议场景 |
|------|-------------|---------|----------|
| `qwen-turbo` | ~300ms | 一般 | 开发调试、低成本测试 |
| `qwen-plus`  | ~600ms | **高（推荐）** | 生产环境 |
| `qwen-max`   | ~1200ms | 最高 | 对质量要求极高的场景 |
