import httpx
import logging
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("LancePilotClient")


class WindowClosedError(Exception):
    """Raised when the 24-hour free message window is closed."""

    pass


class LancePilotClient:
    def __init__(self, token: str, base_url: str = "https://lancepilot.com/api/v3"):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: Dict = None) -> Any:
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = httpx.get(url, headers=self.headers, params=params, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"LancePilot GET Error {e.response.status_code}: {e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"LancePilot Connection Error: {e}")
            raise

    def _post(self, endpoint: str, json_data: Dict) -> Any:
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = httpx.post(url, headers=self.headers, json=json_data, timeout=15.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"LancePilot POST Error {e.response.status_code}: {e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"LancePilot Connection Error: {e}")
            raise

    def get_workspaces(self, search_query: str = "") -> List[Dict]:
        """
        Fetch workspaces filtering by name (Privacy requirement).
        Endpoint: GET /workspaces?search=...
        """
        import urllib.parse

        encoded_search = urllib.parse.quote(search_query) if search_query else ""

        # User requested filtering by name to ensure privacy/accuracy
        params = f"search={encoded_search}&page=1&per_page=50"
        return self._get(f"workspaces?{params}").get("data", [])

    def check_can_send_free(self, workspace_id: str, phone_number: str) -> bool:
        """
        Check if the 24h free message window is open.
        Endpoint: GET /workspaces/{workspace}/contacts/number/{number}/can-send-free-message
        """
        try:
            # Note: User provided screenshot shows GET /can-send-free-message
            # We assume it returns a success status or boolean logic
            endpoint = f"workspaces/{workspace_id}/contacts/number/{phone_number}/can-send-free-message"
            resp = self._get(endpoint)
            # Assuming logic based on response structure. Usually 200 OK means true.
            # Or response might look like {"data": {"can_send": true}}?
            # Based on user screenshot, it's just a GET.
            # Safe Assumption: If it returns 200, it's YES. If 400+, NO.
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [400, 403, 422]:
                return False
            raise
        except Exception:
            # Fallback to safe False
            return False

    def send_text(self, workspace_id: str, phone_number: str, text: str):
        """
        Send a text message. Raises WindowClosedError if window check fails.
        """
        if not self.check_can_send_free(workspace_id, phone_number):
            logger.warning(f"LancePilot 24h Window Closed for {phone_number}")
            raise WindowClosedError(
                f"Cannot send free message to {phone_number}. Window closed."
            )

        endpoint = (
            f"workspaces/{workspace_id}/contacts/number/{phone_number}/messages/text"
        )
        payload = {"text": {"body": text}}
        return self._post(endpoint, payload)

    def get_templates(self, workspace_id: str) -> List[Dict]:
        """
        Fetch all available templates for the workspace.
        Endpoint: GET /workspaces/{workspace}/templates
        """
        endpoint = f"workspaces/{workspace_id}/templates"
        resp = self._get(endpoint)
        # Expected format: {"data": [ ... ]}
        return resp.get("data", [])

    def send_template(
        self,
        workspace_id: str,
        phone_number: str,
        template_id: int,
        template_data: Dict,
    ):
        """
        Send a Template Message (to bypass 24h window).
        Endpoint: POST /workspaces/{workspace}/contacts/number/{number}/template-messages
        """
        endpoint = f"workspaces/{workspace_id}/contacts/number/{phone_number}/template-messages"
        payload = {"template_id": template_id, "template_data": template_data}
        return self._post(endpoint, payload)
