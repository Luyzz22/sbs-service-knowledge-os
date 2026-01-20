# SBS Service Knowledge OS

**Intelligente Suche in technischen Handbüchern | RAG-System für den Maschinenbau**

Entwickelt von [SBS Deutschland GmbH](https://sbsdeutschland.com)

## Features

- PDF-Upload mit Tabellenextraktion (LlamaParse)
- RAG-basierte Suche in technischen Dokumenten
- Quellenangaben mit Seitenzahlen
- Halluzinations-Schutz
- Deutsche Benutzeroberfläche

## Tech Stack

- **Frontend:** Streamlit
- **PDF-Parsing:** LlamaParse
- **RAG-Engine:** LlamaIndex
- **Vector Store:** Qdrant (In-Memory)
- **LLM:** OpenAI GPT-4o

## Installation
```bash
# Repository klonen
git clone https://github.com/Luyzz22/sbs-service-knowledge-os.git
cd sbs-service-knowledge-os

# Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# App starten
streamlit run app.py
```

## API Keys

Du benötigst:
1. **LlamaCloud API Key:** https://cloud.llamaindex.ai/
2. **OpenAI API Key:** https://platform.openai.com/api-keys

## Lizenz

Proprietär - SBS Deutschland GmbH

## Kontakt

- Website: [sbsdeutschland.com](https://sbsdeutschland.com)
- GitHub: [@Luyzz22](https://github.com/Luyzz22)
