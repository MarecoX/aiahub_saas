"""
attlas_tab.py - Aba dedicada ao Attlas CRM

Configura credenciais, regras de qualificacao (Kanban move) e
regras de Lead Scoring. As regras sao convertidas automaticamente
em instrucoes injetadas no prompt da IA.
"""

import json
import copy
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
        "tags e muito mais — tudo via conversa no WhatsApp."
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
            help="Token de API gerado via POST /api/v1/auth-token.",
            key="attlas_token",
        )

    st.divider()

    # =====================================================
    # SECAO 2: Regras de Qualificacao (Kanban Move)
    # =====================================================
    st.subheader("Regras de Qualificacao (Mover no Kanban)")
    st.caption(
        "Defina criterios que, quando atendidos na conversa, fazem a IA "
        "mover o card automaticamente para outra coluna do Kanban."
    )

    # Session state para regras de qualificacao
    qual_key = f"attlas_qual_rules_{user_data['id']}"
    if qual_key not in st.session_state:
        st.session_state[qual_key] = copy.deepcopy(
            attlas_cfg.get("qualification_rules", [])
        )

    qual_rules = st.session_state[qual_key]

    qual_to_remove = []
    for i, rule in enumerate(qual_rules):
        with st.expander(
            f"Regra {i + 1}: {rule.get('name', 'Nova regra')}",
            expanded=(i == len(qual_rules) - 1),
        ):
            rule["name"] = st.text_input(
                "Nome da regra",
                value=rule.get("name", ""),
                placeholder="Ex: Lead Qualificado (BANT)",
                key=f"qual_name_{user_data['id']}_{i}",
            )

            rule["condition"] = st.text_area(
                "Quando mover? (condicao)",
                value=rule.get("condition", ""),
                height=80,
                placeholder=(
                    "Ex: Quando o lead confirmar que tem orcamento acima de R$ 5.000, "
                    "prazo menor que 30 dias, e que ele mesmo decide a compra."
                ),
                key=f"qual_cond_{user_data['id']}_{i}",
                help="Descreva em linguagem natural a condicao para mover.",
            )

            col_proj, col_col = st.columns(2)
            with col_proj:
                rule["project_uuid"] = st.text_input(
                    "UUID do Projeto",
                    value=rule.get("project_uuid", ""),
                    placeholder="abc-123-def-456",
                    key=f"qual_proj_{user_data['id']}_{i}",
                    help="UUID do projeto/pipeline no Attlas.",
                )
            with col_col:
                rule["target_column"] = st.text_input(
                    "Nome da coluna destino",
                    value=rule.get("target_column", ""),
                    placeholder="Ex: Qualificado, Em Negociacao, Ganho",
                    key=f"qual_col_{user_data['id']}_{i}",
                    help="Nome da coluna para onde o card sera movido.",
                )

            rule["also_score"] = st.number_input(
                "Pontos de score ao mover (opcional)",
                value=int(rule.get("also_score", 0)),
                min_value=-100,
                max_value=100,
                key=f"qual_score_{user_data['id']}_{i}",
                help="Pontuacao extra ao mover. 0 = nao pontuar. Positivo = aquecer. Negativo = esfriar.",
            )

            if st.button("Remover regra", key=f"qual_rem_{user_data['id']}_{i}"):
                qual_to_remove.append(i)

    if qual_to_remove:
        for idx in sorted(qual_to_remove, reverse=True):
            del st.session_state[qual_key][idx]
        st.rerun()

    if st.button("Adicionar regra de qualificacao", key="qual_add"):
        st.session_state[qual_key].append(
            {
                "name": "",
                "condition": "",
                "project_uuid": "",
                "target_column": "",
                "also_score": 0,
            }
        )
        st.rerun()

    st.divider()

    # =====================================================
    # SECAO 3: Regras de Lead Scoring
    # =====================================================
    st.subheader("Regras de Lead Scoring")
    st.caption(
        "Defina criterios que aumentam ou diminuem a pontuacao do lead. "
        "A IA aplica automaticamente durante a conversa."
    )

    # Explicacao da classificacao
    with st.expander("Entenda a classificacao A/B/C/D", expanded=False):
        st.markdown("""
| Faixa | Classificacao | Temperatura | Significado |
|-------|:---:|:---:|---|
| 0 - 25 | **D** | Frio | Lead frio, pouco interesse |
| 26 - 50 | **C** | Morno | Algum interesse, precisa nurturing |
| 51 - 75 | **B** | Quente | Bom interesse, em negociacao |
| 76 - 100 | **A** | Muito Quente | Pronto para fechar |

A pontuacao e **cumulativa**: cada interacao na conversa pode somar ou subtrair pontos.
A IA usa `attlas_adicionar_pontuacao(points, reason)` automaticamente conforme as regras abaixo.
""")

    # Session state para regras de score
    score_key = f"attlas_score_rules_{user_data['id']}"
    if score_key not in st.session_state:
        st.session_state[score_key] = copy.deepcopy(
            attlas_cfg.get("scoring_rules", [])
        )

    score_rules = st.session_state[score_key]

    score_to_remove = []
    for i, rule in enumerate(score_rules):
        with st.expander(
            f"Regra {i + 1}: {rule.get('trigger', 'Nova regra')} ({_format_points(rule.get('points', 0))})",
            expanded=(i == len(score_rules) - 1),
        ):
            rule["trigger"] = st.text_input(
                "Gatilho (quando pontuar)",
                value=rule.get("trigger", ""),
                placeholder="Ex: Lead informou orcamento acima de R$ 10.000",
                key=f"score_trigger_{user_data['id']}_{i}",
                help="Descreva a situacao que gera pontuacao.",
            )

            col_pts, col_reason = st.columns([1, 2])
            with col_pts:
                rule["points"] = st.number_input(
                    "Pontos",
                    value=int(rule.get("points", 10)),
                    min_value=-100,
                    max_value=100,
                    key=f"score_pts_{user_data['id']}_{i}",
                    help="Positivo = aquecer lead. Negativo = esfriar.",
                )
            with col_reason:
                rule["reason"] = st.text_input(
                    "Motivo registrado no historico",
                    value=rule.get("reason", ""),
                    placeholder="Ex: Orcamento alto confirmado",
                    key=f"score_reason_{user_data['id']}_{i}",
                    help="Esse texto aparece no historico do score do card.",
                )

            if st.button("Remover regra", key=f"score_rem_{user_data['id']}_{i}"):
                score_to_remove.append(i)

    if score_to_remove:
        for idx in sorted(score_to_remove, reverse=True):
            del st.session_state[score_key][idx]
        st.rerun()

    if st.button("Adicionar regra de score", key="score_add"):
        st.session_state[score_key].append(
            {"trigger": "", "points": 10, "reason": ""}
        )
        st.rerun()

    st.divider()

    # =====================================================
    # SECAO 4: Instrucoes adicionais (livre)
    # =====================================================
    st.subheader("Instrucoes adicionais para a IA")
    st.caption(
        "Instrucoes extras alem das regras acima. "
        "Ex: como a IA deve se comportar ao consultar o Kanban, criar cards, etc."
    )

    extra_instructions = st.text_area(
        "Instrucoes adicionais",
        value=attlas_cfg.get("extra_instructions", ""),
        height=100,
        placeholder=(
            "Ex: Sempre pergunte o nome e telefone antes de criar um card. "
            "Quando o lead fechar negocio, registre como 'ganho' com o valor."
        ),
        key="attlas_extra_instructions",
    )

    st.divider()

    # =====================================================
    # PREVIEW: Instrucoes geradas
    # =====================================================
    generated = _generate_instructions(qual_rules, score_rules, extra_instructions)

    with st.expander("Preview: instrucoes que serao injetadas no prompt da IA", expanded=False):
        st.code(generated, language="markdown")

    st.divider()

    # =====================================================
    # SALVAR
    # =====================================================
    if st.button("Salvar Configuracao Attlas", type="primary", key="attlas_save"):
        if attlas_active and (not base_url or not token):
            st.warning("Preencha a URL do Tenant e o Token para ativar.")
            return

        new_cfg = {
            "active": attlas_active,
            "base_url": base_url.rstrip("/") if base_url else "",
            "token": token,
            "qualification_rules": st.session_state[qual_key],
            "scoring_rules": st.session_state[score_key],
            "extra_instructions": extra_instructions,
            # Gera instrucoes consolidadas para injecao no prompt
            "instructions": generated,
        }

        new_tools = t_config.copy()
        new_tools["attlas_crm"] = new_cfg
        _save_tools_config(user_data, new_tools)


# ─── Helpers ──────────────────────────────────────────────────────────


def _format_points(points: int) -> str:
    """Formata pontos com sinal."""
    if points > 0:
        return f"+{points} pts"
    elif points < 0:
        return f"{points} pts"
    return "0 pts"


def _generate_instructions(
    qual_rules: list, score_rules: list, extra_instructions: str
) -> str:
    """
    Gera texto de instrucoes consolidado a partir das regras configuradas.
    Este texto e salvo em attlas_crm.instructions e injetado no prompt da IA
    automaticamente pelo loop generico do rag_worker.
    """
    parts = []

    # Qualificacao
    valid_qual = [r for r in qual_rules if r.get("condition") and r.get("target_column")]
    if valid_qual:
        parts.append("=== REGRAS DE QUALIFICACAO (MOVER NO KANBAN) ===")
        for i, rule in enumerate(valid_qual, 1):
            name = rule.get("name") or f"Regra {i}"
            parts.append(f"\n{i}. [{name}]")
            parts.append(f"   QUANDO: {rule['condition']}")
            parts.append(
                f"   ACAO: Use attlas_mover_card_simples para mover o card para a coluna \"{rule['target_column']}\"."
            )
            if rule.get("project_uuid"):
                parts.append(f"   PROJETO UUID: {rule['project_uuid']}")
            score = rule.get("also_score", 0)
            if score != 0:
                parts.append(
                    f"   SCORE: Tambem use attlas_adicionar_pontuacao com {_format_points(score)} "
                    f"e motivo \"{name}\"."
                )
        parts.append("")

    # Scoring
    valid_score = [r for r in score_rules if r.get("trigger")]
    if valid_score:
        parts.append("=== REGRAS DE LEAD SCORING ===")
        parts.append("Classificacao: D (0-25), C (26-50), B (51-75), A (76-100)")
        parts.append(
            "Use attlas_adicionar_pontuacao(card_uuid, points, reason) automaticamente:"
        )
        parts.append("")
        for rule in valid_score:
            pts = rule.get("points", 0)
            reason = rule.get("reason") or rule["trigger"]
            parts.append(f"- {rule['trigger']} -> {_format_points(pts)} (motivo: \"{reason}\")")
        parts.append("")

    # Extra
    if extra_instructions and extra_instructions.strip():
        parts.append("=== INSTRUCOES ADICIONAIS ===")
        parts.append(extra_instructions.strip())

    return "\n".join(parts)


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
