# Azure Production Deployment Runbook

## 1. Freigaben vor Technik

Vor dem ersten Deploy müssen Owner und Evidence-ID für Informationssicherheit, Datenschutz, AI Governance, Retention, Betrieb und Fachverantwortung dokumentiert sein. `COMPLIANCE_RELEASE_APPROVED` und `RETENTION_POLICY_APPROVED` sind keine Selbstauskunft des Entwicklers, sondern das Ergebnis dieses Workflows.

## 2. Azure- und GitHub-Voraussetzungen

1. Separate Produktionssubscription und Resource Group in `germanywestcentral`.
2. Registrierte Resource Provider für App, Network, Storage, Security, Cognitive Services, Search, PostgreSQL, Key Vault, Container Registry, Managed Identity und Operational Insights.
3. GitHub Environment `production` mit Required Reviewers, geschützten Branches, Required Status Checks und blockiertem Force Push.
4. Eine GitHub-OIDC-Anwendung mit minimalem Deploymentrecht auf die Ziel-Resource-Group; keine Subscription-Owner-Rolle für den Workflow.
5. Eine separate Entra-Anwendung für HydraulikDoc Interactive Login.

App-Rollen setzen:

```bash
az ad app update --id "$ENTRA_APP_CLIENT_ID" --app-roles @infra/azure/entra-app-roles.json
```

In Entra „Assignment required“ aktivieren, Gruppen den minimalen Rollen zuweisen und Redirect URI `https://<hostname>/.auth/login/aad/callback` konfigurieren. Conditional Access/MFA, Break-glass und Rezertifizierung werden tenantseitig erzwungen.

## 3. TLS-Wert vorbereiten

Application Gateway erwartet einen base64-kodierten, unverschlüsselten PFX-Inhalt. Der Wert wird als geschützter ARM-Parameter in den privaten Ziel-Key-Vault geschrieben. Lokale Zwischenprodukte sicher löschen und den privaten Schlüssel nicht in Tickets oder Logs kopieren.

```bash
openssl pkcs12 -export -out public-tls.pfx -inkey tls.key -in tls.crt -certfile chain.crt -passout pass:
base64 < public-tls.pfx | tr -d '\n'
```

Zertifikatsrotation erfolgt durch Aktualisieren des GitHub-Secrets und erneutes genehmigtes Deployment. Ablaufalarmierung ist im Azure-Betrieb einzurichten.

## 4. GitHub-Konfiguration

Secrets:

- `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- `ENTRA_APP_CLIENT_ID`, `ENTRA_CLIENT_SECRET`
- `AUDIT_HMAC_KEY` mit mindestens 32 zufälligen Bytes
- `POSTGRES_ADMIN_PASSWORD`, `POSTGRES_APP_PASSWORD`, `POSTGRES_LIFECYCLE_PASSWORD`
- `TLS_CERTIFICATE_PFX_BASE64`

Variables:

- `PUBLIC_HOSTNAME`
- `AZURE_DEPLOY_ENABLED=true`
- `COMPLIANCE_RELEASE_APPROVED=true`
- `RETENTION_POLICY_APPROVED=true`
- `RETENTION_POLICY_ID=<signierte Version>`
- `AI_EVALUATION_EVIDENCE_ID=<freigegebener Eval-Report>`
- `AZURE_CHAT_MODEL_NAME=<in der Zielregion geprüft>`
- `AZURE_CHAT_MODEL_VERSION=<evaluiertes Snapshot>`

Das Entra-Client-Secret und alle Passwörter erhalten Rotationstermine und Owner. Der HMAC-Key darf nicht unkoordiniert rotiert werden, weil sich sonst Auditpseudonyme ändern; Rotation braucht eine versionierte Migrationsentscheidung.

## 5. Pipelineablauf

Die Main-Pipeline:

1. kompiliert, lintet, typprüft und testet;
2. führt Bandit, pip-audit und Trivy aus und erzeugt ein CycloneDX-SBOM;
3. validiert Compose und Bicep;
4. authentifiziert sich per OIDC;
5. erstellt die private Azure-Plattform und öffnet ACR nur für die begrenzte Azure-Buildphase;
6. baut das Image in ACR und löst den Digest auf;
7. deployt das immutable Image, deaktiviert ACR Public Access und setzt Runtime-Gates;
8. migriert die Datenbank im manuellen Adminjob, aktiviert FORCE RLS auf allen Tenanttabellen und trennt Web- von Lifecycle-Rolle; beide erhalten weder DDL noch allgemeines `DELETE`;
9. startet einmalig den Retention-Job;
10. startet die App-Revision neu und prüft den öffentlichen Health-Endpunkt.

## 6. DNS und Erstinbetriebnahme

Die Pipeline gibt die öffentliche Application-Gateway-IP aus. DNS A/AAAA-Konfiguration, Zertifikatsname und Hostname müssen übereinstimmen. Erst danach:

- Health, Login und Rollenzuordnung je App-Rolle testen;
- zwei Testtenants anlegen und Cross-Tenant-Negativtests ausführen;
- EICAR in einem isolierten Testtenant verwenden, um das Malware-Gate zu prüfen;
- ein freigegebenes Testhandbuch indexieren, Quellen-/Zitatgate und Reviewexport prüfen;
- Dokument löschen und Search/Blob/PostgreSQL-Propagation nachweisen;
- WAF-, Defender-, Entra- und Container-Logs in das SIEM aufnehmen;
- Backup-/Restore-Drill durchführen.

## 7. Release-Evidenz

Mindestens speichern: Git SHA, Image Digest, SBOM, Scanergebnisse, Bicep-Deployment-ID, reale Region/SKUs, Modellname/-version, Promptversion, Entra-Rollenexport, RLS-/Tenanttest, Malwaretest, Retention-Jobausführung, Zertifikatsfingerprint, DNS, Fach-Eval, Restoretest und externe Freigabe-IDs.

## 8. Rollback

Rollback bedeutet Deployment eines zuvor freigegebenen Digests mit kompatiblem Schema. Keine Datenbankdateien oder Secrets zurücksetzen. Vor Rollback Migrationskompatibilität prüfen; bei Datenkorruption Incident- und Restore-Runbook verwenden. Nach jedem Rollback die Deployment-Evidence-ID aktualisieren und AI-Modell-/Promptkombination erneut verifizieren.
