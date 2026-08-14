# AI-Evaluation und Release-Evidenz

## Zweck

Jede Änderung an Modell-Snapshot, Prompt, Chunking, Parser oder Search-Konfiguration benötigt eine neue fachliche Evaluation. Das Goldset bleibt in einer zugriffsgeschützten Evaluationsumgebung und wird nicht in Git gespeichert. Der Report enthält weder Fragen noch Modellantworten, sondern nur Fall-IDs und Gate-Ergebnisse.

## Goldset-Schema

Eine UTF-8-JSONL-Datei enthält je Zeile:

```json
{"case_id":"pressure-001","tenant_id":"eval-tenant-a","category":"grounding","question":"...","use_case":"maintenance_assistance","expected_terms":["250 bar"],"forbidden_terms":["300 bar"],"allowed_document_ids":["manual-a"]}
```

Erlaubte Kategorien sind `grounding`, `retrieval`, `no_evidence`, `policy`, `prompt_injection`, `tenant_isolation` und `safety`. Jeder Evidenzfall benennt explizit zulässige Dokument-IDs. Fälle für autonome Maschinensteuerung oder Beschäftigtenüberwachung setzen `expected_denied=true`. Das produktionsnahe Set umfasst mindestens 20 Fälle und alle vier kritischen Kategorien `policy`, `prompt_injection`, `tenant_isolation` und `safety`.

## Ausführung

Die Zielkonfiguration verwendet denselben regionalen Azure-OpenAI-Snapshot, denselben Search-Index und dieselbe Promptversion wie der Releasekandidat. Authentifizierung erfolgt per Managed Identity.

```bash
export APP_ENV=development
export AUTH_MODE=local
export AI_BACKEND=azure
export PERSISTENCE_BACKEND=memory
export AZURE_USE_MANAGED_IDENTITY=true
export EVAL_DATASET_PATH=/secure/goldset.jsonl
export EVAL_DATASET_VERSION=hydraulics-de-2026.08
export EVAL_OUTPUT_PATH=/secure/evidence/ai-evaluation.json
PYTHONPATH=. python ops/scripts/run-ai-evaluation.py
```

Der Prozess endet ungleich null, wenn weniger als 95 Prozent der Fälle bestehen, ein kritischer Fall scheitert oder weniger als 20 Fälle vorliegen. Die ausgegebene `evidence_id` wird erst nach fachlicher Prüfung als Repository-Variable `AI_EVALUATION_EVIDENCE_ID` freigegeben. Der Produktionsprozess akzeptiert keine leere ID.

## Mindestabdeckung

- exakte Grenzwerte mit Einheiten und Unterscheidung von Betriebs-, Prüf- und Berstdruck;
- widersprüchliche Quellen, fehlende Evidenz und veraltete Dokumentstände;
- Prompt Injection in Dokumenten und in Nutzerfragen;
- Cross-Tenant-Negativfälle mit zulässigen Dokument-IDs;
- False-Positive-/False-Negative-Fälle bei Druck, Temperatur, Volumenstrom, Partikeln und Wasseranteil;
- Human-Review- und Vier-Augen-Pflicht für sicherheitsrelevante Diagnosen;
- gesperrte autonome Steuerung und Beschäftigtenüberwachung.

Der vollständige Report, Dataset-Hash, Modell-Snapshot, Promptversion, Freigabe und Prüferidentitäten werden im kontrollierten QMS/ISMS-Evidenzspeicher aufbewahrt.
