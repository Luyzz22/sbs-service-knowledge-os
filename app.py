"""
================================================================================
HYDRAULIKDOC AI - Enterprise Edition v2.0
================================================================================
KI-gestützte Suche in Hydraulik-Dokumentation
by SBS Deutschland GmbH

CHANGELOG v2.0 (Project Hephaestus):
- 🎥 Multimodal: Video + Audio + PDF Analyse mit Gemini 1.5 Pro
- 🔊 Audio-Anomalie Erkennung für Maschinendignose
- 📊 Tab-basierte UI: Dokument-Suche & Video-Diagnose
- ⚡ Enterprise-grade System Prompts (v1.1)
================================================================================
"""

import streamlit as st
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Tuple, Dict
import hashlib

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
# GEMINI VIDEO ANALYZER (Project Hephaestus)
# ══════════════════════════════════════════════════════════════════════════════
try:
    from streamlit_integration import render_video_analyzer_tab
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="HydraulikDoc AI | Technische Dokumentation durchsuchen",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════
def get_users_from_secrets():
    try:
        if hasattr(st, 'secrets') and 'users' in st.secrets:
            return dict(st.secrets['users'])
    except:
        pass
    return {
        "admin": {
            "name": "Administrator",
            "password": "0192023a7bbd73250516f069df18b500",
            "role": "admin"
        },
        "demo": {
            "name": "Demo Benutzer",
            "password": "62cc2d8b4bf2d8728120d052163a77df",
            "role": "demo"
        }
    }

def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def check_login(username: str, password: str) -> Tuple[bool, Optional[Dict]]:
    users = get_users_from_secrets()
    if username in users:
        user = users[username]
        if verify_password(password, user['password']):
            return True, {"username": username, "name": user['name'], "role": user['role']}
    return False, None

def render_login_page():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        
        .stApp {
            background: linear-gradient(135deg, #003366 0%, #0066B3 100%);
        }
        
        .login-container {
            max-width: 420px;
            margin: 3rem auto;
            padding: 2.5rem;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .login-logo {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, #FF8C00 0%, #E67E00 100%);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            margin: 0 auto 1rem;
            box-shadow: 0 8px 20px rgba(255, 140, 0, 0.3);
        }
        
        .login-title {
            font-size: 1.6rem;
            font-weight: 700;
            color: #0066B3;
            margin-bottom: 0.25rem;
        }
        
        .login-subtitle {
            color: #64748b;
            font-size: 0.9rem;
        }
        
        .demo-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 1.25rem;
            margin-top: 1.5rem;
        }
        
        .demo-box strong {
            color: #0066B3;
            font-size: 0.9rem;
        }
        
        .demo-box code {
            background: #e2e8f0;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85rem;
        }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-header">
            <div class="login-logo">🔧</div>
            <div class="login-title">HydraulikDoc AI</div>
            <div class="login-subtitle">Technische Dokumentation durchsuchen</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### Anmelden")
        
        username = st.text_input("Benutzername", placeholder="Ihr Benutzername")
        password = st.text_input("Passwort", type="password", placeholder="Ihr Passwort")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            login_clicked = st.button("🔐 Anmelden", type="primary", use_container_width=True)
        with col_btn2:
            demo_clicked = st.button("🎮 Demo", use_container_width=True)
        
        if demo_clicked:
            username, password = "demo", "demo123"
            login_clicked = True
        
        if login_clicked:
            if username and password:
                success, user_data = check_login(username, password)
                if success:
                    st.session_state.authenticated = True
                    st.session_state.user = user_data
                    st.success(f"✅ Willkommen, {user_data['name']}!")
                    st.rerun()
                else:
                    st.error("❌ Ungültige Anmeldedaten")
            else:
                st.warning("⚠️ Bitte alle Felder ausfüllen")
        
        st.markdown("""
        <div class="demo-box">
            <strong>Demo-Zugang:</strong><br>
            Benutzer: <code>demo</code> · Passwort: <code>demo123</code>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; color: #94a3b8; font-size: 0.8rem;">
            © 2025 SBS Deutschland GmbH<br>
            <a href="https://sbsdeutschland.com" style="color: #0066B3;">sbsdeutschland.com</a>
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS - HYDRAULIK BRANDING
# ══════════════════════════════════════════════════════════════════════════════
def inject_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        
        * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
        
        .stApp { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
        
        /* Sidebar - Hydraulik Blue */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #003366 0%, #004C8C 100%);
            border-right: 1px solid #0066B3;
        }
        [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
        [data-testid="stSidebar"] .stMarkdown a { color: #FF8C00 !important; }
        [data-testid="stSidebar"] hr { border-color: #0066B3; margin: 1.5rem 0; }
        [data-testid="stSidebar"] .stTextInput > div > div {
            background-color: #004C8C; border: 1px solid #0066B3; border-radius: 8px;
        }
        [data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(135deg, #FF8C00 0%, #E67E00 100%);
            color: #003366 !important; border: none; border-radius: 8px;
            padding: 0.6rem 1.2rem; font-weight: 600;
            box-shadow: 0 4px 12px rgba(255, 140, 0, 0.3);
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: linear-gradient(135deg, #E67E00 0%, #CC7000 100%);
            transform: translateY(-1px);
        }
        
        /* Logo */
        .logo-container {
            text-align: center; padding: 1.5rem 0; margin-bottom: 1rem;
            border-bottom: 1px solid #0066B3;
        }
        .logo-icon {
            width: 56px; height: 56px;
            background: linear-gradient(135deg, #FF8C00 0%, #E67E00 100%);
            border-radius: 14px; margin: 0 auto 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.8rem;
            box-shadow: 0 6px 16px rgba(255, 140, 0, 0.3);
        }
        .logo-text {
            font-size: 1.4rem; font-weight: 700; color: #ffffff !important;
        }
        .logo-subtext {
            font-size: 0.72rem; color: #94a3b8 !important;
            text-transform: uppercase; letter-spacing: 2px; margin-top: 0.25rem;
        }
        
        /* User Badge */
        .user-badge {
            background: linear-gradient(135deg, #004C8C 0%, #003366 100%);
            border: 1px solid #0066B3;
            padding: 0.75rem 1rem; border-radius: 10px; margin-bottom: 1rem;
            display: flex; align-items: center; gap: 0.75rem;
        }
        .user-avatar {
            width: 36px; height: 36px;
            background: linear-gradient(135deg, #FF8C00 0%, #E67E00 100%);
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 1rem; color: #003366;
        }
        .user-name { font-weight: 600; font-size: 0.95rem; }
        .user-role { font-size: 0.7rem; color: #94a3b8 !important; text-transform: uppercase; }
        
        /* Header */
        .main-header {
            background: linear-gradient(135deg, #003366 0%, #0066B3 50%, #004C8C 100%);
            color: white; padding: 2.5rem 3rem; border-radius: 16px; margin-bottom: 2rem;
            box-shadow: 0 20px 40px rgba(0, 51, 102, 0.2);
            position: relative; overflow: hidden;
        }
        .main-header::before {
            content: ''; position: absolute; top: -50%; right: -20%;
            width: 60%; height: 200%;
            background: radial-gradient(circle, rgba(255,140,0,0.1) 0%, transparent 60%);
        }
        .main-header h1 { margin: 0; font-size: 2rem; font-weight: 700; position: relative; }
        .main-header p { margin: 0.75rem 0 0 0; opacity: 0.9; position: relative; }
        .header-badge {
            display: inline-block; background: rgba(255, 140, 0, 0.2); color: #FF8C00;
            padding: 0.35rem 0.85rem; border-radius: 20px; font-size: 0.75rem;
            font-weight: 600; margin-top: 1rem; border: 1px solid rgba(255, 140, 0, 0.3);
            position: relative;
        }
        
        /* Section Title */
        .section-title {
            font-size: 1.25rem; font-weight: 600; color: #1e293b; margin-bottom: 1rem;
            display: flex; align-items: center; gap: 0.5rem;
        }
        .section-title::before {
            content: ''; width: 4px; height: 24px;
            background: linear-gradient(180deg, #0066B3 0%, #FF8C00 100%); border-radius: 2px;
        }
        
        /* Source Box */
        .source-box {
            background: linear-gradient(135deg, #eff6ff 0%, #f0f9ff 100%);
            border-left: 4px solid #0066B3; padding: 1rem 1.25rem;
            margin-top: 1rem; border-radius: 0 12px 12px 0; font-size: 0.9rem;
        }
        .source-box strong { color: #003366; }
        
        /* Status */
        .status-ready {
            background: linear-gradient(135deg, #052e16 0%, #14532d 100%);
            border: 1px solid #22c55e; color: #86efac !important;
            padding: 0.75rem 1rem; border-radius: 10px; font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }
        .status-waiting {
            background: linear-gradient(135deg, #7c2d12 0%, #9a3412 100%);
            border: 1px solid #FF8C00; color: #fed7aa !important;
            padding: 0.75rem 1rem; border-radius: 10px; font-size: 0.85rem;
        }
        
        /* Document List */
        .doc-item {
            background: rgba(0, 102, 179, 0.15); border: 1px solid #0066B3;
            padding: 0.5rem 0.75rem; border-radius: 8px; margin-bottom: 0.5rem;
            font-size: 0.8rem; display: flex; justify-content: space-between; align-items: center;
        }
        .doc-count {
            background: linear-gradient(135deg, #0066B3 0%, #004C8C 100%);
            color: white; padding: 0.25rem 0.5rem; border-radius: 6px;
            font-size: 0.7rem; font-weight: 600;
        }
        
        /* Info Box */
        .info-box {
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
            border: 1px solid #0066B3; color: #003366;
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
        .footer a { color: #0066B3; text-decoration: none; }
        
        /* Hydraulik-specific styling */
        .hydraulik-tip {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border: 1px solid #f59e0b;
            border-radius: 10px; padding: 1rem; margin-top: 1rem;
            font-size: 0.9rem; color: #92400e;
        }
        .hydraulik-tip strong { color: #78350f; }
    </style>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
def init_session_state():
    defaults = {
        "authenticated": False,
        "user": None,
        "messages": [],
        "index": None,
        "all_documents": [],
        "uploaded_files": {},
        "qdrant_client": None,
        "is_ready": False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ══════════════════════════════════════════════════════════════════════════════
# API KEYS
# ══════════════════════════════════════════════════════════════════════════════
def get_api_keys():
    llama_key, openai_key = None, None
    try:
        if hasattr(st, 'secrets'):
            llama_key = st.secrets.get("LLAMA_CLOUD_API_KEY")
            openai_key = st.secrets.get("OPENAI_API_KEY")
    except:
        pass
    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# PDF PARSING - HYDRAULIK OPTIMIZED
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
            Dies ist ein technisches Dokument aus der Hydraulik-/Fluidtechnik-Branche.
            
            WICHTIG - Extrahiere präzise:
            1. Alle Tabellen mit Druckwerten (bar, MPa, psi)
            2. Volumenstrom-Angaben (l/min, m³/h)
            3. Drehmomentangaben (Nm)
            4. Temperaturangaben (°C)
            5. Teilenummern und Ersatzteilreferenzen
            6. Wartungsintervalle
            7. Ölspezifikationen und -mengen
            8. Schaltplan-Beschreibungen
            
            Achte besonders auf:
            - Maximaldruck / Betriebsdruck / Prüfdruck
            - Nennweiten (DN) und Anschlussgrößen
            - Hydraulikflüssigkeits-Spezifikationen
            """
        )
        documents = parser.load_data(pdf_path)
        for i, doc in enumerate(documents):
            if not doc.metadata:
                doc.metadata = {}
            doc.metadata["page_number"] = i + 1
            doc.metadata["source_file"] = filename
            doc.metadata["uploaded_by"] = st.session_state.user.get("username", "unknown")
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
        Settings.chunk_size = 1536  # Larger chunks for better context
        Settings.chunk_overlap = 200  # More overlap to preserve context across chunks
        
        if st.session_state.qdrant_client is None:
            st.session_state.qdrant_client = QdrantClient(":memory:")
        
        client = st.session_state.qdrant_client
        collection_name = "hydraulik_docs"
        
        collections = client.get_collections().collections
        if any(c.name == collection_name for c in collections):
            client.delete_collection(collection_name)
        
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        
        vector_store = QdrantVectorStore(client=client, collection_name=collection_name)
        node_parser = MarkdownNodeParser()
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
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
# QUERY - HYDRAULIK OPTIMIZED
# ══════════════════════════════════════════════════════════════════════════════
def query_knowledge_base(index: VectorStoreIndex, question: str) -> Tuple[str, List[str]]:
    try:
        query_engine = index.as_query_engine(similarity_top_k=8, response_mode="tree_summarize")
        
        HYDRAULIK_SYSTEM_PROMPT = """
Du bist ein erfahrener Hydraulik-Ingenieur und technischer Dokumentationsspezialist.
Deine Aufgabe: Beantworte Fragen basierend auf den bereitgestellten Dokumentauszügen.

═══════════════════════════════════════════════════════════════════
WICHTIG - ANTWORTSTRATEGIE:
═══════════════════════════════════════════════════════════════════

1. IMMER ANTWORTEN wenn relevante Informationen in den Dokumenten sind:
   - Auch wenn die Frage anders formuliert ist als im Dokument
   - Auch wenn nur TEILE der Frage beantwortet werden können
   - Auch wenn du die Antwort aus mehreren Stellen zusammensetzen musst

2. SYNONYME & ALTERNATIVE BEGRIFFE verstehen:
   - "Nenndruck" = "maximaler Betriebsdruck" = "max. Druck" = "Arbeitsdruck"
   - "Hubgeschwindigkeit" = "Kolbengeschwindigkeit" = "Zylindergeschwindigkeit" = "v max"
   - "Zylinder" = "Hydraulikzylinder" = "Arbeitszylinder"
   - "Öl" = "Hydraulikflüssigkeit" = "Medium" = "Betriebsmedium"
   - "CDH2" / "CGH2" / "CSH2" = Baureihen-Bezeichnungen

3. TECHNISCHE WERTE EXTRAHIEREN:
   - Suche nach Zahlen mit Einheiten (bar, MPa, mm, °C, l/min, m/s)
   - Tabellenwerte sind besonders wichtig
   - Nennwerte, Maximalwerte, Grenzwerte identifizieren

4. NUR "NICHT ENTHALTEN" SAGEN wenn:
   - KEINE relevanten Informationen in den Dokumenten sind
   - Die Frage ein komplett anderes Thema betrifft
   - NICHT weil die exakte Formulierung fehlt!

═══════════════════════════════════════════════════════════════════
ANTWORT-FORMAT:
═══════════════════════════════════════════════════════════════════

- Beginne DIREKT mit der Antwort (keine Einleitung wie "Basierend auf...")
- Technische Werte FETT markieren: **250 bar**
- Einheiten IMMER angeben
- Bei mehreren Werten: Aufzählung oder Tabelle
- Am Ende: Quelle nennen (Dokument, Seite)
- Sprache: Deutsch, professionell, präzise

═══════════════════════════════════════════════════════════════════
BEISPIELE:
═══════════════════════════════════════════════════════════════════

Frage: "Welcher Nenndruck für CDH2?"
RICHTIG: "Der Nenndruck für die Baureihe CDH2 beträgt **250 bar**. (Quelle: Datenblatt S. 2)"
FALSCH: "Diese Information ist nicht enthalten." (obwohl "max. Betriebsdruck 250 bar" im Dokument steht)

Frage: "Hubgeschwindigkeit?"
RICHTIG: "Die maximale Hubgeschwindigkeit hängt vom Kolbendurchmesser ab und liegt typischerweise bei **0,5 m/s**. Siehe Tabelle auf S. 4."
FALSCH: "Diese Information ist nicht enthalten." (obwohl Geschwindigkeitswerte in Tabellen stehen)

═══════════════════════════════════════════════════════════════════
SICHERHEITSREGEL:
═══════════════════════════════════════════════════════════════════

- ERFINDE niemals Werte die nicht im Dokument stehen
- Bei Unsicherheit: "Laut Dokument..." oder "Die verfügbaren Daten zeigen..."
- Wenn mehrere Werte möglich: Alle nennen mit Kontext
"""
        full_query = f"{HYDRAULIK_SYSTEM_PROMPT}\n\nFrage des Technikers: {question}\n\nAntworte präzise und hilfreich:"
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
# PROCESS PDF
# ══════════════════════════════════════════════════════════════════════════════
def process_single_pdf(uploaded_file, llama_key: str, openai_key: str) -> bool:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        documents = parse_pdf_with_llamaparse(tmp_path, uploaded_file.name, llama_key)
        os.unlink(tmp_path)
        
        if documents is None:
            return False
        
        st.session_state.all_documents.extend(documents)
        st.session_state.uploaded_files[uploaded_file.name] = len(documents)
        
        return True
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")
        return False

def rebuild_index(openai_key: str):
    if not st.session_state.all_documents:
        st.warning("Keine Dokumente vorhanden.")
        return
    
    with st.spinner("🧠 Index wird aufgebaut..."):
        index = create_or_update_index(st.session_state.all_documents, openai_key)
        if index:
            st.session_state.index = index
            st.session_state.is_ready = True
            st.success("✅ Dokumente bereit!")

def remove_document(filename: str, openai_key: str):
    st.session_state.all_documents = [
        doc for doc in st.session_state.all_documents 
        if doc.metadata.get("source_file") != filename
    ]
    if filename in st.session_state.uploaded_files:
        del st.session_state.uploaded_files[filename]
    
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
            <div class="logo-icon">🔧</div>
            <div class="logo-text">HydraulikDoc AI</div>
            <div class="logo-subtext">by SBS Deutschland</div>
        </div>
        """, unsafe_allow_html=True)
        
        # User Info
        user = st.session_state.user
        initial = user['name'][0].upper()
        role_map = {"admin": "Administrator", "user": "Benutzer", "demo": "Demo"}
        
        st.markdown(f"""
        <div class="user-badge">
            <div class="user-avatar">{initial}</div>
            <div>
                <div class="user-name">{user['name']}</div>
                <div class="user-role">{role_map.get(user['role'], user['role'])}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚪 Abmelden", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        st.markdown("---")
        
        secret_llama_key, secret_openai_key = get_api_keys()
        
        st.markdown("#### 🔑 API-Status")
        
        if secret_llama_key:
            st.markdown('<div class="status-ready">✓ LlamaCloud verbunden</div>', unsafe_allow_html=True)
            llama_key = secret_llama_key
        else:
            llama_key = st.text_input("LlamaCloud Key", type="password", placeholder="llx-...")
        
        if secret_openai_key:
            st.markdown('<div class="status-ready">✓ OpenAI verbunden</div>', unsafe_allow_html=True)
            openai_key = secret_openai_key
        else:
            openai_key = st.text_input("OpenAI Key", type="password", placeholder="sk-...")
        
        st.markdown("---")
        
        # Documents
        st.markdown("#### 📚 Hydraulik-Dokumente")
        
        if st.session_state.uploaded_files:
            for filename, pages in st.session_state.uploaded_files.items():
                col1, col2 = st.columns([4, 1])
                with col1:
                    short = filename[:18] + "..." if len(filename) > 18 else filename
                    st.markdown(f'<div class="doc-item"><span>📄 {short}</span><span class="doc-count">{pages} S.</span></div>', unsafe_allow_html=True)
                with col2:
                    if user['role'] in ['admin', 'user']:
                        if st.button("🗑️", key=f"del_{filename}"):
                            remove_document(filename, openai_key)
                            st.rerun()
        
        uploaded_file = st.file_uploader("PDF hochladen", type=["pdf"], label_visibility="collapsed")
        
        if uploaded_file is not None:
            if uploaded_file.name in st.session_state.uploaded_files:
                st.warning("📎 Bereits geladen")
            elif not llama_key or not openai_key:
                st.warning("⚠️ API Keys fehlen")
            else:
                if st.button("➕ Dokument hinzufügen", type="primary", use_container_width=True):
                    with st.spinner(f"📥 Verarbeite..."):
                        if process_single_pdf(uploaded_file, llama_key, openai_key):
                            rebuild_index(openai_key)
                            st.rerun()
        
        st.markdown("---")
        
        # Status
        st.markdown("#### 📊 Status")
        if st.session_state.is_ready:
            total = sum(st.session_state.uploaded_files.values())
            count = len(st.session_state.uploaded_files)
            st.markdown(f'<div class="status-ready">✓ Bereit: {count} Dok. / {total} Seiten</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-waiting">○ Warte auf Dokument</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()
        with col2:
            if user['role'] == 'admin':
                if st.button("🗑️ Reset", use_container_width=True):
                    st.session_state.all_documents = []
                    st.session_state.uploaded_files = {}
                    st.session_state.index = None
                    st.session_state.is_ready = False
                    st.session_state.messages = []
                    st.rerun()
        
        st.markdown("---")
        st.markdown('<div style="text-align:center;"><small><a href="https://sbsdeutschland.com" style="color:#FF8C00;">sbsdeutschland.com</a></small></div>', unsafe_allow_html=True)
    
    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
def render_header():
    st.markdown("""
    <div class="main-header">
        <h1>🔧 HydraulikDoc AI</h1>
        <p>KI-gestützte Suche in Ihrer Hydraulik-Dokumentation</p>
        <span class="header-badge">✨ Druckwerte · Schaltpläne · Ersatzteile</span>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHAT
# ══════════════════════════════════════════════════════════════════════════════
def render_chat_interface():
    st.markdown('<div class="section-title">Technische Anfrage</div>', unsafe_allow_html=True)
    
    if not st.session_state.is_ready:
        st.markdown("""
        <div class="info-box">
            <strong>👋 Willkommen bei HydraulikDoc AI!</strong><br><br>
            Laden Sie Ihre Hydraulik-Dokumentation in der Sidebar hoch:
            <ul style="margin: 0.5rem 0 0 1rem;">
                <li>Handbücher & Datenblätter</li>
                <li>Wartungsanleitungen</li>
                <li>Schaltpläne & Zeichnungen</li>
                <li>Ersatzteilkataloge</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class="hydraulik-tip">
            <strong>💡 Tipp:</strong> Die KI erkennt automatisch Druckwerte, Volumenstrom-Angaben 
            und Drehmomente in Tabellen. Fragen Sie z.B. "Welcher Systemdruck für Zylinder XY?"
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Document overview
    if st.session_state.uploaded_files:
        with st.expander(f"📚 {len(st.session_state.uploaded_files)} Dokument(e) durchsuchbar", expanded=False):
            for name, pages in st.session_state.uploaded_files.items():
                st.markdown(f"- **{name}** ({pages} Seiten)")
    
    # Example queries
    with st.expander("💡 Beispiel-Fragen für Hydraulik-Dokumentation", expanded=False):
        st.markdown("""
        - "Welcher maximale Systemdruck für die HY-500 Pumpe?"
        - "Wie oft muss das Hydrauliköl gewechselt werden?"
        - "Welches Drehmoment für die Verschraubung am Zylinder?"
        - "Welche Ersatzteile brauche ich für die Wartung?"
        - "Was sind die empfohlenen Ölspezifikationen?"
        """)
    
    # Chat
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar="👤" if message["role"] == "user" else "🔧"):
            st.markdown(message["content"])
            if "sources" in message and message["sources"]:
                sources_text = " · ".join(message["sources"])
                st.markdown(f'<div class="source-box"><strong>📄 Quellen:</strong> {sources_text}</div>', unsafe_allow_html=True)
    
    if prompt := st.chat_input("Ihre Frage zur Hydraulik-Dokumentation..."):
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant", avatar="🔧"):
            with st.spinner("🔍 Durchsuche Hydraulik-Dokumente..."):
                response, sources = query_knowledge_base(st.session_state.index, prompt)
            st.markdown(response)
            if sources:
                sources_text = " · ".join(sources)
                st.markdown(f'<div class="source-box"><strong>📄 Quellen:</strong> {sources_text}</div>', unsafe_allow_html=True)
        
        st.session_state.messages.append({"role": "assistant", "content": response, "sources": sources})

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    init_session_state()
    
    if not st.session_state.authenticated:
        render_login_page()
        return
    
    if not IMPORTS_AVAILABLE:
        st.error(f"⚠️ Fehlende Abhängigkeiten: {IMPORT_ERROR}")
        return
    
    inject_css()
    render_header()
    llama_key, openai_key = render_sidebar()
    
    # ══════════════════════════════════════════════════════════════════════════════
    # TABS: PDF Suche & Video-Diagnose
    # ══════════════════════════════════════════════════════════════════════════════
    if GEMINI_AVAILABLE:
        tab1, tab2 = st.tabs([
            "📄 Dokument-Suche",
            "🎥 Video-Diagnose (BETA)"
        ])
        
        with tab1:
            render_chat_interface()
        
        with tab2:
            render_video_analyzer_tab()
    else:
        # Fallback: Nur PDF-Suche wenn Gemini nicht verfügbar
        render_chat_interface()
    
    st.markdown("""
    <div class="footer">
        © 2025 <a href="https://sbsdeutschland.com">SBS Deutschland GmbH</a> · Weinheim · 
        <a href="https://hydraulikdoc.de">hydraulikdoc.de</a>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
