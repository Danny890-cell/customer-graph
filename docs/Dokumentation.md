# CustomerGraph – Kundensegmentierung mit neo4j

Wahlfach NoSQL Datenbanksysteme, Prof. Dr. Ilia Petrov, Hochschule Reutlingen

## 1. Motivation

Im Marketing ist Kundensegmentierung ein Standardthema: statt jeden Kunden einzeln zu betrachten, bildet man Gruppen mit ähnlichem Verhalten, um gezielt Maßnahmen zu planen (Premium-Kunden mit besonderen Angeboten halten, abwanderungsgefährdete Kunden reaktivieren usw.). Die klassische Methode dafür ist die RFM-Analyse (Recency, Frequency, Monetary), die es im Database Marketing schon lange gibt.

Kaufbeziehungen und Kundenähnlichkeiten sind von Natur aus ein Netzwerk. Genau bei solchen stark vernetzten Daten tun sich relationale Datenbanken schwerer (siehe Vorlesung Folie 25, Stichwort sparse Tabellen bei vielen Beziehungen). Deshalb kombinieren wir in CustomerGraph die RFM-Idee aus BWL/Marketing mit einer echten graphbasierten Methode: Community Detection, statt Segmente einfach per festem Schwellenwert von Hand zu vergeben.

## 2. Datenmodell

Property Graph Model (Folie 9):

| Element | Typ | Eigenschaften |
|---|---|---|
| `(:Kunde)` | Knoten | name, recency_tage, frequency, monetary, r_score, f_score, m_score, segment |
| `(:Produkt)` | Knoten | name, kategorie, preis |
| `(k)-[:KAUFTE {datum, betrag}]->(p)` | Kante | eine Transaktion |
| `(k1)-[:AEHNLICH_WIE {score}]->(k2)` | gewichtete Kante | berechnete RFM-Ähnlichkeit |

```
(Anna:Kunde {r_score:4, f_score:5, m_score:5, segment:"Premium-Stammkunden"})
      -[:KAUFTE {datum: date("2026-09-26"), betrag: 999}]->
      (Laptop:Produkt {kategorie:"Elektronik"})

(Anna)-[:AEHNLICH_WIE {score: 0.87}]->(Ben)
```

Wichtig dabei: die AEHNLICH_WIE-Kanten und das segment-Attribut stehen nirgendwo fest im Code, sondern werden aus den Transaktionsdaten berechnet und dann dauerhaft im Graph abgelegt. Passt zu dem, was in Folie 41 als "Anreicherung durch Analyse-Ergebnisse" beschrieben wird (da ging's um PageRank, bei uns ist es eben RFM + Ähnlichkeit).

## 3. RFM-Analyse

Jeder Kunde bekommt drei Kennzahlen aus seiner Kaufhistorie:

| Kennzahl | Bedeutung | Berechnung |
|---|---|---|
| Recency | wie kürzlich der letzte Kauf war | Tage seit letztem Kaufdatum |
| Frequency | wie oft gekauft wurde | Anzahl Transaktionen |
| Monetary | wie viel Umsatz der Kunde bringt | Summe aller Käufe |

Jede Kennzahl wird dann per Rangfolge auf einen Score von 1 bis 5 normiert (vereinfachtes Quintil-Scoring – bei größeren Kundenzahlen würde man echte Quintile der Gesamtverteilung nehmen, bei 12 Kunden reicht die vereinfachte Variante). Bei Recency gilt weniger Tage = besser, daher wird da umgekehrt sortiert.

Ein paar Beispiele aus unseren Testdaten:

| Kunde | Recency (Tage) | Frequency | Monetary | R | F | M |
|---|---|---|---|---|---|---|
| Clara | 3 | 5 | 1505 € | 5 | 5 | 5 |
| David | 55 | 1 | 29 € | 3 | 3 | 1 |
| Hannes | 190 | 3 | 597 € | 1 | 4 | 4 |

Umgesetzt in `database.py`, Funktion `berechne_rfm_scores()`.

## 4. Warum nicht Cosinus?

Im ersten Entwurf (noch reine Produktempfehlung, bevor wir auf RFM umgestellt haben) hatten wir die Ähnlichkeit zwischen zwei Kunden per Cosinus-Ähnlichkeit berechnet. Für RFM-Score-Vektoren funktioniert das aber nicht gut, und das ist uns beim Testen auch tatsächlich aufgefallen, nicht nur theoretisch.

Cosinus misst nur den Winkel zwischen zwei Vektoren, nicht ihre Länge. Ein Kunde mit Profil (3,3,3) und einer mit (5,5,5) zeigen exakt in dieselbe Richtung, für Cosinus sind die also identisch (Ähnlichkeit = 1,0) – obwohl der zweite wirtschaftlich klar wertvoller ist. Bei uns hat das dazu geführt, dass Premium-Kunden und Gelegenheitskäufer im selben Cluster gelandet sind, was offensichtlich falsch ist.

Deswegen nutzt CustomerGraph stattdessen die euklidische Distanz, normiert auf einen Wert zwischen 0 und 1. Das ist auch der Ansatz, den man in der Literatur für RFM-Clustering üblicherweise findet:

```
similarity(A, B) = 1 - distanz(A, B) / max_distanz
distanz(A,B) = sqrt((r_A-r_B)^2 + (f_A-f_B)^2 + (m_A-m_B)^2)
```

Nur Paare mit Ähnlichkeit ≥ 0,70 bekommen überhaupt eine AEHNLICH_WIE-Kante. Ohne den Schwellenwert wäre irgendwann alles mit allem verbunden und am Ende würde die Label Propagation alle Kunden in ein einziges Segment werfen.

Umgesetzt in `database.py`, Funktion `berechne_aehnlichkeiten()`.

## 5. Label Propagation

Statt Segmentgrenzen per Hand festzulegen ("Umsatz > 500 € = Premium"), nutzen wir einen Graph-Algorithmus, der Segmente direkt aus der Netzwerkstruktur erkennt: Label Propagation.

So funktioniert's:

1. Jeder Kunde startet mit seinem eigenen, einzigartigen Label.
2. In jeder Runde übernimmt jeder Knoten das Label, das unter seinen Nachbarn (gewichtet mit dem AEHNLICH_WIE-Score) am häufigsten vorkommt.
3. Nach ein paar Runden ändert sich nichts mehr – Kunden mit vielen gemeinsamen Ähnlichkeitskanten laufen auf dasselbe Label zusammen und bilden so ein Segment.

Die Vorlesung erwähnt dieselbe Grundidee unter "Anwendung von Graph-Algorithmen" (Folie 41) und nennt die neo4j Graph Data Science Library als Plugin, das solche Algorithmen fertig und parallelisiert mitbringt (Folie 64). Wir haben Label Propagation bewusst selbst in Python geschrieben (`_label_propagation()` in `database.py`), damit man im Code tatsächlich sieht, was passiert. Mit GDS wäre das dieselbe Berechnung in einer Zeile:

```cypher
CALL gds.labelPropagation.write('kundenGraph', {writeProperty: 'segment_id'})
```

### Segmentnamen

Jedem gefundenen Cluster wird anhand seines Durchschnitts-RFM-Profils ein Name zugeordnet (eigene, vereinfachte Regel, keine offizielle Matrix):

| Bedingung | Segment |
|---|---|
| hohe F- und M-Scores, mindestens mittlerer R-Score | Premium-Stammkunden |
| niedriger R-Score, aber mittlere/hohe F- oder M-Scores | Abwanderungsgefährdete Kunden |
| hoher R-Score, aber niedrige F- und M-Scores | Neukunden mit Potenzial |
| sonst | Gelegenheitskäufer |

Mit unseren Testdaten kommen daraus vier gut unterscheidbare Segmente raus (Tabelle in Abschnitt 7).

### Graph im Dashboard

Weil der ganze Ansatz davon lebt, dass Kundenähnlichkeit ein Netzwerk ist, zeigt das Dashboard das AEHNLICH_WIE-Netzwerk zusätzlich als interaktiven Graphen (Knoten = Kunden, Kantenstärke = Ähnlichkeit, Farbe = Segment). Gerendert wird das im Browser mit vis.js, die Rohdaten kommen vom Endpunkt `/graph-daten` (`graph_daten()` in `database.py`) als simples Cypher-Ergebnis in JSON. So sieht man im Vortrag direkt, was die Label Propagation eigentlich tut.

## 6. Ein paar Cypher-Abfragen

Ähnlichste Kunden zu einem Kunden (vgl. Folie 50, MATCH … ORDER BY):

```cypher
MATCH (k:Kunde {name: $name})-[r:AEHNLICH_WIE]->(andere:Kunde)
RETURN andere.name AS kunde, andere.segment AS segment, r.score AS score
ORDER BY r.score DESC
LIMIT 5
```

Segmentübersicht mit Aggregation:

```cypher
MATCH (k:Kunde)
RETURN k.segment AS segment,
       collect(k.name) AS mitglieder,
       round(avg(k.r_score), 2) AS avg_r,
       round(avg(k.f_score), 2) AS avg_f,
       round(avg(k.m_score), 2) AS avg_m,
       round(avg(k.monetary), 2) AS avg_umsatz
ORDER BY avg_m DESC
```

Beide bleiben auch bei mehr Kunden lesbar. In SQL bräuchte die erste einen JOIN über eine Ähnlichkeits-Tabelle, die zweite ein GROUP BY über eine vorher per JOIN gebaute Segmenttabelle – ähnlich wie beim Freundschafts-Beispiel aus Folie 21-24.

## 7. Testdaten und Ergebnis

10 Produkte in 3 Kategorien, 12 Kunden mit absichtlich unterschiedlichen Kaufmustern, damit beim Vorführen nachvollziehbare Cluster rauskommen:

| Segment | Kunden | Ø R / F / M | Charakteristik |
|---|---|---|---|
| Premium-Stammkunden | Anna, Ben, Clara | 4,0 / 5,0 / 5,0 | häufig, kürzlich, hoher Umsatz |
| Gelegenheitskäufer | David, Felix | 2,5 / 2,5 / 1,0 | selten, länger her, kleine Beträge |
| Abwanderungsgefährdete Kunden | Emma, Greta, Hannes, Ida | 1,8 / 3,5 / 3,5 | früher aktiv, lange nichts mehr gekauft |
| Neukunden mit Potenzial | Jonas, Klara, Liam | 4,7 / 1,3 / 2,3 | ganz frischer erster Kauf |

Die vier Namen stehen nicht fest im Code – sie entstehen aus der Kombination von Label-Propagation-Clustering und der Namensregel aus Abschnitt 5. Ändert man die Testdaten, ändert sich auch der Zuschnitt der Cluster.

## 8. Projektstruktur

```
CustomerGraph/
├── app.py                 Flask-App (Routing)
├── database.py            neo4j-Zugriff: Testdaten, RFM, Aehnlichkeit, Label Propagation
├── requirements.txt
├── templates/index.html   Oberflaeche
└── docs/Dokumentation.md  dieses Dokument
```

Stack: neo4j Community Edition, Python mit neo4j-driver, Flask.

## 9. Stärken, Schwächen, was man noch machen könnte

Die Kombination aus RFM und Ähnlichkeitsnetzwerk funktioniert ganz gut zusammen: RFM liefert die fachliche Kennzahl, der Graph die Struktur für die automatische Gruppierung. Label Propagation findet die Segmente datengetrieben, ohne dass irgendwo ein fester Schwellenwert im Code steht, ab wann jemand "Premium" ist. Und die Umstellung von Cosinus auf euklidische Distanz war für uns ein echter Lernmoment – zeigt ganz gut, dass man eine Standardmethode nicht blind übernehmen sollte, nur weil sie oft in Tutorials auftaucht.

Auf der anderen Seite: die paarweise Ähnlichkeitsberechnung wächst quadratisch mit der Kundenzahl, bei richtig vielen Kunden würde man auf die GDS-Implementierung von neo4j wechseln (Folie 64, Plugins APOC und Graph Data Science). Das Quintil-Scoring ist bei 12 Kunden auch deutlich gröber als bei den üblichen RFM-Anwendungen mit tausenden Kunden. Und die Segment-Namensregel haben wir uns selbst ausgedacht – in der Praxis würde man das natürlich mit dem Marketing abstimmen.

Für eine Erweiterung würde sich am ehesten anbieten, die selbstgeschriebene Label-Propagation-Funktion gegen `gds.labelPropagation` auszutauschen – macht fachlich dasselbe, wäre bei größeren Datenmengen aber deutlich schneller.
