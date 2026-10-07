# yaml2sb

**Language:** [中文](README.md) · [English](README.en.md)

Convert Clash YAML, Base64 subscriptions, or common proxy URIs into sing-box JSON. Supports multiple files/subscriptions, node-name filtering, saved subscription bundles, short remote links, a local web UI, Docker, Vercel, Cloudflare Workers, and command-line usage.

## Contents

- [Supported scope](#supported-scope)
- [Deployment overview](#deployment-overview)
- [Deploy to Vercel](#deploy-to-vercel)
- [Deploy to Cloudflare Workers](#deploy-to-cloudflare-workers)
- [Docker Compose](#docker-compose)
- [Local web](#local-web)
- [API Key usage](#api-key-usage)
- [HTTP API](#http-api)
- [Command line](#command-line)
- [Web UI and custom configuration](#web-ui-and-custom-configuration)
- [Notes](#notes)

## License

This project is licensed under the [MIT License](LICENSE).

## Project Wiki

See the [GitHub Wiki](https://github.com/bacdown/yaml2sb/wiki) for additional usage information.

## Supported scope

- Clash YAML `proxies`
- Plain-text or Base64 subscriptions
- URIs: `vmess://`, `vless://`, `trojan://`, `ss://`, `hysteria2://` / `hy2://`, `hysteria://`, `tuic://`, `anytls://`
- Clash node types: Shadowsocks (including obfs / v2ray-plugin / shadow-tls), VMess, VLESS (including Reality), Trojan, Hysteria2, Hysteria v1, TUIC, AnyTLS, HTTP, and SOCKS5
- Hysteria2 port hopping (`ports` / `mport`), bandwidth, `alpn: h3`, and `disable_chrome_parrot`
- Parsed nodes can be inserted into sing-box JSON templates and policy groups

Unsupported nodes are skipped. Conversion fails if no usable nodes can be parsed.

### Recent improvements

- Fixed Clash `fingerprint` being incorrectly treated as a uTLS client fingerprint; certificate SHA256 pinning is no longer written to `tls.utls`.
- Hysteria2 / TUIC add `alpn: ["h3"]` by default; Hysteria2 enables `disable_chrome_parrot` by default.
- Added Shadowsocks plugins and HTTP / SOCKS5 / AnyTLS / Hysteria v1 support.
- Protocol conversion uses a registry structure for easier extension, with unit tests in `test_convert.py`.
- Added `GET /sub` remote subscription conversion for Vercel and Cloudflare Workers.
- Workers validate every redirect and subscription size during remote requests.
- Vercel and Workers share subscription URL validation and parameter handling; failed remote downloads return `502`, oversized content returns `413`.

## Deployment overview

| Method | Use case | Details |
| --- | --- | --- |
| Vercel | Public web and API | [Deploy to Vercel](#deploy-to-vercel) |
| Cloudflare Workers | Edge deployment and remote subscriptions | [Deploy to Cloudflare Workers](#deploy-to-cloudflare-workers) |
| Docker Compose | Self-hosting, router, or LAN deployment | [Docker Compose](#docker-compose) |
| Local | Development or LAN access | [Local web](#local-web) |

## Deploy to Vercel

![yaml2sb web UI](./docs/images/web-ui.png)

### Deploy from the Vercel website

1. Push this repository to GitHub.
2. Sign in to [Vercel](https://vercel.com/) and import the repository.
3. Set **Root Directory** to the repository root.
4. Keep automatic Python project detection. If a framework is requested, choose **Other**. No Build Command or Output Directory is required.
5. Deploy. The API will be available at `https://<project>.vercel.app/api`.

The deployment configuration is in `vercel.json`. Built-in templates are in `templates/`.

### Deploy with Vercel CLI

```sh
npm install --global vercel
vercel
vercel --prod
```

### Enable API Key (optional)

In **Settings → Environment Variables**, add:

- **Key:** `YAML2SB_API_KEY`
- **Value:** a strong random secret, for example `openssl rand -hex 32`
- **Environment:** Production, Preview and/or Development as required

Redeploy after changing environment variables.

### Enable subscription management and short links

Vercel functions do not provide persistent local storage for this feature. Short-link management requires Upstash Redis plus `YAML2SB_API_KEY`.

Configure:

- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `YAML2SB_API_KEY`

The public `/s/<id>` endpoint does not require an API key.

## Deploy to Cloudflare Workers

The Python Workers entry point is `worker.py`. Use Python 3.11+ for the Worker development toolchain.

```sh
uv sync --group dev --python 3.11
uv run --python 3.11 pywrangler login
uv run --python 3.11 pywrangler dev
uv run --python 3.11 pywrangler deploy
```

After deployment:

```text
https://yaml2sb.<your-subdomain>.workers.dev
```

### Verify the deployment

```sh
WORKER_URL='https://yaml2sb.<your-subdomain>.workers.dev'
curl -fsS "$WORKER_URL/api" | python3 -m json.tool
```

For remote conversion:

```sh
curl --get --fail-with-body \
  --data-urlencode "url=https://example.com/subscribe" \
  --data-urlencode 'template=phone' \
  "$WORKER_URL/sub" -o sing-box.json
python3 -m json.tool sing-box.json > /dev/null
```

### Enable API Key

```sh
uv run --python 3.11 pywrangler secret put YAML2SB_API_KEY
```

You can also configure the secret in **Workers & Pages → yaml2sb → Settings → Variables and Secrets**.

### Enable subscription management and short links

Create a Workers KV namespace and bind it as `SUBSCRIPTIONS` in `wrangler.toml`. Configure `YAML2SB_API_KEY` and redeploy.

For production and preview environments, use separate KV namespaces when possible.

### Client remote configuration

| template | Use case |
| --- | --- |
| `phone` | Phone / SFA / SFI |
| `openwrt` | OpenWrt / router |
| `momo` | Momo |

Example:

```text
https://yaml2sb.<your-subdomain>.workers.dev/sub?url=<encoded-subscription>&template=phone
```

## API Key usage

Vercel, Cloudflare Workers, the local web service, and Docker Compose use `YAML2SB_API_KEY`.

When the variable is unset or empty, authentication is not required. When configured, protected endpoints require a valid key.

Recommended header:

```http
Authorization: Bearer <API_KEY>
```

Alternative:

```http
X-API-Key: <API_KEY>
```

Query-string authentication is also supported where a client cannot set headers, but it may expose the secret in URLs and logs.

### Web form

Enter the API key in the **Source** card on the conversion page. It is sent only with requests and is not stored in the browser.

### curl

```sh
BASE_URL='https://<project>.vercel.app'
export YAML2SB_API_KEY='<your-secret>'

curl -H "Authorization: Bearer $YAML2SB_API_KEY" "$BASE_URL/api"
curl -H "Authorization: Bearer $YAML2SB_API_KEY" \
  "$BASE_URL/api/options?template=config_phone.json"
```

## HTTP API

### API and template information

```sh
curl https://<project>.vercel.app/api
```

### Template mapping

| Purpose | Short name | Template |
| --- | --- | --- |
| Phone / official clients | `phone` | `config_phone.json` |
| OpenWrt / router | `openwrt` | `config_openwrt.json` |
| Momo | `momo` | `momo.json` |

### Remote subscription conversion (GET /sub)

```text
https://<project>.vercel.app/sub?url=<encoded-subscription>&template=<phone|openwrt|momo>
```

| Parameter | Required | Description |
| --- | --- | --- |
| `url` | Yes | Original HTTP(S) subscription URL; may appear multiple times |
| `urls` | No | Multiple URLs, comma-separated |
| `template` | No | `phone` / `openwrt` / `momo`; defaults to `phone` |
| `api_key` | Conditional | Required when `YAML2SB_API_KEY` is configured |

### Save subscription bundles and short links

The web UI can save multiple subscription URLs or uploaded files as a reusable bundle. A short link reloads the remote sources and returns pure sing-box JSON.

Management APIs require `YAML2SB_API_KEY` and persistent storage:

| Runtime | Storage |
| --- | --- |
| Local / self-hosted | SQLite |
| Docker Compose | SQLite named volume `yaml2sb-data` |
| Vercel | Upstash Redis |
| Cloudflare Workers | Workers KV binding `SUBSCRIPTIONS` |

The public `/s/<id>` endpoint does not require an API key.

### POST /api

Send `content`, `url`, or `urls` together with an optional template:

```json
{
  "content": "proxies:\n  - name: Japan 01\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 00000000-0000-0000-0000-000000000000\n    tls: true",
  "template": "config_phone.json"
}
```

### Custom template

Provide `template_json` as a JSON object or JSON string. It must contain an object root and an array-type `outbounds`.

### Request limits and errors

- Request body: **2 MiB** maximum.
- `400`: invalid JSON, missing content, invalid URL, unsupported template, or invalid template format.
- `413`: request or remote subscription content exceeds **2 MiB**.
- `502`: remote subscription is unavailable or invalid.
- `500`: unexpected conversion error.
- `GET /sub` allows at most **10** subscription URLs and validates every redirect target.

## Command line

Requires Python 3.9+.

```sh
python3 -m pip install .
python3 sub2singbox.py
python3 sub2singbox.py --interactive
```

Remote subscription:

```sh
python3 sub2singbox.py 'https://example.com/subscribe' \
  -c templates/config_phone.json \
  -o sing-box.json
```

Local file:

```sh
python3 sub2singbox.py ./subscription.yaml \
  -c templates/config_openwrt.json \
  -o ./sing-box-openwrt.json
```

Multiple URLs or files are supported. Use `-c/--config` to select a template and `-o/--output` to choose the output path.

## Web UI and custom configuration

The web UI is organized into five main areas:

1. **Subscription Converter** — Add sources, select a template, process nodes, configure advanced options, and generate sing-box JSON.
2. **Subscription Manager** — Save provider subscriptions and create combined sources.
3. **Configuration Profiles** — Save reusable subscription/template/filter combinations.
4. **Short Links** — Manage saved remote sing-box configuration URLs.
5. **Settings** — Select light/dark/system theme and manage the current session API key.

### Source

Add a subscription URL, upload YAML/TXT/JSON files, or paste configuration. Multiple sources can be merged.

### Conversion Profile

Choose the iPhone, OpenWrt, or Momo built-in template, or upload a custom sing-box JSON template.

### Node Processing

Configure include/exclude node-name keywords and certificate verification policies. Certificate policy can remain unchanged, verify certificates, or skip verification for supported node types.

### Advanced Configuration

The advanced editor provides:

- Domestic and international DNS selection
- Custom DNS servers
- Routing groups
- Application matching rules and rule order
- Rule sets and custom rule-set URLs
- Outbound selection

DNS entries can be selected per category, with up to two retained in each category. Template-required local, Hosts, and FakeIP DNS dependencies remain preserved.

### Subscription management

The **Subscription Manager** stores provider URLs. Select one or more saved subscriptions to create a combined source or a reusable short link.

### Configuration profiles

The **Configuration Profiles** page saves the current source, template, and filtering settings for reuse.

### Short links

The **Short Links** page manages saved remote sing-box configuration endpoints. Creating and editing management records requires API authentication and persistent storage.

### Language switcher

The top-right **中文 / English** language picker translates the UI, including labels, buttons, options, placeholders, status text, and dynamic configuration controls. The selected language is stored locally and restored on the next visit.

## Docker Compose

The default Docker deployment does not enable API authentication.

Enable it with:

```sh
export YAML2SB_API_KEY="$(openssl rand -hex 32)"
docker compose up --build -d
```

The Compose deployment stores subscription data in the named volume `yaml2sb-data`.

Without authentication:

```sh
docker compose up --build -d
```

Open `http://localhost:8080`.

You can change the host port with `YAML2SB_PORT`.

## Local web

Start the local web server with:

```sh
python3 web_server.py
```

Default address:

```text
http://127.0.0.1:8080
```

For LAN access:

```sh
python3 web_server.py --host 0.0.0.0 --port 8080
```

Set `YAML2SB_API_KEY` before starting the process if authentication is required.

## Notes

- Subscription URLs may contain private credentials. Do not commit real subscription URLs, node passwords, UUIDs, or complete private configurations to a public repository.
- API Key is a shared token, not a full identity, quota, or rate-limiting system. For public deployment, consider Cloudflare Access or a reverse proxy with additional access control.
- Custom templates are submitted in requests; built-in templates are selected through a filename allowlist.
- Conversion results contain node authentication information from the source. Protect exported configuration files.
- Always validate the generated configuration with the target sing-box version before deployment.

### Docker deployment notes

When using Docker Compose, keep the same `YAML2SB_API_KEY` value across container restarts if API authentication is enabled. The SQLite named volume preserves saved subscriptions across container recreation.

### Local web deployment notes

The local web service listens on `127.0.0.1:8080` by default. Use `--host 0.0.0.0` only when LAN access is required, and enable API authentication before exposing the service beyond a trusted network.
