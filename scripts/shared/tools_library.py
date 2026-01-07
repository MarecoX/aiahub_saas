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
        logger.error(f"Erro ao pausar IA no Redis: {e}")
        return f"TRANSBORDO_HUMANO_ATIVADO (erro ao pausar: {e})"


# Mapa de Funções Disponíveis (Nome no JSON do DB -> Função Python)
AVAILABLE_TOOLS = {
    "consultar_cep": consultar_cep,
    "qualificado_kommo_provedor": qualificado_kommo_provedor,
    "consultar_erp": consultar_erp,
    "enviar_relatorio": enviar_relatorio,
    "atendimento_humano": atendimento_humano,
    "audio": audio,
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

                    # Extrai placeholders do template para gerar description dinâmica
                    import re

                    placeholders = (
                        re.findall(r"\{\{(\w+)\}\}", template_cfg)
                        if template_cfg
                        else []
                    )
                    placeholders_str = (
                        ", ".join(placeholders)
                        if placeholders
                        else "nome, cpf, email, telefone, etc."
                    )

                    # Uazapi vem da config global do cliente (DB) ou Env Var (Fallback)
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

                    # Extrai telefone do chat_id (ex: 556199673672@s.whatsapp.net -> 556199673672)
                    telefone_from_chat = ""
                    if chat_id and "@" in str(chat_id):
                        telefone_from_chat = str(chat_id).split("@")[0]
                        logger.info(
                            f"📱 Telefone extraído do chat_id: {telefone_from_chat}"
                        )

                    def create_relatorio_wrapper(f, grp, url, tkn, tpl, telefone_auto):
                        def wrapped_relatorio(tipo: str = "ficha", dados: dict = None):
                            """Envia um relatório para o grupo de vendas no WhatsApp."""
                            # Auto-injeta telefone se não foi preenchido pela IA
                            dados_final = dados or {}
                            if telefone_auto and "telefone" not in dados_final:
                                dados_final["telefone"] = telefone_auto
                                logger.info(
                                    f"📱 Telefone auto-injetado: {telefone_auto}"
                                )

                            logger.info(
                                f"🚀 EXEC enviar_relatorio: tipo={tipo}, dados={dados_final}, grupo={grp}, url={url}"
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

                    # Schema Pydantic DINÂMICO baseado no template
                    class EnviarRelatorioInput(BaseModel):
                        tipo: str = Field(
                            default="ficha",
                            description="Tipo do relatório: ficha, reserva ou pedido",
                        )
                        dados: dict = Field(
                            ...,
                            description=f"""Dicionário OBRIGATÓRIO com os dados do cliente.
Você DEVE preencher TODAS estas chaves extraindo os dados da conversa: {placeholders_str}
Para cada chave, extraia o valor correspondente da conversa com o cliente.
Se algum dado não foi coletado, pergunte ao cliente antes de chamar esta ferramenta.
Exemplo: {{"nome": "João Silva", "cpf": "123.456.789-00", ...}}""",
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
                            ),
                            name=tool_name,
                            description=f"""Envia um relatório para o grupo de vendas no WhatsApp.
QUANDO USAR: Após o cliente confirmar os dados coletados.
CAMPOS NECESSÁRIOS: {placeholders_str}
COMO CHAMAR: Passe o parâmetro "dados" com um dicionário contendo os campos acima.
Extraia os valores da conversa com o cliente.""",
                            args_schema=EnviarRelatorioInput,
                        )
                    )
                    logger.info(
                        f"🔧 Tool Enviar Relatório Ativada: grupo={grupo_cfg[:20]}... | Campos: {placeholders_str}"
                    )
                elif tool_name == "atendimento_humano":
                    # Injeta dependencias (chat_id, timeout, redis_url)
                    # chat_id será passado em runtime, timeout vem da config
                    timeout_cfg = config_dict.get("timeout_minutes", 60)
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
                else:
                    tools.append(tool_func)
                    logger.info(f"🔧 Tool Ativada: {tool_name}")
    return tools or None
