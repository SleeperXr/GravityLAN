# Agenten-Metriken: Historische Analyse & Downsampling

Dieses Dokument beschreibt die Architektur und Implementierungsdetails zur performanten Erweiterung der Agenten-Metriken-Historie in GravityLAN.

---

## 1. Übersicht & Zielsetzung

Um Nutzerwünsche nach weitreichenden Analysen (z. B. Rückblick über 30 Tage) zu erfüllen, wurde die Historienansicht der Hardware-Metriken (CPU, RAM, Temperatur) von der statischen 60-Snapshots-Begrenzung befreit. 

Da physische Agenten standardmäßig alle 30 Sekunden telemetrische Daten senden, entstehen erhebliche Datenmengen:
- **Pro Agent und Tag**: 2.880 Snapshot-Datensätze.
- **Pro Agent und Monat (30 Tage)**: 86.400 Snapshot-Datensätze.

Um den Speicherplatz und die Abfrage-Performance auf SQLite-Systemen zu schonen, wurde ein hocheffizientes **serverseitiges Downsampling-Modell** implementiert. Die Rohdaten werden im Backend mathematisch in Zeitintervalle (Buckets) zusammengefasst und aggregiert.

---

## 2. Aggregationsstufen & Bucket-Größen

Es wurden vier feste, praxisnahe Zeiträume für das Downsampling definiert:

| Zeitraum (`range`) | Intervall / Bucket-Größe | Resultierende Datenpunkte (Maximum) |
| :--- | :--- | :--- |
| **6 Stunden (`6h`)** | 5 Minuten | 72 Punkte |
| **24 Stunden (`24h`)** | 15 Minuten | 96 Punkte |
| **7 Tage (`7d`)** | 2 Stunden | 84 Punkte |
| **30 Tage (`30d`)** | 6 Stunden | 120 Punkte |

---

## 3. Downsampling-Algorithmus (Aggregation)

Die Aggregation erfolgt im Backend (`app/api/agent.py`) über einen mathematischen Gruppierungs-Algorithmus:

1. **Zeitachsen-Rundung**: Die Zeitstempel der einzelnen Datenbankeinträge werden durch Division der Unix-Epoche auf den Beginn des jeweiligen Bucket-Intervalls abgerundet (z. B. auf die nächsten vollen 15 Minuten).
2. **Mittelwertbildung (`avg`)**: Innerhalb jedes Buckets wird das arithmetische Mittel für die Liniendiagramme berechnet:
   - `cpu_percent` (CPU-Auslastung)
   - `ram_percent` (Arbeitsspeicher-Prozent)
   - `ram_used_mb` / `ram_total_mb` (Arbeitsspeicher in Megabytes)
   - `temperature` (CPU-Kerntemperatur)
3. **Schlankes Datenvolumen (Abwärtskompatibilität)**: 
   Da komplexe JSON-Strukturen wie `disk_json` (Monitored Storage) und `net_json` (Netzwerk-I/O) im zeitlichen Verlauf der Liniendiagramme nicht historisch gezeichnet, sondern nur im Detailbereich des Agenten als *Ist-Zustand* visualisiert werden, übernimmt der Algorithmus den **jeweils letzten nicht-leeren JSON-Snapshot** innerhalb des Buckets. Dies spart massiv Bandbreite und hält das JSON-Antwort-Format 100% abwärtskompatibel zum bestehenden TypeScript-Frontend-Schema (`MetricsHistoryResponse`).

---

## 4. Behandlung von Offline-Phasen (Sparse Data)

Wenn ein überwachter Server offline ist (z. B. nachts oder bei Wartungsarbeiten), fehlen für diese Zeiträume Datensätze in der SQLite-Datenbank.
- **Optimierung**: Der Aggregations-Algorithmus **überspringt leere Buckets komplett** (Sparse Data Optimization), anstatt sie mit künstlichen Nullwerten (0% CPU/RAM) aufzufüllen.
- **Vorteil**:
  - Verhindert fehlerhafte und irreführende „Täler“ in den Diagrammen.
  - Reduziert die HTTP-Response-Größe bei längeren Ausfallzeiten drastisch.
  - Das SVG-Liniendiagramm rendert die Verbindungslinien sauber und bricht an den realen Datenlücken ab.

---

## 5. SQLite Performance-Optimierung (Compound Index)

Um die Lese-Performance bei Abfragen über den vollen Zeitraum von 30 Tagen (Bereichsscans) abzusichern, wurde ein zusammengesetzter Compound-Index auf der Tabelle `DeviceMetrics` definiert:

```python
__table_args__ = (
    Index("idx_device_metrics_device_timestamp", "device_id", "timestamp"),
)
```

### Warum dieser Index?
Ein normaler Index auf `device_id` müsste bei der Auswertung eines Zeitbereichs alle passenden Gerätedatensätze laden und im Nachgang nach der Spalte `timestamp` filtern und sortieren.
Der **Compound Index** sortiert die Zeilen auf Festplattenebene bereits vorab hierarchisch nach `device_id` und anschließend chronologisch nach `timestamp`. Dadurch reduziert sich die Suchzeit von SQLite bei Bereichsabfragen (z. B. `timestamp >= cutoff`) auf eine **Sub-Millisekunden-Operation**, selbst bei Hunderttausenden von Datensätzen in der Tabelle.

---

## 6. Zusammenspiel mit der Daten-Retention & Dynamische UI-Zeitbereiche

Die historische Tiefe der Diagramme ist direkt an die konfigurierbare Daten-Retention gekoppelt:
- In `config.py` ist `history_retention_days` standardmäßig auf **30 Tage** voreingestellt (über `GRAVITYLAN_HISTORY_RETENTION_DAYS`).
- Der Scheduler (`scheduler.py`) löscht im Hintergrund in einem rollierenden 12-Stunden-Zyklus alle Datensätze, die älter sind als diese Retention.
- Dadurch sind für den maximalen UI-Zeitraum von **30d** stets alle historischen aggregierten Daten verfügbar.

### Dynamische UI-Zeitbereiche (UX-Konsistenz)
Um Widersprüche zwischen den angebotenen Zeitbereichen in der Benutzeroberfläche und der tatsächlichen Daten-Retention auf Servern zu verhindern, wurde eine dynamische Koppelung integriert:
1. **API-Antwort**: Das Backend liefert im Endpoint `/api/agent/metrics/{device_id}` die Felder `retention_days` und `available_ranges` mit.
2. **Dynamische Berechnung**:
   - `6h` ist immer verfügbar.
   - `24h` wird angeboten, wenn `retention_days >= 1`.
   - `7d` wird angeboten, wenn `retention_days >= 7`.
   - `30d` wird angeboten, wenn `retention_days >= 30`.
3. **Automatisches UI-Layout**: Die Schaltflächen für Zeitbereiche im Dashboard passen sich dynamisch an diese Rückmeldung an. Ranges, die über die konfigurierte Retention hinausgehen, werden dem Benutzer gar nicht erst angeboten. Ein kleiner Info-Text (`System retention: Xd`) klärt den Benutzer elegant über die effektive Datenhaltung auf.

---

## 7. Migration & Wirksamkeit bei Bestandsdaten (Self-Healing Index)

Ein häufiges Problem bei neuen Datenbank-Indizes ist, dass sie bei existierenden Homelab-Installationen nicht automatisch erzeugt werden, wenn die Tabelle bereits existiert (da SQLAlchemy's `create_all` bestehende Tabellen ignoriert).

Um eine völlig reibungslose, wartungsfreie und benutzerfreundliche Inbetriebnahme zu garantieren, wurde ein **Self-Healing-Mechanismus** implementiert:
- Beim Starten der FastAPI-Anwendung wird in `init_db()` ([__init__.py](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/app/database/__init__.py)) nach dem Standard-Schema-Aufbau folgendes raw SQL-Kommando abgesetzt:
  ```sql
  CREATE INDEX IF NOT EXISTS idx_device_metrics_device_timestamp ON device_metrics (device_id, timestamp)
  ```
- **Wirksamkeit**: 
  - **Neues System**: Der Index wird sofort erstellt.
  - **Bestehendes System**: Beim ersten Update/Startup nach dem Git-Pull wird der Index ohne jeglichen Datenverlust oder manuelle Befehle im Hintergrund hinzugefügt.
  - **Zero-Maintenance**: Homelab-Nutzer müssen sich um keinerlei manuelle Migrationen kümmern. Die Anwendung heilt und optimiert sich selbstständig.
