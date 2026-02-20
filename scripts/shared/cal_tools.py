import requests
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

logger = logging.getLogger("CalComTools")

BASE_URL = "https://api.cal.com/v2"


def _get_headers(api_key: str):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "cal-api-version": "2024-08-13",  # Versão recomendada para v2
    }


def get_available_slots(api_key: str, event_type_id: str, days: int = 5):
    """
    Busca horários disponíveis para um Event Type específico.
    """
    try:
        start_time = datetime.now()
        end_time = start_time + timedelta(days=days)

        # Formato ISO 8601 UTC
        params = {
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "eventTypeId": event_type_id,
        }

        url = f"{BASE_URL}/slots/available"
        response = requests.get(url, headers=_get_headers(api_key), params=params)
        response.raise_for_status()

        data = response.json()
        # A estrutura da resposta v2 geralmente é data['data']['slots'] ou similar
        # Ajuste conforme a resposta real da API v2
        slots_data = data.get("data", {}).get("slots", {})

        # Flatten slots e converte UTC → horário local (Brasília)
        _dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        _tz_local = ZoneInfo("America/Sao_Paulo")
        available_slots = []
        for date_str, day_slots in slots_data.items():
            for slot in day_slots:
                utc_str = slot.get("time")
                try:
                    utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    local_dt = utc_dt.astimezone(_tz_local)
                    available_slots.append({
                        "utc_iso": utc_str,
                        "horario_local": local_dt.strftime("%H:%M"),
                        "data": f"{local_dt.strftime('%d/%m/%Y')} ({_dias[local_dt.weekday()]})",
                    })
                except Exception:
                    available_slots.append({"utc_iso": utc_str})

        # Ordena por UTC e limita
        available_slots.sort(key=lambda x: x.get("utc_iso", ""))
        return available_slots[:15]

    except Exception as e:
        logger.error(f"Erro ao buscar slots Cal.com: {e}")
        return f"Erro ao consultar agenda: {str(e)}"


def create_booking(
    api_key: str,
    event_type_id: str,
    start_time: str,
    name: str,
    email: str,
    phone: str = None,
    location_type: str = "google-meet",
    location_value: str = None,
    duration: int = None,
    notes: str = None,
):
    """
    Cria um agendamento (Booking).
    Args:
        location_type: 'google-meet', 'phone', 'address'
        location_value: endereço (se address) ou telefone (se phone)
        duration: duração em minutos
    """
    try:
        # 1. Validação de Email (Obrigatório)
        if not email or "@" not in email:
            return {
                "status": "error",
                "message": "O campo EMAIL é obrigatório para agendamento. Por favor, solicite ao usuário.",
            }

        # 2. Sanitização Rigorosa para UTC (Cal.com requer Z)
        # Remove espaços
        if " " in start_time and "T" not in start_time:
            start_time = start_time.replace(" ", "T")

        try:
            # Tenta parsear qualquer formato ISO
            dt = datetime.fromisoformat(start_time)

            # Se não tiver timezone, assume America/Sao_Paulo (regra de negócio)
            if dt.tzinfo is None:
                from zoneinfo import ZoneInfo

                dt = dt.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))

            # Converte SEMPRE para UTC
            dt_utc = dt.astimezone(timezone.utc)

            # Formata exatamente como Cal.com gosta: 2024-08-13T09:00:00.000Z
            start_time = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        except Exception as e:
            logger.warning(
                f"Falha na conversão UTC estrita: {e}. Usando original sanitizado."
            )
            # Fallback (lógica antiga de regex)
            has_offset = bool(re.search(r"([+-]\d{2}:?\d{2}|Z)$", start_time))
            if not has_offset:
                start_time = f"{start_time}.000Z"

        url = f"{BASE_URL}/bookings"

        # Base Payload
        payload = {
            "start": start_time,
            "eventTypeId": int(event_type_id),
            "attendee": {
                "name": name or "Cliente",  # Nome não pode ser vazio
                "email": email,
                "timeZone": "America/Sao_Paulo",
                "language": "pt-BR",
            },
            "bookingFieldsResponses": {},
            "metadata": {},
        }

        # Duração Customizada
        if duration:
            payload["lengthInMinutes"] = int(duration)

        # Handle Phone & Custom Fields (Attendee)
        if phone:
            payload["attendee"]["phoneNumber"] = phone
            # Mapeia para campo customizado se existir (comum em setups brasileiros)
            payload["bookingFieldsResponses"]["WhatsApp"] = phone

        # Handle Location
        if location_type == "google-meet":
            payload["location"] = {"type": "integration", "integration": "google-meet"}
        elif location_type == "phone":
            # Se location_value não vier, usa o phone do attendee
            phone_val = location_value if location_value else phone
            payload["location"] = {
                "type": "phone",
                "value": phone_val if phone_val else "",
            }
        elif location_type == "address":
            payload["location"] = {
                "type": "address",
                "value": location_value if location_value else "Endereço a definir",
            }
        # Adicionar outros tipos conforme necessidade

        if notes:
            payload["description"] = notes

        logger.info(f"🚀 Enviando Booking para Cal.com: {payload}")
        response = requests.post(url, headers=_get_headers(api_key), json=payload)
        response.raise_for_status()

        result = response.json()
        booking_data = result.get("data", {})

        return {
            "status": "success",
            "uid": booking_data.get("uid"),
            "id": booking_data.get("id"),
            "start": booking_data.get("start"),
            "duration": booking_data.get("duration"),
            "location": booking_data.get("location"),
            "message": "Agendamento realizado com sucesso!",
        }

    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "response") and e.response:
            try:
                error_msg = f"{e} - {e.response.json()}"
            except:
                error_msg = f"{e} - {e.response.text}"

        logger.error(f"Erro ao agendar Cal.com: {error_msg}")
        return f"Falha ao agendar: {error_msg}"


def cancel_booking(
    api_key: str, booking_uid: str, reason: str = "Cancelado pelo usuário"
):
    """
    Cancela um agendamento existente pelo UID.
    """
    try:
        url = f"{BASE_URL}/bookings/{booking_uid}/cancel"
        payload = {"cancellationReason": reason}

        response = requests.post(url, headers=_get_headers(api_key), json=payload)
        response.raise_for_status()

        return "Agendamento cancelado com sucesso."

    except Exception as e:
        logger.error(f"Erro ao cancelar Cal.com: {e}")
        return f"Erro ao cancelar: {str(e)}"


def reschedule_booking(
    api_key: str,
    booking_uid: str,
    new_start_time: str,
    reason: str = "Remarcado pelo usuário",
):
    """
    Remarca um agendamento existente.
    """
    try:
        url = f"{BASE_URL}/bookings/{booking_uid}/reschedule"
        payload = {"start": new_start_time, "reschedulingReason": reason}

        response = requests.post(url, headers=_get_headers(api_key), json=payload)
        response.raise_for_status()

        return "Agendamento remarcado com sucesso."

    except Exception as e:
        logger.error(f"Erro ao remarcar Cal.com: {e}")
        return f"Erro ao remarcar: {str(e)}"
