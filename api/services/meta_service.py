import logging
from scripts.meta.meta_client import MetaClient
from scripts.shared.saas_db import get_client_config, get_provider_config

logger = logging.getLogger(__name__)


class MetaService:
    def _get_meta_cfg(self, token: str):
        """Retorna (client_config, meta_cfg) ou (None, None)."""
        client = get_client_config(token)
        if not client:
            return None, None
        meta_cfg = get_provider_config(str(client["id"]), "meta")
        if not meta_cfg:
            return None, None
        return client, meta_cfg

    async def get_client_meta(self, token: str):
        """Recupera instância do MetaClient configurada para o cliente."""
        _, meta_cfg = self._get_meta_cfg(token)
        if not meta_cfg:
            return None

        access_token = meta_cfg.get("access_token")
        phone_id = meta_cfg.get("phone_id")
        if not access_token or not phone_id:
            return None

        return MetaClient(access_token, phone_id)

    async def list_templates(self, token: str, waba_id: str = None):
        """Lista templates de um cliente."""
        _, meta_cfg = self._get_meta_cfg(token)
        if not meta_cfg:
            raise ValueError("Cliente não configurado ou Meta inativa")

        access_token = meta_cfg.get("access_token")
        phone_id = meta_cfg.get("phone_id")
        if not access_token or not phone_id:
            raise ValueError("Credenciais Meta incompletas")

        client = MetaClient(access_token, phone_id)
        waba_id = waba_id or meta_cfg.get("waba_id")
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
