# 支持的格式和协议

## 输入格式

解析器会尝试识别以下内容：

- Clash YAML：从根对象中的 `proxies` 列表读取节点。
- 明文代理 URI：可一行一个。
- Base64 编码的代理 URI 列表。
- Base64 编码的 Clash YAML。

Base64 解码兼容 URL-safe 字符集和缺失的 `=` padding。订阅服务返回的内容应是上述格式，而不是登录页面或 HTML 管理页。

## 代理类型

### Clash YAML

Clash `proxies` 支持的类型：

| Clash 类型 | 主要读取的字段 |
| --- | --- |
| `ss`、`shadowsocks` | `server`、`port`、`cipher`、`password` |
| `vmess` | `server`、`port`、`uuid`、`cipher`、`alterId` |
| `vless` | `server`、`port`、`uuid`、`flow`、`packet-encoding` |
| `trojan` | `server`、`port`、`password` |
| `hysteria2`、`hy2` | `server`、`port` 或端口范围、`password`/`auth` |

VMess、VLESS、Trojan 等节点还会按代码支持情况转换 TLS、Reality、指纹和传输层配置。WebSocket、gRPC、HTTP 传输配置读取 `network` 及其对应的 `*-opts` 字段。Hysteria2 支持端口跳跃、跳跃间隔和 obfs 字段。

仅转换 `proxies` 节点；来源 YAML 中的 `proxy-groups`、规则和其他配置不会原样迁移到 sing-box。它们由所选 sing-box 模板提供。

### URI

支持以下 URI scheme：

- `vmess://`
- `vless://`
- `trojan://`
- `ss://`
- `hysteria2://`、`hy2://`
- `tuic://`

URI 中的片段（`#` 后的名称）用作节点名称。每种协议只处理代码实现的 URI 参数；不保证所有客户端导出的私有扩展参数均会保留。

## 节点处理规则

- 单个节点缺少必需字段或无法解析时会跳过，并输出诊断信息。
- 订阅状态/流量/到期提示等名称不会被当作代理节点。
- 重复节点名称会自动追加序号，避免 tag 冲突；使用模板时也会避开已有 outbound tag。
- 如果没有留下任何可用节点，转换会失败。

## 不支持的输入

- 不支持从 Clash 配置中迁移规则、代理组、代理提供者或 DNS 设置。
- 不支持的代理协议或不完整节点会被跳过。
- 输入内容必须是订阅文本；API 不会自动把文本字段中的 URL 当作订阅内容下载。需要获取远程链接时，请按 [HTTP API](./API.md) 中的 URL 请求格式调用。

sing-box 字段及协议能力可能随 sing-box 版本变化。转换成功不代表目标版本一定接受配置；使用前请按目标客户端/版本验证。
