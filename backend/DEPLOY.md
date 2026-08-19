# 部署到 47.253.82.38

流程：本机 `docker build` → `docker save` 打包成 tar → `scp` 传到服务器 → 服务器上
`docker load` + `docker compose up`。镜像本身不含模型权重和运行时数据（见下），
所以传的镜像包不大；模型权重单独传一次即可，以后升级镜像不用重传。

## 0. 前提

- 服务器已装 Docker（`docker --version` 能跑），装了 `docker compose` 插件
- ⚠️ **不要跑 `docker compose config`**：它会把 `env_file` 指向的 `.env` 全部展开
  明文打印到终端（本仓库调试时就这么把真实密钥打进过对话记录）。要看 compose 是否
  解析对了，直接看 `docker-compose.yml` 源文件即可，不需要跑这条命令。
- 服务器 8050 端口对公网开放（云服务商安全组 + 系统防火墙都要放行）
- 本机能 SSH 到服务器：`ssh user@47.253.82.38`

## 1. 本机构建镜像

```bash
cd backend
docker build -t agetalker-backend:latest .
```

第一次构建要装 CPU 版 torch，视网速可能要几分钟到十几分钟。

## 2. 打包成 tar 并传到服务器

Windows 默认终端是 PowerShell，没有 `gzip` 命令，`docker save ... | gzip > ...` 这种写法
会静默失败（管道另一头没东西接，`docker save` 就想往终端里吐二进制，报
`cowardly refusing to save to a terminal`）。按你用的终端二选一：

**PowerShell（不压缩，简单，包大一些）：**

```powershell
docker save -o agetalker-backend.tar agetalker-backend:latest

# 换成你的服务器用户名和实际路径
scp agetalker-backend.tar docker-compose.yml .env user@47.253.82.38:/opt/agetalker/
```

**Git Bash（压缩，包小，多一步）：**

```bash
docker save agetalker-backend:latest | gzip > agetalker-backend.tar.gz

scp agetalker-backend.tar.gz docker-compose.yml .env user@47.253.82.38:/opt/agetalker/
```

两种对应地服务器上 `docker load` 的命令不一样，见第 4 步。

`.env` 里是 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY`，走 scp 传等于明文过一次网络，
如果不放心可以到服务器上再手写这个文件，不传这一份。

## 3. 模型权重（只需做一次）

`.model_cache/`（ASR + VAD + 标点 + emotion2vec，约 3.9G）没有打进镜像，也没进 git，
服务器要能跑起来必须有这份目录，二选一：

**方案 A：本机已有缓存，直接传（推荐，快）**

```bash
# 本机 backend/.model_cache 已经存在（正常开发过就会有）
tar czf model_cache.tar.gz -C backend .model_cache
scp model_cache.tar.gz user@47.253.82.38:/opt/agetalker/
# 服务器上解压到 /opt/agetalker/.model_cache/
ssh user@47.253.82.38 'cd /opt/agetalker && tar xzf model_cache.tar.gz'
```

**方案 B：服务器自己联网下载**

`config.py` 的 `_local_or_hub()` 检测到 `.model_cache/` 不存在时会自动从 ModelScope
下载。前提是服务器能连外网（连不上境外/需要代理的模型源就会卡住）。第一次
`docker compose up` 之后会卡在下载上，等它跑完（可能十几分钟到几十分钟，取决于
服务器带宽），后续重启就不再下载。

## 4. 服务器上启动

```bash
ssh user@47.253.82.38
cd /opt/agetalker

# 传的是 .tar（PowerShell -o 那种）：
docker load -i agetalker-backend.tar
# 传的是 .tar.gz（Git Bash 那种）：
gunzip -c agetalker-backend.tar.gz | docker load

docker compose up -d
```

`docker-compose.yml` 里把 `./data` 和 `./.model_cache` 挂载成 volume，容器重建/升级
镜像时这两块不会丢。

## 5. 验证

```bash
curl http://47.253.82.38:8050/health
docker compose logs -f    # 看启动日志，尤其第一次要确认模型加载没报错
```

浏览器也能直接开 `http://47.253.82.38:8050/health` 看。

## 升级镜像（改了后端代码之后）

重复第 1、2、4 步（不用再传模型权重和 `.env`）。PowerShell 版：

```powershell
# 本机
cd backend
docker build -t agetalker-backend:latest .
docker save -o agetalker-backend.tar agetalker-backend:latest
scp agetalker-backend.tar user@47.253.82.38:/opt/agetalker/
```

```bash
# 服务器
ssh user@47.253.82.38
cd /opt/agetalker
docker load -i agetalker-backend.tar
docker compose up -d    # 会用新镜像重建容器，volume 里的数据不受影响
```

## 已知限制 / 待办

- `main.py` 里 CORS 是 `allow_origins=["*"]`——现在这个部署面向外网，之后如果要收紧
  建议改成只放行 App 实际用到的来源，或者干脆去掉浏览器跨域这层（App 不受 CORS
  限制，只有网页端调试会用到）。
- 服务是 `http://`，没上 TLS。Android 9+ 默认拒绝明文流量，APK 那边已经单独配置
  白名单允许连这个 IP（见 `mobile/DEPLOY.md`），但这终究是明文传输，生产环境建议
  上个反向代理（Nginx/Caddy）+ 证书。
