# 模板和策略组

## 内置模板

以下模板位于 `templates/`，可在网页、CLI 交互菜单或 API 中使用：

| 文件名 | 用途 |
| --- | --- |
| `config_phone.json` | 手机配置 |
| `config_openwrt.json` | OpenWrt 配置 |
| `momo.json` | Momo 配置 |

API 默认使用 `config_phone.json`。CLI 非交互模式不会自动选模板，需显式提供 `-c/--config`。

## 节点如何并入模板

选择模板后，转换器会复制模板并把新节点追加到 `outbounds`，不会用生成的默认配置替换模板。对于存在且类型为 `selector` 或 `urltest` 的以下策略组，会追加新节点：

- `手动选择`、`自动选择`
- `日本手动`、`狮城手动`、`香港手动`、`台湾手动`、`美国手动`
- 上述地区的 `自动` 策略组

地区归类根据节点 tag 中的中文/常见英文地名、国家名或代码（如 `JP`、`SG`、`HK`、`TW`、`US`）推断。未匹配地区的节点仍会加入通用选择/自动策略组，但不会进入地区组。

模板策略组不会凭空创建；如果某个组不存在或不是 `selector`/`urltest`，就不会向该组追加节点。自定义模板也可以只提供 `outbounds`，再由你自行添加策略组与路由。

## 自定义模板要求

自定义 JSON 的根节点必须是对象，并包含数组类型的 `outbounds`。`outbounds` 中的每一项必须是对象。模板其余结构由模板作者负责，工具不会完整验证 sing-box schema。

CLI 使用模板文件：

```sh
python3 sub2singbox.py ./subscription.yaml \
  -c ./my-template.json \
  -o ./sing-box.json
```

网页可上传自定义模板文件；API 可通过 `template_json` 提交 JSON 对象或 JSON 字符串。`template` 与 `template_json` 不能同时指定。详见 [HTTP API](./API.md)。

## 输出验证

导入前请确认：

1. 模板和新增节点的字段适用于目标 sing-box 版本。
2. 策略组引用的 outbound tag 存在。
3. 路由、DNS、入站监听等配置符合目标设备环境。

转换器会修正节点间以及节点与模板现有 outbounds 之间的 tag 重名，但不会对模板的全部交叉引用做 schema 验证。
