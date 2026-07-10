# 国际飞书（Larksuite）SSO 配置说明

本文档对应 SQLBot 开源自研实现（`type=9`），流程参考 [官方平台对接 - 飞书设置](https://dataease.cn/sqlbot/v1/X-Pack/platform_integration/#3)，但应用需在 **Lark 国际开放平台** 创建。

## 1. 开放平台创建应用

1. 登录 [https://open.larksuite.com](https://open.larksuite.com)（非 feishu.cn）。
2. 创建企业自建应用，记录 **App ID（APP Key）** 与 **App Secret**。
3. 添加 **网页应用**，桌面端主页填写 SQLBot 访问地址，例如：
   - `https://sqlbot.example.com/`
4. **安全设置 → 重定向 URL**：与 SQLBot 配置中的 `Redirect URI` 完全一致（含路径前缀、末尾斜杠）。
5. **权限管理**：至少开通登录与用户身份相关权限（如 `contact:user.base` 等，以开放平台当前列表为准）。
6. **版本管理与发布**：创建版本并发布应用。

## 2. SQLBot 侧配置

路径：**系统管理 → 平台集成 → 国际飞书**

| 字段 | 说明 |
|------|------|
| APP Key | 开放平台 App ID |
| APP Secret | 开放平台 App Secret |
| Redirect URI | 用户访问 SQLBot 的 origin+path，如 `https://sqlbot.example.com/` |
| Auto Create User | `true` / `false`；`false` 时须先在用户管理同步/创建并绑定飞书用户 |
| Default Workspace ID | 自动创建用户时写入的默认工作空间 `oid` |

保存后点击 **检测**，状态为 **有效** 后再 **开启**。

## 3. 登录方式

### 3.1 扫码登录

登录页 **其他登录方式 → 国际飞书**，使用飞书扫码 SDK（`passport.larksuite.com`）。

### 3.2 飞书 / Lark 客户端内免登（含网页应用、小程序 web-view）

在 Lark 国际开放平台 **网页** 功能中配置主页（必须带 `client=larksuite` 参数）：

- 桌面端主页：`https://sqlbot.example.com/?client=larksuite`
- 移动端主页：同上
- 若使用 **小程序 web-view** 打开 H5，请在 web-view 的 URL 中同样带上 `?client=larksuite`

**自动登录流程（无需扫码）：**

1. 用户在飞书 / Lark 客户端内打开上述地址  
2. 前端加载 `h5-js-sdk`，调用 `tt.requestAuthCode`（或 `requestAccess`）获取临时 `code`  
3. 调用 `POST /api/v1/system/platform/sso/9` 换取 SQLBot JWT  
4. 自动进入问数界面

**注意：**

- 主页 URL 必须包含 `?client=larksuite`，否则只会进入普通登录页  
- SQLBot 侧须 **开启** 国际飞书且 **检测通过**（`enable` + `valid`）  
- `Redirect URI` 与开放平台登记地址一致（如 `https://sqlbot.example.com/`）  
- 建议开启 `Auto Create User`，或在 SQLBot 中预先绑定飞书用户

## 4. API 说明（自研后端）

| 接口 | 说明 |
|------|------|
| `GET /api/v1/system/platform` | 平台卡片列表 |
| `GET /api/v1/system/platform/client/9` | 登录页 client_id / redirect_uri |
| `POST /api/v1/system/platform/sso/9` | 用 `code` 换 SQLBot JWT |
| `GET /api/v1/system/authentication/platform/status` | 登录页各平台是否启用 |

## 5. 常见问题

- **重定向不匹配**：开放平台登记的 URL 必须与浏览器地址栏及 `Redirect URI` 配置一致。
- **小程序 / 客户端内报错 `20029 invalid redirect uri`**：Lark 客户端内 `requestAuthCode` 获取的 code **不能**带 `redirect_uri` 换 token；需使用 `/authen/v1/access_token`（SQLBot 已按 `state=fit2cloud-larksuite-client` 自动区分）。扫码登录仍走 OIDC 并需匹配 `Redirect URI`。
- **账号不存在**：`Auto Create User=false` 时需先在 SQLBot 存在对应 `sys_user_platform` 绑定。
- **无工作空间**：自动创建用户须配置有效的 `Default Workspace ID`。
- **生产环境**：需 HTTPS 公网域名；Linux 部署使用 Linux 版 Python 依赖，勿使用 macOS 编译的 xpack `.so`。
