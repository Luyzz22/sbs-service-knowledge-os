# AI System Card: HydraulikDoc Grounded Maintenance Assistant

Version: `hydraulic-grounded-answer@2026-11-06.1`

## Intended Purpose

Das System erstellt deutsch- oder englischsprachige, quellengebundene Rechercheentwürfe aus tenant-eigenen technischen PDF-Dokumenten für qualifizierte industrielle Instandhaltungsteams.

Die Antwortsprache folgt der Oberflächensprache der Person. Seit Prompt-Version `2026-11-06.1` unterscheiden sich die Prompts nur in Regel 7 (Antwortsprache): Englische Antworten übernehmen Fachbegriffe, Kennzeichnungen und Grenzwerte aus deutschen Quellen zusätzlich wörtlich in Klammern, damit beim Übersetzen keine Bedeutung verloren geht. Quellenpflicht, Untrusted-Data-Regel, Druck- und Grenzwertunterscheidung sowie LOTO-Sperre sind identisch und per Test abgesichert.

## Nicht zugelassene Zwecke

- autonome Maschinensteuerung, Fernabschaltung oder Änderung von SPS-/Safety-Parametern;
- Beschäftigtenüberwachung, Leistungsscore oder arbeitsrechtliche Entscheidung;
- automatische Wartungs-, Sicherheits-, CE-, Rechts- oder Herstellerfreigabe;
- Verwendung eines generischen Outputs anstelle von Originaldokument, Gefährdungsbeurteilung oder LOTO.

Die ersten beiden Zwecke werden vor Retrieval und Modellaufruf technisch gesperrt.

## Systembestandteile

- Azure AI Document Intelligence `prebuilt-layout` für seitenbezogene Extraktion;
- Azure OpenAI Embedding-Deployment für Vektoren;
- Azure AI Search für Keyword-, Vector- und optional Semantic Ranking mit verpflichtendem Tenantfilter;
- regionales Azure OpenAI Chat-Deployment mit Temperature 0;
- Prompt `hydraulic-grounded-answer@2026-11-06.1`;
- serverseitige Quellenmarkerprüfung;
- PostgreSQL-Provenienz und Human Review.

Das konkrete Modell und Snapshot werden nicht im Quelltext behauptet. Deploymentname und Modellversion müssen als signierte Releaseparameter gesetzt und im Output gespeichert werden. Auto-Upgrade ist in IaC deaktiviert.

Der Demo-Pfad (`AI_BACKEND=demo`) nutzt keinen der oben genannten Modellbestandteile: Er ruft kein Modell auf, gibt nur unverändert extrahierte Sätze aus synthetischen Dokumenten aus und ist in Produktion sowie hinter Entra ID per Konfiguration gesperrt.

## Input und Output

Input: validierte PDF-Inhalte und eine Frage bis 2.000 Zeichen. PDF-Dateien durchlaufen statische Kontrolle und Azure Defender Malware Scanning. Source-Inhalte werden als nicht vertrauenswürdige Daten markiert. Als Evidenz kommen nur Dokumente in Frage, die eine zweite Person freigegeben hat und die nicht zurückgezogen sind; Entwürfe sind indexiert, werden aber weder gesucht noch an das Modell übergeben.

Output: ein KI-Entwurf mit `[Sx]`-Markern, einer separaten Liste aus Dokument, Revision, Seite, Chunk und Retrievalscore, Modell-/Deployment-/Region-/Promptprovenienz sowie Reviewstatus. Ungültige oder fehlende Quellenmarker führen zu einem Fehler; der Output wird nicht als Analyse gespeichert.

## Human Oversight

Jeder Output startet als `draft`. Technician, Supervisor oder Admin können reviewen. Nur Supervisor/Admin mit `analysis:export` können einen akzeptierten Output exportieren. Sicherheitsrelevante Diagnose ist als `heightened` markiert und verlangt qualifizierte Prüfung. Die UI weist vor der ersten Nutzung und beim Ergebnis auf Grenzen hin. Der Aufsicht vorgelagert ist die Dokumentenlenkung: Supervisor oder Admin geben Quellen frei, nie den eigenen Upload, und können sie mit Grund zurückziehen. Zitiert eine gespeicherte Antwort eine inzwischen zurückgezogene Quelle, steht das beim Ergebnis.

## Daten- und Loggingkonzept

- Rohfragen werden nicht in technische Logs geschrieben.
- Die Datenbank speichert einen SHA-256 der Frage, den Antwortentwurf und die notwendige Provenienz.
- Akteur- und Ressourcenkennungen werden in Auditdaten HMAC-pseudonymisiert.
- Prompts/Outputs werden über regionale Standarddeployments verarbeitet; die Anbieter-/Transferbewertung bleibt externes Gate.
- Fristen werden pro Record Class gesetzt und täglich über Search, Blob und PostgreSQL propagiert.

## Bekannte Grenzen

- Retrieval kann relevante Seiten verfehlen oder irrelevante Passagen priorisieren.
- Ein formal gültiges Zitat beweist nicht, dass die Aussage fachlich korrekt aus der Quelle abgeleitet wurde.
- Die Freigabe eines Dokuments belegt die Prüfung durch eine zweite Person, nicht seine fachliche Richtigkeit oder Aktualität beim Hersteller. Ein überfälliger Überprüfungstermin sperrt die Quelle nicht.
- Tabellen, Scans, Zeichnungen, alte Normstände und uneinheitliche Einheiten können falsch extrahiert werden.
- Hersteller-, Anlagen- und Fluidgrenzen sind kontextspezifisch.
- Das System besitzt keine Echtzeitkenntnis des Maschinenzustands, sofern Daten nicht explizit importiert werden.
- Modellprovider können Deploymentverfügbarkeit, Sicherheitsfilter oder Serviceverhalten ändern; deshalb sind Snapshot und Regressionstest Releasebestandteil.

## Pflicht-Evaluation vor Produktion

Ausführung, privacy-preserving Reportformat und Produktionsgate sind in [AI-Evaluation und Release-Evidenz](ai-evaluation.md) festgelegt.

1. Goldset aus freigegebenen deutschen und englischen Hydraulikhandbüchern, einschließlich Tabellen und Warnhinweisen.
2. Retrieval Recall@k und Citation Precision mit tenant-übergreifenden Negativtests.
3. Exakte Extraktion von Druck, Temperatur, Durchfluss, Einheit und Grenzwertart.
4. Halluzinations-, Widerspruchs- und „keine Evidenz“-Fälle.
5. Prompt Injection in PDF, Unicode/Obfuskation und unzulässige Zweckanforderungen.
6. False-Positive-/False-Negative-Bewertung für sicherheitsrelevante Warnhinweise.
7. Fachreview durch Hydraulik-/Instandhaltungsexperten mit dokumentierter Akzeptanzschwelle.
8. Regression bei jeder Modell-, Prompt-, Search-, Parser- oder Chunkingänderung.

## Monitoring und Incident

Auditereignisse erfassen Dauer, Quellenanzahl, Modell, Promptversion, Risikoklasse und Reviewstatus ohne Rohinhalt. Abgelehnte und eskalierte Reviews sowie Incidents bilden den Eingang für Post-Market Monitoring. Schwellenwerte, Owner, CAPA und externe Meldepflichten müssen im QMS definiert werden.
