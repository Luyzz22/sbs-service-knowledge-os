"""
================================================================================
SBS DEUTSCHLAND GMBH - SERVICE KNOWLEDGE OS
================================================================================
RAG-System für technische Handbücher - Enterprise Edition v3.0
Multi-PDF Support
================================================================================
"""

import streamlit as st
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Tuple, Dict

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
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
    from llama_index.llms.openai import OpenAI
    from llama_index.embeddings.openai import OpenAIEmbedding
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Service Knowledge OS | SBS Deutschland",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
    
    .stApp { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        border-right: 1px solid #334155;
    }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    [data-testid="stSidebar"] .stMarkdown a { color: #60a5fa !important; }
    [data-testid="stSidebar"] hr { border-color: #334155; margin: 1.5rem 0; }
    [data-testid="stSidebar"] .stTextInput > div > div {
        background-color: #1e293b; border: 1px solid #475569; border-radius: 8px;
    }
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white !important; border: none; border-radius: 8px;
        padding: 0.6rem 1.2rem; font-weight: 600;
        box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.3);
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        transform: translateY(-1px);
    }
    
    /* Logo */
    .logo-container {
        text-align: center; padding: 1.5rem 0; margin-bottom: 1rem;
        border-bottom: 1px solid #334155;
    }
    .logo-text {
        font-size: 1.5rem; font-weight: 700;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .logo-subtext {
        font-size: 0.75rem; color: #94a3b8 !important;
        text-transform: uppercase; letter-spacing: 2px; margin-top: 0.25rem;
    }
    
    /* Header */
    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #1e293b 100%);
        color: white; padding: 2.5rem 3rem; border-radius: 16px; margin-bottom: 2rem;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
    }
    .main-header h1 { margin: 0; font-size: 2rem; font-weight: 700; }
    .main-header p { margin: 0.75rem 0 0 0; opacity: 0.9; }
    .header-badge {
        display: inline-block; background: rgba(59, 130, 246, 0.2); color: #93c5fd;
        padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.75rem;
        font-weight: 600; margin-top: 1rem; border: 1px solid rgba(59, 130, 246, 0.3);
    }
    
    /* Section Title */
    .section-title {
        font-size: 1.25rem; font-weight: 600; color: #1e293b; margin-bottom: 1rem;
        display: flex; align-items: center; gap: 0.5rem;
    }
    .section-title::before {
        content: ''; width: 4px; height: 24px;
        background: linear-gradient(180deg, #3b82f6 0%, #8b5cf6 100%); border-radius: 2px;
    }
    
    /* Source Box */
    .source-box {
        background: linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%);
        border-left: 4px solid #3b82f6; padding: 1rem 1.25rem;
        margin-top: 1rem; border-radius: 0 12px 12px 0; font-size: 0.9rem;
    }
    .source-box strong { color: #1e40af; }
    
    /* Status */
    .status-ready {
        background: linear-gradient(135deg, #052e16 0%, #14532d 100%);
        border: 1px solid #22c55e; color: #86efac !important;
        padding: 0.75rem 1rem; border-radius: 10px; font-size: 0.85rem;
        margin-bottom: 0.5rem;
    }
    .status-waiting {
        background: linear-gradient(135deg, #422006 0%, #713f12 100%);
        border: 1px solid #f59e0b; color: #fcd34d !important;
        padding: 0.75rem 1rem; border-radius: 10px; font-size: 0.85rem;
    }
    
    /* Document List */
    .doc-item {
        background: rgba(59, 130, 246, 0.1); border: 1px solid #3b82f6;
        padding: 0.5rem 0.75rem; border-radius: 8px; margin-bottom: 0.5rem;
        font-size: 0.8rem; display: flex; justify-content: space-between; align-items: center;
    }
    .doc-count {
        background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
        color: white; padding: 0.25rem 0.5rem; border-radius: 6px;
        font-size: 0.7rem; font-weight: 600;
    }
    
    /* Info Box */
    .info-box {
        background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
        border: 1px solid #93c5fd; color: #1e40af;
        padding: 1.5rem; border-radius: 12px; line-height: 1.6;
    }
    
    /* Chat */
    [data-testid="stChatMessage"] {
        background: white; border-radius: 12px; border: 1px solid #e2e8f0;
        padding: 1rem; margin-bottom: 0.75rem;
    }
    
    /* Footer */
    .footer {
        text-align: center; padding: 1.5rem; color: #64748b;
        font-size: 0.85rem; margin-top: 2rem; border-top: 1px solid #e2e8f0;
    }
    .footer a { color: #3b82f6; text-decoration: none; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "index" not in st.session_state:
        st.session_state.index = None
    if "all_documents" not in st.session_state:
        st.session_state.all_documents = []  # List of all parsed documents
    if "uploaded_files" not in st.session_state:
        st.session_state.uploaded_files = {}  # Dict: filename -> page_count
    if "qdrant_client" not in st.session_state:
        st.session_state.qdrant_client = None
    if "is_ready" not in st.session_state:
        st.session_state.is_ready = False

# ══════════════════════════════════════════════════════════════════════════════
# API KEYS
# ══════════════════════════════════════════════════════════════════════════════
def get_api_keys():
    llama_key = None
    openai_key = None
    try:
        if hasattr(st, 'secrets'):
            llama_key = st.secrets.get("LLAMA_CLOUD_API_KEY", None)
            openai_key = st.secrets.get("OPENAI_API_KEY", None)
    except:
        pass
    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# PDF PARSING
# ══════════════════════════════════════════════════════════════════════════════
def parse_pdf_with_llamaparse(pdf_path: str, filename: str, llama_api_key: str) -> Optional[List[Document]]:
    try:
        parser = LlamaParse(
            api_key=llama_api_key,
            result_type="markdown",
            num_workers=1,
            verbose=True,
            language="de",
            parsing_instruction="""
            Dies ist ein technisches Wartungshandbuch aus dem Maschinenbau.
            Extrahiere alle Tabellen präzise mit korrekten Spalten und Werten.
            Achte besonders auf Drehmomentangaben, Maßangaben, Teilenummern.
            """
        )
        documents = parser.load_data(pdf_path)
        for i, doc in enumerate(documents):
            if not doc.metadata:
                doc.metadata = {}
            doc.metadata["page_number"] = i + 1
            doc.metadata["source_file"] = filename  # Store original filename
        return documents
    except Exception as e:
        st.error(f"❌ Fehler beim Parsing von {filename}: {str(e)}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# VECTOR INDEX
# ══════════════════════════════════════════════════════════════════════════════
def create_or_update_index(documents: List[Document], openai_api_key: str) -> Optional[VectorStoreIndex]:
    try:
        llm = OpenAI(model="gpt-4o", api_key=openai_api_key, temperature=0.1)
        embed_model = OpenAIEmbedding(model="text-embedding-3-small", api_key=openai_api_key)
        Settings.llm = llm
        Settings.embed_model = embed_model
        Settings.chunk_size = 1024
        Settings.chunk_overlap = 100
        
        # Create new client if not exists
        if st.session_state.qdrant_client is None:
            st.session_state.qdrant_client = QdrantClient(":memory:")
        
        client = st.session_state.qdrant_client
        collection_name = "service_knowledge"
        
        # Delete existing collection if exists
        collections = client.get_collections().collections
        if any(c.name == collection_name for c in collections):
            client.delete_collection(collection_name)
        
        # Create new collection
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        
        vector_store = QdrantVectorStore(client=client, collection_name=collection_name)
        node_parser = MarkdownNodeParser()
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        # Index ALL documents
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            node_parser=node_parser,
            show_progress=True
        )
        return index
    except Exception as e:
        st.error(f"❌ Fehler bei der Index-Erstellung: {str(e)}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# QUERY
# ══════════════════════════════════════════════════════════════════════════════
def query_knowledge_base(index: VectorStoreIndex, question: str) -> Tuple[str, List[str]]:
    try:
        query_engine = index.as_query_engine(similarity_top_k=5, response_mode="compact")
        SYSTEM_PROMPT = """
Du bist ein technischer Assistent für Wartungshandbücher im deutschen Maschinenbau.

STRIKTE REGELN:
1. Antworte NUR basierend auf den bereitgestellten Dokumentauszügen.
2. Wenn die Information NICHT enthalten ist, sage: "Diese Information ist in den hochgeladenen Dokumenten nicht enthalten."
3. Erfinde NIEMALS Informationen.
4. Gib IMMER die Quelle an (Dateiname und Seitenzahl).
5. Antworte auf Deutsch in professionellem, technischem Stil.
6. Wenn mehrere Dokumente relevant sind, vergleiche die Informationen.
"""
        full_query = f"{SYSTEM_PROMPT}\n\nFrage: {question}"
        response = query_engine.query(full_query)
        
        sources = []
        if response.source_nodes:
            seen = set()
            for node in response.source_nodes:
                filename = node.metadata.get("source_file", "Unbekannt")
                page_num = node.metadata.get("page_number", "?")
                source_str = f"{filename} (S. {page_num})"
                if source_str not in seen:
                    sources.append(source_str)
                    seen.add(source_str)
        return str(response), sources
    except Exception as e:
        return f"❌ Fehler: {str(e)}", []

# ══════════════════════════════════════════════════════════════════════════════
# PROCESS SINGLE PDF
# ══════════════════════════════════════════════════════════════════════════════
def process_single_pdf(uploaded_file, llama_key: str, openai_key: str) -> bool:
    """Process a single PDF and add to document collection"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        documents = parse_pdf_with_llamaparse(tmp_path, uploaded_file.name, llama_key)
        os.unlink(tmp_path)
        
        if documents is None:
            return False
        
        # Add to session state
        st.session_state.all_documents.extend(documents)
        st.session_state.uploaded_files[uploaded_file.name] = len(documents)
        
        return True
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# REBUILD INDEX
# ══════════════════════════════════════════════════════════════════════════════
def rebuild_index(openai_key: str):
    """Rebuild the entire index from all documents"""
    if not st.session_state.all_documents:
        st.warning("Keine Dokumente vorhanden.")
        return
    
    with st.spinner("🧠 Index wird neu aufgebaut..."):
        index = create_or_update_index(st.session_state.all_documents, openai_key)
        if index:
            st.session_state.index = index
            st.session_state.is_ready = True
            st.success("✅ Index aktualisiert!")

# ══════════════════════════════════════════════════════════════════════════════
# REMOVE DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════
def remove_document(filename: str, openai_key: str):
    """Remove a document and rebuild index"""
    # Remove from documents list
    st.session_state.all_documents = [
        doc for doc in st.session_state.all_documents 
        if doc.metadata.get("source_file") != filename
    ]
    # Remove from uploaded files dict
    if filename in st.session_state.uploaded_files:
        del st.session_state.uploaded_files[filename]
    
    # Rebuild index if documents remain
    if st.session_state.all_documents:
        rebuild_index(openai_key)
    else:
        st.session_state.index = None
        st.session_state.is_ready = False

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div class="logo-container">
            <div class="logo-text">SBS Deutschland</div>
            <div class="logo-subtext">Service Knowledge OS</div>
        </div>
        """, unsafe_allow_html=True)
        
        secret_llama_key, secret_openai_key = get_api_keys()
        
        st.markdown("#### 🔑 API-Konfiguration")
        
        if secret_llama_key:
            st.markdown('<div class="status-ready">✓ LlamaCloud verbunden</div>', unsafe_allow_html=True)
            llama_key = secret_llama_key
        else:
            st.markdown("**LlamaCloud API Key**")
            st.markdown('<small><a href="https://cloud.llamaindex.ai/" target="_blank">→ Key erstellen</a></small>', unsafe_allow_html=True)
            llama_key = st.text_input("LlamaCloud", type="password", placeholder="llx-...", label_visibility="collapsed")
        
        st.markdown("")
        
        if secret_openai_key:
            st.markdown('<div class="status-ready">✓ OpenAI verbunden</div>', unsafe_allow_html=True)
            openai_key = secret_openai_key
        else:
            st.markdown("**OpenAI API Key**")
            st.markdown('<small><a href="https://platform.openai.com/api-keys" target="_blank">→ Key erstellen</a></small>', unsafe_allow_html=True)
            openai_key = st.text_input("OpenAI", type="password", placeholder="sk-...", label_visibility="collapsed")
        
        st.markdown("---")
        
        # ═══════════════════════════════════════════════════════════════════
        # MULTI-PDF UPLOAD SECTION
        # ═══════════════════════════════════════════════════════════════════
        st.markdown("#### 📚 Dokumente verwalten")
        
        # Show uploaded documents
        if st.session_state.uploaded_files:
            st.markdown(f"**{len(st.session_state.uploaded_files)} Dokument(e) geladen:**")
            for filename, pages in st.session_state.uploaded_files.items():
                col1, col2 = st.columns([4, 1])
                with col1:
                    short_name = filename[:20] + "..." if len(filename) > 20 else filename
                    st.markdown(f'<div class="doc-item"><span>📄 {short_name}</span><span class="doc-count">{pages} S.</span></div>', unsafe_allow_html=True)
                with col2:
                    if st.button("🗑️", key=f"del_{filename}", help=f"Entferne {filename}"):
                        remove_document(filename, openai_key)
                        st.rerun()
            st.markdown("")
        
        # Upload new document
        st.markdown("**Neues Dokument hinzufügen:**")
        uploaded_file = st.file_uploader(
            "PDF hochladen",
            type=["pdf"],
            label_visibility="collapsed",
            key="pdf_uploader"
        )
        
        if uploaded_file is not None:
            # Check if already uploaded
            if uploaded_file.name in st.session_state.uploaded_files:
                st.warning(f"📎 {uploaded_file.name} ist bereits geladen.")
            elif not llama_key or len(llama_key) < 10:
                st.warning("⚠️ LlamaCloud Key fehlt")
            elif not openai_key or len(openai_key) < 10:
                st.warning("⚠️ OpenAI Key fehlt")
            else:
                if st.button("➕ Dokument hinzufügen", type="primary", use_container_width=True):
                    with st.spinner(f"📥 Verarbeite {uploaded_file.name}..."):
                        success = process_single_pdf(uploaded_file, llama_key, openai_key)
                        if success:
                            st.success(f"✅ {uploaded_file.name} hinzugefügt!")
                            rebuild_index(openai_key)
                            st.rerun()
        
        st.markdown("---")
        
        # Status
        st.markdown("#### 📊 Status")
        if st.session_state.is_ready and st.session_state.index:
            total_pages = sum(st.session_state.uploaded_files.values())
            doc_count = len(st.session_state.uploaded_files)
            st.markdown(f'<div class="status-ready">✓ Bereit: {doc_count} Dok. / {total_pages} Seiten</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-waiting">○ Warte auf Dokument</div>', unsafe_allow_html=True)
        
        st.markdown("")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Chat leeren", use_container_width=True):
                st.session_state.messages = []
                st.rerun()
        with col2:
            if st.button("🗑️ Alle löschen", use_container_width=True):
                st.session_state.all_documents = []
                st.session_state.uploaded_files = {}
                st.session_state.index = None
                st.session_state.is_ready = False
                st.session_state.messages = []
                st.rerun()
        
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; padding: 0.5rem 0;">
            <small style="color: #64748b;">
                <a href="https://sbsdeutschland.com" target="_blank" style="color: #60a5fa;">
                    sbsdeutschland.com
                </a>
            </small>
        </div>
        """, unsafe_allow_html=True)
    
    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
def render_header():
    st.markdown("""
    <div class="main-header">
        <h1>🔧 Service Knowledge OS</h1>
        <p>Intelligente Suche in technischen Handbüchern | RAG-System für den Maschinenbau</p>
        <span class="header-badge">✨ Multi-PDF Support · GPT-4o · LlamaParse</span>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHAT
# ══════════════════════════════════════════════════════════════════════════════
def render_chat_interface():
    st.markdown('<div class="section-title">Technische Anfrage</div>', unsafe_allow_html=True)
    
    if not st.session_state.is_ready or not st.session_state.index:
        st.markdown("""
        <div class="info-box">
            <strong>👋 Willkommen beim Service Knowledge OS!</strong><br><br>
            Laden Sie ein oder mehrere technische Handbücher (PDF) in der Sidebar hoch.
            <br><br>
            <strong>Neu in v3.0:</strong> Multi-PDF Support!
            <ul style="margin: 0.5rem 0 0 0; padding-left: 1.25rem;">
                <li>Mehrere Handbücher gleichzeitig durchsuchen</li>
                <li>Quellenangabe mit Dateiname und Seite</li>
                <li>Dokumente einzeln hinzufügen/entfernen</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Show which documents are searchable
    doc_names = list(st.session_state.uploaded_files.keys())
    if doc_names:
        with st.expander(f"📚 Durchsuche {len(doc_names)} Dokument(e)", expanded=False):
            for name in doc_names:
                pages = st.session_state.uploaded_files[name]
                st.markdown(f"- **{name}** ({pages} Seiten)")
    
    # Chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar="👤" if message["role"] == "user" else "🤖"):
            st.markdown(message["content"])
            if "sources" in message and message["sources"]:
                sources_text = " · ".join(message["sources"])
                st.markdown(f'<div class="source-box"><strong>📚 Quellen:</strong> {sources_text}</div>', unsafe_allow_html=True)
    
    # Input
    if prompt := st.chat_input("Ihre technische Frage..."):
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("🔍 Durchsuche alle Dokumente..."):
                response, sources = query_knowledge_base(st.session_state.index, prompt)
            st.markdown(response)
            if sources:
                sources_text = " · ".join(sources)
                st.markdown(f'<div class="source-box"><strong>📚 Quellen:</strong> {sources_text}</div>', unsafe_allow_html=True)
        
        st.session_state.messages.append({"role": "assistant", "content": response, "sources": sources})

# ══════════════════════════════════════════════════════════════════════════════
# TIPS
# ══════════════════════════════════════════════════════════════════════════════
def render_tips():
    with st.expander("💡 Tipps für bessere Ergebnisse", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **So stellen Sie gute Fragen:**
            - Spezifisch und präzise formulieren
            - Nach konkreten Werten fragen
            - Bei mehreren Dokumenten: Vergleiche anfragen
            """)
        with col2:
            st.markdown("""
            **Beispiele:**
            - "Welches Drehmoment für M10?"
            - "Vergleiche die Wartungsintervalle"
            - "Welches Dokument hat Infos zu Öl?"
            """)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    init_session_state()
    
    if not IMPORTS_AVAILABLE:
        st.error(f"⚠️ Fehlende Abhängigkeiten: {IMPORT_ERROR}")
        st.info("Bitte führen Sie `pip install -r requirements.txt` aus.")
        return
    
    render_header()
    llama_key, openai_key = render_sidebar()
    render_chat_interface()
    render_tips()
    
    st.markdown("""
    <div class="footer">
        © 2025 <a href="https://sbsdeutschland.com" target="_blank">SBS Deutschland GmbH</a> · 
        <a href="https://github.com/Luyzz22/sbs-service-knowledge-os" target="_blank">GitHub</a> ·
        v3.0 Multi-PDF
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
