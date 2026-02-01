import os
import httpx
import logging
from typing import Optional
from pydantic import BaseModel, Field
from langchain.tools import tool
from langchain_core.tools import StructuredTool

logger = logging.getLogger("KestraTools")
# Tenta pegar API Key do Maps, ou fallback pro Gemini (se for a mesma key irrestrita)
# Obtém chave específica do Maps. SEM fallback para Gemini para evitar erros de permissão.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if GOOGLE_MAPS_API_KEY:
    logger.info(f"🗺️ Google Maps Key carregada: ...{GOOGLE_MAPS_API_KEY[-4:]}")
else:
    logger.warning(
        "⚠️ GOOGLE_MAPS_API_KEY não encontrada! A tool consultar_cep vai falhar."
    )


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
                "lat": location.get("lat"),
                "lng": location.get("lng"),
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
            clean_phone = (
                telefone.replace("+", "").replace("-", "").replace(" ", "").strip()
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
def audio(texto: str):
    """
    Gera um áudio falando o texto fornecido (TTS) e envia para o chat.
    Use para dar boas-vindas ou explicações complexas.
    """
    # Lógica Mock - Precisaria integrar com OpenAI TTS ou Google TTS e salvar no bucket
    logger.info(f"🔊 Gerando Áudio: {texto}")
    return {"status": "sent", "message": "Áudio enviado (Simulado)"}


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
):
    """
    Envia um relatório (ficha, reserva, pedido) para um grupo do WhatsApp.
    Use quando o cliente confirmar interesse, fechar pedido ou reservar produto.
    Args:
        tipo (str): Tipo do relatório ("ficha", "reserva", "pedido", etc.)
        dados (dict): Dados coletados (nome, telefone, produto, valor, etc.)
    """
    import asyncio

    logger.info(f"📤 Enviando Relatório ({tipo}) para grupo {grupo_id}")
    missing = []
    if not grupo_id:
        missing.append("grupo_id")
    if not uazapi_url:
        missing.append("uazapi_url")
    if not uazapi_token:
        missing.append("uazapi_token")
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
        # Template padrão
        linhas = [f"📋 *Novo {tipo.upper()}*", ""]
        for key, val in dados.items():
            linhas.append(f"• {key}: {val}")
        msg = "\n".join(linhas)

    # Envia via Uazapi (ASYNC - mesmo padrão do whatsapp_sender que funciona)
    async def _send():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{uazapi_url}/send/text",
                json={"number": grupo_id, "text": msg},
                headers={"token": uazapi_token},
                timeout=30.0,
            )
            return resp

    try:
        resp = asyncio.run(_send())
        if resp.status_code in [200, 201]:
            logger.info(f"✅ Relatório enviado para grupo {grupo_id}")
            return "Relatório enviado com sucesso para o grupo."
        else:
            logger.error(f"❌ Erro Uazapi: {resp.status_code} - {resp.text}")
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
):
    """
    Transfere a conversa para um atendente humano.
    Use em casos de dúvidas complexas, negociações ou quando não encontrar a peça.
    A IA ficará pausada pelo tempo configurado (padrão: 60 min).
    Args:
        motivo (str): Motivo do transbordo (para log).
    """
    import redis

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

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reminders (client_id, chat_id, scheduled_at, message, status)
                    VALUES (%s, %s, %s, %s, 'pending')
                    RETURNING id
                """,
                    (client_id, chat_id, scheduled_at, motivo),
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
            "mensagem": f"Boa notícia! Temos cobertura disponível neste endereço.",
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


# Mapa de Funções Disponíveis (Nome no JSON do DB -> Função Python)
AVAILABLE_TOOLS = {
    "consultar_cep": consultar_cep,
    "qualificado_kommo_provedor": qualificado_kommo_provedor,
    "consultar_erp": consultar_erp,
    "enviar_relatorio": enviar_relatorio,
    "atendimento_humano": atendimento_humano,
    "desativar_ia": desativar_ia,
    "criar_lembrete": criar_lembrete,
    "audio": audio,
    "consultar_viabilidade_hubsoft": consultar_viabilidade_hubsoft,
}


def get_enabled_tools(
    tools_config: dict, chat_id: str = None, client_config: dict = None
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
    if not tools_config:
        return []
    for tool_name, config_value in tools_config.items():
        if tool_name in AVAILABLE_TOOLS:
            tool_func = AVAILABLE_TOOLS[tool_name]
            # Se a config for um dicionário e estiver ativa
            # Ex: {"active": true, "url": "..."} ou apenas {"url": "..."} (implícito active)
            config_dict = config_value if isinstance(config_value, dict) else {}
            is_active = (
                config_dict.get("active", True)
                if isinstance(config_value, dict)
                else bool(config_value)
            )
            if is_active:
                if (
                    isinstance(config_value, dict)
                    and tool_name == "qualificado_kommo_provedor"
                ):
                    # Injeta dependências (kommo_config)
                    kommo_cfg = {k: v for k, v in config_value.items() if k != "active"}
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    def create_kommo_wrapper(f, k_cfg):
                        def wrapped_kommo(nome: str, telefone: str, plano: str):
                            """Registra um lead qualificado movendo-o para a etapa correta no Kommo CRM."""
                            return f(
                                nome=nome,
                                telefone=telefone,
                                plano=plano,
                                kommo_config=k_cfg,
                            )

                        return wrapped_kommo

                    tools.append(
                        StructuredTool.from_function(
                            func=create_kommo_wrapper(fn_captured, kommo_cfg),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(f"🔧 Tool Parametrizada Ativada: {tool_name}")
                    logger.info(f"🔧 Tool Parametrizada Ativada: {tool_name}")
                elif tool_name == "consultar_erp":
                    # Injeta dependencias (betel_config)
                    betel_cfg = {k: v for k, v in config_value.items() if k != "active"}
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    def create_betel_wrapper(f, b_cfg):
                        def wrapped_betel(nome_produto: str):
                            """Consulta o ERP (Betel) para verificar preço e estoque."""
                            return f(nome_produto=nome_produto, betel_config=b_cfg)

                        return wrapped_betel

                    tools.append(
                        StructuredTool.from_function(
                            func=create_betel_wrapper(fn_captured, betel_cfg),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(f"🔧 Tool Betel Ativada: {tool_name}")
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

                    # Uazapi configs
                    uazapi_url_cfg = ""
                    uazapi_token_cfg = ""
                    if client_config:
                        uazapi_config = client_config.get("tools_config", {}).get(
                            "whatsapp", {}
                        )
                        uazapi_url_cfg = client_config.get(
                            "api_url"
                        ) or uazapi_config.get("url")
                        uazapi_token_cfg = client_config.get(
                            "token"
                        ) or uazapi_config.get("key")
                        logger.info(
                            f"🔍 DEBUG UAZAPI CONFIG: Url={uazapi_url_cfg}, Token={uazapi_token_cfg}"
                        )

                    if not uazapi_url_cfg:
                        uazapi_url_cfg = os.getenv("UAZAPI_URL", "")
                    if not uazapi_token_cfg:
                        uazapi_token_cfg = os.getenv("UAZAPI_TOKEN", "")

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
                        f, grp, url, tkn, tpl, telefone_auto, known_fields
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

                            # Auto-injeta ou corrige telefone
                            tel_candidato = dados_final.get("telefone", "")
                            # Limpa caracteres não numéricos para checagem
                            tel_limpo = "".join(filter(str.isdigit, str(tel_candidato)))

                            # Regra de Robustez: Se telefone for inválido (<10 digitos, ex: CEP 8 dig) E tivermos o do chat
                            if telefone_auto:
                                if not tel_candidato or len(tel_limpo) < 10:
                                    logger.warning(
                                        f"⚠️ Telefone inválido detectado ('{tel_candidato}'). Substituindo pelo do Chat ID: {telefone_auto}"
                                    )
                                    dados_final["telefone"] = telefone_auto
                                else:
                                    # Se válido, mantém (pode ser outro número que o cliente passou)
                                    pass
                            elif not tel_candidato:
                                # Sem telefone no chat e sem na tool -> Log de aviso
                                logger.warning(
                                    "⚠️ Relatório sem telefone! (Chat ID inválido e IA não extraiu)"
                                )

                            # VALIDAÇÃO: Precisa ter pelo menos 3 campos preenchidos (além de telefone)
                            campos_validos = [
                                k for k in dados_final.keys() if k != "telefone"
                            ]
                            if len(campos_validos) < 3:
                                logger.warning(
                                    f"⚠️ Dados insuficientes para relatório: {len(campos_validos)} campos. Mínimo: 3"
                                )
                                campos_faltando = [
                                    f
                                    for f in known_fields
                                    if f not in dados_final and f != "telefone"
                                ]
                                return f"Erro: Dados insuficientes para enviar relatório. Colete primeiro: {', '.join(campos_faltando[:5])}..."

                            logger.info(
                                f"🚀 EXEC enviar_relatorio: tipo={tipo}, dados={dados_final}, grupo={grp}"
                            )
                            return f(
                                tipo=tipo,
                                dados=dados_final,
                                grupo_id=grp,
                                uazapi_url=url,
                                uazapi_token=tkn,
                                template=tpl,
                            )

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
                        f"🔧 Tool Enviar Relatório Dinâmica: grupo={grupo_cfg[:20]}... | Campos detectados: {placeholders_str}"
                    )

                elif tool_name == "atendimento_humano":
                    # Injeta dependencias (chat_id, timeout, redis_url)
                    # chat_id será passado em runtime, timeout vem da config
                    timeout_cfg = config_dict.get("timeout_minutes", 60)
                    redis_cfg = os.getenv("REDIS_URL", "redis://localhost:6379")
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    def create_handoff_wrapper(f, cid, tm, r_url):
                        def wrapped_handoff(motivo: str = "Solicitação do cliente"):
                            """Transfere a conversa para um atendente humano. A IA ficará pausada."""
                            return f(
                                motivo=motivo,
                                chat_id=cid,
                                timeout_minutes=tm,
                                redis_url=r_url,
                            )

                        return wrapped_handoff

                    tools.append(
                        StructuredTool.from_function(
                            func=create_handoff_wrapper(
                                fn_captured, chat_id, timeout_cfg, redis_cfg
                            ),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(
                        f"🔧 Tool Atendimento Humano Ativada: timeout={timeout_cfg}min"
                    )
                elif tool_name == "desativar_ia":
                    # Injeta dependencias (chat_id, redis_url)
                    redis_cfg = os.getenv("REDIS_URL", "redis://localhost:6379")
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )

                    def create_stop_wrapper(f, cid, r_url):
                        def wrapped_stop(motivo: str = "Solicitação do cliente"):
                            """Desativa a IA permanentemente e para de responder."""
                            return f(motivo=motivo, chat_id=cid, redis_url=r_url)

                        return wrapped_stop

                    tools.append(
                        StructuredTool.from_function(
                            func=create_stop_wrapper(fn_captured, chat_id, redis_cfg),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info("🔧 Tool Desativar IA Ativada (Opt-out)")
                elif tool_name == "criar_lembrete":
                    # Injeta dependencias (chat_id, client_id)
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )
                    client_id_value = client_config.get("id") if client_config else None

                    def create_reminder_wrapper(f, cid, clid):
                        def wrapped_reminder(
                            quando: str,
                            motivo: str = "Retornar contato conforme solicitado",
                        ):
                            """Cria um lembrete para retornar contato com o cliente em uma data futura."""
                            return f(
                                quando=quando,
                                motivo=motivo,
                                chat_id=cid,
                                client_id=clid,
                            )

                        return wrapped_reminder

                    tools.append(
                        StructuredTool.from_function(
                            func=create_reminder_wrapper(
                                fn_captured, chat_id, client_id_value
                            ),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(f"📅 Tool Criar Lembrete Ativada: chat={chat_id}")
                elif tool_name == "consultar_viabilidade_hubsoft":
                    # Injeta dependencias (hubsoft_config)
                    hubsoft_cfg = {
                        k: v for k, v in config_value.items() if k != "active"
                    }
                    fn_captured = (
                        tool_func.func if hasattr(tool_func, "func") else tool_func
                    )
                    # Pega defaults da config
                    cfg_raio = hubsoft_cfg.get("raio", 250)
                    cfg_detalhar = hubsoft_cfg.get("detalhar_portas", False)

                    def create_hubsoft_wrapper(
                        f, h_cfg, default_raio, default_detalhar
                    ):
                        def wrapped_hubsoft(
                            endereco: str,
                            numero: str,
                            bairro: str,
                            cidade: str,
                            estado: str,
                        ):
                            """Consulta viabilidade de cobertura de internet em um endereço usando HubSoft."""
                            return f(
                                endereco=endereco,
                                numero=numero,
                                bairro=bairro,
                                cidade=cidade,
                                estado=estado,
                                raio=default_raio,
                                detalhar_portas=default_detalhar,
                                hubsoft_config=h_cfg,
                            )

                        return wrapped_hubsoft

                    tools.append(
                        StructuredTool.from_function(
                            func=create_hubsoft_wrapper(
                                fn_captured, hubsoft_cfg, cfg_raio, cfg_detalhar
                            ),
                            name=tool_name,
                            description=tool_func.description,
                        )
                    )
                    logger.info(
                        f"🔧 Tool HubSoft Viabilidade Ativada: api={hubsoft_cfg.get('api_url', 'N/A')[:30]}... raio={cfg_raio}m"
                    )
                else:
                    tools.append(tool_func)
                    logger.info(f"🔧 Tool Ativada: {tool_name}")
    return tools or None
