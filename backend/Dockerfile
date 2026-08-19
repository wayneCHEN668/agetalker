# AgeTalker 后端镜像。CPU 推理（ASR + emotion2vec），LLM/TTS 走 API，不需要 GPU。
FROM python:3.11-slim

# funasr/torchaudio 运行时依赖：libsndfile 解码音频，ffmpeg 兜底格式转换
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，再拷代码：requirements.txt 不变时这层能命中缓存，改代码不用重装 torch
#
# requirements.txt 里 `torch --index-url https://download.pytorch.org/whl/cpu` 这种写法
# 在 pip 里不是"给这一行指定索引"的语法——pip 只认整份 requirements 文件级别的
# --index-url，写在某一行后面会被忽略。本机 venv 装成 CPU 版是巧合（Windows 默认
# 索引没有匹配的 CUDA wheel），Linux 镜像里不吭声就会连 CUDA 运行时一起装（数 GB，
# 且这台机器根本没 GPU）。这里显式分两步：先按 CPU 索引装 torch/torchaudio，
# requirements.txt 里那两行版本已满足就会被跳过，不会被 CUDA 版覆盖。
COPY requirements.txt .
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# .model_cache/（~3.9G 模型权重）和 data/（运行时数据，含真实用户信息）都不打进镜像，
# 见 .dockerignore；部署时用 volume 挂载，见 docker-compose.yml
# .env（DASHSCOPE_API_KEY 等密钥）同理，不 COPY 进镜像，用 --env-file 在运行时注入

EXPOSE 8050

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8050"]
