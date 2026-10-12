"""
CustomerGraph - Flask-App

Start: python app.py, danach http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify
import database as db

app = Flask(__name__)

# einmal beim Start die ganze Pipeline durchlaufen lassen, damit beim ersten
# Aufruf der Seite schon Segmente da sind
db.neu_berechnen()


@app.route("/")
def index():
    kunden = db.alle_kunden()
    statistik = db.graph_statistik()
    segmente = db.segmente_uebersicht()
    return render_template("index.html", kunden=kunden, statistik=statistik, segmente=segmente)


@app.route("/kunde")
def kunde():
    name = request.args.get("name", "Anna")
    kunden = db.alle_kunden()
    statistik = db.graph_statistik()
    segmente = db.segmente_uebersicht()
    profil = db.kunde_profil(name)
    aehnliche = db.aehnlichste_kunden(name)

    return render_template(
        "index.html",
        kunden=kunden, statistik=statistik, segmente=segmente,
        aktiver_kunde=name, profil=profil, aehnliche=aehnliche,
    )


@app.route("/graph-daten")
def graph_daten():
    """JSON fuer die vis.js-Visualisierung im Dashboard."""
    return jsonify(db.graph_daten())


@app.route("/neu-berechnen")
def neu_berechnen():
    """Setzt die Testdaten zurueck und laesst RFM, Aehnlichkeit und
    Label Propagation neu durchlaufen - fuer die Live-Demo."""
    db.neu_berechnen()
    return index()


if __name__ == "__main__":
    app.run(debug=True)
