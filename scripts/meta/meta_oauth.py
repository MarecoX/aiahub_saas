import os
import requests
import logging

logger = logging.getLogger(__name__)


def exchange_code_for_token(code: str):
    """
    Troca o 'code' recebido do Embedded Signup por um Access Token de longo prazo.
    """
    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")

    if not app_id or not app_secret:
        logger.error("META_APP_ID ou META_APP_SECRET não configurados.")
        return None

    url = "https://graph.facebook.com/v24.0/oauth/access_token"

    # Payload para POST conforme documentação oficial
    payload = {
        "client_id": app_id,
        "client_secret": app_secret,
        "code": code,
        "grant_type": "authorization_code",
        # Redirect URI é opcional em alguns fluxos de popup, mas se exigido,
        # deve combinar com o configurado. Para embedded, muitas vezes é omitido ou fixo.
        # "redirect_uri": "..."
    }

    try:
        response = requests.post(url, json=payload)
        data = response.json()

        if response.status_code == 200 and "access_token" in data:
            logger.info("✅ Token de acesso obtido com sucesso via OAuth Exchange.")
            return data
        else:
            logger.error(f"❌ Erro ao trocar token: {data}")
            return None

    except Exception as e:
        logger.error(f"❌ Exceção no OAuth Exchange: {e}")
        return None
