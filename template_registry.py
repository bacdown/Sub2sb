"""内置模板注册表（单一事实源）。

所有入口（api/index.py、worker.py、subscription_lab.py、sub2singbox.py CLI）
都从这里解析模板名与模板文件，避免在多处硬编码映射导致不一致。
新增或更名模板时只需修改这里，并增删 templates/ 下的模板文件。
"""

# 模板 ID -> 模板文件与显示名。顺序即 CLI 交互菜单顺序。
TEMPLATES = {
    "phone": {"file": "config_phone.json", "label": "手机配置"},
    "linux": {"file": "config_linux.json", "label": "Linux 配置"},
    "windows": {"file": "config_windows.json", "label": "Windows 配置"},
    "momo": {"file": "momo.json", "label": "Momo 配置"},
}

DEFAULT_TEMPLATE_ID = "phone"

# 别名 -> 模板 ID，包含短名、无后缀名与完整文件名三种形式。
ALIASES = {
    "phone": "phone",
    "config_phone": "phone",
    "config_phone.json": "phone",
    "linux": "linux",
    "config_linux": "linux",
    "config_linux.json": "linux",
    "windows": "windows",
    "config_windows": "windows",
    "config_windows.json": "windows",
    "momo": "momo",
    "momo.json": "momo",
    # 已弃用别名：OpenWrt 模板已更名为 Linux。保留旧名解析，兼容已保存的
    # 订阅方案与在用的 /sub?template=openwrt 直链，不要直接删除。
    "openwrt": "linux",
    "config_openwrt": "linux",
    "config_openwrt.json": "linux",
}


def resolve_template_id(name):
    """将模板名、别名或文件名解析为注册表 ID；空值返回默认模板。

    无法识别时抛出 ValueError，并列出全部可选项。
    """
    if not isinstance(name, str) or not name.strip():
        return DEFAULT_TEMPLATE_ID
    resolved = ALIASES.get(name.strip().lower()) or ALIASES.get(name.strip())
    if resolved is None:
        options = "、".join(
            f"{template_id} / {info['file']}（{info['label']}）"
            for template_id, info in TEMPLATES.items()
        )
        raise ValueError(f"不支持的模板名称；可选：{options}")
    return resolved


def resolve_template_file(name):
    """将模板名、别名或文件名解析为标准模板文件名。"""
    return TEMPLATES[resolve_template_id(name)]["file"]


def template_files():
    """全部内置模板文件名集合。"""
    return {info["file"] for info in TEMPLATES.values()}


def alias_file_map():
    """全部别名（含弃用别名）-> 模板文件，供各入口的兼容映射使用。"""
    return {alias: TEMPLATES[template_id]["file"] for alias, template_id in ALIASES.items()}


def short_aliases():
    """模板 ID -> 模板文件，供信息接口展示。"""
    return {template_id: info["file"] for template_id, info in TEMPLATES.items()}
