import httpx
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

META_API_VERSION = "v24.0"
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

    async def set_two_step_verification(self, pin: str) -> bool:
        """
        Define o PIN de verificação em duas etapas para o número de telefone.
        Endpoint: POST /{phone_number_id}
        Body: {"pin": "123456"}
        """
        url = f"{BASE_URL}/{self.phone_id}"
        payload = {"pin": pin}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=10
                )
                if response.status_code == 200 and response.json().get("success"):
                    logger.info(f"✅ PIN definido via API para {self.phone_id}")
                    return True
                else:
                    logger.error(f"❌ Falha ao definir PIN: {response.text}")
                    return False
            except Exception as e:
                logger.error(f"❌ Erro ao definir PIN API: {e}")
                return False

    async def request_verification_code(self, method: str = "SMS") -> bool:
        """
        Solicita o envio do código de verificação (SMS ou VOICE).
        POST /{phone_id}/request_code
        """
        url = f"{BASE_URL}/{self.phone_id}/request_code"
        payload = {"code_method": method, "language": "pt_BR"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=15
                )
                if response.status_code == 200:
                    success = response.json().get("success")
                    if success:
                        logger.info("✅ Código de verificação solicitado com sucesso.")
                        return True
                logger.error(f"❌ Falha ao solicitar código: {response.text}")
                return False
            except Exception as e:
                logger.error(f"❌ Erro ao solicitar código: {e}")
                return False

    async def verify_and_register(self, code: str, pin: str) -> bool:
        """
        Verifica o código recebido e registra o telefone com o PIN de 2 fatores.
        Passo 1: POST /{phone_id}/verify_code
        Passo 2: POST /{phone_id}/register
        """
        # 1. Verificar Código
        url_verify = f"{BASE_URL}/{self.phone_id}/verify_code"
        payload_verify = {"code": code}

        async with httpx.AsyncClient() as client:
            try:
                resp_verify = await client.post(
                    url_verify, headers=self.headers, json=payload_verify, timeout=15
                )
                if resp_verify.status_code != 200:
                    logger.error(f"❌ Código incorreto ou expirado: {resp_verify.text}")
                    return False

                # 2. Registrar (Definir PIN)
                url_register = f"{BASE_URL}/{self.phone_id}/register"
                payload_register = {"messaging_product": "whatsapp", "pin": pin}

                resp_register = await client.post(
                    url_register,
                    headers=self.headers,
                    json=payload_register,
                    timeout=15,
                )

                if resp_register.status_code == 200 and resp_register.json().get(
                    "success"
                ):
                    logger.info("✅ Telefone registrado com sucesso!")
                    return True

                logger.error(f"❌ Falha no registro final: {resp_register.text}")
                return False

            except Exception as e:
                logger.error(f"❌ Erro no fluxo de verificação: {e}")
                return False

    async def register_phone(self, pin: str) -> bool:
        """
        Registra o telefone na Cloud API (Finalização).
        Deve ser chamado se o status for VERIFIED mas 'Account does not exist'.
        POST /{phone_id}/register
        """
        url = f"{BASE_URL}/{self.phone_id}/register"
        payload = {"messaging_product": "whatsapp", "pin": pin}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=15
                )
                if response.status_code == 200 and response.json().get("success"):
                    logger.info("✅ Telefone registrado via API com sucesso!")
                    return True

                logger.error(f"❌ Falha no registro: {response.text}")
                return False
            except Exception as e:
                logger.error(f"❌ Erro ao registrar telefone: {e}")
                return False

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

    async def get_business_profile(self) -> Optional[Dict[str, Any]]:
        """
        Recupera os dados do Perfil de Negócios (Bio, Email, Site, etc).
        GET /{phone_id}/whatsapp_business_profile
        """
        url = f"{BASE_URL}/{self.phone_id}/whatsapp_business_profile"
        params = {
            "fields": "about,address,description,email,profile_picture_url,websites,vertical"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, headers=self.headers, params=params, timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    # A resposta geralmente é {"data": [{...}]}
                    if "data" in data and len(data["data"]) > 0:
                        return data["data"][0]
                return {}
            except Exception as e:
                logger.error(f"❌ Erro ao buscar Business Profile: {e}")
                return None

    async def update_business_profile(self, data: Dict[str, Any]) -> bool:
        """
        Atualiza os dados do Perfil.
        POST /{phone_id}/whatsapp_business_profile
        """
        url = f"{BASE_URL}/{self.phone_id}/whatsapp_business_profile"

        # Payload base obrigatório
        payload = {"messaging_product": "whatsapp", **data}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url, headers=self.headers, json=payload, timeout=15
                )
                if response.status_code == 200:
                    success = response.json().get("success")
                    if success:
                        logger.info("✅ Business Profile atualizado com sucesso!")
                        return True

                logger.error(f"❌ Falha ao atualizar perfil: {response.text}")
                return False
            except Exception as e:
                logger.error(f"❌ Erro ao atualizar Business Profile: {e}")
                return False

    async def get_media_url(self, media_id: str) -> Optional[str]:
        """
        Obtém a URL de download de uma mídia pelo ID.
        GET /{media_id}
        """
        url = f"{BASE_URL}/{media_id}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("url")
                else:
                    logger.error(
                        f"❌ Erro ao obter URL de mídia ({media_id}): {response.text}"
                    )
                    return None
            except Exception as e:
                logger.error(f"❌ Erro de conexão (get_media_url): {e}")
                return None

    async def download_media_bytes(self, media_url: str) -> Optional[bytes]:
        """
        Baixa o conteúdo binário de uma Mídia.
        Requer token no Header Authorization (já incluso self.headers).
        """
        async with httpx.AsyncClient() as client:
            try:
                # O download também precisa do Auth Header
                response = await client.get(media_url, headers=self.headers, timeout=30)
                if response.status_code == 200:
                    return response.content
                else:
                    logger.error(f"❌ Erro ao baixar binário: {response.status_code}")
                    return None
            except Exception as e:
                logger.error(f"❌ Erro download_media_bytes: {e}")
                return None
