"""
================================================================================
SBS DEUTSCHLAND GMBH - SERVICE KNOWLEDGE OS
================================================================================
Ein RAG-System (Retrieval Augmented Generation) für technische Handbücher.
Spezialisiert auf die präzise Extraktion von Tabellen und strukturierten Daten
aus Wartungs- und Servicehandbüchern im deutschen Maschinenbau.

Entwickelt von: SBS Deutschland GmbH
Website: https://sbsdeutschland.com
Repository: https://github.com/Luyzz22/ki-rechnungsverarbeitung

Tech Stack:
- Streamlit (UI Framework)
- LlamaParse (PDF-Parsing mit Tabellenextraktion)
- LlamaIndex (RAG-Orchestrierung)
- Qdrant (Vector Store)
- Azure OpenAI GPT-4o (LLM Backend)
================================================================================
"""

import streamlit as st
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Tuple
import hashlib

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS: LlamaIndex & LlamaParse
# ══════════════════════════════════════════════════════════════════════════════
try:
    from llama_parse import LlamaParse
    from llama_index.core import (
        VectorStoreIndex,
        Document,
        Settings,
        StorageContext,
    )
    from llama_index.core.node_parser import MarkdownNodeParser
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from llama_index.llms.azure_openai import AzureOpenAI
    from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)


# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURATION: Seiten-Setup & Styling
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="SBS Service Knowledge OS",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS für Industrial Engineering Look
st.markdown("""
<style>
    /* Hauptfarben: Dunkelblau/Anthrazit für Industrial Look */
    :root {
        --sbs-primary: #1a365d;
        --sbs-secondary: #2d3748;
        --sbs-accent: #3182ce;
        --sbs-success: #38a169;
        --sbs-warning: #d69e2e;
        --sbs-error: #e53e3e;
        --sbs-bg-light: #f7fafc;
    }
    
    /* Header Styling */
    .main-header {
        background: linear-gradient(135deg, #1a365d 0%, #2d3748 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 0 0 10px 10px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .main-header h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 600;
        letter-spacing: -0.5px;
    }
    
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
        font-size: 0.95rem;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }
    
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3 {
        color: #1a365d;
        font-weight: 600;
    }
    
    /* Chat Messages */
    [data-testid="stChatMessage"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
    
    /* Info Box für Quellenangaben */
    .source-box {
        background-color: #ebf8ff;
        border-left: 4px solid #3182ce;
        padding: 0.75rem 1rem;
        margin-top: 1rem;
        border-radius: 0 4px 4px 0;
        font-size: 0.9rem;
    }
    
    /* Warning Box */
    .warning-box {
        background-color: #fffaf0;
        border-left: 4px solid #d69e2e;
        padding: 0.75rem 1rem;
        border-radius: 0 4px 4px 0;
    }
    
    /* Status Indicators */
    .status-ready {
        color: #38a169;
        font-weight: 600;
    }
    
    .status-pending {
        color: #d69e2e;
        font-weight: 600;
    }
    
    .status-error {
        color: #e53e3e;
        font-weight: 600;
    }
    
    /* Button Styling */
    .stButton > button {
        background-color: #1a365d;
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    
    .stButton > button:hover {
        background-color: #2d3748;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    
    /* Divider */
    .section-divider {
        border-top: 2px solid #e2e8f0;
        margin: 1.5rem 0;
    }
    
    /* Footer */
    .footer {
        text-align: center;
        padding: 1rem;
        color: #718096;
        font-size: 0.85rem;
        border-top: 1px solid #e2e8f0;
        margin-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISIERUNG
# ══════════════════════════════════════════════════════════════════════════════
def init_session_state():
    """
    Initialisiert alle benötigten Session State Variablen.
    Session State persistiert Daten zwischen Streamlit-Reruns.
    """
    # Chat-Verlauf: Liste von Dictionaries mit 'role' und 'content'
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Vector Index: Der erstellte Suchindex
    if "index" not in st.session_state:
        st.session_state.index = None
    
    # Geparste Dokumente: Die extrahierten Markdown-Inhalte
    if "parsed_documents" not in st.session_state:
        st.session_state.parsed_documents = None
    
    # Dokument-Metadaten: Speichert Seitenzuordnungen
    if "doc_metadata" not in st.session_state:
        st.session_state.doc_metadata = {}
    
    # Status-Tracking
    if "parsing_complete" not in st.session_state:
        st.session_state.parsing_complete = False
    
    # Dateiname des aktuellen PDFs
    if "current_pdf_name" not in st.session_state:
        st.session_state.current_pdf_name = None
    
    # Qdrant Client (In-Memory)
    if "qdrant_client" not in st.session_state:
        st.session_state.qdrant_client = None


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def get_file_hash(file_content: bytes) -> str:
    """
    Erstellt einen Hash des Dateiinhalts für Caching-Zwecke.
    So vermeiden wir doppeltes Parsen derselben Datei.
    """
    return hashlib.md5(file_content).hexdigest()


def validate_api_keys(llama_key: str, azure_key: str, azure_endpoint: str) -> Tuple[bool, str]:
    """
    Validiert die eingegebenen API-Keys (Grundlegende Formatprüfung).
    
    Returns:
        Tuple[bool, str]: (Ist valide, Fehlermeldung falls nicht valide)
    """
    if not llama_key or len(llama_key) < 10:
        return False, "LlamaCloud API Key fehlt oder ist zu kurz."
    
    if not azure_key or len(azure_key) < 10:
        return False, "Azure OpenAI API Key fehlt oder ist zu kurz."
    
    if not azure_endpoint or not azure_endpoint.startswith("https://"):
        return False, "Azure Endpoint muss eine gültige HTTPS-URL sein."
    
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS: PDF-Parsing & Indexierung
# ══════════════════════════════════════════════════════════════════════════════
def parse_pdf_with_llamaparse(
    pdf_path: str, 
    llama_api_key: str
) -> Optional[List[Document]]:
    """
    Parst ein PDF mit LlamaParse im Markdown-Modus.
    
    LlamaParse ist spezialisiert auf:
    - Komplexe Tabellen (kritisch für technische Handbücher!)
    - Strukturierte Layouts
    - Saubere Markdown-Extraktion
    
    Args:
        pdf_path: Pfad zur PDF-Datei
        llama_api_key: LlamaCloud API Key
    
    Returns:
        Liste von LlamaIndex Document-Objekten oder None bei Fehler
    """
    try:
        # LlamaParse Konfiguration
        # result_type="markdown" ist entscheidend für Tabellenextraktion
        parser = LlamaParse(
            api_key=llama_api_key,
            result_type="markdown",  # Markdown-Ausgabe für strukturierte Daten
            num_workers=1,           # Anzahl paralleler Worker
            verbose=True,            # Detailliertes Logging
            language="de",           # Deutsche Sprache für OCR
            # Erweiterte Optionen für technische Dokumente:
            parsing_instruction="""
            Dies ist ein technisches Wartungshandbuch aus dem Maschinenbau.
            Extrahiere alle Tabellen präzise mit korrekten Spalten und Werten.
            Achte besonders auf:
            - Drehmomentangaben (Nm)
            - Maßangaben (mm, m, kg)
            - Teilenummern und Artikelnummern
            - Wartungsintervalle
            Behalte die Seitennummerierung bei.
            """
        )
        
        # PDF parsen - gibt LlamaIndex Documents zurück
        documents = parser.load_data(pdf_path)
        
        # Metadaten anreichern: Seitenzahlen extrahieren
        for i, doc in enumerate(documents):
            # LlamaParse fügt oft Metadaten hinzu
            if not doc.metadata:
                doc.metadata = {}
            
            # Seitenzahl setzen (1-basiert für Benutzerfreundlichkeit)
            doc.metadata["page_number"] = i + 1
            doc.metadata["source_file"] = Path(pdf_path).name
        
        return documents
        
    except Exception as e:
        st.error(f"Fehler beim PDF-Parsing: {str(e)}")
        return None


def create_vector_index(
    documents: List[Document],
    azure_api_key: str,
    azure_endpoint: str,
    azure_deployment_name: str = "gpt-4o",
    embedding_deployment: str = "text-embedding-ada-002"
) -> Optional[VectorStoreIndex]:
    """
    Erstellt einen Vektor-Index aus den geparsten Dokumenten.
    
    Workflow:
    1. Dokumente werden in Chunks (Nodes) aufgeteilt
    2. Jeder Chunk wird in einen Vektor umgewandelt (Embedding)
    3. Vektoren werden in Qdrant gespeichert
    4. Index ermöglicht semantische Suche
    
    Args:
        documents: Liste der geparsten Dokumente
        azure_api_key: Azure OpenAI API Key
        azure_endpoint: Azure OpenAI Endpoint URL
        azure_deployment_name: Name des GPT-4o Deployments
        embedding_deployment: Name des Embedding-Deployments
    
    Returns:
        VectorStoreIndex oder None bei Fehler
    """
    try:
        # ──────────────────────────────────────────────────────────────────────
        # 1. Azure OpenAI LLM konfigurieren
        # ──────────────────────────────────────────────────────────────────────
        llm = AzureOpenAI(
            model=azure_deployment_name,
            deployment_name=azure_deployment_name,
            api_key=azure_api_key,
            azure_endpoint=azure_endpoint,
            api_version="2024-02-15-preview",  # Aktuelle API-Version
            temperature=0.1,  # Niedrige Temperatur für präzise Antworten
        )
        
        # ──────────────────────────────────────────────────────────────────────
        # 2. Azure OpenAI Embeddings konfigurieren
        # ──────────────────────────────────────────────────────────────────────
        embed_model = AzureOpenAIEmbedding(
            model=embedding_deployment,
            deployment_name=embedding_deployment,
            api_key=azure_api_key,
            azure_endpoint=azure_endpoint,
            api_version="2024-02-15-preview",
        )
        
        # ──────────────────────────────────────────────────────────────────────
        # 3. Globale Settings setzen
        # ──────────────────────────────────────────────────────────────────────
        Settings.llm = llm
        Settings.embed_model = embed_model
        Settings.chunk_size = 1024      # Chunk-Größe in Tokens
        Settings.chunk_overlap = 100    # Überlappung für Kontext
        
        # ──────────────────────────────────────────────────────────────────────
        # 4. Qdrant Vector Store initialisieren (In-Memory für MVP)
        # ──────────────────────────────────────────────────────────────────────
        # Für Produktion: QdrantClient(host="localhost", port=6333)
        client = QdrantClient(":memory:")  # In-Memory für schnelles Prototyping
        st.session_state.qdrant_client = client
        
        # Collection erstellen
        collection_name = "service_knowledge"
        
        # Prüfen ob Collection existiert, falls ja löschen
        collections = client.get_collections().collections
        if any(c.name == collection_name for c in collections):
            client.delete_collection(collection_name)
        
        # Neue Collection erstellen
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=1536,  # Dimension für text-embedding-ada-002
                distance=Distance.COSINE
            )
        )
        
        # Vector Store mit LlamaIndex verbinden
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=collection_name
        )
        
        # ──────────────────────────────────────────────────────────────────────
        # 5. Node Parser für Markdown konfigurieren
        # ──────────────────────────────────────────────────────────────────────
        # MarkdownNodeParser versteht Markdown-Struktur (Headers, Tabellen etc.)
        node_parser = MarkdownNodeParser()
        
        # ──────────────────────────────────────────────────────────────────────
        # 6. Index erstellen
        # ──────────────────────────────────────────────────────────────────────
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            node_parser=node_parser,
            show_progress=True
        )
        
        return index
        
    except Exception as e:
        st.error(f"Fehler bei der Index-Erstellung: {str(e)}")
        return None


def query_knowledge_base(
    index: VectorStoreIndex,
    question: str,
    similarity_top_k: int = 5
) -> Tuple[str, List[str]]:
    """
    Durchsucht den Index und generiert eine Antwort.
    
    WICHTIG: Diese Funktion implementiert die "Guardrails":
    - Antworten NUR basierend auf dem Kontext
    - Explizite Quellenangaben (Seitenzahlen)
    - Keine Halluzinationen
    
    Args:
        index: Der VectorStoreIndex
        question: Die Benutzerfrage
        similarity_top_k: Anzahl der ähnlichsten Chunks für Kontext
    
    Returns:
        Tuple[str, List[str]]: (Antwort-Text, Liste der Quellen)
    """
    try:
        # Query Engine mit spezifischem System-Prompt erstellen
        query_engine = index.as_query_engine(
            similarity_top_k=similarity_top_k,
            response_mode="compact",  # Kompakte, präzise Antworten
        )
        
        # System-Prompt für präzise, quellenbasierte Antworten
        SYSTEM_PROMPT = """
Du bist ein technischer Assistent für Wartungshandbücher im deutschen Maschinenbau.

STRIKTE REGELN:
1. Antworte NUR basierend auf den bereitgestellten Dokumentauszügen.
2. Wenn die Information NICHT in den Dokumenten enthalten ist, sage EXAKT:
   "Diese Information ist im hochgeladenen Dokument nicht enthalten."
3. Erfinde NIEMALS Informationen, Werte oder Spezifikationen.
4. Gib IMMER die Seitenzahl als Quelle an, z.B. "(Quelle: Seite 42)".
5. Bei technischen Werten (Drehmomente, Maße etc.) zitiere exakt aus dem Dokument.
6. Antworte auf Deutsch in professionellem, technischem Stil.

FORMAT:
- Präzise und direkt antworten
- Technische Werte hervorheben
- Quellenangabe am Ende
"""
        
        # Anfrage mit System-Prompt kombinieren
        full_query = f"{SYSTEM_PROMPT}\n\nFrage: {question}"
        
        # Anfrage ausführen
        response = query_engine.query(full_query)
        
        # Quellen extrahieren
        sources = []
        if response.source_nodes:
            for node in response.source_nodes:
                page_num = node.metadata.get("page_number", "Unbekannt")
                source_file = node.metadata.get("source_file", "Dokument")
                sources.append(f"Seite {page_num} ({source_file})")
        
        return str(response), sources
        
    except Exception as e:
        return f"Fehler bei der Anfrage: {str(e)}", []


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════
def render_header():
    """Rendert den Haupt-Header der Anwendung."""
    st.markdown("""
    <div class="main-header">
        <h1>SBS Service Knowledge OS</h1>
        <p>Intelligente Suche in technischen Handbüchern | RAG-System für den Maschinenbau</p>
    </div>
    """, unsafe_allow_html=True)


def render_sidebar():
    """
    Rendert die Sidebar mit:
    - API-Key Eingaben
    - PDF Upload
    - Systemstatus
    """
    with st.sidebar:
        # ──────────────────────────────────────────────────────────────────────
        # Logo & Branding
        # ──────────────────────────────────────────────────────────────────────
        st.markdown("### SBS Deutschland GmbH")
        st.markdown("---")
        
        # ──────────────────────────────────────────────────────────────────────
        # API-Konfiguration
        # ──────────────────────────────────────────────────────────────────────
        st.markdown("#### Konfiguration")
        
        # LlamaCloud API Key
        st.markdown("**LlamaCloud API Key**")
        st.markdown(
            '<small>Für PDF-Parsing mit Tabellenextraktion. '
            '<a href="https://cloud.llamaindex.ai/" target="_blank">Key hier erstellen</a></small>',
            unsafe_allow_html=True
        )
        llama_key = st.text_input(
            "LlamaCloud Key",
            type="password",
            key="llama_api_key",
            label_visibility="collapsed",
            placeholder="llx-..."
        )
        
        st.markdown("")  # Spacer
        
        # Azure OpenAI Konfiguration
        st.markdown("**Azure OpenAI**")
        
        azure_endpoint = st.text_input(
            "Azure Endpoint",
            key="azure_endpoint",
            placeholder="https://your-resource.openai.azure.com/",
            help="Format: https://[resource-name].openai.azure.com/"
        )
        
        azure_key = st.text_input(
            "Azure API Key",
            type="password",
            key="azure_api_key",
            placeholder="Azure OpenAI API Key"
        )
        
        azure_deployment = st.text_input(
            "GPT-4o Deployment Name",
            key="azure_deployment",
            value="gpt-4o",
            help="Name des GPT-4o Deployments in Azure"
        )
        
        embedding_deployment = st.text_input(
            "Embedding Deployment Name",
            key="embedding_deployment",
            value="text-embedding-ada-002",
            help="Name des Embedding-Deployments in Azure"
        )
        
        st.markdown("---")
        
        # ──────────────────────────────────────────────────────────────────────
        # PDF Upload
        # ──────────────────────────────────────────────────────────────────────
        st.markdown("#### Dokument hochladen")
        
        uploaded_file = st.file_uploader(
            "Wartungshandbuch (PDF)",
            type=["pdf"],
            key="pdf_uploader",
            help="Laden Sie ein technisches Handbuch im PDF-Format hoch"
        )
        
        # Verarbeitungs-Button
        if uploaded_file is not None:
            # API-Keys validieren
            is_valid, error_msg = validate_api_keys(
                llama_key, 
                azure_key, 
                azure_endpoint
            )
            
            if not is_valid:
                st.warning(error_msg)
            else:
                if st.button("Dokument verarbeiten", type="primary", use_container_width=True):
                    process_uploaded_pdf(
                        uploaded_file,
                        llama_key,
                        azure_key,
                        azure_endpoint,
                        azure_deployment,
                        embedding_deployment
                    )
        
        st.markdown("---")
        
        # ──────────────────────────────────────────────────────────────────────
        # Systemstatus
        # ──────────────────────────────────────────────────────────────────────
        st.markdown("#### Systemstatus")
        
        # Status-Anzeigen
        if st.session_state.parsing_complete and st.session_state.index is not None:
            st.markdown(
                f'<span class="status-ready">● Bereit</span><br>'
                f'<small>Dokument: {st.session_state.current_pdf_name}</small>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<span class="status-pending">○ Warte auf Dokument</span>',
                unsafe_allow_html=True
            )
        
        # Chat zurücksetzen
        if st.button("Chat zurücksetzen", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        
        st.markdown("---")
        
        # ──────────────────────────────────────────────────────────────────────
        # Footer
        # ──────────────────────────────────────────────────────────────────────
        st.markdown("""
        <div class="footer">
            <small>
                SBS Deutschland GmbH<br>
                <a href="https://sbsdeutschland.com" target="_blank">sbsdeutschland.com</a>
            </small>
        </div>
        """, unsafe_allow_html=True)
    
    return llama_key, azure_key, azure_endpoint, azure_deployment, embedding_deployment


def process_uploaded_pdf(
    uploaded_file,
    llama_key: str,
    azure_key: str,
    azure_endpoint: str,
    azure_deployment: str,
    embedding_deployment: str
):
    """
    Verarbeitet ein hochgeladenes PDF:
    1. Speichert temporär
    2. Parst mit LlamaParse
    3. Erstellt Vector Index
    """
    # Progress-Anzeige
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # ──────────────────────────────────────────────────────────────────────
        # Schritt 1: Temporär speichern
        # ──────────────────────────────────────────────────────────────────────
        status_text.text("Dokument wird vorbereitet...")
        progress_bar.progress(10)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # ──────────────────────────────────────────────────────────────────────
        # Schritt 2: PDF mit LlamaParse parsen
        # ──────────────────────────────────────────────────────────────────────
        status_text.text("PDF wird analysiert (Tabellen & Struktur)...")
        progress_bar.progress(30)
        
        documents = parse_pdf_with_llamaparse(tmp_path, llama_key)
        
        if documents is None:
            st.error("Fehler beim Parsen des PDFs.")
            return
        
        st.session_state.parsed_documents = documents
        progress_bar.progress(60)
        
        # ──────────────────────────────────────────────────────────────────────
        # Schritt 3: Vector Index erstellen
        # ──────────────────────────────────────────────────────────────────────
        status_text.text("Wissensindex wird erstellt...")
        progress_bar.progress(80)
        
        index = create_vector_index(
            documents,
            azure_key,
            azure_endpoint,
            azure_deployment,
            embedding_deployment
        )
        
        if index is None:
            st.error("Fehler bei der Index-Erstellung.")
            return
        
        st.session_state.index = index
        st.session_state.parsing_complete = True
        st.session_state.current_pdf_name = uploaded_file.name
        
        # ──────────────────────────────────────────────────────────────────────
        # Cleanup
        # ──────────────────────────────────────────────────────────────────────
        progress_bar.progress(100)
        status_text.text("Verarbeitung abgeschlossen!")
        
        # Temporäre Datei löschen
        os.unlink(tmp_path)
        
        # Erfolg anzeigen
        st.success(
            f"Dokument erfolgreich verarbeitet: {len(documents)} Seiten indexiert."
        )
        
        # Seite neu laden für aktuellen Status
        st.rerun()
        
    except Exception as e:
        st.error(f"Verarbeitungsfehler: {str(e)}")
        progress_bar.empty()
        status_text.empty()


def render_chat_interface():
    """
    Rendert das Haupt-Chat-Interface.
    """
    # ──────────────────────────────────────────────────────────────────────────
    # Chat-Container
    # ──────────────────────────────────────────────────────────────────────────
    st.markdown("#### Technische Anfrage")
    
    # Hinweis wenn kein Dokument geladen
    if not st.session_state.parsing_complete or st.session_state.index is None:
        st.info(
            "Laden Sie zunächst ein technisches Handbuch in der Sidebar hoch, "
            "um Fragen stellen zu können."
        )
        return
    
    # ──────────────────────────────────────────────────────────────────────────
    # Chat-Verlauf anzeigen
    # ──────────────────────────────────────────────────────────────────────────
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # Quellen anzeigen falls vorhanden
            if "sources" in message and message["sources"]:
                sources_text = ", ".join(message["sources"])
                st.markdown(
                    f'<div class="source-box"><strong>Quellen:</strong> {sources_text}</div>',
                    unsafe_allow_html=True
                )
    
    # ──────────────────────────────────────────────────────────────────────────
    # Chat-Eingabe
    # ──────────────────────────────────────────────────────────────────────────
    if prompt := st.chat_input(
        "Ihre technische Frage (z.B. 'Anzugsdrehmoment für M12 Schraube?')"
    ):
        # Benutzernachricht anzeigen
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Benutzernachricht speichern
        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })
        
        # Antwort generieren
        with st.chat_message("assistant"):
            with st.spinner("Durchsuche Dokumentation..."):
                response, sources = query_knowledge_base(
                    st.session_state.index,
                    prompt
                )
            
            # Antwort anzeigen
            st.markdown(response)
            
            # Quellen anzeigen
            if sources:
                sources_text = ", ".join(sources)
                st.markdown(
                    f'<div class="source-box"><strong>Quellen:</strong> {sources_text}</div>',
                    unsafe_allow_html=True
                )
        
        # Antwort speichern
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "sources": sources
        })


def render_info_section():
    """
    Rendert den Informationsbereich unter dem Chat.
    """
    with st.expander("Hinweise zur Nutzung", expanded=False):
        st.markdown("""
        **Beispielanfragen:**
        - "Wie hoch ist das Anzugsdrehmoment für Schraube M12?"
        - "Welches Öl wird für das Getriebe empfohlen?"
        - "Was sind die Wartungsintervalle für den Hydraulikfilter?"
        - "Welche Sicherheitshinweise gelten bei der Demontage?"
        
        **Funktionsweise:**
        1. Das PDF wird mit LlamaParse analysiert (optimiert für Tabellen)
        2. Der Inhalt wird in einen durchsuchbaren Vektor-Index umgewandelt
        3. Bei Ihrer Anfrage werden die relevantesten Abschnitte gefunden
        4. Die Antwort basiert ausschließlich auf dem Dokumentinhalt
        
        **Hinweis:** Das System antwortet nur mit Informationen, die im 
        hochgeladenen Dokument enthalten sind. Bei fehlenden Informationen 
        wird dies explizit mitgeteilt.
        """)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════
def main():
    """Haupteinstiegspunkt der Anwendung."""
    
    # Session State initialisieren
    init_session_state()
    
    # Import-Prüfung
    if not IMPORTS_AVAILABLE:
        st.error(f"""
        **Fehlende Abhängigkeiten**
        
        Bitte installieren Sie die erforderlichen Pakete:
        ```
        pip install -r requirements.txt
        ```
        
        Fehler: {IMPORT_ERROR}
        """)
        return
    
    # Header rendern
    render_header()
    
    # Sidebar rendern (gibt API-Keys zurück)
    llama_key, azure_key, azure_endpoint, azure_deployment, embedding_deployment = render_sidebar()
    
    # Hauptbereich
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Chat-Interface
        render_chat_interface()
        
        # Info-Bereich
        render_info_section()
    
    with col2:
        # Statistiken wenn Dokument geladen
        if st.session_state.parsing_complete and st.session_state.parsed_documents:
            st.markdown("#### Dokumentinfo")
            st.metric(
                "Seiten indexiert",
                len(st.session_state.parsed_documents)
            )
            st.metric(
                "Anfragen gestellt",
                len([m for m in st.session_state.messages if m["role"] == "user"])
            )


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
