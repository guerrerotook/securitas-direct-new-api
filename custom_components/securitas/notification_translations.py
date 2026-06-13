"""Translations for persistent notifications and mobile push action labels.

Home Assistant's `strings.json` schema does not include a category for
persistent-notification titles/messages, so these are stored inline in
Python instead of `translations/*.json`. The structure intentionally
mirrors the schema HA uses for translatable categories — each entry has
`title` and `message`, and some entries have additional fields (e.g.
`mobile_message`, `force_arm_action`, `cancel_action`) consumed by call
sites that need them.

All locales use the "Verisure" brand name.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

NOTIFICATION_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "Your Verisure configuration uses an old format. "
                "Please remove the integration entry and re-add it."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": ("Verisure needs a 2FA verification code. Please log in again."),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "Could not log in to Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Arming failed",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Disarming failed",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure: Arm not confirmed",
            "message": (
                "The arm command was sent to {installation} and accepted, but "
                "the panel hasn't confirmed the new state within {timeout}s. The "
                "state shown is provisional and will update automatically once "
                "the panel reports in. If this keeps happening, raise the "
                "**Operation poll timeout** in the integration options."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: Disarm not confirmed",
            "message": (
                "The disarm command was sent to {installation} and accepted, but "
                "the panel hasn't confirmed the new state within {timeout}s. The "
                "state shown is provisional and will update automatically once "
                "the panel reports in. If this keeps happening, raise the "
                "**Operation poll timeout** in the integration options."
            ),
        },
        "rate_limited": {
            "title": "Verisure: Rate limited",
            "message": (
                "Too many requests — blocked by Verisure servers. "
                "Please wait a few minutes before trying again."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Alarm not armed",
            "message": (
                "The force-arm option has expired. The alarm was **not armed**. "
                "Please try arming again."
            ),
            "mobile_message": ("Force-arm window expired. The alarm was not armed."),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Arm blocked — open sensor(s)",
            "message": (
                "Arming was blocked because the following sensor(s) are open:\n"
                "{sensor_list}\n\n"
                "To arm anyway, tap **Force Arm** on the alarm card."
            ),
            "mobile_message": (
                "Arm blocked — open sensor(s): {sensor_list}. Arm anyway?"
            ),
            "force_arm_action": "Force Arm",
            "cancel_action": "Cancel",
        },
        "migration_complete": {
            "title": "Verisure OWA upgrade complete",
            "message": (
                "The Securitas Direct integration has been migrated. "
                "[Review breaking changes →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Services, events, and Lovelace cards have been renamed; legacy "
                "aliases keep working until v6.0.0."
            ),
        },
    },
    "es": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "Tu configuración de Verisure usa un formato antiguo. "
                "Por favor, elimina la integración y vuelve a añadirla."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure necesita un código de verificación 2FA. "
                "Por favor, inicia sesión de nuevo."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "No se pudo iniciar sesión en Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Error al armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Error al desarmar",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure: Armado sin confirmar",
            "message": (
                "El comando de armado se envió a {installation} y se aceptó, pero "
                "el panel no ha confirmado el nuevo estado en {timeout}s. El estado "
                "mostrado es provisional y se actualizará automáticamente cuando el "
                "panel responda. Si ocurre con frecuencia, aumenta el **Tiempo de "
                "espera de confirmación** en las opciones de la integración."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: Desarmado sin confirmar",
            "message": (
                "El comando de desarmado se envió a {installation} y se aceptó, pero "
                "el panel no ha confirmado el nuevo estado en {timeout}s. El estado "
                "mostrado es provisional y se actualizará automáticamente cuando el "
                "panel responda. Si ocurre con frecuencia, aumenta el **Tiempo de "
                "espera de confirmación** en las opciones de la integración."
            ),
        },
        "rate_limited": {
            "title": "Verisure: Demasiadas solicitudes",
            "message": (
                "Demasiadas solicitudes — bloqueado por los servidores de "
                "Verisure. Espera unos minutos antes de volver a intentarlo."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Alarma no armada",
            "message": (
                "La opción de armado forzado ha expirado. La alarma **no** se "
                "armó. Por favor, intenta armar de nuevo."
            ),
            "mobile_message": ("El armado forzado ha expirado. La alarma no se armó."),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Armado bloqueado — sensor(es) abierto(s)",
            "message": (
                "El armado se bloqueó porque los siguientes sensores están "
                "abiertos:\n{sensor_list}\n\n"
                "Para armar de todos modos, pulsa **Armar de todos modos** en "
                "la tarjeta de la alarma."
            ),
            "mobile_message": (
                "Armado bloqueado — sensor(es) abierto(s): {sensor_list}. "
                "¿Armar de todos modos?"
            ),
            "force_arm_action": "Armar de todos modos",
            "cancel_action": "Cancelar",
        },
        "migration_complete": {
            "title": "Actualización a Verisure OWA completa",
            "message": (
                "La integración Securitas Direct se ha migrado. "
                "[Revisar cambios incompatibles →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Los servicios, eventos y tarjetas Lovelace se han renombrado; los alias "
                "antiguos siguen funcionando hasta la v6.0.0."
            ),
        },
    },
    "fr": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "Votre configuration Verisure utilise un ancien format. "
                "Veuillez supprimer l'intégration et l'ajouter à nouveau."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure a besoin d'un code de vérification 2FA. "
                "Veuillez vous reconnecter."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "Impossible de se connecter à Verisure : {error}",
        },
        "arm_failed": {
            "title": "Verisure : Échec de l'armement",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure : Échec du désarmement",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure : Armement non confirmé",
            "message": (
                "La commande d'armement a été envoyée à {installation} et acceptée, "
                "mais le panneau n'a pas confirmé le nouvel état en {timeout}s. "
                "L'état affiché est provisoire et se mettra à jour automatiquement "
                "dès que le panneau répondra. Si cela se reproduit souvent, "
                "augmentez le **Délai d'attente de confirmation** dans les options."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure : Désarmement non confirmé",
            "message": (
                "La commande de désarmement a été envoyée à {installation} et "
                "acceptée, mais le panneau n'a pas confirmé le nouvel état en "
                "{timeout}s. L'état affiché est provisoire et se mettra à jour "
                "automatiquement dès que le panneau répondra. Si cela se reproduit "
                "souvent, augmentez le **Délai d'attente de confirmation** dans les "
                "options."
            ),
        },
        "rate_limited": {
            "title": "Verisure : Trop de requêtes",
            "message": (
                "Trop de requêtes — bloqué par les serveurs Verisure. "
                "Veuillez patienter quelques minutes avant de réessayer."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure : Alarme non armée",
            "message": (
                "L'option d'armement forcé a expiré. "
                "L'alarme **n'a pas** été armée. Veuillez réessayer."
            ),
            "mobile_message": (
                "L'armement forcé a expiré. L'alarme n'a pas été armée."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure : Armement bloqué — capteur(s) ouvert(s)",
            "message": (
                "L'armement a été bloqué car les capteurs suivants sont "
                "ouverts :\n{sensor_list}\n\n"
                "Pour armer quand même, appuyez sur **Armer quand même** sur "
                "la carte d'alarme."
            ),
            "mobile_message": (
                "Armement bloqué — capteur(s) ouvert(s) : {sensor_list}. "
                "Armer quand même ?"
            ),
            "force_arm_action": "Armer quand même",
            "cancel_action": "Annuler",
        },
        "migration_complete": {
            "title": "Mise à niveau vers Verisure OWA terminée",
            "message": (
                "L'intégration Securitas Direct a été migrée. "
                "[Voir les changements incompatibles →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Les services, événements et cartes Lovelace ont été renommés ; les alias "
                "hérités fonctionnent jusqu'à la v6.0.0."
            ),
        },
    },
    "it": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "La tua configurazione Verisure utilizza un formato "
                "obsoleto. Rimuovi l'integrazione e aggiungila di nuovo."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure richiede un codice di verifica 2FA. "
                "Effettua di nuovo l'accesso."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "Impossibile accedere a Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Attivazione fallita",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Disattivazione fallita",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure: inserimento non confermato",
            "message": (
                "Il comando di inserimento è stato inviato a {installation} ed "
                "accettato, ma la centrale non ha confermato il nuovo stato entro "
                "{timeout}s. Lo stato mostrato è provvisorio e si aggiornerà "
                "automaticamente quando la centrale risponderà. Se accade spesso, "
                "aumenta il **Timeout di conferma operazione** nelle opzioni."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: disinserimento non confermato",
            "message": (
                "Il comando di disinserimento è stato inviato a {installation} ed "
                "accettato, ma la centrale non ha confermato il nuovo stato entro "
                "{timeout}s. Lo stato mostrato è provvisorio e si aggiornerà "
                "automaticamente quando la centrale risponderà. Se accade spesso, "
                "aumenta il **Timeout di conferma operazione** nelle opzioni."
            ),
        },
        "rate_limited": {
            "title": "Verisure: Troppe richieste",
            "message": (
                "Troppe richieste — bloccato dai server Verisure. "
                "Attendi alcuni minuti prima di riprovare."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Allarme non attivato",
            "message": (
                "L'opzione di attivazione forzata è scaduta. "
                "L'allarme **non** è stato attivato. Riprova ad attivarlo."
            ),
            "mobile_message": (
                "L'attivazione forzata è scaduta. L'allarme non è stato attivato."
            ),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Attivazione bloccata — sensore(i) aperto(i)",
            "message": (
                "L'attivazione è stata bloccata perché i seguenti sensori "
                "sono aperti:\n{sensor_list}\n\n"
                "Per attivare comunque, tocca **Attiva comunque** sulla card "
                "dell'allarme."
            ),
            "mobile_message": (
                "Attivazione bloccata — sensore(i) aperto(i): {sensor_list}. "
                "Attivare comunque?"
            ),
            "force_arm_action": "Attiva comunque",
            "cancel_action": "Annulla",
        },
        "migration_complete": {
            "title": "Aggiornamento a Verisure OWA completato",
            "message": (
                "L'integrazione Securitas Direct è stata migrata. "
                "[Vedi le modifiche di rottura →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Servizi, eventi e card Lovelace sono stati rinominati; gli alias legacy "
                "continuano a funzionare fino alla v6.0.0."
            ),
        },
    },
    "pt": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "A sua configuração do Verisure usa um formato antigo. "
                "Por favor, remova a integração e adicione-a novamente."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure precisa de um código de verificação 2FA. "
                "Por favor, inicie sessão novamente."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "Não foi possível iniciar sessão no Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Falha ao armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Falha ao desarmar",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure: Armar não confirmado",
            "message": (
                "O comando de armar foi enviado para {installation} e aceito, mas "
                "o painel não confirmou o novo estado em {timeout}s. O estado "
                "mostrado é provisório e será atualizado automaticamente quando o "
                "painel responder. Se isto acontecer com frequência, aumente o "
                "**Tempo limite de confirmação** nas opções da integração."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: Desarmar não confirmado",
            "message": (
                "O comando de desarmar foi enviado para {installation} e aceito, "
                "mas o painel não confirmou o novo estado em {timeout}s. O estado "
                "mostrado é provisório e será atualizado automaticamente quando o "
                "painel responder. Se isto acontecer com frequência, aumente o "
                "**Tempo limite de confirmação** nas opções da integração."
            ),
        },
        "rate_limited": {
            "title": "Verisure: Demasiados pedidos",
            "message": (
                "Demasiados pedidos — bloqueado pelos servidores Verisure. "
                "Aguarde alguns minutos antes de tentar novamente."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Alarme não armado",
            "message": (
                "A opção de armar à força expirou. "
                "O alarme **não** foi armado. Tente armar novamente."
            ),
            "mobile_message": ("Armar à força expirou. O alarme não foi armado."),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Armar bloqueado — sensor(es) aberto(s)",
            "message": (
                "O armar foi bloqueado porque os seguintes sensores estão "
                "abertos:\n{sensor_list}\n\n"
                "Para armar na mesma, toque em **Armar na mesma** no cartão "
                "do alarme."
            ),
            "mobile_message": (
                "Armar bloqueado — sensor(es) aberto(s): {sensor_list}. Armar na mesma?"
            ),
            "force_arm_action": "Armar na mesma",
            "cancel_action": "Cancelar",
        },
        "migration_complete": {
            "title": "Atualização para Verisure OWA concluída",
            "message": (
                "A integração Securitas Direct foi migrada. "
                "[Ver alterações incompatíveis →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Os serviços, eventos e cartões Lovelace foram renomeados; os aliases "
                "antigos continuam a funcionar até à v6.0.0."
            ),
        },
    },
    "pt-BR": {
        "migration_required": {
            "title": "Verisure",
            "message": (
                "Sua configuração do Verisure usa um formato antigo. "
                "Por favor, remova a integração e adicione-a novamente."
            ),
        },
        "two_factor_required": {
            "title": "Verisure",
            "message": (
                "Verisure precisa de um código de verificação 2FA. "
                "Por favor, faça login novamente."
            ),
        },
        "login_failed": {
            "title": "Verisure",
            "message": "Não foi possível fazer login no Verisure: {error}",
        },
        "arm_failed": {
            "title": "Verisure: Falha ao armar",
            "message": "{error}",
        },
        "disarm_failed": {
            "title": "Verisure: Falha ao desarmar",
            "message": "{error}",
        },
        "arm_unconfirmed": {
            "title": "Verisure: Armar não confirmado",
            "message": (
                "O comando de armar foi enviado para {installation} e aceito, mas "
                "o painel não confirmou o novo estado em {timeout}s. O estado "
                "mostrado é provisório e será atualizado automaticamente quando o "
                "painel responder. Se isto acontecer com frequência, aumente o "
                "**Tempo limite de confirmação** nas opções da integração."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: Desarmar não confirmado",
            "message": (
                "O comando de desarmar foi enviado para {installation} e aceito, "
                "mas o painel não confirmou o novo estado em {timeout}s. O estado "
                "mostrado é provisório e será atualizado automaticamente quando o "
                "painel responder. Se isto acontecer com frequência, aumente o "
                "**Tempo limite de confirmação** nas opções da integração."
            ),
        },
        "rate_limited": {
            "title": "Verisure: Limite de requisições",
            "message": (
                "Muitas requisições — bloqueado pelos servidores Verisure. "
                "Aguarde alguns minutos antes de tentar novamente."
            ),
        },
        "force_arm_expired": {
            "title": "Verisure: Alarme não armado",
            "message": (
                "A opção de forçar armado expirou. "
                "O alarme **não** foi armado. Tente armar novamente."
            ),
            "mobile_message": ("Forçar armado expirou. O alarme não foi armado."),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Armar bloqueado — sensor(es) aberto(s)",
            "message": (
                "Armar foi bloqueado porque os seguintes sensores estão "
                "abertos:\n{sensor_list}\n\n"
                "Para armar mesmo assim, toque em **Forçar armado** no cartão "
                "do alarme."
            ),
            "mobile_message": (
                "Armar bloqueado — sensor(es) aberto(s): {sensor_list}. "
                "Armar mesmo assim?"
            ),
            "force_arm_action": "Forçar armado",
            "cancel_action": "Cancelar",
        },
        "migration_complete": {
            "title": "Atualização para Verisure OWA concluída",
            "message": (
                "A integração Securitas Direct foi migrada. "
                "[Ver mudanças incompatíveis →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Serviços, eventos e cards Lovelace foram renomeados; os aliases antigos "
                "continuam funcionando até a v6.0.0."
            ),
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
        "arm_unconfirmed": {
            "title": "Verisure: Armat sense confirmar",
            "message": (
                "L'ordre d'armat s'ha enviat a {installation} i s'ha acceptat, però "
                "el panell no ha confirmat el nou estat en {timeout}s. L'estat "
                "mostrat és provisional i s'actualitzarà automàticament quan el "
                "panell respongui. Si passa sovint, augmenta el **Temps d'espera de "
                "confirmació** a les opcions de la integració."
            ),
        },
        "disarm_unconfirmed": {
            "title": "Verisure: Desarmat sense confirmar",
            "message": (
                "L'ordre de desarmat s'ha enviat a {installation} i s'ha acceptat, "
                "però el panell no ha confirmat el nou estat en {timeout}s. L'estat "
                "mostrat és provisional i s'actualitzarà automàticament quan el "
                "panell respongui. Si passa sovint, augmenta el **Temps d'espera de "
                "confirmació** a les opcions de la integració."
            ),
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
            "mobile_message": ("L'armat forçat ha expirat. L'alarma no s'ha armat."),
        },
        "arm_blocked_open_sensors": {
            "title": "Verisure: Armat bloquejat — sensor(s) obert(s)",
            "message": (
                "L'armat s'ha bloquejat perquè els següents sensors estan "
                "oberts:\n{sensor_list}\n\n"
                "Per armar igualment, toca **Forçar armat** a la targeta de "
                "l'alarma."
            ),
            "mobile_message": (
                "Armat bloquejat — sensor(s) obert(s): {sensor_list}. Armar igualment?"
            ),
            "force_arm_action": "Forçar armat",
            "cancel_action": "Cancel·lar",
        },
        "migration_complete": {
            "title": "Actualització a Verisure OWA completa",
            "message": (
                "La integració Securitas Direct s'ha migrat. "
                "[Reviseu els canvis incompatibles →]("
                "https://github.com/guerrerotook/securitas-direct-new-api"
                "/blob/main/CHANGES.md#breaking-changes)"
                "\n\n"
                "Els serveis, esdeveniments i targetes Lovelace s'han reanomenat; els àlies "
                "antics continuen funcionant fins a la v6.0.0."
            ),
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
