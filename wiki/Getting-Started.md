# 快速上手

## 环境准备

- Python 3.9 或更高版本。
- 项目依赖：PyYAML。

在项目根目录安装依赖：

```sh
python3 -m pip install -r requirements.txt
```

## 命令行转换

### 交互模式

直接启动会进入菜单。每行输入一个本地文件路径或订阅链接，空行结束输入；之后选择模板和输出路径。

```sh
python3 sub2singbox.py
```

也可显式启用交互模式：

```sh
python3 sub2singbox.py --interactive
```

### 非交互模式

非交互调用需要通过 `-c/--config` 指定 JSON 模板；`-o/--output` 可选。

```sh
python3 sub2singbox.py ./subscription.yaml \
  -c templates/config_phone.json \
  -o ./sing-box-phone.json
```

可一次提供多个源，节点会合并转换：

```sh
python3 sub2singbox.py ./first.yaml 'https://example.com/subscribe' \
  -c templates/config_openwrt.json \
  -o ./sing-box-openwrt.json
```

未指定输出路径时，程序将结果写到第一个本地输入文件所在目录；如果所有输入都是链接，则写到当前目录。文件名按模板名选择，如 `config_phone.json` 对应 `sing-box-phone.json`。

### 转换结果

程序会报告转换节点数和输出路径。使用内置模板时，如果模板定义了 Mixed 入站，还会打印该入站的监听地址。没有得到任何可用节点时，程序以失败状态退出，不会生成有效配置。

## 本地网页

```sh
python3 web_server.py
```

打开 <http://127.0.0.1:8080>。网页可粘贴订阅内容、选择多个本地文件、输入远程 HTTP(S) 订阅链接，并选择模板或上传自定义模板。多个输入源会合并转换。

默认只监听本机。如需从局域网访问，可明确指定监听地址：

```sh
python3 web_server.py --host 0.0.0.0 --port 8080
```

公开监听前应启用 API 密钥并配置适当的网络访问控制；详见[部署方式](./Deployment.md)。

## 接下来

- 查看[支持的格式和协议](./Supported-Formats.md)，确认订阅内容可解析。
- 查看[模板和策略组](./Templates.md)，了解转换结果如何合并到目标配置。
- 使用自动化集成时，参考 [HTTP API](./API.md)。
