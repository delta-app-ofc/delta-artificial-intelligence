"""Escrita pelo contrato interno da API Mongo, sem acesso direto de escrita ao histórico."""
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from app.config import get_settings

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class AlertsClient:
    def __init__(self, url=None, key=None):
        settings=get_settings()
        self.url=(url or settings.alerts_api_url or "").rstrip("/")
        self._key=key or settings.alerts_service_key
        parsed=urlsplit(self.url)
        if not self._key or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password or not (parsed.scheme=="https" or
            parsed.scheme=="http" and parsed.hostname in {"localhost","127.0.0.1","::1"}):
            raise ValueError("Configure ALERTS_API_URL e ALERTS_SERVICE_KEY com um destino seguro.")
        self._opener=build_opener(NoRedirect())
    def post(self, path, payload):
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
        request=Request(self.url+path,data=data,method="POST",headers={"Content-Type":"application/json","X-Service-Key":self._key})
        with self._opener.open(request,timeout=10) as response:
            return response.status,json.load(response)
    def create(self, payload): return self.post("/api/internal/alerts",payload)
    def resolve(self, key): return self.post("/api/internal/alerts/resolve",{"dedup_key":key})
