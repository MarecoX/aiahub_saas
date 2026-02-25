"""
client.py - HTTP Client para a API do Attlas CRM

Encapsula autenticação (Sanctum), multi-tenant e chamadas HTTP.
Todas as tools usam este client como base.
"""

import httpx
import logging
from typing import Any, Optional

logger = logging.getLogger("AttlasCRM.Client")

# Timeout padrão em segundos
DEFAULT_TIMEOUT = 30.0


class AttlasCRMClient:
    """Cliente HTTP para a API REST do Attlas CRM (multi-tenant)."""

    def __init__(self, base_url: str, token: str):
        """
        Args:
            base_url: URL base do tenant (ex: https://empresa.attlascrm.com)
            token: Token Sanctum (Bearer) para autenticação
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        """Monta URL completa a partir do path relativo."""
        return f"{self.base_url}/api/v1{path}"

    def _handle_response(self, resp: httpx.Response) -> dict | list | str:
        """Processa resposta HTTP e retorna dados ou mensagem de erro."""
        try:
            data = resp.json()
        except Exception:
            data = resp.text

        if resp.status_code >= 400:
            error_msg = ""
            if isinstance(data, dict):
                error_msg = data.get("message", "")
                errors = data.get("errors", {})
                if errors:
                    details = []
                    for field, msgs in errors.items():
                        if isinstance(msgs, list):
                            details.append(f"{field}: {', '.join(msgs)}")
                        else:
                            details.append(f"{field}: {msgs}")
                    error_msg += " | " + " | ".join(details)
            else:
                error_msg = str(data)

            logger.warning(
                f"AttlasCRM API {resp.status_code}: {resp.request.method} {resp.request.url} -> {error_msg}"
            )
            return {"error": True, "status": resp.status_code, "message": error_msg}

        return data

    # ─── Métodos HTTP ───

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """GET request."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(self._url(path), headers=self._headers, params=params)
            return self._handle_response(resp)

    def post(self, path: str, json_data: Optional[dict | list] = None) -> Any:
        """POST request."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(self._url(path), headers=self._headers, json=json_data)
            return self._handle_response(resp)

    def put(self, path: str, json_data: Optional[dict] = None) -> Any:
        """PUT request."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.put(self._url(path), headers=self._headers, json=json_data)
            return self._handle_response(resp)

    def patch(self, path: str, json_data: Optional[dict] = None) -> Any:
        """PATCH request."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.patch(self._url(path), headers=self._headers, json=json_data)
            return self._handle_response(resp)

    def delete(self, path: str, json_data: Optional[dict] = None) -> Any:
        """DELETE request."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.delete(
                self._url(path), headers=self._headers, json=json_data
            )
            return self._handle_response(resp)


def build_client(config: dict) -> AttlasCRMClient:
    """
    Factory: cria AttlasCRMClient a partir do config do tool_registry.

    Args:
        config: Dict com keys 'base_url' e 'token'

    Returns:
        AttlasCRMClient configurado
    """
    base_url = config.get("base_url", "")
    token = config.get("token", "")
    if not base_url or not token:
        raise ValueError("attlas_crm requer 'base_url' e 'token' configurados.")
    return AttlasCRMClient(base_url=base_url, token=token)
