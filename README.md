# yaml2sb

将 Clash YAML、Base64 订阅或常见代理 URI 转换为 sing-box JSON。提供本地网页版、Docker 部署、Vercel HTTP API 和命令行用法。

## 支持范围

- Clash YAML 中的 `proxies` 节点
- 明文或 Base64 编码的订阅
- VMess、VLESS、Trojan、Shadowsocks、Hysteria2、TUIC URI
- 将解析出的节点并入 sing-box JSON 模板中的策略组

不支持的节点会被跳过；如果没有解析到任何可用节点，转换会报错。

## 部署到 Vercel

### 通过 Vercel 网站部署

1. 将本项目目录推送到 GitHub 仓库。
2. 登录 [Vercel](https://vercel.com/)，选择 **Add New → Project**，导入该仓库。
3. 确认 **Root Directory** 指向本项目目录。若仓库本身就是本项目，则使用仓库根目录。
4. 保持 Python 项目自动检测设置；如 Vercel 要求选择框架，选择 **Other**。本项目不需要 Build Command 或 Output Directory。
5. 点击 **Deploy**。部署完成后，API 地址为 `https://<项目名>.vercel.app/api`。

部署配置位于 `vercel.json`。三个内置模板整理在 `templates/` 目录中：`templates/config_phone.json`、`templates/config_openwrt.json` 和 `templates/momo.json`。修改脚本或模板后，推送到已连接的分支即可触发重新部署。

### 通过 Vercel CLI 部署

在项目根目录执行：

```sh
npm install --global vercel
vercel
```

按提示关联或创建项目。正式部署执行：

```sh
vercel --prod
```

## HTTP API 使用方法

### 查看 API 和模板

```sh
curl https://<项目名>.vercel.app/api
```

返回 API 信息、默认模板及可选的内置模板列表。

### 使用内置模板转换

向 `POST /api` 发送 JSON。`content` 必须是实际的 YAML 或订阅文本，`template` 可省略（默认 `config_phone.json`），也可选择 `config_openwrt.json` 或 `momo.json`。

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

成功时返回：

```json
{
  "config": {
    "outbounds": []
  },
  "node_count": 1
}
```

上面的 `outbounds` 仅用于展示响应结构；实际内容是完整转换后的 sing-box 配置。

### 使用自定义模板

在请求中提供 `template_json`，值可以是 JSON 对象或 JSON 字符串。模板必须是对象，并至少包含数组类型的 `outbounds`。已有 `template` 和 `template_json` 不可同时提供。

```json
{
  "content": "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000\n    tls: true",
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

转换时会保留模板配置并追加节点。模板中的策略组若要引用新节点，需使用脚本支持的组名（例如 `手动选择`、`自动选择` 和地区策略组）；其他模板可只提供 `outbounds`，由客户端按需调整策略组。

### 请求与错误

- 请求体最大为 **2 MiB**。
- `400`：JSON 格式错误、缺少 `content`、模板名称不支持或模板格式无效。
- `413`：请求体超过大小限制。
- `500`：转换期间发生未预期错误。
- API 接收的是订阅内容本身，不会根据 `content` 中的 URL 去下载订阅。将链接内容先取回，再把 YAML/URI 文本作为 `content` 发送。

## 本地命令行

需要 Python 3.9 或更高版本。安装依赖：

```sh
python3 -m pip install -r requirements.txt
```

转换远程订阅链接（模板文件位于 `templates/` 目录）：

```sh
python3 sub2singbox.py 'https://example.com/subscribe' \
  -c templates/config_phone.json \
  -o sing-box.json
```

转换本地文件：

```sh
python3 sub2singbox.py ./subscription.yaml \
  -c templates/config_openwrt.json \
  -o ./sing-box-openwrt.json
```

也可以一次传入多个链接或文件；`-c/--config` 模板参数必填，`-o/--output` 可选。不指定输出路径时，输出到第一个本地输入文件所在目录；如果输入全是链接，则输出到当前目录。

## 注意事项

- 订阅链接通常包含私密凭据。不要将真实订阅链接、节点密码、UUID 或完整配置提交到公开仓库，也不要在公开 issue 或日志中粘贴。
- Vercel API 当前没有身份验证，且 CORS 允许跨域访问。公开部署后，任何能访问部署 URL 的人都可以调用转换接口；如需限制使用，请在前置服务或 Vercel 层添加访问控制，并留意调用量。
- 自定义模板通过请求提交；内置模板通过文件名白名单选择，不允许传入任意文件路径。
- 转换结果会携带订阅中的节点认证信息。请妥善保存响应内容，避免公开分享。
- 输出是转换后的 sing-box 配置，不代表配置一定符合所有 sing-box 版本或运行环境的要求；部署/导入前请使用目标 sing-box 版本验证。

## 网页版

网页版支持两种输入方式：

1. 粘贴订阅内容，或一次选择多个本地 YAML / TXT 文件，内容会合并转换。
2. 输入一条或多条远程 HTTP(S) 订阅链接（每行一条），由服务端下载并合并转换。

两种方式都可以选择手机、OpenWrt 或 Momo 内置模板（文件整理在 `templates/` 目录），也可以上传自定义 sing-box JSON 模板；页面会检查 JSON 根节点及 `outbounds` 必要项，通过校验后才允许转换。下载结果为转换后的 sing-box JSON。远程下载仅允许公网 HTTP(S) 地址，单次下载最大 2 MiB，并会检查重定向目标。Vercel 部署时首页由 `public/index.html` 提供，页面输入（含远程链接）统一提交至 `/api`。

### 使用 Docker Compose 部署

在项目目录执行：

```sh
docker compose up --build -d
```

打开 <http://localhost:8080> 使用网页。可通过 `YAML2SB_PORT` 修改宿主机映射端口，例如：

```sh
YAML2SB_PORT=9090 docker compose up --build -d
```

查看日志和停止服务：

```sh
docker compose logs -f
docker compose down
```

也可以直接构建并运行 Docker 镜像：

```sh
docker build -t yaml2sb .
docker run --rm -p 8080:8080 yaml2sb
```

### 本地启动网页版

安装项目依赖后运行：

```sh
python3 web_server.py
```

默认仅监听本机 `127.0.0.1:8080`。如需从局域网其他设备访问，可显式监听所有网卡：

```sh
python3 web_server.py --host 0.0.0.0 --port 8080
```

网页和转换 API 均未配置身份验证。Docker Compose 会将服务端口映射到宿主机；不要直接暴露到公网。若需公网访问，请先在反向代理或其他前置层增加身份验证、HTTPS 和访问控制。
