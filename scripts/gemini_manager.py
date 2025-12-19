import os
import time
import logging
from google import genai
from google.genai import types
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GeminiManagerV2")

load_dotenv(dotenv_path="../.env")
load_dotenv()

import unicodedata

API_KEY = os.getenv("GEMINI_API_KEY")
client = None

def normalize_to_ascii(text):
    """Remove acentos e caracteres especiais para evitar erro de Header/ASCII."""
    if not text: return ""
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

if API_KEY:
    try:
        client = genai.Client(api_key=API_KEY)
        logger.info("✅ Client Google GenAI inicializado.")
    except Exception as e:
        logger.error(f"❌ Falha ao iniciar Client GenAI: {e}")

def get_or_create_vector_store(store_name_or_id: str):
    """
    Busca ou cria um File Search Store.
    Retorna (store, error_message).
    """
    if not client:
        return None, "Client Gemini não inicializado (Verifique API KEY)."

    try:
        # Se já parece um ID (não sabemos o formato exato do v1alpha, mas geralmente tem barras)
        # O user disse que retorna um store object.
        # Vamos tentar GET primeiro se tiver cara de ID.
        pass 
        # API v1 (Enterprise) não tem 'get_vector_store' pelo nome de exibição fácil.
        # Mas 'store_bf99' é o nosso controle.
        
        # Vamos assumir: Se começar com 'corpora/' ou 'fileSearchStores/', é ID.
        # Caso contrário, criamos um novo com esse display_name.
        
        # NOVO SDK: client.file_search_stores.create(config=...)
        
        # Check safe
        is_id = store_name_or_id and ("fileSearchStores/" in store_name_or_id or "corpora/" in store_name_or_id)
        
        if is_id:
             # Tenta obter
             try:
                 # get requer name="fileSearchStores/xyz"
                 store = client.file_search_stores.get(name=store_name_or_id)
                 return store, None
             except Exception:
                 # Se falhar, talvez não exista.
                 pass

        # Criação
        # Se for None, gera um genérico
        display_val = store_name_or_id if store_name_or_id else f"Store-Auto-{int(time.time())}"
        
        logger.info(f"Criando Store com display_name: {display_val}")
        store = client.file_search_stores.create(
            config={'display_name': f"Store: {display_val}"}
        )
        logger.info(f"✅ Store Criado: {store.name}")
        return store, None

    except Exception as e:
        logger.error(f"Erro no Vector Store: {e}")
        return None, str(e)

import mimetypes

# ... (imports)

def upload_file_to_store(file_path: str, store_name: str, custom_display_name: str = None):
    """
    Faz upload direto e indexa no Store.
    Retorna (operation, error).
    """
    if not client:
        return None, "Client Off."

    try:
        final_name = custom_display_name if custom_display_name else os.path.basename(file_path)
        # Sanitiza para evitar crash de ASCII no SDK
        safe_name = normalize_to_ascii(final_name)
        
        logger.info(f"📤 Uploading {final_name} (as {safe_name}) to {store_name}...")
        
        # Detect MIME
        mime_type, _ = mimetypes.guess_type(file_path)
        
        # Force text/plain for CSV to avoid 500 INTERNAL or handling issues
        if file_path.lower().endswith(".csv"):
            mime_type = "text/plain"
            
        if not mime_type:
            mime_type = "text/plain" # Fallback safe
            
        logger.info(f"📄 MIME detectado: {mime_type}")
        
        with open(file_path, "rb") as f:
            op = client.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config={
                    'display_name': safe_name,
                    'mime_type': mime_type 
                }
            )
            
        # O OP é assíncrono? O user fez while not op.done.
        # Vamos esperar um pouco para garantir.
        
        logger.info("⏳ Aguardando processamento...")
        while not op.done:
             time.sleep(2)
             try:
                 op = client.operations.get(name=op.name)
             except Exception:
                 # as vezes o get falha se acabar rápido
                 break
             
        # op.result não existe em todos os SDKs/Versões, se op.done=True, assumimos sucesso se não tiver error
        if op.error:
             return None, str(op.error)
             
        logger.info(f"✅ Arquivo processado: {final_name}")
        return op, None

    except Exception as e:
        logger.error(f"Erro upload: {e}")
        return None, str(e)

def list_files_in_store(store_name: str):
    """
    Lista arquivos em um Store.
    """
    if not client: return []
    try:
        # Padrão Enterprise: parent = store_name (resource name)
        # O retorno é um iterável de Document
        return client.file_search_stores.documents.list(parent=store_name)
    except Exception as e:
        logger.error(f"Erro list files: {e}")
        return []

def delete_file(file_name: str):
    """
    Deleta um arquivo pelo seu Resource Name (corpora/x/documents/y).
    """
    if not client: return False
    try:
        client.file_search_stores.documents.delete(name=file_name)
        logger.info(f"🗑️ Arquivo deletado: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Erro delete file: {e}")
        return False
