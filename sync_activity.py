"""
In-Memory-Zustand "läuft gerade ein Sync?" für die TopBar-Sync-Pille (SyncBadge, live gepolltes
visuelles Feedback) - bewusst NICHT in der DB, nur für die Dauer des laufenden Backend-Prozesses
relevant. Der persistente Verlauf ("was ist wann passiert") liegt in db.py::sync_log/log_sync_event
- dieses Modul beantwortet nur "passiert JETZT gerade etwas", unabhängig davon. Getrennt für
Garmin/Withings, da die Pille beide Quellen zusammenfasst, aber unterschiedliche Hintergrund-Tasks
(auto_sync.py bzw. withings_auto_sync.py) und manuelle Trigger dahinterstehen.
"""
_active = {"garmin_syncing": False, "withings_syncing": False}


def set_garmin_syncing(value):
    _active["garmin_syncing"] = value


def set_withings_syncing(value):
    _active["withings_syncing"] = value


def get_sync_activity():
    return dict(_active)
