import os
import httpx
import logging
from google.generativeai.types import FunctionDeclaration, Tool

logger = logging.getLogger("KestraTools")

# Tenta pegar API Key do Maps, ou fallback pro Gemini (se for a mesma key irrestrita)
# Obtém chave específica do Maps. SEM fallback para Gemini para evitar erros de permissão.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if GOOGLE_MAPS_API_KEY:
    logger.info(f"🗺️ Google Maps Key carregada: ...{GOOGLE_MAPS_API_KEY[-4:]}")
else:
    logger.warning("⚠️ GOOGLE_MAPS_API_KEY não encontrada! A tool consultar_cep vai falhar.")


from langchain.tools import tool

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
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        # EXECUÇÃO SÍNCRONA (Segura para ThreadPool)
        with httpx.Client() as client:
            resp = client.get(url, params=params, timeout=10.0)
            data = resp.json()
            
            # Log de Debug Profundo
            logger.info(f"🗺️ Maps API Status: {data.get('status')} | Results: {len(data.get('results', []))}")
            
            if data['status'] != 'OK':
                logger.error(f"❌ Erro Maps API: {data}")
                return {"error": f"Google Maps Error: {data['status']}"}
            
            if not data['results']:
                return {"error": "CEP não encontrado (ZERO_RESULTS). Verifique o número."}

            # Simplifica a resposta para o LLM não se perder
            result = data['results'][0]
            # logger.info(f"💬 Query do Usuário: {result}")
            formatted_address = result.get('formatted_address', 'Endereço não formatado')
            location = result.get('geometry', {}).get('location', {})
            
            components = {}
            for comp in result.get('address_components', []):
                types = comp.get('types', [])
                if 'route' in types:
                    components['logradouro'] = comp['long_name']
                elif 'sublocality' in types:
                    components['bairro'] = comp['long_name']
                elif 'administrative_area_level_2' in types:
                    components['cidade'] = comp['long_name']
                elif 'administrative_area_level_1' in types:
                    components['estado'] = comp['short_name']

            final_payload = {
                "cep": clean_cep,
                "endereco": formatted_address,
                "detalhes": components,
                "lat": location.get('lat'),
                "lng": location.get('lng')
            }
            logger.info(f"✅ Retornando para o Agente: {final_payload}")
            return final_payload

    except Exception as e:
        logger.error(f"Erro no consultar_cep: {e}")
        return {"error": str(e)}

# Mapa de Funções Disponíveis (Nome no JSON do DB -> Função Python)
AVAILABLE_TOOLS = {
    "consultar_cep": consultar_cep,
    # "check_inventory": check_inventory, etc...
}

def get_enabled_tools(tools_config: dict):
    """
    Retorna a lista de funcoes Python para passar pro Gemini
    baseado no JSON de configuração do cliente.
    Ex: tools_config = {"consultar_cep": true}
    """
    tools = []
    
    # Se o config for nulo, retorna vazio
    if not tools_config:
        return []

    # Itera sobre o config do banco
    for tool_name, is_enabled in tools_config.items():
        if is_enabled and tool_name in AVAILABLE_TOOLS:
            tools.append(AVAILABLE_TOOLS[tool_name])
            logger.info(f"🔧 Tool Ativada: {tool_name}")
            
    return tools or None
