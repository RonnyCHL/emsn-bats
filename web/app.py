"""EMSN Bats Web UI - BirdNET-Pi stijl interface voor vleermuismonitoring."""

import json
import sys
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

# Voeg project root toe aan path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.core.config import (
    DEFAULTS,
    get_all_config,
    get_config,
    get_config_int,
    set_config,
)
from scripts.core.database import (
    get_connection,
    get_hourly_counts,
    get_recent_detections,
    get_today_species,
    get_today_stats,
    init_db,
)
from scripts.core.species import SPECIES_DUTCH, get_dutch_name, get_rarity

app = Flask(__name__)

# Initialiseer database
init_db()


@app.route("/")
def overview():
    """Overzichtspagina - zoals BirdNET-Pi homepage."""
    stats = get_today_stats()
    species_today = get_today_species()
    hourly = get_hourly_counts()
    recent = get_recent_detections(5)

    # Nieuwe soorten vandaag (niet eerder gezien)
    conn = get_connection()
    today = conn.execute("SELECT date('now', 'localtime')").fetchone()[0]
    new_species = []
    rare_species = []
    for sp in species_today:
        first_ever = conn.execute(
            """SELECT MIN(date) FROM daily_stats WHERE species = ?""",
            (sp["species"],),
        ).fetchone()[0]
        if first_ever == today:
            new_species.append(sp)
        elif get_rarity(sp["species"]) >= 4:
            rare_species.append(sp)

    return render_template(
        "overview.html",
        stats=stats,
        species_today=species_today,
        hourly=hourly,
        recent=recent,
        new_species=new_species,
        rare_species=rare_species,
        now=datetime.now(),
    )


@app.route("/detections")
def detections():
    """Vandaag's detecties."""
    page = request.args.get("page", 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_connection()
    today = conn.execute("SELECT date('now', 'localtime')").fetchone()[0]

    rows = conn.execute(
        """SELECT * FROM detections
           WHERE detection_time LIKE ?
           ORDER BY detection_time DESC
           LIMIT ? OFFSET ?""",
        (f"{today}%", per_page, offset),
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) FROM detections WHERE detection_time LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]

    return render_template(
        "detections.html",
        detections=[dict(r) for r in rows],
        page=page,
        total=total,
        per_page=per_page,
        now=datetime.now(),
    )


@app.route("/spectrogram")
def spectrogram_view():
    """Live spectrogram / laatste detectie."""
    recent = get_recent_detections(1)
    return render_template(
        "spectrogram.html",
        detection=recent[0] if recent else None,
        now=datetime.now(),
    )


@app.route("/species")
def species_stats():
    """Soorten statistieken."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT species, species_dutch,
                  COUNT(*) as total,
                  MAX(confidence) as max_confidence,
                  MIN(detection_time) as first_seen,
                  MAX(detection_time) as last_seen,
                  COUNT(DISTINCT date(detection_time)) as active_days
           FROM detections
           GROUP BY species
           ORDER BY total DESC"""
    ).fetchall()

    species_list = []
    for r in rows:
        d = dict(r)
        d["rarity"] = get_rarity(d["species"])
        species_list.append(d)

    return render_template(
        "species.html",
        species_list=species_list,
        now=datetime.now(),
    )


@app.route("/recordings")
def recordings():
    """Opnames browser."""
    recordings_dir = Path(get_config("storage.recordings_dir"))
    dates = sorted(
        [d.name for d in recordings_dir.iterdir() if d.is_dir()],
        reverse=True,
    )[:30]

    selected_date = request.args.get("date", dates[0] if dates else None)
    files = []
    if selected_date:
        date_dir = recordings_dir / selected_date
        if date_dir.exists():
            files = sorted(
                [f.name for f in date_dir.glob("*.wav")], reverse=True
            )

    return render_template(
        "recordings.html",
        dates=dates,
        selected_date=selected_date,
        files=files,
        now=datetime.now(),
    )


@app.route("/settings")
def settings_page():
    """Instellingen pagina."""
    config = get_all_config()
    return render_template(
        "settings.html",
        config=config,
        defaults=DEFAULTS,
        now=datetime.now(),
    )


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """Sla instellingen op via AJAX."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Geen data"}), 400

    for key, value in data.items():
        if key in DEFAULTS:
            set_config(key, str(value))

    return jsonify({"status": "ok", "saved": len(data)})


@app.route("/api/stats")
def api_stats():
    """API endpoint voor statistieken."""
    return jsonify(get_today_stats())


@app.route("/api/detections")
def api_detections():
    """API endpoint voor detecties."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_recent_detections(limit))


@app.route("/api/hourly")
def api_hourly():
    """API endpoint voor uurlijkse counts."""
    date = request.args.get("date")
    return jsonify(get_hourly_counts(date))


@app.route("/api/species")
def api_species():
    """API endpoint voor soorten vandaag."""
    return jsonify(get_today_species())


@app.route("/recordings/<path:filepath>")
def serve_recording(filepath):
    """Serveer audio bestanden."""
    recordings_dir = get_config("storage.recordings_dir")
    return send_from_directory(recordings_dir, filepath)


@app.route("/spectrograms/<path:filepath>")
def serve_spectrogram(filepath):
    """Serveer spectrogram bestanden."""
    spectrograms_dir = get_config("storage.spectrograms_dir")
    return send_from_directory(spectrograms_dir, filepath)


@app.template_filter("dutch_name")
def dutch_name_filter(scientific):
    """Jinja2 filter voor Nederlandse namen."""
    return get_dutch_name(scientific)


@app.template_filter("timeago")
def timeago_filter(dt_str):
    """Jinja2 filter voor 'x minuten geleden'."""
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        diff = datetime.now() - dt
        seconds = diff.total_seconds()
        if seconds < 60:
            return "zojuist"
        elif seconds < 3600:
            return f"{int(seconds / 60)} min geleden"
        elif seconds < 86400:
            return f"{int(seconds / 3600)} uur geleden"
        else:
            return f"{int(seconds / 86400)} dagen geleden"
    except (ValueError, TypeError):
        return dt_str


def main():
    """Start de web server."""
    port = get_config_int("web.port")
    host = get_config("web.host")
    print(f"EMSN Bats Web UI: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
