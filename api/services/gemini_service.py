import os
import time
import logging
import unicodedata
import mimetypes
from google import genai
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv(dotenv_path="../.env")
load_dotenv()

logger = logging.getLogger("GeminiService")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class GeminiService:
    def __init__(self):
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set!")
            self.client = None
        else:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                logger.info("✅ Client Google GenAI inicializado (Service V2).")
            except Exception as e:
                logger.error(f"❌ Falha ao iniciar Client GenAI: {e}")
                self.client = None

    def normalize_to_ascii(self, text):
        """Remove acentos e caracteres especiais para evitar erro de Header/ASCII."""
        if not text:
            return ""
        return (
            unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore")
            .decode("ascii")
        )

    def get_or_create_vector_store(self, store_name_or_id: str):
        """
        Busca ou cria um File Search Store.
        Retorna (store, error_message).
        """
        if not self.client:
            return None, "Client Gemini não inicializado (Verifique API KEY)."

        try:
            # Check safe se já é um ID
            is_id = store_name_or_id and (
                "fileSearchStores/" in store_name_or_id
                or "corpora/" in store_name_or_id
            )

            if is_id:
                try:
                    store = self.client.file_search_stores.get(name=store_name_or_id)
                    return store, None
                except Exception:
                    pass

            # Criação
            display_val = (
                store_name_or_id
                if store_name_or_id
                else f"Store-Auto-{int(time.time())}"
            )

            logger.info(f"Criando Store no Gemini com display_name: {display_val}")
            store = self.client.file_search_stores.create(
                config={"display_name": f"Store: {display_val}"}
            )
            logger.info(f"✅ Store Criado: {store.name}")
            return store, None

        except Exception as e:
            logger.error(f"Erro no Vector Store: {e}")
            return None, str(e)

    def upload_file_to_store(
        self, file_path: str, store_name: str, custom_display_name: str = None
    ):
        """
        Faz upload direto e indexa no Store.
        Retorna (operation, error).
        """
        if not self.client:
            return None, "Client Off."

        try:
            final_name = (
                custom_display_name
                if custom_display_name
                else os.path.basename(file_path)
            )
            safe_name = self.normalize_to_ascii(final_name)

            logger.info(
                f"📤 Uploading {final_name} (as {safe_name}) to {store_name}..."
            )

            mime_type, _ = mimetypes.guess_type(file_path)
            if file_path.lower().endswith(".csv"):
                mime_type = "text/plain"
            if not mime_type:
                mime_type = "text/plain"

            logger.info(f"📄 MIME detectado: {mime_type}")

            # Usa método de conveniência de upload > store
            op = self.client.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config={"display_name": safe_name, "mime_type": mime_type},
            )
            logger.info("⏳ Aguardando processamento do arquivo no Gemini...")
            # Pooling simples para garantir que completou
            while not op.done:
                time.sleep(2)
                try:
                    op = self.client.operations.get(name=op.name)
                except Exception:
                    break

            if op.error:
                return None, str(op.error)

            logger.info(f"✅ Arquivo indexado: {final_name}")
            return op, None

        except Exception as e:
            logger.error(f"Erro upload: {e}")
            return None, str(e)

    def list_files_in_store(self, store_name: str):
        """
        Lista arquivos em um Store. Retorna lista de Documents.
        """
        if not self.client:
            return []
        try:
            return self.client.file_search_stores.documents.list(parent=store_name)
        except Exception as e:
            logger.error(f"Erro list files: {e}")
            return []
    
    def delete_file(self, file_name: str):
        """
        Deleta um arquivo.
        Args:
            file_name (str): URI do documento (fileSearchStores/.../documents/...) ou file name.
        """
        if not self.client:
            return False

        logger.info(f"🗑️ Solicitando deleção (FORCE): {file_name}")

        try:
            # force=True permite deletar documentos que possuem chunks (non-empty)
            # Python SDK provavelmente espera isso dentro de 'config'
            self.client.file_search_stores.documents.delete(
                name=file_name, config={"force": True}
            )
            logger.info(f"✅ Documento deletado do store: {file_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Erro delete document ({file_name}): {e}")
            return False


# Singleton instance
