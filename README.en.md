# yaml2sb

**Language:** [中文](README.md) · [English](README.en.md)

Convert Clash YAML, Base64 subscriptions, or common proxy URIs into sing-box JSON. yaml2sb supports multiple subscription/file inputs, node-name filtering, reusable subscription bundles, short remote links, a web UI, Docker, Vercel, Cloudflare Workers, and a command-line workflow.

## Features

- **Subscription conversion** — Accept subscription URLs, uploaded YAML/TXT/JSON files, pasted Clash YAML, Base64 subscriptions, and common proxy URIs.
- **Multiple sources** — Merge multiple subscriptions or files into one conversion request.
- **Client templates** — Built-in iPhone/mobile, OpenWrt/router, and Momo templates, plus custom JSON templates.
- **Node processing** — Include/exclude keywords and certificate verification policies.
- **Advanced configuration** — Configure DNS servers, routing groups, rule sets, matching rules, and rule order.
- **DNS selection** — Keep separate domestic and international DNS selections, with support for custom DNS servers.
- **Subscription management** — Save provider subscriptions and create combined subscription sources.
- **Configuration profiles** — Save the current sources, template, and filters as reusable remote configurations.
- **Short links** — Create, refresh, edit, and delete remote sing-box configuration links.
- **API authentication** — Optional `YAML2SB_API_KEY` protection for API and management endpoints.
- **Bilingual UI** — Switch between Chinese and English from the top-right corner of the web interface.

## Supported formats

Supported Clash / proxy input includes:

- Clash YAML `proxies`
- Plain-text or Base64 subscriptions
- `vmess://`
- `vless://`
- `trojan://`
- `ss://`
- `hysteria2://` / `hy2://`
- `hysteria://`
- `tuic://`
- `anytls://`

Supported Clash node types include Shadowsocks, VMess, VLESS, Trojan, Hysteria2, Hysteria v1, TUIC, AnyTLS, HTTP, and SOCKS5. Unsupported nodes are skipped; conversion fails if no usable nodes are parsed.

Hysteria2 supports port hopping (`ports` / `mport`), bandwidth, `alpn: h3`, and `disable_chrome_parrot`. Parsed nodes can be merged into sing-box JSON templates and policy groups.

## Deployment

Choose one of the following deployment methods:

| Method | Use case |
| --- | --- |
| [Vercel](https://vercel.com/) | Fast public web and API deployment |
| [Cloudflare Workers](https://workers.cloudflare.com/) | Edge deployment and remote subscription conversion |
| Docker Compose | Self-hosting, routers, or LAN deployment |
| Local Web | Local development or LAN access |

### Vercel

1. Push this repository to GitHub.
2. Sign in to Vercel and import the repository.
3. Keep the project root as the **Root Directory**.
4. Let Vercel detect the Python project. No Build Command or Output Directory is required.
5. Deploy. The API endpoint will be available at `https://<project>.vercel.app/api`.

To protect the API, add the `YAML2SB_API_KEY` environment variable in Vercel and redeploy.

Short-link management on Vercel requires Upstash Redis. Configure:

- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `YAML2SB_API_KEY`

The public short-link endpoint `/s/<id>` does not require an API key.

### Cloudflare Workers

The Worker entry point is `worker.py`. Install the development dependencies with Python 3.11+ and deploy with Wrangler:

```sh
uv sync --group dev --python 3.11
uv run --python 3.11 pywrangler login
uv run --python 3.11 pywrangler deploy
```

The deployed address looks like:

```text
https://yaml2sb.<your-subdomain>.workers.dev
```

For short-link management, create a Workers KV namespace and bind it as `SUBSCRIPTIONS` in `wrangler.toml`. Also configure `YAML2SB_API_KEY`.

### Docker Compose

Use the repository Docker Compose configuration for self-hosted deployment. This is suitable for a LAN, router, or private server environment. Keep API authentication enabled when the service is exposed beyond a trusted network.

### Local Web

The web interface is served from `public/index.html`. Use the project's existing local server or Python entry point, then open the corresponding local URL in a browser.

## Web interface

The web UI is organized into five main areas:

1. **Subscription Converter** — Add sources, select a template, process nodes, configure advanced options, and generate sing-box JSON.
2. **Subscription Manager** — Store provider subscriptions and create combined sources.
3. **Configuration Profiles** — Save reusable subscription/template/filter combinations.
4. **Short Links** — Manage saved remote sing-box configuration URLs.
5. **Settings** — Select the light/dark/system theme and manage the current session's API key.

The **Source** section supports subscription URLs, file uploads, pasted configuration, and optional API authentication.

The **Conversion Profile** section provides built-in templates and custom JSON templates.

The **Node Processing** section supports include/exclude keyword filtering and certificate verification policies.

The **Advanced Configuration** section provides:

- DNS selection and custom DNS servers
- Routing groups
- Matching rules and rule order
- Rule sets and custom rule-set URLs
- Outbound selection

The top-right language switcher changes the complete UI between **中文** and **English**. The selected language is stored locally so the preference is restored on the next visit.

## API authentication

Vercel, Cloudflare Workers, the local web service, and Docker deployments use the `YAML2SB_API_KEY` environment variable.

When the variable is unset or empty, authentication is not required. When configured, protected endpoints require a valid key.

Recommended authentication:

```http
Authorization: Bearer <API_KEY>
```

The API also supports:

```http
X-API-Key: <API_KEY>
```

and, where necessary:

```text
?api_key=<API_KEY>
```

Do not commit API keys, subscription credentials, or real private subscription URLs to the repository.

## Command-line usage

The conversion logic is shared by the web interface and command-line workflow. See the existing Python entry points and tests in the repository for local conversion and development.

## Project structure

- `public/index.html` — Web UI
- `templates/` — Built-in sing-box templates
- `worker.py` — Cloudflare Workers entry point
- `vercel.json` — Vercel configuration
- `wrangler.toml` — Cloudflare Workers configuration
- `tests/` — Conversion tests

## Security notes

Subscription URLs may contain private credentials. Deploy the service only in trusted environments and enable authentication before exposing management APIs publicly.

Never commit:

- API keys
- Subscription URLs containing credentials
- Private configuration files
- Production Redis or KV credentials

## License

This project is licensed under the [MIT License](LICENSE).

## Wiki

See the [GitHub Wiki](https://github.com/bacdown/yaml2sb/wiki) for additional usage and deployment information.
