"""
business_hours_tab.py - Horário de Atendimento da IA

Permite ao cliente definir dias e horários em que a IA responde automaticamente.
Fora do expediente, a IA fica silenciosa ou envia mensagem personalizada.
"""

import json
import streamlit as st

from scripts.shared.saas_db import (
    get_connection,
    is_within_business_hours,
)

_DAY_LABELS = [
    ("seg", "Segunda-feira"),
    ("ter", "Terça-feira"),
    ("qua", "Quarta-feira"),
    ("qui", "Quinta-feira"),
    ("sex", "Sexta-feira"),
    ("sab", "Sábado"),
    ("dom", "Domingo"),
]

_DEFAULT_SCHEDULE = {
    "seg": {"on": True, "start": "08:00", "end": "18:00"},
    "ter": {"on": True, "start": "08:00", "end": "18:00"},
    "qua": {"on": True, "start": "08:00", "end": "18:00"},
    "qui": {"on": True, "start": "08:00", "end": "18:00"},
    "sex": {"on": True, "start": "08:00", "end": "18:00"},
    "sab": {"on": False, "start": "09:00", "end": "13:00"},
    "dom": {"on": False, "start": "", "end": ""},
}

# Gera lista de horários de 00:00 a 23:30 (intervalos de 30min)
_TIME_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def render_business_hours_tab(user_data: dict):
    st.header("Horário de Atendimento IA")
    st.caption("Defina os dias e horários em que a IA responde automaticamente.")

    t_config = user_data.get("tools_config", {}) or {}
    bh = t_config.get("business_hours", {})
    if not isinstance(bh, dict):
        bh = {}

    # --- Status atual ---
    is_open, _ = is_within_business_hours(t_config)
    mode = bh.get("mode", "dentro")
    if bh.get("active"):
        if mode == "fora":
            if is_open:
                st.success("Status atual: Fora do expediente configurado - IA respondendo normalmente.")
            else:
                st.warning("Status atual: Dentro do expediente configurado - IA pausada (modo: atender fora do horário).")
        else:
            if is_open:
                st.success("Status atual: Dentro do expediente - IA respondendo normalmente.")
            else:
                st.warning("Status atual: Fora do expediente - IA pausada.")
    else:
        st.info("Horário de atendimento desativado - IA responde 24/7.")

    st.divider()

    # --- Toggle principal ---
    bh_active = st.toggle(
        "Ativar Horário de Atendimento",
        value=bh.get("active", False),
        help="Quando ativado, a IA respeita os horários configurados abaixo.",
        key="toggle_business_hours",
    )

    schedule = bh.get("schedule", _DEFAULT_SCHEDULE)
    new_schedule = {}
    off_message = bh.get("off_message", "")

    if bh_active:
        st.divider()

        # --- Modo de operação ---
        _mode_options = ["Atender DENTRO do horário", "Atender FORA do horário"]
        _mode_idx = 1 if mode == "fora" else 0
        selected_mode = st.radio(
            "Modo de operação da IA",
            options=_mode_options,
            index=_mode_idx,
            key="bh_mode",
            help=(
                "**Dentro do horário**: a IA responde apenas nos dias/horários configurados "
                "(ex: atendimento 8h-18h, IA fica ativa nesse período).\n\n"
                "**Fora do horário**: a IA responde apenas FORA dos dias/horários configurados "
                "(ex: equipe humana atende 8h-18h, IA assume fora desse período)."
            ),
        )
        new_mode = "fora" if selected_mode == _mode_options[1] else "dentro"

        if new_mode == "fora":
            st.info(
                "🔄 **Modo invertido ativo** — Configure abaixo o horário da sua equipe humana. "
                "A IA assumirá automaticamente fora desses horários."
            )

        st.divider()

        # --- Tabela de horários ---
        # Header
        cols = st.columns([2.5, 1, 2, 2])
        with cols[0]:
            st.markdown("**Dia**")
        with cols[1]:
            st.markdown("**Ativo**")
        with cols[2]:
            st.markdown("**Início**")
        with cols[3]:
            st.markdown("**Fim**")

        for day_key, day_label in _DAY_LABELS:
            day_cfg = schedule.get(day_key, _DEFAULT_SCHEDULE.get(day_key, {}))

            cols = st.columns([2.5, 1, 2, 2])
            with cols[0]:
                st.markdown(f"**{day_label}**")
            with cols[1]:
                day_on = st.toggle(
                    day_label,
                    value=day_cfg.get("on", False),
                    key=f"bh_on_{day_key}",
                    label_visibility="collapsed",
                )
            with cols[2]:
                start_val = day_cfg.get("start", "08:00")
                start_idx = _TIME_OPTIONS.index(start_val) if start_val in _TIME_OPTIONS else 16
                day_start = st.selectbox(
                    "Início",
                    options=_TIME_OPTIONS,
                    index=start_idx,
                    key=f"bh_start_{day_key}",
                    label_visibility="collapsed",
                    disabled=not day_on,
                )
            with cols[3]:
                end_val = day_cfg.get("end", "18:00")
                end_idx = _TIME_OPTIONS.index(end_val) if end_val in _TIME_OPTIONS else 36
                day_end = st.selectbox(
                    "Fim",
                    options=_TIME_OPTIONS,
                    index=end_idx,
                    key=f"bh_end_{day_key}",
                    label_visibility="collapsed",
                    disabled=not day_on,
                )

            new_schedule[day_key] = {
                "on": day_on,
                "start": day_start if day_on else day_cfg.get("start", ""),
                "end": day_end if day_on else day_cfg.get("end", ""),
            }

        st.divider()

        # --- Mensagem fora do horário ---
        off_message = st.text_area(
            "Mensagem fora do horário (opcional)",
            value=off_message,
            height=100,
            placeholder="Ex: Nosso horário de atendimento é de segunda a sexta, das 8h às 18h. Retornaremos em breve!",
            help="Se preenchida, essa mensagem será enviada automaticamente quando alguém mandar mensagem fora do horário. Se vazia, a IA simplesmente não responde.",
            key="bh_off_message",
        )
    else:
        new_schedule = schedule
        new_mode = mode  # preserva o modo salvo quando toggle está desativado

    # --- Salvar ---
    st.divider()
    if st.button("Salvar Horário de Atendimento", type="primary"):
        new_bh = {
            "active": bh_active,
            "mode": new_mode,
            "schedule": new_schedule,
            "off_message": off_message,
        }

        try:
            new_tools_config = t_config.copy()
            new_tools_config["business_hours"] = new_bh

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET tools_config = %s WHERE id = %s",
                        (json.dumps(new_tools_config), user_data["id"]),
                    )

            user_data["tools_config"] = new_tools_config
            st.session_state["user_data"] = user_data
            st.success("Horário de atendimento salvo com sucesso!")
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
