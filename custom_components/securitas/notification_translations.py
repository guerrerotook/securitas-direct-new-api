"""Translations for persistent notifications and mobile push action labels.

Home Assistant's `strings.json` schema does not include a category for
persistent-notification titles/messages, so these are stored inline in
Python instead of `translations/*.json`. The structure intentionally
mirrors the schema HA uses for translatable categories — each entry has
`title` and `message`, and some entries have additional fields (e.g.
`mobile_message`, `force_arm_action`, `cancel_action`) consumed by call
sites that need them.

Catalan strings use the "Verisure" brand name; all other locales use
"Securitas"/"Securitas Direct".
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

NOTIFICATION_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "Your Securitas Direct configuration uses an old format. "
                "Please remove the integration entry and re-add it."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct needs a 2FA verification code. Please log in again."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "Could not log in to Securitas Direct: {error}",
        },
        "arm_failed": {
            "title": "Securitas: Arming failed",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas: Disarming failed",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas: Rate limited",
            "message": (
                "Too many requests — blocked by Securitas servers. "
                "Please wait a few minutes before trying again."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas: Alarm not armed",
            "message": (
                "The force-arm option has expired. The alarm was **not armed**. "
                "Please try arming again."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas: Arm blocked — open sensor(s)",
            "message": (
                "Arming was blocked because the following sensor(s) are open:\n"
                "{sensor_list}\n\n"
                "To arm anyway, tap **Force Arm** on the alarm card "
                "or on your mobile notification."
            ),
            "mobile_message": (
                "Arm blocked — open sensor(s): {sensor_list}. Arm anyway?"
            ),
            "force_arm_action": "Force Arm",
            "cancel_action": "Cancel",
        },
    },
    "es": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "Tu configuración de Securitas Direct usa un formato antiguo. "
                "Por favor, elimina la integración y vuelve a añadirla."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct necesita un código de verificación 2FA. "
                "Por favor, inicia sesión de nuevo."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "No se pudo iniciar sesión en Securitas Direct: {error}",
        },
        "arm_failed": {
            "title": "Securitas: Error al armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas: Error al desarmar",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas: Demasiadas solicitudes",
            "message": (
                "Demasiadas solicitudes — bloqueado por los servidores de "
                "Securitas. Espera unos minutos antes de volver a intentarlo."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas: Alarma no armada",
            "message": (
                "La opción de armado forzado ha expirado. La alarma **no** se "
                "armó. Por favor, intenta armar de nuevo."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas: Armado bloqueado — sensor(es) abierto(s)",
            "message": (
                "El armado se bloqueó porque los siguientes sensores están "
                "abiertos:\n{sensor_list}\n\n"
                "Para armar de todos modos, pulsa **Armar de todos modos** en "
                "la tarjeta de la alarma o en tu notificación móvil."
            ),
            "mobile_message": (
                "Armado bloqueado — sensor(es) abierto(s): {sensor_list}. "
                "¿Armar de todos modos?"
            ),
            "force_arm_action": "Armar de todos modos",
            "cancel_action": "Cancelar",
        },
    },
    "fr": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "Votre configuration Securitas Direct utilise un ancien format. "
                "Veuillez supprimer l'intégration et l'ajouter à nouveau."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct a besoin d'un code de vérification 2FA. "
                "Veuillez vous reconnecter."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "Impossible de se connecter à Securitas Direct : {error}",
        },
        "arm_failed": {
            "title": "Securitas : Échec de l'armement",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas : Échec du désarmement",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas : Trop de requêtes",
            "message": (
                "Trop de requêtes — bloqué par les serveurs Securitas. "
                "Veuillez patienter quelques minutes avant de réessayer."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas : Alarme non armée",
            "message": (
                "L'option d'armement forcé a expiré. "
                "L'alarme **n'a pas** été armée. Veuillez réessayer."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas : Armement bloqué — capteur(s) ouvert(s)",
            "message": (
                "L'armement a été bloqué car les capteurs suivants sont "
                "ouverts :\n{sensor_list}\n\n"
                "Pour armer quand même, appuyez sur **Armer quand même** sur "
                "la carte d'alarme ou sur votre notification mobile."
            ),
            "mobile_message": (
                "Armement bloqué — capteur(s) ouvert(s) : {sensor_list}. "
                "Armer quand même ?"
            ),
            "force_arm_action": "Armer quand même",
            "cancel_action": "Annuler",
        },
    },
    "it": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "La tua configurazione Securitas Direct utilizza un formato "
                "obsoleto. Rimuovi l'integrazione e aggiungila di nuovo."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct richiede un codice di verifica 2FA. "
                "Effettua di nuovo l'accesso."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "Impossibile accedere a Securitas Direct: {error}",
        },
        "arm_failed": {
            "title": "Securitas: Attivazione fallita",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas: Disattivazione fallita",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas: Troppe richieste",
            "message": (
                "Troppe richieste — bloccato dai server Securitas. "
                "Attendi alcuni minuti prima di riprovare."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas: Allarme non attivato",
            "message": (
                "L'opzione di attivazione forzata è scaduta. "
                "L'allarme **non** è stato attivato. Riprova ad attivarlo."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas: Attivazione bloccata — sensore(i) aperto(i)",
            "message": (
                "L'attivazione è stata bloccata perché i seguenti sensori "
                "sono aperti:\n{sensor_list}\n\n"
                "Per attivare comunque, tocca **Attiva comunque** sulla card "
                "dell'allarme o sulla tua notifica mobile."
            ),
            "mobile_message": (
                "Attivazione bloccata — sensore(i) aperto(i): {sensor_list}. "
                "Attivare comunque?"
            ),
            "force_arm_action": "Attiva comunque",
            "cancel_action": "Annulla",
        },
    },
    "pt": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "A sua configuração do Securitas Direct usa um formato antigo. "
                "Por favor, remova a integração e adicione-a novamente."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct precisa de um código de verificação 2FA. "
                "Por favor, inicie sessão novamente."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "Não foi possível iniciar sessão no Securitas Direct: {error}",
        },
        "arm_failed": {
            "title": "Securitas: Falha ao armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas: Falha ao desarmar",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas: Demasiados pedidos",
            "message": (
                "Demasiados pedidos — bloqueado pelos servidores Securitas. "
                "Aguarde alguns minutos antes de tentar novamente."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas: Alarme não armado",
            "message": (
                "A opção de armar à força expirou. "
                "O alarme **não** foi armado. Tente armar novamente."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas: Armar bloqueado — sensor(es) aberto(s)",
            "message": (
                "O armar foi bloqueado porque os seguintes sensores estão "
                "abertos:\n{sensor_list}\n\n"
                "Para armar na mesma, toque em **Armar na mesma** no cartão "
                "do alarme ou na sua notificação móvel."
            ),
            "mobile_message": (
                "Armar bloqueado — sensor(es) aberto(s): {sensor_list}. Armar na mesma?"
            ),
            "force_arm_action": "Armar na mesma",
            "cancel_action": "Cancelar",
        },
    },
    "pt-BR": {
        "migration_required": {
            "title": "Securitas Direct",
            "message": (
                "Sua configuração do Securitas Direct usa um formato antigo. "
                "Por favor, remova a integração e adicione-a novamente."
            ),
        },
        "two_factor_required": {
            "title": "Securitas Direct",
            "message": (
                "Securitas Direct precisa de um código de verificação 2FA. "
                "Por favor, faça login novamente."
            ),
        },
        "login_failed": {
            "title": "Securitas Direct",
            "message": "Não foi possível fazer login no Securitas Direct: {error}",
        },
        "arm_failed": {
            "title": "Securitas: Falha ao armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Securitas: Falha ao desarmar",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Securitas: Limite de requisições",
            "message": (
                "Muitas requisições — bloqueado pelos servidores Securitas. "
                "Aguarde alguns minutos antes de tentar novamente."
            ),
        },
        "force_arm_expired": {
            "title": "Securitas: Alarme não armado",
            "message": (
                "A opção de forçar armado expirou. "
                "O alarme **não** foi armado. Tente armar novamente."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Securitas: Armar bloqueado — sensor(es) aberto(s)",
            "message": (
                "Armar foi bloqueado porque os seguintes sensores estão "
                "abertos:\n{sensor_list}\n\n"
                "Para armar mesmo assim, toque em **Forçar armado** no cartão "
                "do alarme ou na sua notificação móvel."
            ),
            "mobile_message": (
                "Armar bloqueado — sensor(es) aberto(s): {sensor_list}. "
                "Armar mesmo assim?"
            ),
            "force_arm_action": "Forçar armado",
            "cancel_action": "Cancelar",
        },
    },
    "ca": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "La teva configuració de Verisure utilitza un format antic. "
                "Si us plau, elimina la integració i torna-la a afegir."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure necessita un codi de verificació 2FA. "
                "Si us plau, torna a iniciar sessió."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "No s'ha pogut iniciar sessió a Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Error en armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Error en desarmar",
            "message": "{error}",
        },
        "rate_limited": {
            "title": "Verisure: Massa peticions",
            "message": (
                "Massa peticions — bloquejat pels servidors de Verisure. "
                "Espera uns minuts abans de tornar a provar."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Alarma no armada",
            "message": (
                "L'opció d'armat forçat ha expirat. "
                "L'alarma **no** s'ha armat. Si us plau, torna a provar a armar."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Armat bloquejat — sensor(s) obert(s)",
            "message": (
                "L'armat s'ha bloquejat perquè els següents sensors estan "
                "oberts:\n{sensor_list}\n\n"
                "Per armar igualment, toca **Forçar armat** a la targeta de "
                "l'alarma o a la teva notificació mòbil."
            ),
            "mobile_message": (
                "Armat bloquejat — sensor(s) obert(s): {sensor_list}. Armar igualment?"
            ),
            "force_arm_action": "Forçar armat",
            "cancel_action": "Cancel·lar",
        },
    },
}


def get_notification_strings(
    hass: HomeAssistant, translation_key: str
) -> dict[str, str]:
    """Return all translated fields for a notification key in the user's language.

    Falls back to English when the user's language is not localized or the
    key is missing in that locale.
    """
    locale = NOTIFICATION_TRANSLATIONS.get(hass.config.language)
    if locale is None or translation_key not in locale:
        return NOTIFICATION_TRANSLATIONS["en"].get(translation_key, {})
    return locale[translation_key]
