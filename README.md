# CustomerGraph – Kundensegmentierung mit neo4j

Projekt für das Wahlfach NoSQL Datenbanksysteme (Prof. Dr. Ilia Petrov). Eine kleine Webanwendung, die Kunden per RFM-Analyse (Recency, Frequency, Monetary) bewertet und sie dann über ein Ähnlichkeitsnetzwerk mit Label-Propagation-Community-Detection automatisch in Marketing-Segmente einteilt (z. B. "Premium-Stammkunden", "Abwanderungsgefährdete Kunden").

Die ausführliche fachliche Doku (Motivation, Datenmodell, RFM-Theorie, warum euklidisch statt Cosinus, Label Propagation, Cypher-Abfragen, SQL-Vergleich) liegt in `docs/Dokumentation.md` – das ist auch die Grundlage für unseren Vortrag.

## Installation (Windows)

### 1. neo4j installieren

1. Auf [neo4j.com/download](https://neo4j.com/download) Neo4j Desktop runterladen (kostenlos).
2. Installieren wie jedes andere Windows-Programm.
3. Neo4j Desktop öffnen, dann New Project → Add → Local DBMS.
4. Name ist egal, Passwort `password123` setzen und auf Create klicken.
   (Anderes Passwort geht auch, dann einfach in `database.py` die Zeile `AUTH = ("neo4j", "password123")` anpassen.)
5. Auf Start klicken, die Datenbank läuft dann lokal unter `bolt://localhost:7687`.

Die Zusatz-Plugins (Bloom, Gen AI, Graph Data Science) braucht man nicht, die ganze RFM- und Clustering-Logik läuft komplett in Python.

### 2. Python vorbereiten

In der Eingabeaufforderung in den Projektordner wechseln:

```bash
cd Pfad\zu\CustomerGraph
pip install -r requirements.txt
```

### 3. App starten

```bash
python app.py
```

Dann im Browser: http://localhost:5000

## Bedienung

Die Startseite zeigt die Segmentübersicht: wie viele Kunden pro Segment, Durchschnitts-RFM-Werte, Mitgliederliste. Klickt man auf einen Kundennamen, sieht man dessen RFM-Profil, Kaufhistorie und die ähnlichsten anderen Kunden. Der Link "Testdaten neu laden & Pipeline neu berechnen" setzt die Datenbank zurück und lässt RFM-Scoring, Ähnlichkeitsberechnung und Label Propagation neu durchlaufen – praktisch für die Live-Demo.

## Projektstruktur

```
CustomerGraph/
├── app.py                  Flask-App
├── database.py              neo4j-Zugriff, RFM, Aehnlichkeit, Label Propagation
├── requirements.txt
├── templates/index.html     Oberflaeche
└── docs/Dokumentation.md    fachliche Doku fuer den Vortrag
```

## Troubleshooting

- ServiceUnavailable / Verbindungsfehler: neo4j läuft nicht, in Neo4j Desktop auf Start klicken und warten bis der Status grün ist.
- AuthError: Passwort in `database.py` stimmt nicht mit dem beim Anlegen der Datenbank vergebenen überein.
- Port 5000 belegt: in `app.py` ganz unten `app.run(debug=True, port=5001)` setzen.
