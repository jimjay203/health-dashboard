"""
Gemeinsames Pydantic-Response-Modell für Korrelations-Statistiken (siehe correlation_stats.py::
correlation_summary), von backend/routers/sleep.py UND backend/routers/body.py importiert - ein
Modul mit führendem Unterstrich (kein eigener Router), damit es nicht in main.py registriert werden
muss (gleiches "kein Router, nur geteilte Modelle"-Prinzip wie die geteilte correlation_stats.py-
Berechnung selbst).
"""
from pydantic import BaseModel


class CorrelationStatsOut(BaseModel):
    n: int
    r: float | None = None
    slope: float | None = None
    intercept: float | None = None
    strength: str
    direction: str | None = None
    sufficient: bool
