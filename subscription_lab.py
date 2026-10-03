"""Persistent storage for saved subscription profiles."""

import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from subscription_utils import collect_subscription_urls, validate_public_url_syntax

MAX_PROFILE_BYTES = 2 * 1024 * 1024
PROFILE_PREFIX = "yaml2sb:profile:"
PROFILE_INDEX = "yaml2sb:profiles"


class SubscriptionStoreUnavailable(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_profile(payload):
    if not isinstance(payload, dict):
        raise ValueError("订阅配置必须是 JSON 对象")

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("名称必须为 1 到 80 个字符")

    urls = payload.get("urls")
    contents = payload.get("contents")
    if urls is not None and contents is not None:
        raise ValueError("远程订阅链接与 YAML 内容只能选择一种来源")
    if urls is not None:
        urls = collect_subscription_urls({"urls": urls})
        if not urls:
            raise ValueError("请至少提供一个订阅链接")
        for url in urls:
            validate_public_url_syntax(url)
        normalized = {"urls": urls}
    elif contents is not None:
        if (
            not isinstance(contents, list)
            or not contents
            or any(not isinstance(item, str) or not item.strip() for item in contents)
        ):
            raise ValueError("请至少提供一份有效 YAML 或订阅文本")
        if sum(len(item.encode("utf-8")) for item in contents) > MAX_PROFILE_BYTES:
            raise ValueError("订阅内容总大小不能超过 2 MiB")
        normalized = {"contents": contents}
    else:
        raise ValueError("请提供 urls 或 contents 作为订阅来源")

    node_filter = payload.get("node_filter", {})
    if not isinstance(node_filter, dict):
        raise ValueError("node_filter 必须是对象")
    normalized_filter = {}
    for key in ("include_names", "exclude_names"):
        values = node_filter.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 50
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError(f"node_filter.{key} 必须是最多 50 项的非空字符串数组")
        normalized_filter[key] = [value.strip() for value in values]

    template = payload.get("template", "phone")
    if not isinstance(template, str) or template.strip().lower() not in {
        "phone", "config_phone", "config_phone.json",
        "openwrt", "config_openwrt", "config_openwrt.json",
        "momo", "momo.json",
    }:
        raise ValueError("template 必须是 phone、openwrt 或 momo")
    if payload.get("template_json") is not None:
        custom_template = payload["template_json"]
        if (
            not isinstance(custom_template, dict)
            or not isinstance(custom_template.get("outbounds"), list)
            or any(not isinstance(item, dict) for item in custom_template["outbounds"])
        ):
            raise ValueError("自定义模板必须是包含对象数组 outbounds 的 JSON 对象")
        if payload.get("template_options") is not None:
            raise ValueError("自定义模板不能与 template_options 同时使用")
    if payload.get("template_options") is not None and not isinstance(
        payload["template_options"], dict
    ):
        raise ValueError("template_options 必须是对象")

    result = {
        "name": name.strip(),
        **normalized,
        "template": template.strip(),
        "node_filter": normalized_filter,
    }
    for key in ("template_json", "template_options"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    return result


class SQLiteSubscriptionStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get(
            "YAML2SB_DB_PATH", "data/subscriptions.sqlite3"
        ))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _read_all(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT id, record FROM profiles").fetchall()
        return [dict(id=profile_id, **json.loads(record)) for profile_id, record in rows]

    def list(self):
        return sorted(self._read_all(), key=lambda item: item["updated_at"], reverse=True)

    def get(self, profile_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return dict(id=profile_id, **json.loads(row[0])) if row else None

    def create(self, record):
        timestamp = _now()
        for _ in range(5):
            profile_id = secrets.token_urlsafe(12)
            stored = {**record, "created_at": timestamp, "updated_at": timestamp}
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO profiles (id, record) VALUES (?, ?)",
                        (profile_id, json.dumps(stored, ensure_ascii=False)),
                    )
                return dict(id=profile_id, **stored)
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("无法生成唯一的短链接 ID")

    def update(self, profile_id, record):
        existing = self.get(profile_id)
        if existing is None:
            return None
        stored = {
            **record,
            "created_at": existing["created_at"],
            "updated_at": _now(),
        }
        with self._connect() as connection:
            connection.execute(
                "UPDATE profiles SET record = ? WHERE id = ?",
                (json.dumps(stored, ensure_ascii=False), profile_id),
            )
        return dict(id=profile_id, **stored)

    def delete(self, profile_id):
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        return cursor.rowcount > 0


class UpstashSubscriptionStore:
    def __init__(self, url, token):
        if not url.startswith("https://") or not token:
            raise SubscriptionStoreUnavailable("Upstash Redis REST 配置无效")
        self.url = url.rstrip("/")
        self.token = token

    def _command(self, *args):
        request = urllib.request.Request(
            self.url,
            data=json.dumps(args).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SubscriptionStoreUnavailable("Upstash Redis 暂时不可用") from exc
        if result.get("error"):
            raise SubscriptionStoreUnavailable("Upstash Redis 请求失败")
        return result.get("result")

    def list(self):
        profile_ids = self._command("SMEMBERS", PROFILE_INDEX) or []
        profiles = [self.get(profile_id) for profile_id in profile_ids]
        return sorted(
            (item for item in profiles if item is not None),
            key=lambda item: item["updated_at"],
            reverse=True,
        )

    def get(self, profile_id):
        value = self._command("GET", PROFILE_PREFIX + profile_id)
        return dict(id=profile_id, **json.loads(value)) if value else None

    def create(self, record):
        timestamp = _now()
        for _ in range(5):
            profile_id = secrets.token_urlsafe(12)
            stored = {**record, "created_at": timestamp, "updated_at": timestamp}
            if self._command(
                "SET",
                PROFILE_PREFIX + profile_id,
                json.dumps(stored, ensure_ascii=False),
                "NX",
            ):
                self._command("SADD", PROFILE_INDEX, profile_id)
                return dict(id=profile_id, **stored)
        raise RuntimeError("无法生成唯一的短链接 ID")

    def update(self, profile_id, record):
        existing = self.get(profile_id)
        if existing is None:
            return None
        stored = {
            **record,
            "created_at": existing["created_at"],
            "updated_at": _now(),
        }
        self._command(
            "SET", PROFILE_PREFIX + profile_id, json.dumps(stored, ensure_ascii=False)
        )
        return dict(id=profile_id, **stored)

    def delete(self, profile_id):
        deleted = self._command("DEL", PROFILE_PREFIX + profile_id)
        if deleted:
            self._command("SREM", PROFILE_INDEX, profile_id)
        return bool(deleted)


def get_subscription_store():
    store_name = os.environ.get("YAML2SB_STORE", "").lower()
    if store_name == "upstash" or os.environ.get("VERCEL"):
        url = os.environ.get("UPSTASH_REDIS_REST_URL")
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        if not url or not token:
            raise SubscriptionStoreUnavailable(
                "订阅管理需要配置 UPSTASH_REDIS_REST_URL 和 UPSTASH_REDIS_REST_TOKEN"
            )
        return UpstashSubscriptionStore(url, token)
    if store_name not in ("", "sqlite"):
        raise SubscriptionStoreUnavailable("YAML2SB_STORE 仅支持 sqlite 或 upstash")
    return SQLiteSubscriptionStore()
