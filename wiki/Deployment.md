# 部署方式

## 本地命令行

安装 Python 3.9+ 和依赖后即可使用 CLI：

```sh
python3 -m pip install -r requirements.txt
python3 sub2singbox.py --help
```

详细转换示例见[快速上手](./Getting-Started.md)。

## 本地网页

```sh
python3 -m pip install -r requirements.txt
python3 web_server.py
```

默认监听 `127.0.0.1:8080`。指定其他地址或端口：

```sh
python3 web_server.py --host 0.0.0.0 --port 8080
```

若要让 API 需要密钥，在启动服务前设置 `YAML2SB_API_KEY`：

```sh
YAML2SB_API_KEY='替换为强随机密钥' python3 web_server.py
```

启用后，网页首页仍可打开；在页面的 API 访问密钥栏填写密钥。API 客户端可发送 `Authorization: Bearer <密钥>` 或 `X-API-Key: <密钥>`。

## Docker Compose

在项目目录构建并启动：

```sh
docker compose up --build -d
```

访问 <http://localhost:8080>。宿主机端口默认 `8080`，可通过 `YAML2SB_PORT` 修改；密钥通过 `YAML2SB_API_KEY` 传入：

```sh
YAML2SB_PORT=9090 YAML2SB_API_KEY='替换为强随机密钥' \
  docker compose up --build -d
```

查看日志和停止服务：

```sh
docker compose logs -f
docker compose down
```

也可自行构建并运行：

```sh
docker build -t yaml2sb .
docker run --rm -p 8080:8080 \
  -e YAML2SB_API_KEY='替换为强随机密钥' \
  yaml2sb
```

## Vercel

### 网站部署

1. 将项目推送至 GitHub，并在 Vercel 导入该仓库。
2. 将 Root Directory 设为项目目录；框架选择保持自动检测，必要时选 **Other**。
3. 本项目不需要额外的 Build Command 或 Output Directory。
4. 点击 Deploy。部署后网页由项目提供，API 地址为 `https://<项目名>.vercel.app/api`。

如果需要 API 认证，在 Vercel 项目环境变量中设置 `YAML2SB_API_KEY` 后重新部署。未设置时 API 为公开访问。

### Vercel CLI

```sh
npm install --global vercel
vercel
vercel --prod
```

部署配置位于 `vercel.json`。修改脚本或模板后，推送到已连接的分支即可触发重新部署。

## 公网部署提示

不要在未认证的情况下将本地服务或 API 直接暴露到公网。应配置强随机 API 密钥、HTTPS 和访问控制。订阅及输出配置包含节点凭据，请避免记录或公开分享。
