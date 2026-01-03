import httpx
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

META_API_VERSION = "v23.0"
BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"


class MetaClient:
    """
    Cliente para interação com a Graph API do WhatsApp Business (Meta).
    Abstrai chamadas HTTP puras.
    """

    def __init__(self, token: str, phone_id: str):
        self.token = token
        self.phone_id = phone_id
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def send_message_text(self, to: str, text: str) -> Optional[Dict[str, Any]]:
        """Envia mensagem de texto simples."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return await self._post_message(payload)

    async def send_message_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "pt_BR",
        components: List[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """Envia mensagem de template (obrigatório para iniciar conversas após 24h)."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components

        return await self._post_message(payload)

    async def _post_message(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Método interno genérico de envio."""
        url = f"{BASE_URL}/{self.phone_id}/messages"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=15
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"❌ Erro HTTP Meta ({e.response.status_code}): {e.response.text}"
                )
                return None
            except Exception as e:
                logger.error(f"❌ Erro ao conectar Meta: {e}")
                return None

    async def get_templates(
        self, waba_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Busca templates aprovados na conta WABA.
        Necessário permissão: whatsapp_business_management
        """
        url = f"{BASE_URL}/{waba_id}/message_templates"
        params = {"limit": limit, "status": "APPROVED"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=self.headers, params=params, timeout=15
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"❌ Erro ao buscar templates ({e.response.status_code}): {e.response.text}"
                )
                return []
            except Exception as e:
                logger.error(f"❌ Erro de conexão Meta Templates: {e}")
                return []

    async def subscribe_app_to_waba(self, waba_id: str) -> bool:
        """
        Subscreve o App (dono do Token) aos eventos da WABA.
        Essencial para receber Webhooks.
        """
        url = f"{BASE_URL}/{waba_id}/subscribed_apps"
        async with httpx.AsyncClient() as client:
            try:
                # POST sem body para inscrever
                response = await client.post(url, headers=self.headers, timeout=10)
                if response.status_code == 200 and "success" in response.json():
                    logger.info(f"✅ WABA {waba_id} subscrita no App com sucesso.")
                    return True
                logger.error(f"❌ Falha ao subscrever WABA: {response.text}")
                return False
            except Exception as e:
                logger.error(f"❌ Erro subscrever WABA: {e}")
                return False

    async def create_template(
        self,
        name: str,
        category: str,
        components: List[Dict[str, Any]],
        language: str = "pt_BR",
    ) -> Optional[Dict[str, Any]]:
        """
        Cria um novo template de mensagem na WABA.
        Necessário para aprovação 'whatsapp_business_management'.
        """
        url = f"{BASE_URL}/{self.phone_id}/message_templates"
        # Para criar templates, usamos o WABA ID, não o Phone ID.
        # Mas a Meta aceita via WABA ID. Vamos precisar do WABA ID aqui.
        # Ajuste: O método precisa receber o WABA ID, ou o cliente precisa ser inicializado com ele.
        # Por padrão, vamos tentar usar o phone_id se o waba_id não for passado,
        # mas a documentação diz POST /{whatsapp-business-account-id}/message_templates.
        # O self.phone_id é o ID do número.
        pass

    async def create_template_waba(
        self,
        waba_id: str,
        name: str,
        category: str,
        components: List[Dict[str, Any]],
        language: str = "pt_BR",
    ) -> Optional[Dict[str, Any]]:
        """
        Cria template usando o WABA ID correto.
        """
        url = f"{BASE_URL}/{waba_id}/message_templates"

        payload = {
            "name": name,
            "category": category,
            "components": components,
            "language": language,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=15
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"❌ Erro Criar Template ({e.response.status_code}): {e.response.text}"
                )
                return {"error": e.response.json()}
            except Exception as e:
                logger.error(f"❌ Erro de conexão Meta Create Template: {e}")
                return {"error": str(e)}

    async def get_phone_number_info(self) -> Optional[Dict]:
        """Busca dados do número para validar conexão."""
        url = f"{BASE_URL}/{self.phone_id}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    return response.json()
                return None
            except Exception:
                return None
