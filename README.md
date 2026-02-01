# SBS Service Knowledge OS

**Intelligente Suche in technischen Handbüchern | RAG-System für den deutschen Maschinenbau**

Entwickelt von [SBS Deutschland GmbH](https://sbsdeutschland.com)

---

## Überblick

Das Service Knowledge OS ist ein spezialisiertes RAG-System (Retrieval Augmented Generation), das für die präzise Suche in technischen Wartungshandbüchern optimiert ist. Im Gegensatz zu herkömmlichen PDF-Readern kann dieses System:

- **Komplexe Tabellen** korrekt extrahieren (Drehmomente, Maße, Teilenummern)
- **Strukturierte Daten** aus technischen Dokumenten verstehen
- **Präzise Quellenangaben** mit Seitenzahlen liefern
- **Halluzinationen vermeiden** durch strikte Quellenbasierung

## Tech Stack

| Komponente | Technologie | Zweck |
|------------|-------------|-------|
| UI Framework | Streamlit | Web-Interface |
| PDF-Parsing | LlamaParse | Tabellenextraktion |
| Orchestrierung | LlamaIndex | RAG-Pipeline |
| Vector Store | Qdrant (In-Memory) | Semantische Suche |
| LLM Backend | Azure OpenAI GPT-4o | Antwortgenerierung |

---

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/Luyzz22/sbs-service-knowledge-os.git
cd sbs-service-knowledge-os
```

### 2. Python-Umgebung einrichten

```bash
# Empfohlen: Virtual Environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder: venv\Scripts\activate  # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### 3. Anwendung starten

```bash
streamlit run app.py
```

Die Anwendung öffnet sich unter `http://localhost:8501`

---

## API-Keys einrichten

### LlamaCloud API Key (für LlamaParse)

LlamaParse ist der Schlüssel für präzise Tabellenextraktion. So erhalten Sie einen API Key:

1. **Account erstellen**: Gehen Sie zu [cloud.llamaindex.ai](https://cloud.llamaindex.ai/)
2. **Registrieren**: Erstellen Sie einen kostenlosen Account
3. **API Key generieren**: 
   - Navigieren Sie zu "API Keys" im Dashboard
   - Klicken Sie auf "Create new key"
   - Kopieren Sie den Key (Format: `llx-...`)

**Kosten**: LlamaParse bietet ein kostenloses Kontingent von 1.000 Seiten/Tag. Für Produktion: ~$0.003 pro Seite.

### Azure OpenAI Konfiguration

Sie benötigen ein Azure OpenAI Deployment:

1. **Azure Portal**: [portal.azure.com](https://portal.azure.com)
2. **OpenAI Ressource erstellen**:
   - Suchen Sie nach "Azure OpenAI"
   - Erstellen Sie eine neue Ressource
3. **Modelle deployen**:
   - GPT-4o (für Antwortgenerierung)
   - text-embedding-ada-002 (für Vektorisierung)
4. **Credentials kopieren**:
   - **Endpoint**: `https://[ihre-ressource].openai.azure.com/`
   - **API Key**: Im Bereich "Keys and Endpoint"
   - **Deployment Names**: Die Namen Ihrer Deployments

---

## Verwendung

### Schritt 1: API-Keys eingeben

Geben Sie in der Sidebar Ihre API-Keys ein:
- LlamaCloud API Key
- Azure OpenAI Endpoint
- Azure OpenAI API Key
- Deployment-Namen (GPT-4o und Embeddings)

### Schritt 2: PDF hochladen

Laden Sie ein technisches Handbuch im PDF-Format hoch. Das System:
1. Analysiert das PDF mit LlamaParse (inkl. Tabellen)
2. Erstellt einen durchsuchbaren Vektor-Index
3. Zeigt den Status "Bereit" an

### Schritt 3: Fragen stellen

Stellen Sie technische Fragen im Chat-Interface:

```
✓ "Wie hoch ist das Anzugsdrehmoment für Schraube M12?"
✓ "Welches Öl wird für das Getriebe empfohlen?"
✓ "Was sind die Wartungsintervalle für den Hydraulikfilter?"
✓ "Welche Sicherheitshinweise gelten bei der Demontage?"
```

Das System antwortet mit:
- Präziser Information aus dem Dokument
- Quellenangabe (Seitenzahl)
- Oder: "Diese Information ist im hochgeladenen Dokument nicht enthalten."

---

## Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         STREAMLIT UI                                │
│  ┌─────────────┐  ┌─────────────────────────────────────────────┐  │
│  │   Sidebar   │  │              Chat Interface                 │  │
│  │  - API Keys │  │  User: "Drehmoment M12?"                    │  │
│  │  - Upload   │  │  Bot:  "45 Nm (Quelle: Seite 23)"           │  │
│  │  - Status   │  │                                             │  │
│  └─────────────┘  └─────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │      LlamaIndex         │
                    │   Query Engine          │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐
│   LlamaParse    │    │     Qdrant      │    │  Azure OpenAI   │
│  PDF → Markdown │    │  Vector Store   │    │   GPT-4o        │
│  (Tabellen!)    │    │  (Similarity)   │    │  (Generation)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## Konfiguration für Produktion

### Persistenter Qdrant-Speicher

Für Produktion sollte Qdrant persistent betrieben werden:

```python
# Änderung in app.py
# Statt:
client = QdrantClient(":memory:")

# Verwenden Sie:
client = QdrantClient(
    host="localhost",  # oder Qdrant Cloud URL
    port=6333,
    api_key="your-qdrant-api-key"  # für Qdrant Cloud
)
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Umgebungsvariablen (empfohlen für Produktion)

Erstellen Sie eine `.env` Datei:

```env
LLAMA_CLOUD_API_KEY=llx-...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://...
AZURE_GPT4O_DEPLOYMENT=gpt-4o
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
```

---

## Roadmap

- [ ] Multi-PDF Support (mehrere Handbücher gleichzeitig)
- [ ] Persistente Qdrant-Anbindung (Cloud/Docker)
- [ ] Benutzerauthentifizierung
- [ ] Export der Antworten (PDF/Word)
- [ ] Mehrsprachigkeit (EN/DE)
- [ ] Integration mit SAP/ERP-Systemen

---

## Lizenz

Proprietär - SBS Deutschland GmbH

## Kontakt

**SBS Deutschland GmbH**  
Website: [sbsdeutschland.com](https://sbsdeutschland.com)  
GitHub: [github.com/Luyzz22](https://github.com/Luyzz22)
