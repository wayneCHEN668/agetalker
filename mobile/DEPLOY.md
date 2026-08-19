# 打包 APK（EAS Build）

前提：后端已经按 `backend/DEPLOY.md` 部署在 `http://47.253.82.38:8050` 并且
`curl http://47.253.82.38:8050/health` 能通——APK 里的地址是编译时写死的，后端没起来
先打包也没意义，调不通还得重打一遍。

## 已经改好的部分

- `constants/Api.ts`：后端地址唯一来源，已指向 `47.253.82.38:8050`。要换地址
  改这一个文件就行。
- `app.json`：加了 `android.package`（`com.agetalker.mobile`，EAS 构建必须有）
  和 `expo-build-properties` 插件，开了 `usesCleartextTraffic`——服务器现在是
  明文 `http://`，不开这个 Android 9+ 会直接拒连（见文末说明）。
- `eas.json`：`preview` 配置产出 `.apk`（EAS 默认产出 `.aab`，Google Play 用的格式，
  手机装不了，测试要显式指定 `buildType: apk`）。

## 打包步骤

```bash
cd mobile
npx eas login              # 用你的 Expo 账号登录，没有就去 expo.dev 免费注册一个
npx eas build:configure    # 第一次跑，把项目和你的 Expo 账号关联，会问几个问题按默认选就行
npx eas build -p android --profile preview
```

`build:configure` 之后 `app.json` 里会多出一个 `extra.eas.projectId` 字段，属于正常产出，
不用管。

构建在 Expo 云端跑，免费额度通常够偶尔打包用，几分钟到十几分钟不等。跑完终端会
给一个下载链接（也能在 https://expo.dev 的项目页面里看到），手机直接用浏览器打开
那个链接下载 apk，或者用下面命令把下载链接转成二维码在电脑上扫：

```bash
npx eas build:list --platform android --limit 1
```

## 手机安装

1. 手机设置里允许"安装未知来源应用"（不同手机厂商路径不一样，一般在"应用管理"
   或安装时系统会弹窗引导）
2. 下载 apk 直接点开安装

## 关于明文 HTTP

服务器现在没有 TLS 证书，是 `http://`。Android 9（API 28）起系统默认拒绝 App
发起明文网络请求，`expo-build-properties` 里的 `usesCleartextTraffic: true` 是全局
放开这个限制——够用于测试，但这意味着这个 APK 对任何域名的明文请求都不拦截，
不是只放行这一个 IP。如果之后要发正式版，建议给服务器配个反向代理
（Nginx/Caddy）挂证书，改回 `https://`，再把这个开关关掉。

## 改后端地址之后

改 `constants/Api.ts` 里的 `API_HOST`/`API_PORT`，重新走一遍打包步骤——地址是
编译时打进 apk 里的，不是运行时读的，改完必须重新构建、重新安装到手机上。
