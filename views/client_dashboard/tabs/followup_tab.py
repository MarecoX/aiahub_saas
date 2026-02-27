import json
import copy
import streamlit as st
import os
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection, is_within_followup_hours

# Gera lista de horarios de 00:00 a 23:30 (intervalos de 30min)
_TIME_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]

_DAY_LABELS = [
    ("seg", "Seg"),
    ("ter", "Ter"),
    ("qua", "Qua"),
    ("qui", "Qui"),
    ("sex", "Sex"),
    ("sab", "Sab"),
    ("dom", "Dom"),
]

_DEFAULT_DAYS = {
    "seg": True,
    "ter": True,
    "qua": True,
    "qui": True,
    "sex": True,
    "sab": False,
    "dom": False,
}


def render_followup_tab(user_data):
    st.header("Follow-up Automatico")
    st.info(
        "Configure mensagens automaticas para enviar quando o cliente para de responder."
    )

    f_config = user_data.get("followup_config", {})
    if not f_config:
        f_config = {}

    # Keys de Sessao
    stages_key = f"followup_stages_{user_data['id']}"
    active_key = f"active_{user_data['id']}"

    # Inicializacao Robusta (Separada)
    if stages_key not in st.session_state:
        st.session_state[stages_key] = copy.deepcopy(f_config.get("stages", []))

    if active_key not in st.session_state:
        st.session_state[active_key] = f_config.get("active", False)

    # Toggle principal
    active = st.toggle("Ativar Follow-up Automatico", key=active_key)

    # =====================================================
    # CONTROLE DE FAIXA DE HORARIO
    # =====================================================
    if active:
        st.divider()
        st.subheader("Faixa de Horario Permitida")

        allowed_hours = f_config.get("allowed_hours", {})

        ah_enabled = st.toggle(
            "Restringir horario de disparo",
            value=allowed_hours.get("enabled", False),
            help="Se ativado, follow-ups so serao enviados dentro da faixa de horario configurada.",
            key=f"ah_enabled_{user_data['id']}",
        )

        if ah_enabled:
            # Status atual em tempo real
            can_fire = is_within_followup_hours(
                {"allowed_hours": {
                    "enabled": True,
                    "start": allowed_hours.get("start", "08:00"),
                    "end": allowed_hours.get("end", "20:00"),
                    "days": allowed_hours.get("days", _DEFAULT_DAYS),
                }}
            )
            if can_fire:
                st.success("Status: Dentro da faixa permitida — follow-ups podem disparar agora.")
            else:
                st.warning("Status: Fora da faixa permitida — follow-ups estao em espera.")

            # Horario inicio/fim
            col_start, col_end = st.columns(2)
            with col_start:
                start_val = allowed_hours.get("start", "08:00")
                start_idx = _TIME_OPTIONS.index(start_val) if start_val in _TIME_OPTIONS else 16
                ah_start = st.selectbox(
                    "Horario de Inicio",
                    options=_TIME_OPTIONS,
                    index=start_idx,
                    key=f"ah_start_{user_data['id']}",
                )
            with col_end:
                end_val = allowed_hours.get("end", "20:00")
                end_idx = _TIME_OPTIONS.index(end_val) if end_val in _TIME_OPTIONS else 40
                ah_end = st.selectbox(
                    "Horario de Fim",
                    options=_TIME_OPTIONS,
                    index=end_idx,
                    key=f"ah_end_{user_data['id']}",
                )

            if ah_start >= ah_end:
                st.warning("O horario de inicio deve ser anterior ao de fim.")

            # Dias da semana
            st.caption("Dias permitidos:")
            saved_days = allowed_hours.get("days", _DEFAULT_DAYS)
            new_days = {}
            day_cols = st.columns(7)
            for idx, (day_key, day_label) in enumerate(_DAY_LABELS):
                with day_cols[idx]:
                    new_days[day_key] = st.checkbox(
                        day_label,
                        value=saved_days.get(day_key, _DEFAULT_DAYS.get(day_key, True)),
                        key=f"ah_day_{day_key}_{user_data['id']}",
                    )
        else:
            ah_start = allowed_hours.get("start", "08:00")
            ah_end = allowed_hours.get("end", "20:00")
            new_days = allowed_hours.get("days", _DEFAULT_DAYS)
    else:
        ah_enabled = False
        ah_start = "08:00"
        ah_end = "20:00"
        new_days = _DEFAULT_DAYS

    st.divider()

    # =====================================================
    # ETAPAS DE RETOMADA
    # =====================================================
    current_stages = st.session_state[stages_key]

    st.subheader(f"Etapas de Retomada ({len(current_stages)})")

    indices_to_remove = []
    for i, stage in enumerate(current_stages):
        with st.expander(f"Etapa {i + 1}", expanded=True):
            c1, c2 = st.columns([2, 1])
            stage_type = c1.selectbox(
                "Tipo de Mensagem",
                ["Texto (IA)", "Audio Gravado"],
                index=0 if stage.get("type", "text") == "text" else 1,
                key=f"t_{user_data['id']}_{i}",
            )
            stage["type"] = "audio" if stage_type == "Audio Gravado" else "text"

            stage["delay_minutes"] = c2.number_input(
                "Esperar (minutos)",
                min_value=0,
                value=int(stage.get("delay_minutes", 60)),
                key=f"d_{user_data['id']}_{i}",
                help="0 = Enviar junto com a mensagem anterior (Cadeia).",
            )

            if stage["type"] == "text":
                stage["prompt"] = st.text_area(
                    "Instrucao para IA",
                    value=stage.get("prompt", "Pergunte se precisa de ajuda."),
                    key=f"p_{user_data['id']}_{i}",
                )
                stage["audio_url"] = None
            else:
                stage["audio_url"] = st.text_input(
                    "URL do Audio (MP3/OGG)",
                    value=stage.get("audio_url", ""),
                    placeholder="https://exemplo.com/audio.mp3",
                    key=f"a_{user_data['id']}_{i}",
                    help="Link direto para o arquivo de audio. Deve ser publico.",
                )
                stage["prompt"] = None

            if st.button("Remover Etapa", key=f"rem_{user_data['id']}_{i}"):
                indices_to_remove.append(i)

    if indices_to_remove:
        for index in sorted(indices_to_remove, reverse=True):
            del st.session_state[stages_key][index]
        st.rerun()

    if st.button("Adicionar Nova Etapa"):
        st.session_state[stages_key].append(
            {
                "delay_minutes": 60,
                "prompt": "Pergunte educadamente se ficou alguma duvida pendente.",
            }
        )
        st.rerun()

    # =====================================================
    # SALVAR
    # =====================================================
    st.divider()
    if st.button("Salvar Configuracao de Follow-up", type="primary"):
        final_config = {
            "active": active,
            "stages": st.session_state[stages_key],
            "allowed_hours": {
                "enabled": ah_enabled,
                "start": ah_start,
                "end": ah_end,
                "days": new_days,
            },
        }
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET followup_config = %s WHERE id = %s",
                        (json.dumps(final_config), user_data["id"]),
                    )
            user_data["followup_config"] = final_config
            st.success("Configuracao salva com sucesso!")
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
