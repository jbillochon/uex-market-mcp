# -*- coding: utf-8 -*-
"""Auto-approving OAuth facade for clients that insist on OAuth.

The UEX tools are public and read-only, so the server needs no
authentication. Some clients (claude.ai custom connectors, as of 2026) still
run OAuth discovery and Dynamic Client Registration when the user clicks
"Connect", and give up if the server has no registration endpoint. This
module answers that flow without asking anything: any client registers,
/authorize redirects straight back with a code, /token hands out a token.

The token grants nothing: the MCP endpoint ignores Authorization headers and
stays open to everyone. Security is unchanged; the facade only lets those
clients complete their flow. Only redirect URIs on an allowlist of hosts are
accepted, so /authorize cannot be used as an open redirector.

Enabled with --oauth-shim (or UEX_MCP_OAUTH_SHIM=1) and the public base URL
(--public-url or UEX_MCP_PUBLIC_URL). Off by default.
"""
from __future__ import annotations

import secrets
import time
import urllib.parse

DEFAULT_REDIRECT_HOSTS = ("claude.ai", "claude.com", "localhost", "127.0.0.1")
TOKEN_TTL = 30 * 86400


def _json(data, status=200):
    from starlette.responses import JSONResponse
    return JSONResponse(data, status_code=status, headers=dict([("Cache-Control", "no-store")]))


def _error(code, description, status=400):
    return _json(dict(error=code, error_description=description), status)


def redirect_allowed(uri, hosts):
    try:
        u = urllib.parse.urlsplit(uri or "")
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme == "http":
        return host in ("localhost", "127.0.0.1") and host in hosts
    if u.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in hosts)


def metadata(base, mcp_path="/mcp"):
    base = base.rstrip("/")
    return dict(
        resource=dict(
            resource=base + mcp_path,
            authorization_servers=[base],
            bearer_methods_supported=["header"],
            scopes_supported=["mcp"],
            resource_documentation="https://github.com/jbillochon/uex-market-mcp",
        ),
        server=dict(
            issuer=base,
            authorization_endpoint=base + "/authorize",
            token_endpoint=base + "/token",
            registration_endpoint=base + "/register",
            jwks_uri=base + "/jwks",
            scopes_supported=["mcp"],
            response_types_supported=["code"],
            response_modes_supported=["query"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none", "client_secret_post",
                                                   "client_secret_basic"],
            code_challenge_methods_supported=["S256"],
            # OpenID fields: some clients validate the document as OIDC.
            subject_types_supported=["public"],
            id_token_signing_alg_values_supported=["RS256"],
        ),
    )


def install(mcp, base, mcp_path="/mcp", redirect_hosts=DEFAULT_REDIRECT_HOSTS):
    """Register the OAuth routes on an MCPServer (custom routes)."""
    meta = metadata(base, mcp_path)
    hosts = tuple(h.strip().lower() for h in redirect_hosts if h.strip())

    async def protected_resource(request):  # noqa: ARG001
        return _json(meta["resource"])

    async def authorization_server(request):  # noqa: ARG001
        return _json(meta["server"])

    for path in ("/.well-known/oauth-protected-resource",
                 "/.well-known/oauth-protected-resource" + mcp_path):
        mcp.custom_route(path, methods=["GET"])(protected_resource)
    for path in ("/.well-known/oauth-authorization-server",
                 "/.well-known/openid-configuration"):
        mcp.custom_route(path, methods=["GET"])(authorization_server)

    @mcp.custom_route("/jwks", methods=["GET"])
    async def jwks(request):  # noqa: ARG001
        return _json(dict(keys=[]))

    @mcp.custom_route("/register", methods=["POST"])
    async def register(request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = dict()
        if not isinstance(body, dict):
            body = dict()
        uris = body.get("redirect_uris") or []
        if not isinstance(uris, list) or not uris:
            return _error("invalid_redirect_uri", "redirect_uris is required")
        refused = [u for u in uris if not redirect_allowed(u, hosts)]
        if refused:
            return _error("invalid_redirect_uri", "redirect URI not allowed: %s" % refused[0])
        out = dict(
            client_id="uex-" + secrets.token_urlsafe(16),
            client_id_issued_at=int(time.time()),
            redirect_uris=uris,
            token_endpoint_auth_method=body.get("token_endpoint_auth_method") or "none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name=str(body.get("client_name") or "")[:100],
            scope="mcp",
        )
        if out["token_endpoint_auth_method"] != "none":
            out["client_secret"] = secrets.token_urlsafe(24)
            out["client_secret_expires_at"] = 0
        return _json(out, 201)

    @mcp.custom_route("/authorize", methods=["GET"])
    async def authorize(request):
        from starlette.responses import RedirectResponse
        q = request.query_params
        uri = q.get("redirect_uri")
        if not redirect_allowed(uri, hosts):
            return _error("invalid_request", "redirect_uri missing or not allowed")
        params = dict()
        if q.get("response_type") != "code":
            params["error"] = "unsupported_response_type"
        else:
            params["code"] = secrets.token_urlsafe(24)
        if q.get("state"):
            params["state"] = q.get("state")
        params["iss"] = meta["server"]["issuer"]
        sep = "&" if "?" in uri else "?"
        return RedirectResponse(uri + sep + urllib.parse.urlencode(params), status_code=302)

    @mcp.custom_route("/token", methods=["POST"])
    async def token(request):
        try:
            form = await request.form()
        except Exception:  # noqa: BLE001
            return _error("invalid_request", "form body expected")
        grant = form.get("grant_type")
        if grant not in ("authorization_code", "refresh_token"):
            return _error("unsupported_grant_type", "grant_type not supported")
        return _json(dict(
            access_token=secrets.token_urlsafe(32),
            token_type="Bearer",
            expires_in=TOKEN_TTL,
            refresh_token=secrets.token_urlsafe(32),
            scope="mcp",
        ))

    return meta
