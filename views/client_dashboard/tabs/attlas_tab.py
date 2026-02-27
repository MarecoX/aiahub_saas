"""
attlas_tab.py - Aba dedicada ao Attlas CRM

Configura credenciais, instrucoes para a IA e exibe as tools mais
importantes (Kanban Move + Lead Scoring) com orientacoes de uso.
"""

import json
import os
import sys
import streamlit as st

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection


def render_attlas_tab(user_data):
    st.header("Attlas CRM")
    st.caption(
        "Integre a IA com o Attlas CRM para gerenciar Kanban, Lead Scoring, "
        "tags, comentarios e muito mais — tudo via conversa no WhatsApp."
    )

    t_config = user_data.get("tools_config", {}) or {}
    attlas_cfg = t_config.get("attlas_crm", {})
    if isinstance(attlas_cfg, bool):
        attlas_cfg = {"active": attlas_cfg}

    # --- Toggle principal ---
    attlas_active = st.toggle(
        "Ativar Attlas CRM",
        value=attlas_cfg.get("active", False),
        help="Habilita 62 ferramentas do Attlas CRM para sua IA.",
        key="attlas_toggle",
    )

    if not attlas_active:
        st.info("Ative a integracao para configurar credenciais e ferramentas.")
        # Salvar estado desativado
        if st.button("Salvar", key="attlas_save_off"):
            new_tools = t_config.copy()
            new_tools["attlas_crm"] = {"active": False}
            _save_tools_config(user_data, new_tools)
        return

    st.divider()

    # =====================================================
    # SECAO 1: Credenciais
    # =====================================================
    st.subheader("Credenciais")

    col_url, col_token = st.columns(2)
    with col_url:
        base_url = st.text_input(
            "URL do Tenant",
            value=attlas_cfg.get("base_url", ""),
            placeholder="https://empresa.attlascrm.com",
            help="URL base do seu tenant no Attlas CRM (sem barra no final).",
            key="attlas_base_url",
        )
    with col_token:
        token = st.text_input(
            "Token Sanctum (Bearer)",
            value=attlas_cfg.get("token", ""),
            type="password",
            help="Token de API gerado via POST /api/v1/auth-token (valido por 7 dias).",
            key="attlas_token",
        )

    st.divider()

    # =====================================================
    # SECAO 2: Instrucoes para a IA
    # =====================================================
    st.subheader("Instrucoes para a IA")
    st.caption(
        "Essas instrucoes sao adicionadas ao prompt do sistema para guiar "
        "o comportamento da IA ao usar as ferramentas do Attlas."
    )

    instructions = st.text_area(
        "Instrucoes",
        value=attlas_cfg.get("instructions", ""),
        height=120,
        placeholder=(
            "Ex: Quando o cliente perguntar sobre um lead, consulte o Kanban. "
            "Quando pedir para criar um card, pergunte nome e telefone primeiro. "
            "Registre resultado como 'ganho' quando o cliente confirmar a compra."
        ),
        key="attlas_instructions",
    )

    st.divider()

    # =====================================================
    # SECAO 3: Mover Kanban (Qualificacao)
    # =====================================================
    st.subheader("Mover no Kanban (Qualificacao Automatica)")

    with st.expander("Como funciona?", expanded=False):
        st.markdown("""
**A IA pode mover cards entre colunas do Kanban automaticamente.**

Para isso, inclua nas instrucoes acima (ou no prompt do sistema) regras como:

**Exemplo de qualificacao por perguntas:**
```
Quando o lead responder as 3 perguntas qualificatorias:
1. Qual seu orcamento? (acima de R$ 5.000)
2. Qual o prazo desejado? (menos de 30 dias)
3. Quem decide a compra? (o proprio lead)

Se TODAS as respostas forem positivas:
  -> Use attlas_mover_card para mover o card para a coluna "Qualificado"
  -> Use attlas_adicionar_pontuacao para dar +30 pontos com motivo "Lead qualificado por perguntas"

Se ALGUMA resposta for negativa:
  -> Mova para "Nurturing"
  -> Adicione -10 pontos com motivo "Nao atende criterios"
```

**Tools disponiveis para Kanban:**
- `attlas_buscar_kanban` — Ver todas as colunas e cards de um projeto
- `attlas_listar_colunas` — Listar colunas (IDs necessarios para mover)
- `attlas_mover_card` — Mover card para outra coluna
- `attlas_criar_card` — Criar novo card/lead
- `attlas_registrar_resultado` — Marcar como ganho/perdido
""")

    st.divider()

    # =====================================================
    # SECAO 4: Lead Scoring
    # =====================================================
    st.subheader("Lead Scoring (Pontuacao Automatica)")

    with st.expander("Como funciona?", expanded=False):
        st.markdown("""
**A IA pode aumentar ou diminuir a pontuacao de um lead automaticamente.**

Inclua nas instrucoes regras de pontuacao. Exemplo:

```
Regras de Lead Scoring:
- Lead informou orcamento acima de R$ 10.000 -> +20 pontos
- Lead pediu proposta ou demonstracao -> +15 pontos
- Lead confirmou que e o decisor -> +10 pontos
- Lead respondeu dentro de 5 minutos -> +5 pontos
- Lead disse que "vai pensar" -> -5 pontos
- Lead nao respondeu apos follow-up -> -10 pontos
- Lead pediu para nao entrar em contato -> -30 pontos
```

**Tools disponiveis para Score:**
- `attlas_adicionar_pontuacao` — Adiciona pontos (positivo ou negativo) com motivo
- `attlas_historico_pontuacao` — Consulta historico completo de score de um card

**Temperaturas automaticas do Attlas:**
- **Frio**: 0-30 pontos
- **Morno**: 31-70 pontos
- **Quente**: 71+ pontos
""")

    st.divider()

    # =====================================================
    # SECAO 5: Todas as Tools
    # =====================================================
    st.subheader("Ferramentas Disponiveis")
    st.caption("62 ferramentas organizadas em 13 modulos.")

    _tools_summary = {
        "Projetos": "Listar, criar e gerenciar pipelines/funis",
        "Listas (Colunas)": "Criar, renomear, reordenar, configurar etapas do Kanban",
        "Cards (Leads)": "CRUD completo, mover, duplicar, arquivar, definir responsavel",
        "Lead Scoring": "Adicionar/remover pontuacao, consultar historico",
        "Comentarios": "Adicionar, listar e deletar comentarios em cards",
        "Tags": "Criar, listar, aplicar e remover tags de cards",
        "Participantes": "Adicionar/remover participantes de cards",
        "Vinculos": "Vincular cards entre si (dependencias, relacionamentos)",
        "Checklists": "Criar, editar, marcar itens de checklists em cards",
        "Produtos": "Criar produtos, vincular a cards, registrar vendas",
        "Workflows": "Criar/editar automacoes (triggers, condicoes, acoes)",
        "Integracoes": "Gerenciar tokens de API e webhooks",
        "Atalhos": "Mover card simplificado, preencher CRM em lote, qualificar lead",
    }

    for name, desc in _tools_summary.items():
        st.markdown(f"- **{name}**: {desc}")

    st.divider()

    # =====================================================
    # SALVAR
    # =====================================================
    if st.button("Salvar Configuracao Attlas", type="primary", key="attlas_save"):
        new_cfg = {
            "active": attlas_active,
            "base_url": base_url.rstrip("/") if base_url else "",
            "token": token,
            "instructions": instructions,
        }

        if attlas_active and (not base_url or not token):
            st.warning("Preencha a URL do Tenant e o Token para ativar.")
            return

        new_tools = t_config.copy()
        new_tools["attlas_crm"] = new_cfg
        _save_tools_config(user_data, new_tools)


def _save_tools_config(user_data: dict, new_tools_config: dict):
    """Salva tools_config no banco e atualiza session_state."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE clients SET tools_config = %s WHERE id = %s",
                    (json.dumps(new_tools_config), user_data["id"]),
                )
        user_data["tools_config"] = new_tools_config
        st.session_state["user_data"] = user_data
        st.success("Configuracao salva com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
