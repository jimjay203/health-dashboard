"""
Gemeinsame Statistik-Basis für alle Korrelations-Charts (Schlaf-Seite + Körper-Seite). Reine
Python-Logik, kein Streamlit-/FastAPI-Import (gleiches Muster wie sleep_insight.py/
daily_recommendation.py). Berechnet Pearson r/Regression/Stärke-Einordnung serverseitig, EINMAL pro
Request - Chart-Badge und KI-Einordnungstext greifen beide auf dieselben Werte zu und können
dadurch nie auseinanderlaufen (sleep_insight.py macht das schon für den Fließtext, dieses Modul
generalisiert es für alle Korrelations-Endpoints).
"""

# Kein Settings-UI - gleiche Konvention wie alle anderen Schwellenwerte dieser App
# (OVERREACH_RHR_PCT, LATE_WORKOUT_HOUR_THRESHOLD, TAPER_DAYS_THRESHOLD sind ebenfalls
# Modul-Konstanten, keine ist heute per UI änderbar).
MIN_CORRELATION_SAMPLE_SIZE = 10


def pearson_r(pairs):
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def linear_regression(pairs):
    """Kleinste-Quadrate-Gerade (slope, intercept) - nutzt dieselben Summen wie pearson_r, damit
    Trendlinie und r-Wert konsistent aus denselben Rohdaten stammen. None bei <3 Punkten oder
    fehlender Varianz in x (keine sinnvolle Gerade möglich)."""
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept


def strength_bucket(r):
    """Rein die Stärke-Kategorie (kein Text) - <0.1/<0.3/<0.5-Schwellenwerte, wie bisher fest in
    sleep_insight._strength_label verdrahtet. Badge-Farbe UND Fließtext leiten sich beide hieraus
    ab, statt die Schwellenwerte zweimal zu pflegen."""
    abs_r = abs(r)
    if abs_r < 0.1:
        return "none"
    if abs_r < 0.3:
        return "weak"
    if abs_r < 0.5:
        return "moderate"
    return "strong"


def correlation_summary(pairs):
    """Fasst ein Punkte-Paar-Set (x, y) zu allem zusammen, was ein Scatter-Chart + Badge braucht.
    `sufficient` gated auf MIN_CORRELATION_SAMPLE_SIZE - der Aufrufer (Router/Frontend-Fallback)
    entscheidet, was bei unzureichender Stichprobe angezeigt wird (z.B. "zu wenig Daten")."""
    n = len(pairs)
    r = pearson_r(pairs)
    regression = linear_regression(pairs)
    slope, intercept = regression if regression is not None else (None, None)
    return {
        "n": n,
        "r": r,
        "slope": slope,
        "intercept": intercept,
        "strength": strength_bucket(r) if r is not None else "none",
        "direction": ("positive" if r > 0 else "negative") if r is not None else None,
        "sufficient": n >= MIN_CORRELATION_SAMPLE_SIZE,
    }
