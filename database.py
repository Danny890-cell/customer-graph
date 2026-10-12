"""
neo4j-Zugriff fuer CustomerGraph.

Kurz zum Ablauf: Testdaten anlegen -> RFM-Scores berechnen -> Aehnlichkeit
zwischen Kunden berechnen und als Kante speichern -> Label Propagation
drauf laufen lassen, damit Segmente automatisch entstehen statt per
Hand festgelegt zu werden.
"""

import math
import datetime
from collections import defaultdict
from itertools import combinations
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password123")

driver = GraphDatabase.driver(URI, auth=AUTH)

HEUTE = datetime.date.today()

# ab welcher Aehnlichkeit wir ueberhaupt eine Kante ziehen. Mit allem drunter
# als Kante wird am Ende alles mit allem verbunden und Label Propagation
# wirft nur noch ein riesiges Segment aus - 0.70 hat bei uns am saubersten
# vier Gruppen ergeben
AEHNLICHKEITS_SCHWELLENWERT = 0.70

# groesstmoegliche euklidische Distanz zwischen zwei RFM-Vektoren (Werte 1-5),
# zum Normieren auf 0..1
_MAX_RFM_DISTANZ = math.sqrt(3 * (5 - 1) ** 2)


PRODUKTE = [
    ("Laptop", "Elektronik", 999), ("Maus", "Elektronik", 29),
    ("Tastatur", "Elektronik", 79), ("Kopfhoerer", "Elektronik", 149),
    ("Monitor", "Elektronik", 249), ("Laufschuhe", "Sport", 89),
    ("Fitnessuhr", "Sport", 199), ("Kaffeemaschine", "Haushalt", 119),
    ("Staubsauger", "Haushalt", 229), ("Pfannenset", "Haushalt", 79),
]

# (Kunde, Produkt, Tage_zurueck, Betrag). Haben die Kaeufe absichtlich in
# vier Gruppen angelegt (Vielkaeufer / Gelegenheitskaeufer / lange nix mehr
# gekauft / ganz neu), damit am Ende beim Vorfuehren vernuenftige Segmente
# rauskommen und man nicht raten muss, ob der Algorithmus was Sinnvolles tut.
TRANSAKTIONEN = [
    # Vielkaeufer: haeufig, kuerzlich, hohe Betraege
    ("Anna",  "Laptop", 5, 999), ("Anna", "Monitor", 12, 249), ("Anna", "Kopfhoerer", 20, 149),
    ("Anna",  "Tastatur", 28, 79), ("Anna", "Maus", 35, 29),
    ("Ben",   "Laptop", 8, 999), ("Ben", "Monitor", 15, 249), ("Ben", "Fitnessuhr", 22, 199),
    ("Ben",   "Kopfhoerer", 30, 149),
    ("Clara", "Monitor", 3, 249), ("Clara", "Laptop", 10, 999), ("Clara", "Tastatur", 18, 79),
    ("Clara", "Maus", 25, 29), ("Clara", "Kopfhoerer", 32, 149),

    # Gelegenheitskaeufer: selten, laenger her, kleinere Betraege
    ("David", "Maus", 55, 29),
    ("Emma",  "Laufschuhe", 48, 89), ("Emma", "Pfannenset", 70, 79),
    ("Felix", "Tastatur", 60, 79),

    # frueher aktiv, aber seit Monaten nichts mehr gekauft
    ("Greta",  "Kaffeemaschine", 180, 119), ("Greta", "Staubsauger", 210, 229),
    ("Greta",  "Pfannenset", 240, 79), ("Greta", "Laptop", 260, 999),
    ("Hannes", "Staubsauger", 190, 229), ("Hannes", "Kaffeemaschine", 220, 119),
    ("Hannes", "Monitor", 250, 249),
    ("Ida",    "Pfannenset", 200, 79), ("Ida", "Kaffeemaschine", 230, 119),
    ("Ida",    "Fitnessuhr", 270, 199),

    # Neukunden, erster Kauf erst vor ein paar Tagen
    ("Jonas", "Laufschuhe", 2, 89),
    ("Klara", "Kopfhoerer", 4, 149),
    ("Liam",  "Fitnessuhr", 1, 199),
]


def seed_data():
    """Setzt die DB komplett zurueck und legt Kunden, Produkte und Kaeufe neu an."""
    kunden = sorted({t[0] for t in TRANSAKTIONEN})

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

        for name in kunden:
            session.run("CREATE (:Kunde {name: $name})", name=name)

        for name, kategorie, preis in PRODUKTE:
            session.run(
                "CREATE (:Produkt {name: $name, kategorie: $kategorie, preis: $preis})",
                name=name, kategorie=kategorie, preis=preis,
            )

        for kunde, produkt, tage_zurueck, betrag in TRANSAKTIONEN:
            datum = (HEUTE - datetime.timedelta(days=tage_zurueck)).isoformat()
            session.run(
                """
                MATCH (k:Kunde {name: $kunde}), (p:Produkt {name: $produkt})
                CREATE (k)-[:KAUFTE {datum: date($datum), betrag: $betrag}]->(p)
                """,
                kunde=kunde, produkt=produkt, datum=datum, betrag=betrag,
            )


# --- RFM ---

def _rfm_rohdaten():
    """Recency (Tage seit letztem Kauf), Frequency (Anzahl Kaeufe) und
    Monetary (Gesamtumsatz) pro Kunde, direkt aus den KAUFTE-Kanten."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:Kunde)-[r:KAUFTE]->(:Produkt)
            RETURN k.name AS kunde, r.datum AS datum, r.betrag AS betrag
            """
        )
        kaeufe = defaultdict(list)
        for row in result:
            kaeufe[row["kunde"]].append((row["datum"].to_native(), row["betrag"]))

    rohdaten = {}
    for kunde, liste in kaeufe.items():
        letzter_kauf = max(d for d, _ in liste)
        recency_tage = (HEUTE - letzter_kauf).days
        frequency = len(liste)
        monetary = sum(b for _, b in liste)
        rohdaten[kunde] = {"recency_tage": recency_tage, "frequency": frequency, "monetary": monetary}
    return rohdaten


def _score_1_bis_5(werte, hoeher_ist_besser):
    """Sortiert nach Rang und verteilt auf 5 Gruppen (1-5). Quintil-Scoring,
    nur eben auf unsere kleine Stichprobe runterskaliert."""
    sortierte_kunden = sorted(werte.keys(), key=lambda k: werte[k], reverse=hoeher_ist_besser)
    n = len(sortierte_kunden)
    scores = {}
    for rang, kunde in enumerate(sortierte_kunden):
        # Rang 0 (bester Wert) -> Score 5, letzter Rang -> Score 1
        score = 5 - int(rang * 5 / n)
        scores[kunde] = max(1, min(5, score))
    return scores


def berechne_rfm_scores():
    """R-, F- und M-Score (1-5) je Kunde ausrechnen und am Kunde-Knoten speichern."""
    rohdaten = _rfm_rohdaten()

    # bei Recency ist WENIGER besser, deshalb hoeher_ist_besser=False
    r_scores = _score_1_bis_5({k: v["recency_tage"] for k, v in rohdaten.items()}, hoeher_ist_besser=False)
    f_scores = _score_1_bis_5({k: v["frequency"] for k, v in rohdaten.items()}, hoeher_ist_besser=True)
    m_scores = _score_1_bis_5({k: v["monetary"] for k, v in rohdaten.items()}, hoeher_ist_besser=True)

    with driver.session() as session:
        for kunde, werte in rohdaten.items():
            session.run(
                """
                MATCH (k:Kunde {name: $kunde})
                SET k.recency_tage = $recency_tage, k.frequency = $frequency, k.monetary = $monetary,
                    k.r_score = $r, k.f_score = $f, k.m_score = $m
                """,
                kunde=kunde, recency_tage=werte["recency_tage"], frequency=werte["frequency"],
                monetary=werte["monetary"], r=r_scores[kunde], f=f_scores[kunde], m=m_scores[kunde],
            )


# --- Aehnlichkeit zwischen Kunden ---

def berechne_aehnlichkeiten():
    """Vergleicht jedes Kundenpaar anhand ihrer RFM-Scores und speichert
    Paare oberhalb des Schwellenwerts als AEHNLICH_WIE-Kante mit Score.

    Kurz zur Vorgeschichte: angefangen hatten wir mit Cosinus-Aehnlichkeit
    (wie im ersten Entwurf fuer die reine Produktempfehlung). Das passt aber
    nicht fuer RFM-Vektoren, weil Cosinus nur den Winkel zwischen zwei
    Vektoren vergleicht und nicht deren Laenge - ein Kunde mit Scores (3,3,3)
    und einer mit (5,5,5) zeigen in dieselbe Richtung und waeren fuer Cosinus
    identisch, obwohl der eine wirtschaftlich viel wertvoller ist. Bei uns
    sind dadurch Premium-Kunden und Gelegenheitskaeufer im selben Cluster
    gelandet. Deshalb jetzt stattdessen normierte euklidische Distanz:

    similarity(A,B) = 1 - distanz(A,B) / max_distanz
    mit distanz(A,B) = sqrt((r_A-r_B)^2 + (f_A-f_B)^2 + (m_A-m_B)^2)
    """
    with driver.session() as session:
        session.run("MATCH ()-[r:AEHNLICH_WIE]->() DELETE r")
        result = session.run(
            "MATCH (k:Kunde) RETURN k.name AS name, k.r_score AS r, k.f_score AS f, k.m_score AS m"
        )
        profile = {row["name"]: (row["r"], row["f"], row["m"]) for row in result}

        for k1, k2 in combinations(profile.keys(), 2):
            v1, v2 = profile[k1], profile[k2]
            distanz = math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))
            score = round(1 - distanz / _MAX_RFM_DISTANZ, 4)

            if score >= AEHNLICHKEITS_SCHWELLENWERT:
                session.run(
                    """
                    MATCH (a:Kunde {name:$k1}), (b:Kunde {name:$k2})
                    CREATE (a)-[:AEHNLICH_WIE {score: $score}]->(b)
                    CREATE (b)-[:AEHNLICH_WIE {score: $score}]->(a)
                    """,
                    k1=k1, k2=k2, score=score,
                )


# --- Segmente ueber Label Propagation ---

def _label_propagation(knoten, kanten, max_iterationen=20):
    """Simple Label-Propagation-Variante: jeder Knoten startet mit eigenem
    Label, uebernimmt dann Runde fuer Runde das Label, das unter den
    Nachbarn (gewichtet mit dem Aehnlichkeits-Score) am staerksten vertreten
    ist. Nach ein paar Runden ist Ruhe, ohne dass man vorher weiss, wie
    viele Cluster es am Ende sein werden.

    Fuer groessere Datenmengen gibt's dasselbe fertig und parallelisiert in
    neo4j als gds.labelPropagation - fuer unsere 12 Kunden reicht die
    selbstgebaute Variante locker und man sieht wenigstens, was passiert.
    """
    labels = {k: k for k in knoten}

    for _ in range(max_iterationen):
        veraendert = False
        for knoten_name in sorted(knoten):  # feste Reihenfolge, sonst nicht reproduzierbar
            gewicht_je_label = defaultdict(float)
            for nachbar, gewicht in kanten.get(knoten_name, []):
                gewicht_je_label[labels[nachbar]] += gewicht
            if not gewicht_je_label:
                continue
            bestes_label = max(gewicht_je_label.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if bestes_label != labels[knoten_name]:
                labels[knoten_name] = bestes_label
                veraendert = True
        if not veraendert:
            break

    return labels


def _segment_name(avg_r, avg_f, avg_m):
    """Vergibt anhand des Cluster-Durchschnitts einen Marketing-Namen.
    Eigene, vereinfachte Regel, keine offizielle RFM-Matrix."""
    if avg_f >= 3.5 and avg_m >= 3.5 and avg_r >= 3:
        return "Premium-Stammkunden"
    if avg_r <= 2 and (avg_f >= 2.5 or avg_m >= 2.5):
        return "Abwanderungsgefaehrdete Kunden"
    if avg_r >= 4 and avg_f <= 2 and avg_m <= 2.5:
        return "Neukunden mit Potenzial"
    return "Gelegenheitskaeufer"


def segmentiere_kunden():
    """Laesst Label Propagation auf dem AEHNLICH_WIE-Netzwerk laufen, benennt
    die gefundenen Cluster und schreibt das Ergebnis als segment-Property."""
    with driver.session() as session:
        knoten = [r["name"] for r in session.run("MATCH (k:Kunde) RETURN k.name AS name")]

        kanten = defaultdict(list)
        for row in session.run(
            "MATCH (a:Kunde)-[r:AEHNLICH_WIE]->(b:Kunde) RETURN a.name AS a, b.name AS b, r.score AS score"
        ):
            kanten[row["a"]].append((row["b"], row["score"]))

        rfm = {
            r["name"]: (r["r_score"], r["f_score"], r["m_score"])
            for r in session.run("MATCH (k:Kunde) RETURN k.name AS name, k.r_score AS r_score, k.f_score AS f_score, k.m_score AS m_score")
        }

    labels = _label_propagation(knoten, kanten)

    cluster = defaultdict(list)
    for kunde, label in labels.items():
        cluster[label].append(kunde)

    with driver.session() as session:
        for mitglieder in cluster.values():
            avg_r = sum(rfm[k][0] for k in mitglieder) / len(mitglieder)
            avg_f = sum(rfm[k][1] for k in mitglieder) / len(mitglieder)
            avg_m = sum(rfm[k][2] for k in mitglieder) / len(mitglieder)
            name = _segment_name(avg_r, avg_f, avg_m)

            for kunde in mitglieder:
                session.run(
                    "MATCH (k:Kunde {name:$kunde}) SET k.segment = $segment",
                    kunde=kunde, segment=name,
                )


def neu_berechnen():
    """Einmal alles von vorne: Testdaten -> RFM -> Aehnlichkeit -> Segmente."""
    seed_data()
    berechne_rfm_scores()
    berechne_aehnlichkeiten()
    segmentiere_kunden()


# --- Abfragen fuer die Oberflaeche ---

def alle_kunden():
    with driver.session() as session:
        result = session.run(
            "MATCH (k:Kunde) RETURN k.name AS name, k.segment AS segment ORDER BY k.name"
        )
        return [dict(r) for r in result]


def kunde_profil(name):
    with driver.session() as session:
        row = session.run(
            """
            MATCH (k:Kunde {name:$name})
            RETURN k.name AS name, k.segment AS segment, k.recency_tage AS recency_tage,
                   k.frequency AS frequency, k.monetary AS monetary,
                   k.r_score AS r_score, k.f_score AS f_score, k.m_score AS m_score
            """,
            name=name,
        ).single()
        kaeufe = session.run(
            """
            MATCH (k:Kunde {name:$name})-[r:KAUFTE]->(p:Produkt)
            RETURN p.name AS produkt, r.betrag AS betrag, r.datum AS datum
            ORDER BY r.datum DESC
            """,
            name=name,
        )
        profil = dict(row)
        profil["kaeufe"] = [{"produkt": k["produkt"], "betrag": k["betrag"], "datum": str(k["datum"])} for k in kaeufe]
        return profil


def aehnlichste_kunden(name, limit=5):
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:Kunde {name:$name})-[r:AEHNLICH_WIE]->(andere:Kunde)
            RETURN andere.name AS kunde, andere.segment AS segment, r.score AS score
            ORDER BY r.score DESC
            LIMIT $limit
            """,
            name=name, limit=limit,
        )
        return [dict(r) for r in result]


def segmente_uebersicht():
    """Mitglieder und Durchschnitts-RFM-Profil je Segment - die Tabelle, die
    wir im Vortrag eigentlich zeigen wollen."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:Kunde)
            RETURN k.segment AS segment, collect(k.name) AS mitglieder,
                   round(avg(k.r_score), 2) AS avg_r, round(avg(k.f_score), 2) AS avg_f,
                   round(avg(k.m_score), 2) AS avg_m, round(avg(k.monetary), 2) AS avg_umsatz
            ORDER BY avg_m DESC
            """
        )
        return [dict(r) for r in result]


def graph_daten():
    """Knoten + Kanten des Aehnlichkeitsnetzwerks als JSON fuer vis.js im Dashboard."""
    with driver.session() as session:
        knoten = session.run(
            "MATCH (k:Kunde) RETURN k.name AS name, k.segment AS segment, k.monetary AS monetary"
        )
        nodes = [
            {"id": r["name"], "label": r["name"], "group": r["segment"], "umsatz": r["monetary"]}
            for r in knoten
        ]

        kanten = session.run(
            """
            MATCH (a:Kunde)-[r:AEHNLICH_WIE]->(b:Kunde)
            WHERE a.name < b.name
            RETURN a.name AS von, b.name AS zu, r.score AS score
            """
        )
        edges = [{"from": r["von"], "to": r["zu"], "value": r["score"]} for r in kanten]

        return {"nodes": nodes, "edges": edges}


def graph_statistik():
    with driver.session() as session:
        kunden = session.run("MATCH (k:Kunde) RETURN count(k) AS c").single()["c"]
        produkte = session.run("MATCH (p:Produkt) RETURN count(p) AS c").single()["c"]
        kaeufe = session.run("MATCH ()-[r:KAUFTE]->() RETURN count(r) AS c").single()["c"]
        aehnlich = session.run("MATCH ()-[r:AEHNLICH_WIE]->() RETURN count(r) AS c").single()["c"]
        segmente = session.run("MATCH (k:Kunde) RETURN count(DISTINCT k.segment) AS c").single()["c"]
        return {
            "kunden": kunden, "produkte": produkte, "kaeufe": kaeufe,
            "aehnlichkeiten": aehnlich, "segmente": segmente,
        }
