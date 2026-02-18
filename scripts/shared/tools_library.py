import sys
import os
import json
import httpx
import logging
from typing import Optional
from pydantic import Field
from langchain.tools import tool
from langchain_core.tools import StructuredTool

logger = logging.getLogger("KestraTools")

# Garante que o diretório atual está no path para as ferramentas (Docker/Kestra fix)
_shared_dir = os.path.dirname(os.path.abspath(__file__))
if _shared_dir not in sys.path:
    sys.path.append(_shared_dir)
# Adiciona também o diretório pai (scripts) para suportar scripts.shared...
_scripts_dir = os.path.abspath(os.path.join(_shared_dir, ".."))
if _scripts_dir not in sys.path:
    sys.path.append(_scripts_dir)

try:
    # 1. Tenta import direto (se shared_dir estiver no path)
    from sgp_tools import get_sgp_tools

    logger.info("✅ SGP Tools carregadas via import direto.")
except ImportError:
    try:
        # 2. Tenta via scripts.shared (se root estiver no path - fallback Kestra)
        from scripts.shared.sgp_tools import get_sgp_tools

        logger.info("✅ SGP Tools carregadas via scripts.shared.")
    except ImportError:
        try:
            # 3. Tenta via Kestra_2.0 path absoluto
            import importlib.util

            sgp_path = os.path.join(_shared_dir, "sgp_tools.py")
            if os.path.exists(sgp_path):
                spec = importlib.util.spec_from_file_location(
                    "sgp_tools_dynamic", sgp_path
                )
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                get_sgp_tools = m.get_sgp_tools
                logger.info("✅ SGP Tools carregadas via importlib (Path Absoluto).")
            else:
                raise ImportError(f"Arquivo não encontrado: {sgp_path}")
        except Exception as e:
            error_msg = str(e)

            def get_sgp_tools():
                logger.warning(f"⚠️ SGP Tools fallback (vazio) ativado: {error_msg}")
                return []


# Tenta pegar API Key do Maps, ou fallback pro Gemini (se for a mesma key irrestrita)
# Obtém chave específica do Maps. SEM fallback para Gemini para evitar erros de permissão.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if GOOGLE_MAPS_API_KEY:
    logger.info(f"🗺️ Google Maps Key carregada: ...{GOOGLE_MAPS_API_KEY[-4:]}")
else:
    logger.warning(
        "⚠️ GOOGLE_MAPS_API_KEY não encontrada! A tool consultar_cep vai falhar."
    )


try:
    # Tenta importar como se 'shared' estivesse no path (setup do Docker/Kestra)
    from cal_tools import (
        get_available_slots,
        create_booking,
        reschedule_booking,
        cancel_booking,
    )
    from saas_db import get_provider_config
except ImportError:
    # Tenta importar do caminho completo (setup local/IDE)
    try:
        from scripts.shared.cal_tools import (
            get_available_slots,
            create_booking,
            reschedule_booking,
            cancel_booking,
        )
        from scripts.shared.saas_db import get_provider_config
    except ImportError:
        # Fallback final se saas_db não estiver no path
        def get_provider_config(*args, **kwargs):
            return {}

        pass
    try:
        from scripts.shared.cal_tools import (
            get_available_slots,
            create_booking,
            reschedule_booking,
            cancel_booking,
        )
    except ImportError:
        logger.error(
            "❌ Não foi possível importar cal_tools (nem direto, nem via scripts.shared)"
        )
        raise


@tool
def consultar_cep(cep: str):
    """
    Consulta o endereço de um CEP brasileiro usando Google Maps Geocoding API.
    Args:
        cep (str): O CEP a ser consultado (ex: 01001000 ou 01001-000).
    """
    if not GOOGLE_MAPS_API_KEY:
        return {"error": "API Key de Mapas não configurada."}
    # Limpa o CEP
    clean_cep = cep.replace("-", "").replace(".", "").strip()
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "components": f"postal_code:{clean_cep}|country:BR",
        "key": GOOGLE_MAPS_API_KEY,
    }
    try:
        # EXECUÇÃO SÍNCRONA (Segura para ThreadPool)
        with httpx.Client() as client:
            resp = client.get(url, params=params, timeout=10.0)
            data = resp.json()
            # Log de Debug Profundo
            logger.info(
                f"🗺️ Maps API Status: {data.get('status')} | Results: {len(data.get('results', []))}"
            )
            if data["status"] != "OK":
                logger.error(f"❌ Erro Maps API: {data}")
                return {"error": f"Google Maps Error: {data['status']}"}
            if not data["results"]:
                return {
                    "error": "CEP não encontrado (ZERO_RESULTS). Verifique o número."
                }
            # Simplifica a resposta para o LLM não se perder
            result = data["results"][0]
            # logger.info(f"💬 Query do Usuário: {result}")
            formatted_address = result.get(
                "formatted_address", "Endereço não formatado"
            )
            location = result.get("geometry", {}).get("location", {})
            components = {}
            for comp in result.get("address_components", []):
                types = comp.get("types", [])
                if "route" in types:
                    components["logradouro"] = comp["long_name"]
                elif "sublocality" in types:
                    components["bairro"] = comp["long_name"]
                elif "administrative_area_level_2" in types:
                    components["cidade"] = comp["long_name"]
                elif "administrative_area_level_1" in types:
                    components["estado"] = comp["short_name"]
            final_payload = {
                "cep": clean_cep,
                "endereco": formatted_address,
                "detalhes": components,
                "lng": location.get("lng"),
                "system_note": "FIM DA AÇÃO. O endereço já foi retornado. Use estes dados para responder ao cliente. NÃO CHAME MAIS NENHUMA TOOL.",
            }
            logger.info(f"✅ Retornando para o Agente: {final_payload}")
            return final_payload
    except Exception as e:
        logger.error(f"Erro no consultar_cep: {e}")
        return {"error": str(e)}


@tool
def qualificado_kommo_provedor(
    nome: str, telefone: str, plano: str, kommo_config: dict = None
):
    """
    Registra um lead qualificado movendo-o para a etapa correta no Kommo CRM.
    Args:
        nome (str): Nome do cliente
        telefone (str): Telefone
        plano (str): Plano escolhido
    """
    if not kommo_config:
        return {
            "error": "Configuração do Kommo CRM não encontrada (kommo_config is None)."
        }
    base_url = kommo_config.get("url")
    auth_header = {"Authorization": kommo_config.get("token")}
    pipeline_id = kommo_config.get("pipeline_id")
    status_id = kommo_config.get("status_id")  # Status ID de "Lead Qualificado"
    if not base_url or not auth_header["Authorization"]:
        return {"error": "URL ou Token do Kommo não configurados."}
    logger.info(f"🚀 Iniciando Qualificação Kommo para {nome} - {telefone}")
    try:
        with httpx.Client() as client:
            # 1. Buscar Contact ID pelo Telefone
            # Importante: O telefone deve estar limpo ou no formato que o Kommo espera.
            clean_phone = telefone.split("@")[0]
            clean_phone = (
                clean_phone.replace("+", "").replace("-", "").replace(" ", "").strip()
            )
            # --- FIX: Formatação BR (Adiciona 55 se vier apenas DDD + Numero) ---
            # Ex: 61981287914 (11 digitos) -> 5561981287914
            if clean_phone.isdigit() and len(clean_phone) in [10, 11]:
                clean_phone = f"55{clean_phone}"
                logger.info(f"🇧🇷 Telefone formatado para BR: {clean_phone}")
            search_url = f"{base_url}/api/v4/contacts"
            # Adicionado 'with=leads' para garantir que venham os leads associados
            resp_search = client.get(
                search_url,
                params={"query": clean_phone, "with": "leads"},
                headers=auth_header,
            )
            if resp_search.status_code != 200:
                logger.error(f"Erro Busca Kommo: {resp_search.text}")
                return {"error": f"Erro ao buscar contato: {resp_search.status_code}"}
            data_search = resp_search.json()
            contacts = data_search.get("_embedded", {}).get("contacts", [])
            lead_id = None
            if not contacts:
                # Se não achou contato, poderíamos criar tudo do zero, mas por segurança retornamos erro orientativo
                # Ou poderíamos criar Contato + Lead. Vamos manter erro por enquanto para não duplicar se formatacao estiver errada.
                return {
                    "error": "Contato não encontrado no CRM pelo telefone fornecido."
                }
            contact = contacts[0]
            contact_id = contact["id"]
            leads = contact.get("_embedded", {}).get("leads", [])
            if leads:
                # Pega o primeiro lead (assumindo ser o ativo/mais recente)
                lead_id = leads[0]["id"]
                logger.info(f"Lead existente encontrado: {lead_id}")
                # Atualizar Status (PATCH)
                patch_url = f"{base_url}/api/v4/leads"
                payload_item = {"id": int(lead_id), "status_id": int(status_id)}
                if pipeline_id:
                    payload_item["pipeline_id"] = int(pipeline_id)
                resp_patch = client.patch(
                    patch_url, json=[payload_item], headers=auth_header
                )
                if resp_patch.status_code not in [200, 202]:
                    return {
                        "error": f"Falha ao mover lead existente: {resp_patch.text}"
                    }
            else:
                # Contato existe, mas sem Lead -> CRIAR LEAD NOVO
                logger.info(f"Contato {contact_id} sem leads. Criando novo Lead...")
                create_url = f"{base_url}/api/v4/leads_complex"  # Usando complex para garantir link
                # Ou usar POST /leads simples com _embedded contacts
                create_url = f"{base_url}/api/v4/leads"
                new_lead_payload = [
                    {
                        "name": f"Lead IA - {nome}",
                        "status_id": int(status_id),
                        "pipeline_id": int(pipeline_id) if pipeline_id else None,
                        "_embedded": {"contacts": [{"id": int(contact_id)}]},
                    }
                ]
                resp_create = client.post(
                    create_url, json=new_lead_payload, headers=auth_header
                )
                if resp_create.status_code not in [200, 201, 202]:
                    logger.error(f"Erro ao criar Lead: {resp_create.text}")
                    return {"error": f"Falha ao criar novo lead: {resp_create.text}"}
                # Tenta extrair ID do criado
                try:
                    lead_id = resp_create.json()["_embedded"]["leads"][0]["id"]
                except Exception:
                    lead_id = "recém-criado"
            logger.info(f"✅ Lead {lead_id} qualificado/criado com Status {status_id}")
            return {
                "status": "success",
                "message": f"Sucesso! Lead {lead_id} processado para etapa qualificada.",
            }
    except Exception as e:
        logger.error(f"Erro Tool Kommo: {e}")
        return {"error": str(e)}


@tool
def consultar_erp(nome_produto: str, betel_config: dict = None):
    """
    Consulta o ERP (Betel) para verificar preço e estoque de um produto.
    Use quando o cliente perguntar sobre "quanto custa", "tem tal peça", etc.
    Args:
        nome_produto (str): Nome do produto para busca (ex: "iphone 13 tela", "samsung a54 bateria").
    """
    if not betel_config:
        return {"error": "Configuração do ERP Betel não encontrada."}
    # Extrai configs
    loja_id = betel_config.get("loja_id")
    access_token = betel_config.get("access_token")
    secret_token = betel_config.get("secret_token")
    base_url = "https://api.beteltecnologia.com/produtos"
    if not all([loja_id, access_token, secret_token]):
        return {
            "error": "Credenciais Betel incompletas (loja_id, access_token, secret_token)."
        }
    headers = {
        "Content-Type": "application/json",
        "access-token": access_token,
        "secret-access-token": secret_token,
    }
    params = {"loja_id": loja_id, "nome": nome_produto}
    logger.info(f"🔎 Buscando produto Betel: {nome_produto} (Loja {loja_id})")
    try:
        with httpx.Client() as client:
            resp = client.get(base_url, params=params, headers=headers, timeout=15.0)
            if resp.status_code != 200:
                logger.error(f"❌ Erro Betel API: {resp.status_code} - {resp.text}")
                return {"error": f"Erro na API ERP: {resp.status_code}"}
            data = resp.json()
            # Ajuste conforme retorno real (assumindo lista direta ou chave 'data')
            # O print n8n sugere retorno direto de itens? Vamos assumir que sim ou verificar.
            # Se for muito grande, limitamos.
            # Formata para o LLM
            produtos_formatados = []
            lista_bluta = data if isinstance(data, list) else data.get("data", [])
            for p in lista_bluta[:10]:  # Top 10
                produtos_formatados.append(
                    {
                        "id": p.get("id"),
                        "nome": p.get("nome"),
                        "preco": p.get("preco_venda", "N/A"),
                        "estoque": p.get("estoque_atual", "N/A"),
                    }
                )
            if not produtos_formatados:
                return "Nenhum produto encontrado com esse nome."
            return produtos_formatados
    except Exception as e:
        logger.error(f"Erro Tool Betel: {e}")
        return {"error": str(e)}


@tool
def enviar_relatorio(
    tipo: str = "ficha",
    dados: dict = None,
    grupo_id: str = None,
    uazapi_url: str = None,
    uazapi_token: str = None,
    template: str = None,
    provider_type: str = None,
    provider_config: dict = None,
):
    """
    Envia um relatório (ficha, reserva, pedido) para um grupo do WhatsApp.
    Use quando o cliente confirmar interesse, fechar pedido ou reservar produto.
    Args:
        tipo (str): Tipo do relatório ("ficha", "reserva", "pedido", etc.)
        dados (dict): Dados coletados (nome, telefone, produto, valor, etc.)
    """
    import asyncio

    logger.info(f"📤 Enviando Relatório ({tipo}) para grupo {grupo_id} via {provider_type or 'uazapi'}")
    missing = []
    if not grupo_id:
        missing.append("grupo_id")
    if not provider_type and not uazapi_url:
        missing.append("credenciais do provider")
    if missing:
        logger.warning(
            f"⚠️ Configuração incompleta: {', '.join(missing)}. Relatório não enviado."
        )
        return f"Erro: Configurações ausentes ({', '.join(missing)}). Verifique o cadastro."
    if not dados:
        dados = {}
    # Valida se tem dados para preencher o template
    if template and not dados:
        logger.warning("⚠️ Template definido mas dados vazios! Não foi possível enviar.")
        return "Erro: Você precisa coletar os dados do cliente antes de enviar o relatório. Pergunte: nome, CPF, RG, data de nascimento, nome da mãe, email, endereço, plano, cidade, dia de vencimento e se quer débito automático."
    # Monta mensagem
    if template:
        msg = template
        for key, val in dados.items():
            msg = msg.replace(f"{{{{{key}}}}}", str(val))
    else:
        linhas = [f"📋 *Novo {tipo.upper()}*", ""]
        for key, val in dados.items():
            linhas.append(f"• {key}: {val}")
        msg = "\n".join(linhas)

    # Envia via provider configurado
    async def _send():
        async with httpx.AsyncClient() as client:
            p_type = provider_type or "uazapi"
            p_cfg = provider_config or {}

            if p_type == "uazapi":
                url = p_cfg.get("url") or uazapi_url
                token = p_cfg.get("token") or uazapi_token
                resp = await client.post(
                    f"{url.rstrip('/')}/send/text",
                    json={"number": grupo_id, "text": msg},
                    headers={"token": token},
                    timeout=30.0,
                )
            elif p_type == "lancepilot":
                token = p_cfg.get("token", "")
                workspace = p_cfg.get("workspace_id", "")
                lp_url = f"https://lancepilot.com/api/v3/workspaces/{workspace}/contacts/number/{grupo_id}/messages/text"
                resp = await client.post(
                    lp_url,
                    json={"text": {"body": msg}},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=15.0,
                )
            elif p_type == "meta":
                access_token = p_cfg.get("access_token") or p_cfg.get("token", "")
                phone_id = p_cfg.get("phone_id", "")
                resp = await client.post(
                    f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                    json={
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": grupo_id,
                        "type": "text",
                        "text": {"body": msg},
                    },
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    timeout=15.0,
                )
            else:
                return None, f"Provider desconhecido: {p_type}"

            return resp, None

    try:
        resp, err = asyncio.run(_send())
        if err:
            return f"Erro ao enviar relatório: {err}"
        if resp.status_code in [200, 201]:
            logger.info(f"✅ Relatório enviado para {grupo_id} via {provider_type or 'uazapi'}")
            return "SUCESSO: Relatório enviado. AÇÃO CONCLUÍDA. NÃO chame esta ferramenta novamente. Apenas responda ao usuário confirmando."
        else:
            logger.error(f"❌ Erro envio: {resp.status_code} - {resp.text}")
            return f"Erro ao enviar relatório: {resp.status_code}"
    except Exception as e:
        logger.error(f"Erro enviar_relatorio: {e}")
        return f"Erro ao enviar: {e}"


@tool
def atendimento_humano(
    motivo: str = "Solicitação do cliente",
    chat_id: str = None,
    timeout_minutes: int = 60,
    redis_url: str = None,
) -> str:
    """
    Transfere a conversa para um atendente humano.
    Use em casos de dúvidas complexas, negociações ou quando não encontrar a peça.
    A IA ficará pausada pelo tempo configurado (padrão: 60 min).
    Args:
        motivo (str): Motivo do transbordo (para log).
    """
    import redis

    # DEBUG FORCE LOG
    logger.info(
        f"🐛 DEBUG TOOL CALL: atendimento_humano called with motivo={motivo}, chat_id={chat_id}"
    )

    logger.info(f"👤 Transbordo Humano: {motivo} | Chat: {chat_id}")
    if not chat_id:
        logger.warning(
            "⚠️ chat_id não fornecido para atendimento_humano. Pausa não ativada."
        )
        return "TRANSBORDO_HUMANO_ATIVADO (sem pausa - chat_id ausente)"
    if not redis_url:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        r = redis.Redis.from_url(redis_url, decode_responses=True)
        pause_key = f"ai_paused:{chat_id}"
        ttl_seconds = timeout_minutes * 60
        r.set(pause_key, "true", ex=ttl_seconds)
        r.close()
        logger.info(f"🛑 IA PAUSADA por {timeout_minutes} min para {chat_id}")
        return f"TRANSBORDO_HUMANO_ATIVADO. IA pausada por {timeout_minutes} minutos."
    except Exception as e:
        return f"TRANSBORDO_HUMANO_ATIVADO (erro ao pausar: {e})"


@tool
def desativar_ia(
    motivo: str = "Solicitação do cliente",
    chat_id: str = None,
    redis_url: str = None,
):
    """
    Desativa a IA para este cliente PERMANENTEMENTE (Opt-out).
    Use quando o cliente pedir para 'parar', 'não quero mais mensagens' ou enviar emojis de parada (🛑).
    A IA não responderá mais até ser reativada manualmente no sistema.
    Args:
        motivo (str): Motivo da parada (para log).
    """
    import redis

    logger.info(f"🛑 Desativando IA Permanentemente: {motivo} | Chat: {chat_id}")
    if not chat_id:
        logger.warning("⚠️ chat_id não fornecido para desativar_ia. Pausa não ativada.")
        return "ERRO: chat_id ausente."

    if not redis_url:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    try:
        r = redis.Redis.from_url(redis_url, decode_responses=True)
        pause_key = f"ai_paused:{chat_id}"

        # Set SEM data de expiração (Persistente)
        r.set(pause_key, "true_permanent")
        r.close()

        logger.info(f"💀 IA MORTA (Pausada para sempre) para {chat_id}")
        return "IA_DESATIVADA_COM_SUCESSO. O cliente não receberá mais respostas automáticas."
    except Exception as e:
        logger.error(f"Erro ao desativar IA no Redis: {e}")
        return f"ERRO_AO_DESATIVAR_IA: {e}"


@tool
def criar_lembrete(
    quando: str,
    motivo: str = "Retornar contato conforme solicitado",
    chat_id: str = None,
    client_id: str = None,
):
    """
    Cria um lembrete para retornar contato com o cliente em uma data futura.
    Use quando o cliente pedir para ligar depois, retornar na semana que vem, etc.
    Args:
        quando (str): Quando retornar - pode ser "amanhã", "em 3 dias", "semana que vem", "dia 15", "2026-02-10 10:00"
        motivo (str): Motivo/contexto do lembrete para personalizar a mensagem de retorno.
    """
    from datetime import datetime, timedelta
    import re

    logger.info(
        f"📅 Criando Lembrete: quando={quando}, motivo={motivo}, chat={chat_id}"
    )

    if not chat_id:
        logger.warning("⚠️ chat_id não fornecido para criar_lembrete.")
        return "ERRO: chat_id ausente."

    if not client_id:
        logger.warning("⚠️ client_id não fornecido para criar_lembrete.")
        return "ERRO: client_id ausente."

    # Parseia data natural
    now = datetime.now()
    scheduled_at = None

    quando_lower = quando.lower().strip()

    # Padrões de data natural
    if "amanhã" in quando_lower or "amanha" in quando_lower:
        scheduled_at = now + timedelta(days=1)
    elif "depois de amanhã" in quando_lower:
        scheduled_at = now + timedelta(days=2)
    elif "semana que vem" in quando_lower or "próxima semana" in quando_lower:
        scheduled_at = now + timedelta(days=7)
    elif "mês que vem" in quando_lower or "próximo mês" in quando_lower:
        scheduled_at = now + timedelta(days=30)
    elif match := re.search(r"em (\d+)\s*(dias?|horas?|minutos?)", quando_lower):
        quantidade = int(match.group(1))
        unidade = match.group(2)
        if "dia" in unidade:
            scheduled_at = now + timedelta(days=quantidade)
        elif "hora" in unidade:
            scheduled_at = now + timedelta(hours=quantidade)
        elif "minuto" in unidade:
            scheduled_at = now + timedelta(minutes=quantidade)
    elif match := re.search(r"dia (\d{1,2})", quando_lower):
        dia = int(match.group(1))
        # Assume mês atual ou próximo
        try:
            scheduled_at = now.replace(day=dia)
            if scheduled_at < now:
                # Já passou, vai pro próximo mês
                if now.month == 12:
                    scheduled_at = scheduled_at.replace(year=now.year + 1, month=1)
                else:
                    scheduled_at = scheduled_at.replace(month=now.month + 1)
        except ValueError:
            pass
    else:
        # Tenta parsear como data ISO
        try:
            scheduled_at = datetime.fromisoformat(quando)
        except ValueError:
            # Fallback: 3 dias
            logger.warning(
                f"⚠️ Não consegui interpretar '{quando}'. Usando 3 dias como padrão."
            )
            scheduled_at = now + timedelta(days=3)

    # Define horário padrão às 10h se não especificado
    if scheduled_at.hour == now.hour and scheduled_at.minute == now.minute:
        scheduled_at = scheduled_at.replace(hour=10, minute=0, second=0)

    # Salva no banco de dados
    try:
        import sys

        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from saas_db import get_connection

        import uuid

        new_id = str(uuid.uuid4())

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reminders (id, client_id, chat_id, scheduled_at, message, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending')
                    RETURNING id
                """,
                    (new_id, client_id, chat_id, scheduled_at, motivo),
                )
                reminder_id = cur.fetchone()["id"]

        logger.info(f"✅ Lembrete criado: ID={reminder_id}, para {scheduled_at}")
        return f"LEMBRETE_CRIADO_COM_SUCESSO. Vou retornar o contato em {scheduled_at.strftime('%d/%m/%Y às %H:%M')}."

    except Exception as e:
        logger.error(f"Erro ao criar lembrete: {e}")
        return f"ERRO_AO_CRIAR_LEMBRETE: {e}"


# --- HUBSOFT VIABILIDADE ---


def _get_hubsoft_access_token(hubsoft_config: dict) -> str:
    """Obtém token de acesso OAuth2 da API HubSoft."""
    api_url = hubsoft_config.get("api_url", "").rstrip("/")
    client_id = hubsoft_config.get("client_id")
    client_secret = hubsoft_config.get("client_secret")
    username = hubsoft_config.get("username")
    password = hubsoft_config.get("password")

    if not all([api_url, client_id, client_secret, username, password]):
        raise ValueError(
            "Configuração HubSoft incompleta. Verifique api_url, client_id, client_secret, username e password."
        )

    token_url = f"{api_url}/oauth/token"
    payload = {
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
    }

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(token_url, data=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")


@tool
def consultar_viabilidade_hubsoft(
    endereco: str,
    numero: str,
    bairro: str,
    cidade: str,
    estado: str,
    hubsoft_config: dict = None,
    raio: int = 250,
    detalhar_portas: bool = False,
):
    """
    Consulta viabilidade de cobertura de internet em um endereço usando API HubSoft.
    Use esta tool quando o cliente perguntar se tem cobertura/viabilidade em determinado endereço.

    Args:
        endereco: Rua ou Avenida (ex: "Rua das Flores")
        numero: Número da residência (ex: "123")
        bairro: Bairro (ex: "Centro")
        cidade: Cidade (ex: "São Paulo")
        estado: Estado - sigla UF (ex: "SP", "MG", "RJ")
        raio: Raio de busca em metros (default: 250)
        detalhar_portas: Se True, retorna detalhes das portas disponíveis

    Returns:
        Informações de viabilidade com projetos disponíveis na região.
    """
    if not hubsoft_config:
        return {
            "error": "Configuração HubSoft não encontrada. Entre em contato com o suporte."
        }

    try:
        # 1. Obter Access Token
        access_token = _get_hubsoft_access_token(hubsoft_config)
        api_url = hubsoft_config.get("api_url", "").rstrip("/")

        # 2. Consultar Viabilidade
        viab_url = f"{api_url}/api/v1/integracao/mapeamento/viabilidade/consultar"
        payload = {
            "tipo_busca": "endereco",
            "raio": raio,
            "endereco": {
                "numero": str(numero),
                "endereco": endereco,
                "bairro": bairro,
                "cidade": cidade,
                "estado": estado.upper()[:2],  # Garante sigla UF
            },
            "detalhar_portas": 1 if detalhar_portas else 0,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        logger.info(
            f"🌐 HubSoft Viabilidade: Consultando {endereco}, {numero} - {cidade}/{estado}"
        )

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(viab_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # 3. Processar Resposta
        status = data.get("status", "unknown")
        if status != "success":
            msg = data.get("msg", "Erro desconhecido na API HubSoft")
            logger.warning(f"⚠️ HubSoft retornou status: {status} - {msg}")
            return {"viavel": False, "mensagem": msg}

        resultado = data.get("resultado", {})

        # API pode retornar resultado como string em vez de dict
        if isinstance(resultado, str):
            try:
                resultado = json.loads(resultado)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"⚠️ HubSoft: resultado veio como string: {resultado}")
                return {
                    "viavel": False,
                    "mensagem": resultado or "Não foi possível consultar viabilidade neste endereço.",
                    "endereco_consultado": f"{endereco}, {numero} - {bairro}, {cidade}/{estado}",
                }

        if not isinstance(resultado, dict):
            logger.warning(f"⚠️ HubSoft: resultado com tipo inesperado: {type(resultado)}")
            return {
                "viavel": False,
                "mensagem": "Resposta inesperada da API HubSoft ao consultar viabilidade.",
                "endereco_consultado": f"{endereco}, {numero} - {bairro}, {cidade}/{estado}",
            }

        projetos = resultado.get("projetos", [])

        if not projetos:
            return {
                "viavel": False,
                "mensagem": "Infelizmente não há cobertura disponível neste endereço no momento.",
                "endereco_consultado": f"{endereco}, {numero} - {bairro}, {cidade}/{estado}",
            }

        # Formata lista de projetos para o LLM
        projetos_formatados = []
        for p in projetos:
            proj_info = p.get("projeto", {})
            projetos_formatados.append(
                {
                    "id": proj_info.get("id_mapeamento_projeto"),
                    "nome": proj_info.get("nome"),
                    "tipo": resultado.get("origem", "desconhecido"),
                }
            )

        logger.info(f"✅ HubSoft: {len(projetos_formatados)} projeto(s) encontrado(s)")

        return {
            "viavel": True,
            "mensagem": "Boa notícia! Temos cobertura disponível neste endereço.",
            "endereco_consultado": f"{endereco}, {numero} - {bairro}, {cidade}/{estado}",
            "projetos_disponiveis": projetos_formatados,
            "total_projetos": len(projetos_formatados),
        }

    except httpx.HTTPStatusError as e:
        logger.error(
            f"❌ Erro HTTP HubSoft: {e.response.status_code} - {e.response.text}"
        )
        return {"error": f"Erro na API HubSoft: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ Erro ao consultar viabilidade HubSoft: {e}")
        return {"error": f"Erro ao consultar viabilidade: {str(e)}"}


# --- HUBSOFT CONSULTAR CLIENTE ---


@tool
def consultar_cliente_hubsoft(
    cpf_cnpj: str,
    hubsoft_config: dict = None,
):
    """
    Consulta dados cadastrais de um cliente no HubSoft pelo CPF ou CNPJ.
    Use esta tool quando precisar buscar informações de cadastro do cliente.
    IMPORTANTE: O resultado inclui o campo 'id_cliente_servico' dos serviços,
    que é necessário para realizar desbloqueio de confiança.

    Args:
        cpf_cnpj: CPF ou CNPJ do cliente (apenas números, ex: "12345678901")

    Returns:
        Dados cadastrais do cliente incluindo serviços contratados.
    """
    if not hubsoft_config:
        return {
            "error": "Configuração HubSoft não encontrada. Configure as credenciais na ferramenta HubSoft Viabilidade."
        }

    try:
        access_token = _get_hubsoft_access_token(hubsoft_config)
        api_url = hubsoft_config.get("api_url", "").rstrip("/")

        url = f"{api_url}/api/v1/integracao/cliente"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params = {
            "busca": "cpf_cnpj",
            "termo_busca": cpf_cnpj.strip().replace(".", "").replace("-", "").replace("/", ""),
        }

        logger.info(f"🔍 HubSoft: Consultando cliente CPF/CNPJ {cpf_cnpj}")

        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        clientes = data.get("clientes", [])
        if not clientes:
            return {
                "encontrado": False,
                "mensagem": "Nenhum cliente encontrado com este CPF/CNPJ.",
            }

        cliente = clientes[0]
        servicos = cliente.get("servicos", [])
        servicos_formatados = []
        for s in servicos:
            servicos_formatados.append({
                "id_cliente_servico": s.get("id_cliente_servico"),
                "plano": s.get("nome") or s.get("plano"),
                "status": s.get("status"),
                "login": s.get("login"),
            })

        resultado = {
            "encontrado": True,
            "nome": cliente.get("nome_razaosocial") or cliente.get("nome"),
            "cpf_cnpj": cliente.get("cpf_cnpj"),
            "email": cliente.get("email"),
            "telefone": cliente.get("telefone") or cliente.get("celular"),
            "endereco": cliente.get("endereco"),
            "status": cliente.get("status"),
            "servicos": servicos_formatados,
        }

        logger.info(f"✅ HubSoft: Cliente encontrado - {resultado.get('nome')}")
        return resultado

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erro HTTP HubSoft: {e.response.status_code} - {e.response.text}")
        return {"error": f"Erro na API HubSoft: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ Erro ao consultar cliente HubSoft: {e}")
        return {"error": f"Erro ao consultar cliente: {str(e)}"}


# --- HUBSOFT CONSULTAR FINANCEIRO ---


@tool
def consultar_financeiro_hubsoft(
    cpf_cnpj: str,
    hubsoft_config: dict = None,
):
    """
    Consulta faturas e situação financeira de um cliente no HubSoft pelo CPF ou CNPJ.
    Retorna apenas faturas pendentes (em aberto).

    Args:
        cpf_cnpj: CPF ou CNPJ do cliente (apenas números, ex: "12345678901")

    Returns:
        Lista de faturas pendentes do cliente.
    """
    if not hubsoft_config:
        return {
            "error": "Configuração HubSoft não encontrada. Configure as credenciais na ferramenta HubSoft Viabilidade."
        }

    try:
        access_token = _get_hubsoft_access_token(hubsoft_config)
        api_url = hubsoft_config.get("api_url", "").rstrip("/")

        url = f"{api_url}/api/v1/integracao/cliente/financeiro"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params = {
            "busca": "cpf_cnpj",
            "termo_busca": cpf_cnpj.strip().replace(".", "").replace("-", "").replace("/", ""),
            "apenas_pendente": "sim",
        }

        logger.info(f"💰 HubSoft: Consultando financeiro CPF/CNPJ {cpf_cnpj}")

        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        faturas = data.get("faturas", data.get("titulos", []))
        if not faturas:
            return {
                "tem_pendencia": False,
                "mensagem": "Nenhuma fatura pendente encontrada para este cliente.",
            }

        faturas_formatadas = []
        for f in faturas:
            faturas_formatadas.append({
                "vencimento": f.get("data_vencimento") or f.get("vencimento"),
                "valor": f.get("valor"),
                "status": f.get("status") or f.get("situacao"),
                "descricao": f.get("descricao") or f.get("referencia"),
                "linha_digitavel": f.get("linha_digitavel"),
                "link_boleto": f.get("link_boleto") or f.get("url_boleto"),
            })

        logger.info(f"✅ HubSoft: {len(faturas_formatadas)} fatura(s) pendente(s) encontrada(s)")
        return {
            "tem_pendencia": True,
            "total_faturas": len(faturas_formatadas),
            "faturas": faturas_formatadas,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erro HTTP HubSoft: {e.response.status_code} - {e.response.text}")
        return {"error": f"Erro na API HubSoft: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ Erro ao consultar financeiro HubSoft: {e}")
        return {"error": f"Erro ao consultar financeiro: {str(e)}"}


# --- HUBSOFT DESBLOQUEIO DE CONFIANÇA ---


@tool
def desbloqueio_de_confianca_hubsoft(
    id_cliente_servico: str,
    hubsoft_config: dict = None,
):
    """
    Realiza desbloqueio de confiança de um serviço do cliente no HubSoft.
    IMPORTANTE: Antes de usar esta tool, é necessário consultar o cliente primeiro
    (usando consultar_cliente_hubsoft) para obter o 'id_cliente_servico' correto.

    Args:
        id_cliente_servico: ID do serviço do cliente (obtido na consulta de cliente, campo 'id_cliente_servico')

    Returns:
        Resultado do desbloqueio de confiança.
    """
    if not hubsoft_config:
        return {
            "error": "Configuração HubSoft não encontrada. Configure as credenciais na ferramenta HubSoft Viabilidade."
        }

    dias = hubsoft_config.get("dias_desbloqueio", 3)

    try:
        access_token = _get_hubsoft_access_token(hubsoft_config)
        api_url = hubsoft_config.get("api_url", "").rstrip("/")

        url = f"{api_url}/api/v1/integracao/cliente/desbloqueio_confianca"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params = {
            "id_cliente_servico": str(id_cliente_servico),
            "dias_desbloqueio": str(dias),
        }

        logger.info(
            f"🔓 HubSoft: Desbloqueio de confiança - Serviço {id_cliente_servico}, {dias} dia(s)"
        )

        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "unknown")
        msg = data.get("msg", data.get("mensagem", ""))

        if status == "success" or "sucesso" in str(msg).lower():
            logger.info(f"✅ HubSoft: Desbloqueio realizado com sucesso")
            return {
                "sucesso": True,
                "mensagem": f"Desbloqueio de confiança realizado com sucesso por {dias} dia(s).",
                "detalhes": msg,
            }
        else:
            logger.warning(f"⚠️ HubSoft: Desbloqueio retornou status {status}: {msg}")
            return {
                "sucesso": False,
                "mensagem": msg or f"Não foi possível realizar o desbloqueio. Status: {status}",
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erro HTTP HubSoft: {e.response.status_code} - {e.response.text}")
        return {"error": f"Erro na API HubSoft: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ Erro ao realizar desbloqueio HubSoft: {e}")
        return {"error": f"Erro ao realizar desbloqueio: {str(e)}"}


# Mapa de Funções Disponíveis (Nome no JSON do DB -> Função Python)
AVAILABLE_TOOLS = {
    "consultar_cep": consultar_cep,
    "qualificado_kommo_provedor": qualificado_kommo_provedor,
    "consultar_erp": consultar_erp,
    "enviar_relatorio": enviar_relatorio,
    "atendimento_humano": atendimento_humano,
    "desativar_ia": desativar_ia,
    "criar_lembrete": criar_lembrete,
    "consultar_viabilidade_hubsoft": consultar_viabilidade_hubsoft,
    "consultar_cliente_hubsoft": consultar_cliente_hubsoft,
    "consultar_financeiro_hubsoft": consultar_financeiro_hubsoft,
    "desbloqueio_de_confianca_hubsoft": desbloqueio_de_confianca_hubsoft,
    "cal_dot_com": "cal_dot_com",  # Placeholder para group tool
    "whatsapp_reactions": "whatsapp_reactions",  # String para evitar NameError
    "sgp_tools": "sgp_tools",  # Placeholder para SGP (Viabilidade + Pré-Cadastro)
    "rag_active": "rag_active",  # Tool de Pesquisa em Documentos (Base de Conhecimento)
}


def get_enabled_tools(
    tools_config: dict,
    chat_id: str = None,
    client_config: dict = None,
    last_msg_id: str = None,
):
    """
    Retorna a lista de funcoes Python para passar pro Gemini.
    Suporta configuração injetada (dict).
    Args:
        tools_config: Dicionário de configuração das tools.
        chat_id: ID do chat atual (para injetar em tools como atendimento_humano).
        client_config: Dict completo do cliente (para pegar api_url, token, etc).
    Ex: tools_config = {
        "consultar_cep": true,
        "qualificado_kommo_provedor": {"url": "...", "token": "...", "status_id": 123}
    }
    """
    tools = []

    # Resolve credenciais do provider via client_providers
    uazapi_url_cfg = ""
    uazapi_token_cfg = ""

    if client_config:
        client_id_str = str(client_config.get("id", ""))
        try:
            uazapi_cfg = get_provider_config(client_id_str, "uazapi")
            if uazapi_cfg:
                uazapi_url_cfg = uazapi_cfg.get("url", "")
                uazapi_token_cfg = uazapi_cfg.get("token", "")
        except Exception as e:
            logger.debug(f"Fallback env: {e}")

    # Fallback para Env se resolução falhou
    if not uazapi_url_cfg:
        uazapi_url_cfg = os.getenv("UAZAPI_URL", "")
    if not uazapi_token_cfg:
        uazapi_token_cfg = os.getenv("UAZAPI_TOKEN", "")

    # Provider resolvido para tools que precisam (enviar_relatorio, etc)
    resolved_provider_type = "uazapi"
    resolved_provider_config = {"url": uazapi_url_cfg, "token": uazapi_token_cfg}
    if not tools_config:
        logger.warning("⚠️ Tools Config is empty or None!")
        return []

    logger.info(f"🔍 DEBUG TOOLS CONFIG: Keys={list(tools_config.keys())}")

    # Import registry for wrapper_type dispatching
    from tool_registry import TOOL_REGISTRY

    for tool_name, config_value in tools_config.items():
        if tool_name in AVAILABLE_TOOLS:
            tool_func = AVAILABLE_TOOLS[tool_name]
            # Se a config for um dicionário e estiver ativa
            # Ex: {"active": true, "url": "..."} ou apenas {"url": "..."} (implícito active)
            config_dict = config_value if isinstance(config_value, dict) else {}
            if isinstance(config_value, dict):
                is_active = config_value.get("active", False)
            elif isinstance(config_value, bool):
                is_active = config_value

            if is_active:
                # ── REGISTRY-BASED DISPATCH ──
                registry_entry = TOOL_REGISTRY.get(tool_name, {})
                wrapper_type = registry_entry.get("wrapper_type", "simple")

                # ── inject_config: Injeta config_dict na kwarg específica ──
                if wrapper_type == "inject_config":
                    inject_kwarg = registry_entry.get("inject_kwarg_name", "config")
                    tool_cfg = (
                        {k: v for k, v in config_value.items() if k != "active"}
                        if isinstance(config_value, dict)
                        else {}
                    )
                    # config_source: herda credenciais de outra tool (ex: HubSoft compartilhado)
                    config_source = registry_entry.get("config_source")
                    if config_source:
                        base_cfg = tools_config.get(config_source, {})
                        if isinstance(base_cfg, dict):
                            merged = {k: v for k, v in base_cfg.items() if k != "active"}
                            merged.update(tool_cfg)  # tool-specific fields override
                            tool_cfg = merged
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    def _make_config_wrapper(f, kwarg_name, cfg):
                        import inspect

                        sig = inspect.signature(f)
                        # Cria nova signature SEM o kwarg injetado (esconde do LangChain/LLM)
                        visible_params = [
                            p for p in sig.parameters.values() if p.name != kwarg_name
                        ]

                        def wrapped(**kwargs):
                            kwargs[kwarg_name] = cfg
                            valid = {
                                k: v for k, v in kwargs.items() if k in sig.parameters
                            }
                            return f(**valid)

                        # Seta assinatura explícita: LangChain só vê params visíveis
                        wrapped.__signature__ = sig.replace(parameters=visible_params)
                        wrapped.__name__ = f.__name__
                        wrapped.__doc__ = f.__doc__
                        # FIX: Copia anotações para que Pydantic encontre os tipos dos argumentos visíveis
                        wrapped.__annotations__ = {
                            k: v
                            for k, v in f.__annotations__.items()
                            if k in [p.name for p in visible_params] or k == "return"
                        }
                        return wrapped

                    wrapped_fn = _make_config_wrapper(
                        fn_captured, inject_kwarg, tool_cfg
                    )
                    tools.append(
                        StructuredTool.from_function(
                            func=wrapped_fn,
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(
                        f"🔧 Tool [{wrapper_type}] Ativada: {tool_name} (injetando {inject_kwarg})"
                    )

                # ── inject_runtime: Injeta chat_id, redis_url, client_id, etc ──
                elif wrapper_type == "inject_runtime":
                    runtime_map = registry_entry.get("runtime_kwargs", {})
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    # Resolve runtime values
                    resolved = {}
                    for kwarg_name, source in runtime_map.items():
                        if source == "chat_id":
                            resolved[kwarg_name] = chat_id
                        elif source == "client_id":
                            resolved[kwarg_name] = (
                                client_config.get("id") if client_config else None
                            )
                        elif source.startswith("env:"):
                            env_key = source.split(":", 1)[1]
                            resolved[kwarg_name] = os.getenv(
                                env_key,
                                "redis://localhost:6379" if "REDIS" in env_key else "",
                            )
                        elif source.startswith("config:"):
                            cfg_key = source.split(":", 1)[1]
                            resolved[kwarg_name] = config_dict.get(
                                cfg_key,
                                registry_entry.get("config_fields", {})
                                .get(cfg_key, {})
                                .get("default"),
                            )

                    def _make_runtime_wrapper(f, injected):
                        import inspect

                        sig = inspect.signature(f)
                        # Cria nova signature SEM os kwargs injetados (esconde do LangChain/LLM)
                        visible_params = [
                            p for p in sig.parameters.values() if p.name not in injected
                        ]

                        def wrapped(**kwargs):
                            final = {**injected, **kwargs}
                            valid = {
                                k: v for k, v in final.items() if k in sig.parameters
                            }
                            return f(**valid)

                        # Seta assinatura explícita: LangChain só vê params visíveis
                        wrapped.__signature__ = sig.replace(parameters=visible_params)
                        wrapped.__name__ = f.__name__
                        wrapped.__doc__ = f.__doc__
                        # FIX: Copia anotações para que Pydantic encontre os tipos dos argumentos visíveis
                        wrapped.__annotations__ = {
                            k: v
                            for k, v in f.__annotations__.items()
                            if k in [p.name for p in visible_params] or k == "return"
                        }
                        return wrapped

                    wrapped_fn = _make_runtime_wrapper(fn_captured, resolved)
                    tools.append(
                        StructuredTool.from_function(
                            func=wrapped_fn,
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(
                        f"🔧 Tool [{wrapper_type}] Ativada: {tool_name} (runtime: {list(resolved.keys())})"
                    )

                # ── CUSTOM HANDLERS (mantidos como antes) ──
                elif tool_name == "enviar_relatorio":
                    # Injeta dependencias (grupo_id, uazapi, template)
                    grupo_cfg = config_dict.get("grupo_id", "")
                    template_cfg = config_dict.get("template", "")

                    # 1. Extrai placeholders do template
                    import re
                    from pydantic import create_model

                    placeholders = (
                        re.findall(r"\{\{(\w+)\}\}", template_cfg)
                        if template_cfg
                        else []
                    )
                    # Remove duplicatas mantendo ordem
                    placeholders = list(dict.fromkeys(placeholders))

                    placeholders_str = (
                        ", ".join(placeholders)
                        if placeholders
                        else "nome, cpf, email, telefone, etc."
                    )

                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    telefone_from_chat = ""
                    if chat_id and "@" in str(chat_id):
                        telefone_from_chat = str(chat_id).split("@")[0]
                        logger.info(
                            f"📱 Telefone extraído do chat_id: {telefone_from_chat}"
                        )

                    # 2. Wrapper que aceita **kwargs dinâmicos
                    def create_relatorio_wrapper(
                        f, grp, p_type, p_config, url, tkn, tpl, telefone_auto, known_fields
                    ):
                        def wrapped_relatorio(tipo: str = "ficha", **kwargs):
                            """Envia um relatório para o grupo de vendas no WhatsApp."""

                            # Reconstrói o dict 'dados' a partir dos kwargs (FILTRA None e strings vazias)
                            dados_final = {
                                k: v
                                for k, v in kwargs.items()
                                if k in known_fields
                                and v is not None
                                and str(v).strip() != ""
                            }

                            # Injeta campos extras que podem ter vindo soltos mas não estavam no template (fallback)
                            # ou se o modelo mandou 'dados' como dict explicitamente (retrocompatibilidade)
                            if "dados" in kwargs and isinstance(kwargs["dados"], dict):
                                # Também filtra None/vazios do sub-dict
                                dados_extra = {
                                    k: v
                                    for k, v in kwargs["dados"].items()
                                    if v is not None and str(v).strip() != ""
                                }
                                dados_final.update(dados_extra)

                            # Auto-injeta ou corrige telefone (suporta alias: numero_do_cliente)
                            tel_candidato = dados_final.get(
                                "telefone"
                            ) or dados_final.get("numero_do_cliente", "")
                            # Limpa caracteres não numéricos para checagem
                            tel_limpo = "".join(filter(str.isdigit, str(tel_candidato)))

                            # Regra de Robustez: Se telefone for inválido (<10 digitos, ex: CEP 8 dig) E tivermos o do chat
                            if telefone_auto:
                                if not tel_candidato or len(tel_limpo) < 10:
                                    logger.warning(
                                        f"⚠️ Telefone inválido detectado ('{tel_candidato}'). Substituindo pelo do Chat ID: {telefone_auto}"
                                    )
                                    # Injeta em ambos os campos possíveis
                                    dados_final["telefone"] = telefone_auto
                                    if "numero_do_cliente" in dados_final:
                                        dados_final["numero_do_cliente"] = telefone_auto
                                else:
                                    # Se válido, mantém (pode ser outro número que o cliente passou)
                                    pass
                            elif not tel_candidato:
                                # Sem telefone no chat e sem na tool -> Log de aviso
                                logger.warning(
                                    "⚠️ Relatório sem telefone! (Chat ID inválido e IA não extraiu)"
                                )

                            # Formata telefone (remove @s.whatsapp.net se presente)
                            if dados_final.get("telefone"):
                                dados_final["telefone"] = str(
                                    dados_final["telefone"]
                                ).split("@")[0]
                            if dados_final.get("numero_do_cliente"):
                                dados_final["numero_do_cliente"] = str(
                                    dados_final["numero_do_cliente"]
                                ).split("@")[0]

                            # VALIDAÇÃO: Precisa ter pelo menos 2 campos preenchidos (inclui telefone)
                            campos_validos = list(dados_final.keys())
                            if len(campos_validos) < 2:
                                logger.warning(
                                    f"⚠️ Dados insuficientes para relatório: {len(campos_validos)} campos. Mínimo: 2"
                                )
                                # Mensagem clara para IA PARAR de tentar (evita loop infinito)
                                return "AÇÃO CANCELADA: Ainda não há dados suficientes para enviar relatório. NÃO tente novamente agora. Continue a conversa normalmente e colete as informações necessárias primeiro."

                            logger.info(
                                f"🚀 EXEC enviar_relatorio: tipo={tipo}, dados={dados_final}, grupo={grp}, provider={p_type}"
                            )
                            response_msg = f(
                                tipo=tipo,
                                dados=dados_final,
                                grupo_id=grp,
                                provider_type=p_type,
                                provider_config=p_config,
                                uazapi_url=url,
                                uazapi_token=tkn,
                                template=tpl,
                            )

                            # Se houve correção automática, avisa no retorno para a IA ficar ciente
                            if telefone_auto and (
                                not tel_candidato or len(tel_limpo) < 10
                            ):
                                response_msg += f" (Nota: O telefone foi corrigido automaticamente para {telefone_auto}. NÃO reenvie.)"

                            return response_msg

                        return wrapped_relatorio

                    # 3. Cria Schema Pydantic DINÂMICO
                    # Define os campos dinâmicos baseados no template
                    field_definitions = {
                        "tipo": (
                            str,
                            Field(
                                default="ficha",
                                description="Tipo do relatório (ficha, pedido, etc)",
                            ),
                        ),
                    }

                    for field_name in placeholders:
                        field_definitions[field_name] = (
                            Optional[str],
                            Field(
                                default=None,
                                description=f"Valor para o campo '{field_name}' extraído da conversa",
                            ),
                        )

                    # Cria o modelo dinamicamente
                    DynamicInputModel = create_model(
                        "EnviarRelatorioInput", **field_definitions
                    )

                    tools.append(
                        StructuredTool.from_function(
                            func=create_relatorio_wrapper(
                                fn_captured,
                                grupo_cfg,
                                resolved_provider_type,
                                resolved_provider_config,
                                uazapi_url_cfg,
                                uazapi_token_cfg,
                                template_cfg,
                                telefone_from_chat,
                                placeholders,
                            ),
                            name=tool_name,
                            description=f"""Envia um relatório preenchido para o grupo da agência/vendas.
ATENÇÃO: Extraia os dados da conversa e passe como argumentos individuais.
Campos esperados: {placeholders_str}""",
                            args_schema=DynamicInputModel,
                        )
                    )
                    logger.info(
                        f"🔧 Tool Enviar Relatório Dinâmica: grupo={grupo_cfg[:20]}... | provider={resolved_provider_type} | Campos: {placeholders_str}"
                    )

                elif tool_name == "cal_dot_com":
                    # Injeta dependencias (api_key, event_type_id)
                    cal_config = config_value if isinstance(config_value, dict) else {}
                    api_key = cal_config.get("api_key")
                    event_type_id = cal_config.get("event_type_id")

                    if api_key and event_type_id:
                        # 1. Consultar Slots
                        def wrap_slots(days: int = 5):
                            """Busca horários disponíveis na agenda para os próximos dias."""
                            return get_available_slots(api_key, event_type_id, days)

                        tools.append(
                            StructuredTool.from_function(
                                func=wrap_slots,
                                name="consultar_agenda",
                                description="Verifica disponibilidade de horários para agendamento.",
                            )
                        )

                        # 2. Agendar
                        # 2. Agendar
                        def wrap_book(
                            start_time: str,
                            name: str,
                            email: str,
                            phone: str = None,
                            location_type: str = "google-meet",
                            location_value: str = None,
                            duration: int = None,
                            notes: str = None,
                        ):
                            """
                            Realiza o agendamento de uma reunião.
                            Args:
                                start_time: Data/hora ISO 8601 (ex: retirado do consultar_agenda).
                                phone: Telefone com DDI e DDD (obrigatório se for reunião online ou para notificações).
                                location_type: 'google-meet' (padrão), 'phone' ou 'address'.
                                location_value: Endereço (se address) ou telefone alternativo.
                                duration: Duração em minutos (opcional, sobrescreve o padrão do evento).
                            """
                            return create_booking(
                                api_key,
                                event_type_id,
                                start_time,
                                name,
                                email,
                                phone,
                                location_type,
                                location_value,
                                duration,
                                notes,
                            )

                        tools.append(
                            StructuredTool.from_function(
                                func=wrap_book,
                                name="agendar_reuniao",
                                description="Agenda reunião. Requer nome, email, telefone e horário. Suporta local (address/google-meet/phone) e duração.",
                            )
                        )

                        # 3. Cancelar
                        def wrap_cancel(
                            booking_uid: str, reason: str = "Solicitado pelo cliente"
                        ):
                            """Cancela um agendamento existente usando o UID."""
                            return cancel_booking(api_key, booking_uid, reason)

                        tools.append(
                            StructuredTool.from_function(
                                func=wrap_cancel,
                                name="cancelar_reuniao",
                                description="Cancela uma reunião agendada. Requer o UID do agendamento.",
                            )
                        )

                        # 4. Remarcar
                        def wrap_resched(
                            booking_uid: str,
                            new_start_time: str,
                            reason: str = "Solicitado pelo cliente",
                        ):
                            """Remarca um agendamento existente para um novo horário."""
                            return reschedule_booking(
                                api_key, booking_uid, new_start_time, reason
                            )

                        tools.append(
                            StructuredTool.from_function(
                                func=wrap_resched,
                                name="remarcar_reuniao",
                                description="Muda o horário de uma reunião existente. Requer UID e novo horário.",
                            )
                        )

                        logger.info("📅 Tools Cal.com v2 Ativadas!")
                # SGP Tools Integration
                elif tool_name == "sgp_tools":
                    # Injeta dependencias do SGP (URL, Token, App)
                    sgp_cfg = {k: v for k, v in config_value.items() if k != "active"}
                    try:
                        sgp_list = get_sgp_tools()
                        for s_tool in sgp_list:
                            orig_func = s_tool.func

                            def create_sgp_wrapper(f, s_cfg):
                                def wrapped_sgp(**kwargs):
                                    return f(**kwargs, sgp_config=s_cfg)

                                return wrapped_sgp

                            wrapped_f = create_sgp_wrapper(orig_func, sgp_cfg)
                            tools.append(
                                StructuredTool.from_function(
                                    func=wrapped_f,
                                    name=s_tool.name,
                                    description=s_tool.description,
                                    args_schema=s_tool.args_schema,
                                )
                            )
                        logger.info(
                            f"🔧 SGP Tools Ativadas (Injetadas): {[t.name for t in sgp_list]}"
                        )
                    except Exception as e:
                        logger.error(f"❌ Erro ao carregar SGP Tools: {e}")

                elif tool_name == "whatsapp_reactions":
                    if chat_id:
                        # Pega configs do Uazapi já processadas anteriormente (linhas 806+)
                        # Mas como estão locais no loop, melhor pegar de client_config de novo ou usar as vars do escopo se acessíveis
                        # Vamos recalcular ou usar o que já temos se possível.
                        # Na verdade, uazapi_url_cfg e uazapi_token_cfg foram calculados no inicio do loop SIM.
                        # Eles estão no escopo da função get_enabled_tools?
                        # Estão dentro do loop 'for tool_name in tools_config:'.
                        # Sim, e o elif está no loop. Então podemos usar uazapi_url_cfg e uazapi_token_cfg.

                        current_url = uazapi_url_cfg
                        current_token = uazapi_token_cfg

                        def react_standard(emoji: str, message_id: str):
                            """
                            Envia uma reação (emoji) para uma mensagem específica.
                            Args:
                                emoji: O emoji para reagir (ex: 👍, ❤️).
                                message_id: O ID da mensagem que receberá a reação (obrigatório).
                            """
                            return _reagir_mensagem_sync(
                                emoji=emoji,
                                message_id=message_id,
                                chat_id=chat_id,
                                api_url=current_url,
                                api_token=current_token,
                            )

                        # Cria a ferramenta estruturada
                        standard_tool = StructuredTool.from_function(
                            func=react_standard,
                            name="reagir_mensagem",
                            description="AÇÃO DE INTERFACE: Envia reação para uma mensagem. Requer 'message_id' (veja no prompt) e 'emoji'.",
                        )
                        tools.append(standard_tool)
                        logger.info(
                            f"🔧 Tool Ativada: reagir_mensagem (STANDARD BOUND) -> Chat: {chat_id}"
                        )
                elif tool_name == "rag_active":
                    # Injeta Base de Conhecimento (RAG) se houver Store ID
                    from chains_saas import create_knowledge_base_tool

                    store_id = client_config.get(
                        "gemini_store_id"
                    ) or client_config.get("store_id")
                    if store_id:
                        kb_tool = create_knowledge_base_tool(store_id)
                        tools.append(kb_tool)
                        logger.info(
                            f"📎 Tool Enterprise Docs (RAG) injetada dinamicamente: {store_id}"
                        )
                    else:
                        logger.warning(
                            "⚠️ rag_active solicitado mas client_config sem store_id!"
                        )
                else:
                    # SAFETY GUARD: Ignore placeholders (strings) that fall through
                    if isinstance(tool_func, str):
                        logger.warning(
                            f"⚠️ Placeholder tool detected & skipped: {tool_name} (Safety Guard)"
                        )
                        continue

                    tools.append(tool_func)
                    logger.info(f"🔧 Tool Ativada: {tool_name}")
    return tools or None


def _reagir_mensagem_sync(
    emoji: str,
    message_id: str,
    chat_id: str = None,
    api_url: str = None,
    api_token: str = None,
):
    """Implementação interna da lógica de reação."""
    # IMPORTANTE: Implementação SÍNCRONA para compatibilidade com Agent Executor

    # Tenta usar args, senão env vars
    url = api_url or os.getenv("UAZAPI_URL")
    token = api_token or os.getenv("UAZAPI_KEY")

    if not url or not token:
        return {
            "error": "Credenciais Uazapi (URL/KEY) não encontradas (Env ou Config)."
        }

    # Sanitize URL
    url = url.rstrip("/")

    if not chat_id:
        return {"error": "chat_id é obrigatório para reagir."}

    logger.info(f"📤 [SYNC] Enviando Reação: {emoji} para {chat_id} (ID: {message_id})")

    try:
        # Uso de cliente Síncrono (httpx.Client)
        with httpx.Client() as client:
            payload = {
                "number": chat_id,
                "text": emoji or "",
                "id": message_id,
            }
            resp = client.post(
                f"{url}/message/react",
                json=payload,
                headers={"token": f"{token}", "Content-Type": "application/json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    except Exception as e:
        logger.error(f"❌ Erro ao reagir (Sync): {e}")
        return {"error": f"Erro ao reagir: {str(e)}"}


@tool
def reagir_mensagem(emoji: str, message_id: str, chat_id: str = None):
    """
    AÇÃO DE INTERFACE: Envia uma reação (emoji) para uma mensagem do WhatsApp.
    USE ESTA FERRAMENTA SEMPRE QUE FOR INSTRUÍDO A REAGIR.
    Args:
        emoji (str): O emoji para reagir (ex: 👍, ❤️).
        message_id (str): O ID da mensagem (fornecido no prompt).
        chat_id (str): O RemoteJid (fornecido no prompt).
    """
    return _reagir_mensagem_sync(emoji, message_id, chat_id)
