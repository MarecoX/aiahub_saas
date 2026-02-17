import os
import httpx
import logging
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Configurações do SGP
SGP_URL = os.getenv("SGP_URL", "https://sgp.net.br")  # URL base padrão ou via ENV
SGP_TOKEN = os.getenv("SGP_TOKEN", "")
SGP_APP = os.getenv("SGP_APP", "")


# --- 1. Consultar Viabilidade ---


class ViabilidadeInput(BaseModel):
    cep: str = Field(description="CEP para consulta (apenas números ou com traço)")
    numero: Optional[str] = Field(description="Número do endereço", default=None)


def consultar_viabilidade(cep: str, numero: str = None, sgp_config: dict = None) -> str:
    """
    Consulta a viabilidade técnica no SGP para um determinado CEP.
    """
    cfg = sgp_config or {}
    url_base = cfg.get("sgp_url") or SGP_URL
    token = cfg.get("sgp_token") or SGP_TOKEN
    app_name = cfg.get("sgp_app") or SGP_APP

    if not url_base or not token or not app_name:
        return "Erro: Configuração do SGP incompleta (URL, TOKEN ou APP faltando)."

    url = f"{url_base}/api/ura/viabilidade/"

    # O exemplo do usuário mostra form-data/POST parameters
    payload = {"app": app_name, "token": token, "cep": cep.replace("-", "").strip()}

    if numero:
        payload["numero"] = numero

    try:
        # Usando httpx Sincrono
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, data=payload)
            response.raise_for_status()
            data = response.json()

        # Processar resposta (adaptar conforme retorno real da API)
        return f"Retorno Viabilidade: {data}"
    except Exception as e:
        logger.error(f"Erro ao consultar viabilidade: {e}")
        return f"Erro ao consultar viabilidade: {str(e)}"


tool_viabilidade = StructuredTool.from_function(
    func=consultar_viabilidade,
    name="consultar_viabilidade",
    description="ÚNICA ferramenta para verificar cobertura/viabilidade. Chame IMEDIATAMENTE após receber o CEP. NÃO use pesquisa em documentos para isso.",
    args_schema=ViabilidadeInput,
)


# --- 2. Pré-Cadastro ---


class PreCadastroInput(BaseModel):
    nome: str = Field(description="Nome do cliente ou Razão Social")
    cpfcnpj: str = Field(description="CPF ou CNPJ do cliente")
    email: str = Field(description="Email do cliente")
    celular: str = Field(description="Celular do cliente (com DDD)")
    cep: str = Field(description="CEP do endereço")
    logradouro: str = Field(description="Logradouro (Rua, Av, etc)")
    numero: int = Field(description="Número do endereço")
    bairro: str = Field(description="Bairro")
    cidade: str = Field(description="Cidade")
    uf: str = Field(description="Estado (UF)")
    datanasc: Optional[str] = Field(
        description="Data de nascimento (AAAA-MM-DD)", default=None
    )
    complemento: Optional[str] = Field(
        description="Complemento do endereço", default=""
    )
    tipo_pessoa: str = Field(
        description="Tipo de pessoa: 'F' (Física) ou 'J' (Jurídica)", default="F"
    )


def realizar_precadastro(
    nome: str,
    cpfcnpj: str,
    email: str,
    celular: str,
    cep: str,
    logradouro: str,
    numero: int,
    bairro: str,
    cidade: str,
    uf: str,
    datanasc: str = None,
    complemento: str = "",
    tipo_pessoa: str = "F",
    sgp_config: dict = None,
) -> str:
    """
    Realiza o pré-cadastro de um cliente no SGP (Pessoa Física ou Jurídica).
    """
    cfg = sgp_config or {}
    url_base = cfg.get("sgp_url") or SGP_URL
    token = cfg.get("sgp_token") or SGP_TOKEN
    app_name = cfg.get("sgp_app") or SGP_APP

    if not url_base or not token or not app_name:
        return "Erro: Credenciais do SGP não configuradas."

    endpoint = "F" if tipo_pessoa.upper() == "F" else "J"
    url = f"{url_base}/api/precadastro/{endpoint}"

    # Payload simplificado com campos obrigatórios
    payload = {
        "app": app_name,
        "token": token,
        "nome": nome,
        "cpfcnpj": cpfcnpj,
        "email": email,
        "celular": celular,
        "cep": cep,
        "logradouro": logradouro,
        "numero": numero,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "pais": "BR",
        "complemento": complemento,
        "origem": "wpp_bot",  # Identificador extra se útil
        "precadastro_ativar": 0,  # Default: apenas pré-cadastro
    }

    if datanasc:
        payload["datanasc"] = datanasc

    try:
        # Enviar como JSON
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return f"Pré-cadastro realizado com sucesso! ID: {data.get('id') or data}"
    except Exception as e:
        logger.error(f"Erro no pré-cadastro SGP: {e}")
        return f"Erro ao realizar pré-cadastro: {str(e)}"


tool_precadastro = StructuredTool.from_function(
    func=realizar_precadastro,
    name="realizar_precadastro",  # Nome simplificado
    description="Realiza o pré-cadastro de um novo cliente no sistema SGP.",
    args_schema=PreCadastroInput,
)


# --- 3. Verificar Cliente (CPF/CNPJ) ---


class VerificarClienteInput(BaseModel):
    cpfcnpj: str = Field(description="CPF ou CNPJ do cliente (apenas números)")


def verificar_cliente_sgp(cpfcnpj: str, sgp_config: dict = None) -> str:
    """
    Verifica se a pessoa é cliente do provedor pelo CPF ou CNPJ.
    Retorna dados do cliente e contratos ativos se encontrado.
    """
    cfg = sgp_config or {}
    url_base = cfg.get("sgp_url") or SGP_URL
    token = cfg.get("sgp_token") or SGP_TOKEN
    app_name = cfg.get("sgp_app") or SGP_APP

    if not url_base or not token or not app_name:
        return "Erro: Configuração do SGP incompleta (URL, TOKEN ou APP faltando)."

    url = f"{url_base}/api/ura/clientes/"
    payload = {
        "app": app_name,
        "token": token,
        "cpfcnpj": cpfcnpj.replace(".", "").replace("-", "").replace("/", "").strip(),
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, data=payload)
            response.raise_for_status()
            data = response.json()

        if not data or (isinstance(data, dict) and data.get("erro")):
            return f"Cliente não encontrado para CPF/CNPJ: {cpfcnpj}"

        return f"Dados do cliente: {data}"
    except Exception as e:
        logger.error(f"Erro ao verificar cliente SGP: {e}")
        return f"Erro ao verificar cliente: {str(e)}"


tool_verificar_cliente = StructuredTool.from_function(
    func=verificar_cliente_sgp,
    name="verificar_cliente_sgp",
    description="Verifica se a pessoa é cliente do provedor pelo CPF ou CNPJ. Use ANTES de qualquer consulta de fatura ou suporte.",
    args_schema=VerificarClienteInput,
)


# --- 4. Segunda Via de Fatura ---


class SegundaViaInput(BaseModel):
    id_contrato: str = Field(
        description="ID do contrato do cliente (obtido via verificar_cliente_sgp)"
    )


def segunda_via_fatura_sgp(id_contrato: str, sgp_config: dict = None) -> str:
    """
    Gera a segunda via de fatura(s) de um contrato no SGP.
    Retorna as faturas em aberto com valores, vencimentos e IDs.
    """
    cfg = sgp_config or {}
    url_base = cfg.get("sgp_url") or SGP_URL
    token = cfg.get("sgp_token") or SGP_TOKEN
    app_name = cfg.get("sgp_app") or SGP_APP

    if not url_base or not token or not app_name:
        return "Erro: Configuração do SGP incompleta (URL, TOKEN ou APP faltando)."

    url = f"{url_base}/api/ura/fatura2via/"
    payload = {
        "app": app_name,
        "token": token,
        "id_contrato": id_contrato,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, data=payload)
            response.raise_for_status()
            data = response.json()

        if not data or (isinstance(data, dict) and data.get("erro")):
            return f"Nenhuma fatura encontrada para o contrato {id_contrato}."

        return f"Faturas do contrato {id_contrato}: {data}"
    except Exception as e:
        logger.error(f"Erro ao buscar segunda via SGP: {e}")
        return f"Erro ao buscar segunda via: {str(e)}"


tool_segunda_via = StructuredTool.from_function(
    func=segunda_via_fatura_sgp,
    name="segunda_via_fatura_sgp",
    description="Busca faturas em aberto de um contrato e retorna dados para pagamento. Necessita do id_contrato obtido via verificar_cliente_sgp.",
    args_schema=SegundaViaInput,
)


# --- 5. Gerar PIX ---


class GerarPixInput(BaseModel):
    id_fatura: str = Field(
        description="ID da fatura (obtido via segunda_via_fatura_sgp)"
    )


def gerar_pix_sgp(id_fatura: str, sgp_config: dict = None) -> str:
    """
    Gera o código PIX (copia e cola) para pagamento de uma fatura específica.
    """
    cfg = sgp_config or {}
    url_base = cfg.get("sgp_url") or SGP_URL
    token = cfg.get("sgp_token") or SGP_TOKEN
    app_name = cfg.get("sgp_app") or SGP_APP

    if not url_base or not token or not app_name:
        return "Erro: Configuração do SGP incompleta (URL, TOKEN ou APP faltando)."

    url = f"{url_base}/api/ura/pagamento/pix/{id_fatura}"
    payload = {
        "app": app_name,
        "token": token,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, data=payload)
            response.raise_for_status()
            data = response.json()

        if not data or (isinstance(data, dict) and data.get("erro")):
            return f"Não foi possível gerar PIX para a fatura {id_fatura}."

        return f"PIX gerado para fatura {id_fatura}: {data}"
    except Exception as e:
        logger.error(f"Erro ao gerar PIX SGP: {e}")
        return f"Erro ao gerar PIX: {str(e)}"


tool_gerar_pix = StructuredTool.from_function(
    func=gerar_pix_sgp,
    name="gerar_pix_sgp",
    description="Gera código PIX (copia e cola) para pagamento de uma fatura. Necessita do id_fatura obtido via segunda_via_fatura_sgp.",
    args_schema=GerarPixInput,
)


# Exportar lista de tools
def get_sgp_tools():
    return [
        tool_viabilidade,
        tool_precadastro,
        tool_verificar_cliente,
        tool_segunda_via,
        tool_gerar_pix,
    ]
