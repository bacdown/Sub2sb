# yaml2sb Wiki

yaml2sb 将 Clash YAML、Base64 订阅和常见代理 URI 转换为 sing-box JSON。可通过命令行、本地网页、Docker、Vercel 网页或 HTTP API 使用。

## 文档导航

- [快速上手](./Getting-Started.md)：安装依赖，转换本地文件或订阅链接。
- [支持的格式和协议](./Supported-Formats.md)：查看输入格式、代理类型及支持边界。
- [模板和策略组](./Templates.md)：选择内置模板，或准备自己的 sing-box JSON 模板。
- [HTTP API](./API.md)：提交文本、订阅链接或自定义模板。
- [部署方式](./Deployment.md)：在本机、Docker Compose 或 Vercel 运行。
- [常见问题](./Troubleshooting.md)：排查输入、模板和部署问题。

## 一般使用流程

1. 准备 Clash YAML、代理 URI 文本或订阅服务提供的订阅内容。
2. 选择输入方式：CLI、本地网页或 HTTP API。
3. 选择手机、OpenWrt、Momo 内置模板，或提供自定义 JSON 模板。
4. 转换并保存 sing-box JSON，在目标 sing-box 版本中检查配置后再使用。

## 项目目录

| 路径 | 用途 |
| --- | --- |
| `sub2singbox.py` | 命令行入口、解析器及模板合并逻辑 |
| `web_server.py` | 本地网页服务器 |
| `api/index.py` | Vercel 和本地服务器共用的 HTTP API |
| `converter.py` | 转换模块入口 |
| `public/index.html` | 网页界面 |
| `templates/` | 手机、OpenWrt 和 Momo 配置模板 |
| `tests/` | CLI 和网页/API 测试 |

## 安全提示

订阅链接、节点密码、UUID 和转换结果都可能包含私密凭据。不要将真实订阅或完整配置提交到公开仓库、issue 或日志。API 默认不启用密钥认证；公网部署前请阅读[部署方式](./Deployment.md)和[HTTP API](./API.md)。
