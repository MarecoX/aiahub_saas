import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LancePilotClient:
    """
    Cliente para interação com a API do LancePilot (v3).
    API Oficial Wrapper / CRM.
    """

    BASE_URL = "https://lancepilot.com/api/v3"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_workspaces(self, search_query: str = None) -> list:
        """
        Lista os workspaces disponíveis.
        """
        try:
            url = f"{self.BASE_URL}/workspaces"
            # Tenta aumentar o limite padrão e passar busca
            params = {"limit": 100, "per_page": 100}
            if search_query:
                params["search"] = search_query

            response = httpx.get(url, headers=self.headers, params=params, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                items = data.get("data", [])

                # Client-side filtering fallback se a API ignorar o search param
                if search_query and items:
                    query = search_query.lower()
                    filtered = [
                        i
                        for i in items
                        if query in i.get("attributes", {}).get("name", "").lower()
                        or query in i.get("id", "").lower()
                    ]
                    # Se API já filtrou, filtered será igual (ou menor).
                    # Se API trouxe tudo, filtered reduz.
                    return filtered

                return items
            return []
        except Exception as e:
            logger.error(f"Erro ao buscar workspaces: {e}")
            return []

    def check_can_send_via_number(self, workspace_id: str, phone_number: str) -> bool:
        """
        Verifica se é possível enviar mensagem (Janela de 24h) via número.
        GET /workspaces/{workspace}/contacts/number/{number}/can-send-free-message
        """
        try:
            url = f"{self.BASE_URL}/workspaces/{workspace_id}/contacts/number/{phone_number}/can-send-free-message"
            response = httpx.get(url, headers=self.headers, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("canSend", False)
            elif response.status_code == 404:
                return False
            else:
                logger.warning(
                    f"LancePilot Check Status: {response.status_code} - {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Erro ao verificar can-send: {e}")
            return False

    def send_text_message_via_number(
        self, workspace_id: str, phone_number: str, text: str
    ) -> Dict[str, Any]:
        """
        Envia mensagem de texto via número.
        POST /workspaces/{workspace}/contacts/number/{number}/messages/text
        Payload: { "text": { "body": "..." } }
        """
        try:
            url = f"{self.BASE_URL}/workspaces/{workspace_id}/contacts/number/{phone_number}/messages/text"
            payload = {"text": {"body": text}}

            response = httpx.post(url, json=payload, headers=self.headers, timeout=15.0)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Erro HTTP LancePilot Send: {e.response.status_code} - {e.response.text}"
            )
            raise e
        except Exception as e:
            logger.error(f"Erro LancePilot Send: {e}")
            raise e

    def send_image_message_via_number(
        self, workspace_id: str, phone_number: str, image_url: str, caption: str = ""
    ) -> Dict[str, Any]:
        """
        Envia mensagem de imagem via número (usando URL).
        POST /workspaces/{workspace}/contacts/number/{number}/messages/image
        Payload: { "file": "https://...", "caption": "..." }
        """
        try:
            url = f"{self.BASE_URL}/workspaces/{workspace_id}/contacts/number/{phone_number}/messages/image"
            payload = {"file": image_url, "caption": caption}

            response = httpx.post(url, json=payload, headers=self.headers, timeout=15.0)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Erro HTTP LancePilot Send Image: {e.response.status_code} - {e.response.text}"
            )
            raise e
        except Exception as e:
            logger.error(f"Erro LancePilot Send Image: {e}")
            raise e
