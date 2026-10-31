import base64
import importlib
from urllib.parse import urlencode

from fastapi.testclient import TestClient


def test_unicode_login_and_untrusted_cookie(monkeypatch):
    monkeypatch.setenv("QD_DASH_USER", "dévan")
    monkeypatch.setenv("QD_DASH_PASS", "pässword")
    m = importlib.import_module("quant_desk.dashboard.app")
    c = TestClient(m.app, base_url="https://testserver")
    bad = c.post("/login", content=urlencode({"username": "dévan", "password": "wrong"}), follow_redirects=False)
    assert bad.status_code == 401
    good = c.post("/login", content=urlencode({"username": "dévan", "password": "pässword"}), follow_redirects=False)
    assert good.status_code == 303
    assert m._valid_token(m._make_token("dévan"))
    forged = base64.urlsafe_b64encode("dévan|9999999999|é".encode()).decode()
    assert not m._valid_token(forged)


def test_partial_auth_configuration_does_not_expose_dashboard(monkeypatch):
    monkeypatch.setenv("QD_DASH_USER", "devan")
    monkeypatch.delenv("QD_DASH_PASS", raising=False)
    m = importlib.import_module("quant_desk.dashboard.app")
    c = TestClient(m.app, base_url="https://testserver")
    assert c.get("/api/overview").status_code == 503
    assert c.post("/login", content="username=devan&password=x").status_code == 503
    assert c.get("/healthz").status_code == 200
