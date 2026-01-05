import logging
from scripts.meta.meta_client import MetaClient
from scripts.shared.saas_db import get_client_config

logger = logging.getLogger(__name__)


class MetaService:
    def __init__(self):
        pass

    async def get_client_meta(self, token: str):
        """
        Recupera instância do MetaClient configurada para o cliente.
        """
        client = get_client_config(token)
        if not client:
            return None

        tools = client.get("tools_config", {})
        # Suporta chave nova 'whatsapp' e legada 'whatsapp_official'
        waba = tools.get("whatsapp") or tools.get("whatsapp_official") or {}

        if not waba.get("active"):
            return None

        access_token = waba.get("access_token") or waba.get("token")
        phone_id = waba.get("phone_id")

        if not access_token or not phone_id:
            return None

        return MetaClient(access_token, phone_id)

    async def list_templates(self, token: str, waba_id: str = None):
        """
        Lista templates de um cliente.
        """
        client = await self.get_client_meta(token)
        if not client:
            raise ValueError("Cliente não configurado ou Meta inativa")

        # Pega WABA ID do config se não passado
        if not waba_id:
            cl_conf = get_client_config(token)
            tools = cl_conf.get("tools_config", {})
            waba = tools.get("whatsapp") or tools.get("whatsapp_official") or {}
            waba_id = waba.get("waba_id")

        if not waba_id:
            raise ValueError("WABA ID não encontrado na configuração")

        return await client.get_templates(waba_id)

    async def send_message(
        self, token: str, to: str, template_name: str, language: str = "pt_BR"
    ):
        client = await self.get_client_meta(token)
        if not client:
            raise ValueError("Cliente inválido")

        return await client.send_message_template(to, template_name, language)
