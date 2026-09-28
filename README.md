# yaml2sb

将 Clash YAML、Base64 订阅或常见代理 URI 转换为 sing-box JSON。提供本地网页版、Docker 部署、Vercel HTTP API 和命令行用法。

## 许可证

本项目采用 [MIT License](LICENSE)。

## 项目 Wiki

请前往 [GitHub Wiki](https://github.com/bacdown/yaml2sb/wiki) 查看使用说明。

## 支持范围

- Clash YAML 中的 `proxies` 节点
- 明文或 Base64 编码的订阅
- VMess、VLESS、Trojan、Shadowsocks、Hysteria2、TUIC URI
- 将解析出的节点并入 sing-box JSON 模板中的策略组

不支持的节点会被跳过；如果没有解析到任何可用节点，转换会报错。

## 部署到 Vercel

### 通过 Vercel 网站部署

![yaml2sb 网页界面示例](./docs/images/vercel-web-ui.png)

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

### 使用自定义制作配置

网页选择 **自定义制作配置** 后，可从 iPhone、OpenWrt 或 Momo 配置开始制作。界面采用横向表单布局；未开放的配置部分保持所选基础配置默认值。国内和国际 DNS 均可直接点击选中或取消，每类最多选择两项；提供阿里云、腾讯 DNSPod、114DNS、Cloudflare、Google Public DNS、Quad9 等主流公共 DNS 及 DoH、DoT、DoQ、DoH3、UDP 等类型，也可直接点击添加自定义 DNS。已选择的 DNS 会显示在下方，可逐项移除；配置中的本地、Hosts 和 FakeIP DNS 作为内部依赖保留，不单独提供选择。

应用分流和规则集都在“匹配规则与顺序”中选择：名称对应具体应用分流，目标出站可选地区及手动/自动组，不提供直连选项；自定义应用名称会生成对应的 selector 组，所选出站作为该应用组的默认首选。规则集链接可在同一区域展开添加，名称和链接均可自定义，并选择 sing-box `binary` 或 `source` 格式。创建规则的表单与规则列表采用统一的字体和控件样式，添加后可上下移动或删除；未改动的模板默认出站保持原样。

#### 默认匹配规则及顺序建议

基础配置中的这些规则处理的是不同类型的流量：

| 规则 | 意义 |
| --- | --- |
| `{"ip_is_private": true, "outbound": "直连"}` | 目标 IP 属于内网/私有地址时走直连，常用于访问局域网设备和本地服务。 |
| `{"network": "icmp", "action": "resolve"}` | 匹配 ICMP 流量并执行解析动作；它本身不指定出站，不等同于“直连”。 |
| `{"network": "icmp", "outbound": "直连"}` | 将匹配到的 ICMP 流量（例如 ping）交给直连接出站。 |
| `{"clash_mode": "Direct", "outbound": "直连"}` | Clash 当前模式为 `Direct` 时，将匹配流量直连。 |
| `{"clash_mode": "Global", "outbound": "GLOBAL"}` | Clash 当前模式为 `Global` 时，将匹配流量交给 `GLOBAL` 出站组，由该组决定具体出口。 |

建议保留基础配置默认顺序：先处理内网地址、协议或其他基础例外，再处理 ICMP 的解析与直连，随后放置 `Direct` / `Global` 模式规则，然后排列应用分流和规则集规则，最后才放通用兜底规则。应用规则越具体越适合放在越前面；模式规则放在应用规则前，才能使 `Direct` / `Global` 模式覆盖常规应用分流。若希望特定应用在 `Global` 模式下仍使用自己的分流，可将该应用规则移到 `Global` 规则之前，但这会改变全局模式下的行为。ICMP 的 `resolve` 应排在 ICMP 直连之前，以免直连规则先结束对该流量的处理。

部分模板（如 iPhone 配置）会出现两条相同的 `ip_is_private: true` 直连规则；两者条件和出站相同，后出现的重复项通常不会增加新的匹配效果。调整顺序时可将其视为同一条规则；如需精简，可移除重复项，但建议先确认没有依赖模板的其他自定义改动。

程序会清理被取消规则集对应的规则和分流组引用；移除 DNS 服务器后，其余配置中指向该服务器的 DNS 引用会改指剩余可用 DNS。地区、手动/自动组和“延迟辅助”会作为出站保留，但不会作为应用名称显示。“延迟辅助”和直连不会出现在匹配目标出站选择器中；模板中已有的直连规则保持原样。

同一功能也可通过 API 使用。`GET /api/options?template=config_phone.json` 返回对应基础模板可选的 DNS、分流组和规则集；分流组带有 `application` 标识，界面据此将应用组与地区出站区分，`matching_targets` 不包含应用组、直连或“延迟辅助”。配置了 `YAML2SB_API_KEY` 时，读取该接口也需要 API 密钥。转换请求的 `template_options` 可以传入 `dns_servers`、`custom_dns_servers`、`groups`、`custom_groups`、`rule_sets`、`custom_rule_sets`、`custom_matching_rules`、`rule_destinations`、`rule_order` 和 `rule_outbounds`。`custom_groups` 可通过 `rule_sets` 将规则集加入应用分流组；`custom_matching_rules` 可按名称、规则集和初始出站新增应用分流及匹配规则；`rule_order` 使用 `/api/options` 返回的匹配规则索引字符串，以及新增规则集对应的 `custom:<tag>` 或自定义匹配规则的 `builder-<序号>` 排列。`custom_dns_servers` 中的 DNS 对象按 sing-box DNS server 字段传入，例如 `{"tag":"doh","type":"https","server":"dns.example","server_port":443,"path":"/dns-query"}`。未提供 DNS 选择时，使用基础模板默认 DNS；被取消的内部 DNS 依赖仍会保留。

```json
{
  "content": "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000\n    tls: true",
  "template": "config_phone.json",
  "template_options": {
    "custom_dns_servers": [
      {"tag": "custom-dns", "type": "https", "server": "1.1.1.1"}
    ],
    "custom_groups": [
      {"tag": "Games", "rule_sets": ["geosite-youtube"]}
    ],
    "custom_rule_sets": [
      {
        "tag": "geosite-games",
        "url": "https://example.com/games.srs",
        "format": "binary",
        "outbound": "Games"
      }
    ]
  }
}
```

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

直接运行脚本会启动交互式菜单，可逐行输入订阅链接或文件路径、选择模板并指定输出位置：

```sh
python3 sub2singbox.py
```

也可以显式启动菜单：

```sh
python3 sub2singbox.py --interactive
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

也可以一次传入多个链接或文件；使用非交互命令行参数时，`-c/--config` 模板参数必填，`-o/--output` 可选。不指定输出路径时，输出到第一个本地输入文件所在目录；如果输入全是链接，则输出到当前目录。

如果远程地址下载成功但内容无法识别，程序会显示响应的 `Content-Type` 和字节数，不会打印响应正文或 URL 中的凭据。请确认使用的是服务商提供的 Clash/Mihomo 订阅地址，而非管理页面或登录链接；也可在服务商处导出订阅文件后作为本地文件转换。

## 注意事项

- 订阅链接通常包含私密凭据。不要将真实订阅链接、节点密码、UUID 或完整配置提交到公开仓库，也不要在公开 issue 或日志中粘贴。
- 可选的令牌认证：当前代码支持通过设置 Vercel 环境变量 YAML2SB_API_KEY 启用简单的 token 保护。将该变量设置为一个强随机字符串后，服务端会拒绝未携带密钥的请求（保持向后兼容：未设置时仍为公开）。支持的认证方式：
  - HTTP Header: Authorization: Bearer <key>
  - HTTP Header: X-API-Key: <key>
  - 查询字符串: ?api_key=<key>

  例如：

  ```sh
  curl -H "Authorization: Bearer $YAML2SB_API_KEY" -H 'Content-Type: application/json' \
    -X POST https://<项目名>.vercel.app/api --data-binary @request.json
  ```

  如果需要更强的访问控制（OAuth、IP 限制、速率限制等），建议在 Vercel 前置一层认证/反向代理（例如 Cloudflare Access、NGINX、Caddy 或自托管的 proxy）。
- 本地网页版和 Docker 部署也支持相同的 `YAML2SB_API_KEY` 令牌认证。启用后，`/api` 和 `/fetch` 需要 Bearer 或 `X-API-Key` 请求头；首页仍可打开，网页转换表单中填写 API 访问密钥即可使用。未设置该变量时，API 不启用令牌认证。
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

默认未启用令牌认证。若需启用，可在启动进程前设置 `YAML2SB_API_KEY`：

```sh
YAML2SB_API_KEY='替换为强随机密钥' python3 web_server.py
```

Docker Compose 会把当前环境中的 `YAML2SB_API_KEY` 传给容器；可在启动前导出该变量或放入 Compose `.env` 文件。直接运行 Docker 镜像时使用 `-e YAML2SB_API_KEY='替换为强随机密钥'`。启用后，网页首页仍可打开，在页面的“API 访问密钥”栏输入密钥；调用 API 的客户端使用 `Authorization: Bearer <密钥>` 或 `X-API-Key: <密钥>` 请求头。密钥未设置时仍是公开访问，因此不要直接把未保护的服务暴露到公网；公网部署还应使用 HTTPS、访问控制和适当的用量限制。
