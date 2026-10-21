# -*- coding: utf-8 -*-
"""The auto-approving OAuth facade, over real HTTP."""
import json
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import uvicorn  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from test_market import market  # noqa: E402
from uex_market import oauth_shim  # noqa: E402
from uex_market.server import build_server  # noqa: E402


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class OAuthShimTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m, _ = market()
        srv, _ = build_server(market=m)
        oauth_shim.install(srv, "https://uex.example.org")
        app = srv.streamable_http_app(
            json_response=True, stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"]))
        cls.port = _port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port,
                                                   log_level="warning"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        for _ in range(50):
            if cls.server.started:
                break
            time.sleep(0.1)
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True

    def call(self, path, data=None, headers=None, form=False):
        h = dict(headers or {})
        body = None
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode()
                h["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(data).encode()
                h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, headers=h)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def test_metadata(self):
        for path in ("/.well-known/oauth-protected-resource/mcp",
                     "/.well-known/oauth-protected-resource"):
            s, _, b = self.call(path)
            self.assertEqual(s, 200)
            self.assertEqual(json.loads(b)["resource"], "https://uex.example.org/mcp")
        for path in ("/.well-known/oauth-authorization-server",
                     "/.well-known/openid-configuration"):
            s, _, b = self.call(path)
            d = json.loads(b)
            self.assertEqual(d["registration_endpoint"], "https://uex.example.org/register")
            self.assertIn("jwks_uri", d)
        self.assertEqual(json.loads(self.call("/jwks")[2]), {"keys": []})

    def test_full_flow(self):
        cb = "https://claude.ai/api/mcp/auth_callback"
        s, _, b = self.call("/register", dict(redirect_uris=[cb], client_name="Claude"))
        self.assertEqual(s, 201)
        client = json.loads(b)["client_id"]
        q = urllib.parse.urlencode(dict(response_type="code", client_id=client,
                                        redirect_uri=cb, state="xyz",
                                        code_challenge="abc", code_challenge_method="S256"))
        s, h, _ = self.call("/authorize?" + q)
        self.assertEqual(s, 302)
        loc = urllib.parse.urlsplit(h["location"])
        params = urllib.parse.parse_qs(loc.query)
        self.assertEqual(loc.netloc, "claude.ai")
        self.assertEqual(params["state"], ["xyz"])
        s, _, b = self.call("/token", dict(grant_type="authorization_code", code=params["code"][0],
                                           redirect_uri=cb, client_id=client,
                                           code_verifier="v"), form=True)
        self.assertEqual(s, 200)
        tok = json.loads(b)
        self.assertEqual(tok["token_type"], "Bearer")
        s, _, b = self.call("/token", dict(grant_type="refresh_token",
                                           refresh_token=tok["refresh_token"]), form=True)
        self.assertEqual(s, 200)
        # The MCP endpoint works with that token, and without any.
        rpc = dict(jsonrpc="2.0", id=1, method="tools/list")
        hdr = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        for extra in ({"Authorization": "Bearer " + tok["access_token"]}, {}):
            s, _, b = self.call("/mcp", rpc, dict(hdr, **extra))
            self.assertEqual(s, 200)
            self.assertEqual(len(json.loads(b)["result"]["tools"]), 3)

    def test_no_open_redirect(self):
        for bad in ("https://evil.example/cb", "http://claude.ai/cb", "javascript:alert(1)",
                    "https://claude.ai.evil.example/cb"):
            s, _, _ = self.call("/register", dict(redirect_uris=[bad]))
            self.assertEqual(s, 400, bad)
            q = urllib.parse.urlencode(dict(response_type="code", redirect_uri=bad))
            s, _, _ = self.call("/authorize?" + q)
            self.assertEqual(s, 400, bad)
        self.assertTrue(oauth_shim.redirect_allowed("http://localhost:33418/callback",
                                                    oauth_shim.DEFAULT_REDIRECT_HOSTS))

    def test_bad_grant(self):
        s, _, _ = self.call("/token", dict(grant_type="password"), form=True)
        self.assertEqual(s, 400)


if __name__ == "__main__":
    unittest.main()
