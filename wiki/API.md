# HTTP API

Vercel 部署和本地服务器提供 JSON HTTP API。Vercel 路径为 `/api`；本地网页版服务在 `/api` 提供转换 API，并额外提供 `/fetch` 远程链接入口。

## 查看 API 信息

```sh
curl https://<项目名>.vercel.app/api
```

响应包含 API 名称、可用模板和默认模板。若配置了 API 密钥，请按下文添加认证请求头。

## 提交订阅文本

请求体支持 `content`（单个字符串）或 `contents`（字符串数组）：

```sh
curl -X POST 'https://<项目名>.vercel.app/api' \
  -H 'Content-Type: application/json' \
  --data-binary @request.json
```

`request.json` 示例：

```json
{
  "content": "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000\n    tls: true",
  "template": "config_phone.json"
}
```

多个内容示例：

```json
{
  "contents": [
    "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000",
    "trojan://password@example.org:443#Example"
  ],
  "template": "momo.json"
}
```

成功响应包含转换后的完整配置和节点数：

```json
{
  "config": {
    "outbounds": []
  },
  "node_count": 1
}
```

示例中的 `outbounds` 仅展示响应结构；实际响应包括模板和转换后的节点。

## 提交远程订阅链接

Vercel `/api` 接受 `url` 或 `urls`：

```json
{
  "urls": [
    "https://example.com/subscription"
  ],
  "template": "config_phone.json"
}
```

本地服务器也可对 `/fetch` 发送相同 JSON。服务端下载订阅并转换；公网 HTTP(S) URL 会经过公网地址检查，重定向目标也会检查。单次请求体和单个远程下载均限制为 2 MiB。不要把访问你不信任的远程地址的能力开放给未授权用户。

## 模板选择

使用 `template` 选择内置模板，可选值为：

- `config_phone.json`（默认）
- `config_openwrt.json`
- `momo.json`

自定义模板使用 `template_json`，值可为 JSON 对象或 JSON 字符串，且需含有数组类型的 `outbounds`：

```json
{
  "content": "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000",
  "template_json": {
    "outbounds": [
      {
        "type": "selector",
        "tag": "手动选择",
        "outbounds": []
      }
    ]
  }
}
```

`template` 和 `template_json` 不可同时提供。模板的策略组合并逻辑见[模板和策略组](./Templates.md)。

## 响应状态

| 状态码 | 含义 |
| --- | --- |
| `200` | 转换成功 |
| `400` | JSON、输入内容或模板无效 |
| `401` | 已启用密钥认证，但请求未通过认证 |
| `404` | 未知路径 |
| `413` | 请求体超过 2 MiB |
| `500` | 转换期间发生未预期错误 |

## 认证

设置服务端环境变量 `YAML2SB_API_KEY` 后，API 请求必须提供以下任一方式：

```http
Authorization: Bearer <密钥>
```

或：

```http
X-API-Key: <密钥>
```

密钥未设置时 API 保持公开访问。查询参数 `api_key` 也被服务端接受，但密钥可能进入 URL、代理日志或浏览器历史；优先使用请求头，并通过 HTTPS 传输。
