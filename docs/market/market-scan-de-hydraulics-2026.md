# Markt- und Capability-Scan: industrielle Hydraulik

Stand: 14. August 2026. Quellen: öffentlich zugängliche Herstellerunterlagen. Die Auswahl betrachtet drei für den deutschen Hydraulikmarkt repräsentative, international führende Anbieter. Sie ist keine belastbare Umsatzrangliste; eine Aussage „die drei größten“ wäre ohne einheitliche Segment- und Geschäftsjahresdaten nicht beweisbar.

## Bosch Rexroth

Bosch Rexroth beschreibt CytroConnect als modularen Condition-Monitoring-Dienst für Hydrauliksysteme. Öffentlich belegt sind Echtzeitüberwachung, Druck-/Temperatur-/Volumenstromsignale, regelbasierte Analysen, Benachrichtigungen, Berichte sowie weiterführende Komponenten-, Öl- und Remaining-Useful-Life-Analysen. Quelle: [Bosch Rexroth CytroConnect Solutions](https://www.boschrexroth.com/en/us/connected-hydraulics/products/cytroconnect-solutions/).

Produktimplikation für HydraulikDoc:

- Asset-zentrierter Leitstand statt dokumentzentriertem Chat.
- Messgrößen und anlagenbezogene Warn-/Prüfgrenzen als deterministischer Pfad.
- Incidents direkt aus einer Bewertung anlegen.
- KI nur für quellengebundene Dokumentinterpretation, nicht für die Grenzwertarithmetik.

## Parker Hannifin

Parker positioniert SensoNODE/Voice of the Machine für kontinuierliches Remote Monitoring mit Druck- und Temperatursensorik, Dashboards, Alarmierung, Export und Cloud-/lokalen Betriebsvarianten. Quellen: [Parker SensoNODE Gold](https://discover.parker.com/sensonode-gold-sensors), [Parker Condition Monitoring with SensoNODE](https://www.parker.com/content/dam/parker/na/united-states/industries/industrial-manufacturing/pdfs-indusmanuequip/Condition%20Monitoring%20with%20SensoNODE%E2%84%A2.pdf) und [Parker Voice of the Machine](https://www.parker.com/content/dam/parker/fcg/quick-coupling-division/solutions/vom/Condition-Monitoring-Brochure_VoM.pdf).

Produktimplikation für HydraulikDoc:

- CSV-Import als herstellerneutraler Einstieg, bevor Live-Connectoren freigegeben werden.
- Mehrbenutzer- und Rollenmodell mit klarer Trennung zwischen Technician und Supervisor.
- Export nur aus einem kontrollierten Reviewzustand.
- Eine private Edge-/lokale Option bleibt dokumentiert, während Azure der primäre Enterprise-Pfad ist.

## HYDAC

HYDAC beschreibt CMX als Condition-Monitoring-Plattform mit Dashboard und automatisiertem Schmierstoff-/Fluid-Monitoring. Quelle: [HYDAC Magazin, CMX und Fluid Monitoring](https://www.hydac.com/media/magazine/hy/hy-no-01_2023_en.pdf).

Produktimplikation für HydraulikDoc:

- Fluidbewertung ist ein eigener Fachpfad und kein beiläufiger Chatprompt.
- Partikel- und Wasserindikatoren werden mit klaren Einheiten und konfigurierbaren Grenzen verarbeitet.
- Anlagenkritikalität und Incident-Workflow verbinden Diagnose mit Verantwortung.
- Herstellergrenzen werden nicht vorgegeben; die UI verlangt anlagenbezogene Bestätigung.

## Vergleich und Positionierung

| Markterwartung | Bosch Rexroth | Parker | HYDAC | HydraulikDoc 5.0 |
| --- | --- | --- | --- | --- |
| Asset-/Flottenübersicht | belegt | belegt | belegt | Assetregister und Leitstand |
| Druck/Temperatur/Flow | belegt | Druck/Temperatur belegt | Condition Monitoring | deterministische CSV-Prüfung |
| Fluid-/Ölzustand | belegt | Sensorportfolio | Kernstärke | Fluidpfad mit Incident-Übergabe |
| Alarm/Incident | Benachrichtigungen | Alerts | Dashboard | tenant-isolierter Incident-Workflow |
| Dokumentwissen | nicht Kern der betrachteten Quelle | nicht Kern der betrachteten Quelle | nicht Kern der betrachteten Quelle | PDF-Struktur, Hybrid Retrieval, Seitenquellen |
| Human Review/Evidenz | nicht Gegenstand der Quelle | nicht Gegenstand der Quelle | nicht Gegenstand der Quelle | Modell-/Promptprovenienz und Pflichtreview |
| Herstellerneutralität | Rexroth-Ökosystem | Parker-Ökosystem | HYDAC-Ökosystem | herstellerneutrale Assets, CSV und Dokumente |

HydraulikDoc konkurriert deshalb nicht als Sensorhardware oder OEM-Telematik. Die Marktposition ist die herstellerneutrale Evidence-and-Governance-Schicht für deutsche Instandhaltungsteams: vorhandene Dokumente und Messdaten werden in einen überprüfbaren, tenant-isolierten Entscheidungsprozess überführt.

## Nicht implementierte Marktanforderungen

- Live-OPC-UA-/MQTT-/ERP-/CMMS-Connectoren benötigen je Zielsystem Bedrohungsmodell, Datenvertrag und Mandantenfreigabe.
- Remaining Useful Life braucht anlagenspezifische Trainings-/Validierungsdaten und ist nicht durch generische LLM-Antworten ersetzbar.
- Mobile Offline-Arbeit, digitale Arbeitsaufträge und Ersatzteilkataloge sind Produkt-Roadmap, keine aktuelle Fähigkeit.
- SLA, Referenzkunden, Einsparzahlen und Zertifizierungen dürfen erst nach realem Betriebsnachweis vermarktet werden.
