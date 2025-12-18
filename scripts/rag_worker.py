import sys
import os
import asyncio
import logging
import redis.asyncio as redis
import google.generativeai as genai
from kestra import Kestra

# Adiciona o diretório do script ao path para importar saas_db
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from saas_db import get_client_config
from tools_library import get_enabled_tools

# Configuração de Logs
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("KestraRAG")

# Configurações Globais
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BUFFER_KEY_SUFIX = os.getenv("BUFFER_KEY_SUFIX", "_buffer")

# Configuração Gemini (Chave API do Sistema ou do Cliente?)
# Por enquanto vamos usar a do Sistema (.env) para simplificar
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("⚠️ GEMINI_API_KEY não encontrada no ambiente!")

async def run_rag():
    logger.info("🚀 Iniciando Worker SaaS (Kestra 2.0)")
    
    # 1. Inputs do Kestra
    chat_id = os.getenv("KESTRA_CHAT_ID")
    client_token = os.getenv("KESTRA_CLIENT_TOKEN") # <--- O Token que define quem paga a conta
    
    if not chat_id or chat_id == 'None':
        logger.info("Nenhum Chat ID para processar. Encerrando.")
        return

    if not client_token:
        logger.error("❌ ERRO: KESTRA_CLIENT_TOKEN não fornecido! O Worker não sabe quem é o cliente.")
        return

    # 2. Carregar "Cérebro" do Banco de Dados
    logger.info(f"🔍 Buscando configs para o token: {client_token}")
    client_config = get_client_config(client_token)
    
    if not client_config:
        logger.error("❌ Cliente não encontrado no Banco de Dados. Abortando.")
        # Opcional: Mandar msg de erro pro WhatsApp
        return

    logger.info(f"🧠 Cliente Carregado: {client_config['name']}")
    system_prompt = client_config['system_prompt']
    # store_id = client_config['gemini_store_id'] # Futuro: Usar no contexto
    
    # 3. Recuperar Mensagens do Redis (Buffer)
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    
    # --- TRAP LIST (Check Pause) ---
    pause_key = f"ai_paused:{chat_id}"
    is_paused = await redis_client.get(pause_key)
    
    if is_paused:
        logger.warning(f"🛑 ATENÇÃO: Chat {chat_id} PAUSADO (Atendimento Humano). Ignorando ciclo.")
        # Limpa o buffer de mensagens acumuladas do usuário para não processar depois
        cleanup_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        await redis_client.delete(cleanup_key)
        await redis_client.close()
        
        # Output VAZIO para não disparar envio
        Kestra.outputs({'response_text': '', 'chat_id': chat_id})
        return
    # -------------------------------

    key = f"{chat_id}{BUFFER_KEY_SUFIX}"
    
    # Leitura + Limpeza Atômica
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        results = await pipe.execute()
    
    msgs = results[0]
    
    if not msgs:
        logger.info(f"Buffer vazio para {chat_id}. Worker duplicado?")
        return
        
    full_query = " ".join(msgs)
    logger.info(f"💬 Query do Usuário: {full_query}")
    
    # 4. Processamento Inteligente (Agente Híbrido: OpenAI + Gemini Tools)
    # Importa aqui para evitar circularidade se houver, ou move para topo
    from chains_saas import ask_saas
    
    try:
        # Carrega Tools Dinâmicas
        tools_list = get_enabled_tools(client_config.get('tools_config'))
        
        # Chama o Cérebro (OpenAI) passando as Tools (Gemini/Maps)
        response_text = await ask_saas(
            query=full_query,
            chat_id=chat_id,
            system_prompt=system_prompt,
            client_config=client_config,
            tools_list=tools_list
        )
        
        logger.info(f"🤖 Resposta Agente SaaS: {response_text[:50]}...")
        
        # 5. Output para o Kestra (Task de Envio)
        # Extrai possíveis overrides (SaaS Private Mode)
        # Agora api_url é coluna dedicada
        api_override_url = client_config.get('api_url') or ''
        
        # api_key ainda fica no json pois é uso raro (Private Instance)
        tools_cfg = client_config.get('tools_config', {}) or {}
        api_override_key = tools_cfg.get('api_key', '')
        
        Kestra.outputs({
            'response_text': response_text, 
            'chat_id': chat_id,
            'api_url': api_override_url,
            'api_key': api_override_key
        })
        
    except Exception as e:
        logger.error(f"❌ Erro na Geração IA: {e}", exc_info=True)
        raise e

if __name__ == "__main__":
    asyncio.run(run_rag())
