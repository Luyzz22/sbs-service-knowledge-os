"""
================================================================================
HYDRAULIKDOC AI - ENTERPRISE KNOWLEDGE OS v3.3 (Native Hybrid Edition)
================================================================================
Entwickelt für: SBS Deutschland GmbH
Architektur: LlamaIndex (BM25 + Vector Fusion) + LlamaParse + OpenAI GPT-4o
Author: Luis Schenk (Head of Digital Product)

SYSTEM STATUS:
- Core Engine:  Active (v3.3)
- Retrieval:    NATIVE HYBRID (BM25 Keyword Search + Vector Search) via QueryFusion
- Parsing:      Semantic Table Recognition enabled (Chunk Size 2048)
- Security:     Role-Based Access Control (RBAC) enabled
- Multimodal:   Project Hephaestus (Video/Audio) ready

COPYRIGHT © 2026 SBS DEUTSCHLAND GMBH. ALL RIGHTS RESERVED.
================================================================================
"""

import streamlit as st
import tempfile
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any, Union
import hashlib

# ══════════════════════════════════════════════════════════════════════════════
# ENTERPRISE LOGGING CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HydraulikDoc_Enterprise")

# ══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY MANAGEMENT
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
    from llama_index.core.retrievers import VectorIndexRetriever, QueryFusionRetriever
    from llama_index.retrievers.bm25 import BM25Retriever
    from llama_index.core.query_engine import RetrieverQueryEngine
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    IMPORTS_AVAILABLE = True
    logger.info("Core dependencies loaded successfully.")
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)
    logger.critical(f"Critical dependency failure: {e}")

# PROJECT HEPHAESTUS INTEGRATION (Video/Audio Analysis)
try:
    from streamlit_integration import render_video_analyzer_tab
    GEMINI_AVAILABLE = True
    logger.info("Project Hephaestus (Gemini Video) module loaded.")
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Project Hephaestus module not found. Video features disabled.")

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
class SystemConfig:
    """Central configuration for Enterprise Parameters."""
    APP_NAME = "HydraulikDoc AI"
    VERSION = "3.3.0-ENT"
    COMPANY = "SBS Deutschland GmbH"
    
    # Retrieval Settings (Optimized for Hybrid Search)
    RETRIEVAL_TOP_K = 15  # Increased depth for precise recall
    CHUNK_SIZE = 2048     # DOUBLED to capture full pages (fixing Page 39 issue)
    CHUNK_OVERLAP = 100   # Reduced overlap for larger chunks
    
    # Model Settings
    LLM_MODEL = "gpt-4o"
    EMBED_MODEL = "text-embedding-3-small"
    TEMPERATURE = 0.0     # Zero creativity for technical specs

st.set_page_config(
    page_title=f"{SystemConfig.APP_NAME} | {SystemConfig.VERSION}",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION LAYER (RBAC)
# ══════════════════════════════════════════════════════════════════════════════
def get_users_from_secrets() -> Dict[str, Dict[str, str]]:
    """
    Securely retrieves the user database.
    Prioritizes Streamlit Secrets, falls back to local dev defaults.
    """
    try:
        if hasattr(st, 'secrets') and 'users' in st.secrets:
            return dict(st.secrets['users'])
    except Exception as e:
        logger.error(f"Error loading secrets: {e}")
    
    # Dev Fallback
    return {
        "admin": {
            "name": "Administrator",
            "password": "0192023a7bbd73250516f069df18b500", # MD5 hash
            "role": "admin"
        },
        "demo": {
            "name": "Demo Benutzer",
            "password": "62cc2d8b4bf2d8728120d052163a77df",
            "role": "demo"
        }
    }

def hash_password(password: str) -> str:
    """Creates MD5 hash for password verification."""
    return hashlib.md5(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verifies input password against stored hash."""
    return hash_password(password) == hashed

def check_login(username: str, password: str) -> Tuple[bool, Optional[Dict]]:
    """Validates credentials against the user directory."""
    users = get_users_from_secrets()
    if username in users:
        user = users[username]
        if verify_password(password, user['password']):
            logger.info(f"User login successful: {username}")
            return True, {"username": username, "name": user['name'], "role": user['role']}
    
    logger.warning(f"Failed login attempt for user: {username}")
    return False, None

def render_login_page():
    """Renders the Enterprise Login Interface."""
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        
        .stApp {
            background: linear-gradient(135deg, #003366 0%, #001F3F 100%);
        }
        
        .login-container {
            max-width: 420px;
            margin: 3rem auto;
            padding: 2.5rem;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.2);
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .login-logo {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, #FF8C00 0%, #E67E00 100%);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.5rem;
            margin: 0 auto 1.5rem;
            box-shadow: 0 8px 25px rgba(255, 140, 0, 0.4);
        }
        
        .login-title {
            font-size: 1.8rem;
            font-weight: 800;
            color: #003366;
            margin-bottom: 0.5rem;
            font-family: 'Inter', sans-serif;
        }
        
        .login-subtitle {
            color: #475569;
            font-size: 0.95rem;
            font-weight: 500;
        }
        
        .demo-box {
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 12px;
            padding: 1.25rem;
            margin-top: 2rem;
            text-align: center;
        }
        
        .demo-box code {
            background: #e2e8f0;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
            color: #0f172a;
        }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown(f"""
        <div class="login-header">
            <div class="login-logo">🔧</div>
            <div class="login-title">{SystemConfig.APP_NAME}</div>
            <div class="login-subtitle">Enterprise Service Intelligence</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### Secure Login")
        
        username = st.text_input("Benutzer ID", placeholder="z.B. admin")
        password = st.text_input("Passwort", type="password", placeholder="••••••••")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            login_clicked = st.button("🔐 Anmelden", type="primary", use_container_width=True)
        with col_btn2:
            demo_clicked = st.button("🎮 Demo Mode", use_container_width=True)
        
        if demo_clicked:
            username, password = "demo", "demo123"
            login_clicked = True
        
        if login_clicked:
            if username and password:
                with st.spinner("Authenticating..."):
                    time.sleep(0.5) # Security delay simulation
                    success, user_data = check_login(username, password)
                    if success:
                        st.session_state.authenticated = True
                        st.session_state.user = user_data
                        st.toast(f"Welcome back, {user_data['name']}!", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ Zugangsdaten ungültig. Zugriff verweigert.")
            else:
                st.warning("⚠️ Bitte geben Sie Ihre Zugangsdaten ein.")
        
        st.markdown("""
        <div class="demo-box">
            <strong>Schnellzugriff für Präsentationen:</strong><br>
            User: <code>demo</code> · Pass: <code>demo123</code>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown(f"""
        <div style="text-align: center; color: #94a3b8; font-size: 0.8rem;">
            © 2026 {SystemConfig.COMPANY}<br>
            System Version: {SystemConfig.VERSION}
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ENTERPRISE UI & BRANDING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════
def inject_css():
    """Injects the comprehensive Enterprise CSS Design System."""
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {
            --primary-blue: #003366;
            --secondary-blue: #0066B3;
            --accent-orange: #FF8C00;
            --accent-orange-hover: #E67E00;
            --bg-light: #f8fafc;
            --text-dark: #0f172a;
        }

        * { font-family: 'Inter', -apple-system, sans-serif; }
        
        .stApp { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
        
        /* ─── Sidebar Styling ─── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, var(--primary-blue) 0%, #001F3F 100%);
            border-right: 1px solid rgba(255,255,255,0.1);
        }
        [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
        [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.2); margin: 1.5rem 0; }
        
        /* Input Fields in Sidebar */
        [data-testid="stSidebar"] .stTextInput > div > div {
            background-color: rgba(255,255,255,0.05); 
            border: 1px solid rgba(255,255,255,0.2); 
            color: white;
        }
        
        /* Primary Buttons */
        .stButton > button {
            background: linear-gradient(135deg, var(--accent-orange) 0%, var(--accent-orange-hover) 100%);
            color: white !important;
            border: none; 
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(255, 140, 0, 0.2);
        }
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(255, 140, 0, 0.3);
        }
        
        /* ─── Branding Components ─── */
        .logo-container {
            text-align: center; padding: 2rem 0; margin-bottom: 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .logo-icon {
            width: 64px; height: 64px;
            background: linear-gradient(135deg, var(--accent-orange) 0%, var(--accent-orange-hover) 100%);
            border-radius: 16px; margin: 0 auto 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 2rem;
            box-shadow: 0 0 20px rgba(255, 140, 0, 0.3);
        }
        .logo-text {
            font-size: 1.5rem; font-weight: 700; color: #ffffff !important; letter-spacing: -0.5px;
        }
        
        /* ─── User Badge ─── */
        .user-badge {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            padding: 1rem; border-radius: 12px; margin-bottom: 1.5rem;
            display: flex; align-items: center; gap: 1rem;
        }
        .user-avatar {
            width: 40px; height: 40px;
            background: var(--accent-orange);
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-weight: 700; color: white;
        }
        
        /* ─── Main Header ─── */
        .main-header {
            background: linear-gradient(135deg, var(--primary-blue) 0%, var(--secondary-blue) 100%);
            color: white; padding: 3rem; border-radius: 16px; margin-bottom: 2.5rem;
            box-shadow: 0 20px 40px rgba(0, 51, 102, 0.15);
            position: relative; overflow: hidden;
        }
        .main-header::after {
            content: ''; position: absolute; top: 0; right: 0; bottom: 0; left: 0;
            background: url('data:image/svg+xml;base64,...'); /* Optional pattern */
            opacity: 0.1;
        }
        
        /* ─── Content Elements ─── */
        .source-box {
            background: #f0f9ff;
            border-left: 4px solid var(--secondary-blue);
            padding: 1rem; margin-top: 0.5rem; border-radius: 0 8px 8px 0;
            font-size: 0.85rem; color: var(--primary-blue);
        }
        
        .hydraulik-tip {
            background: #fffbeb;
            border: 1px solid #fcd34d;
            border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0;
            color: #92400e; display: flex; gap: 1rem; align-items: start;
        }
        
        /* ─── Status Indicators ─── */
        .status-badge {
            padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.5px;
        }
        .status-active { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
        .status-beta { background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; }
        
    </style>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
def init_session_state():
    """Initializes the Application State Machine."""
    defaults = {
        "authenticated": False,
        "user": None,
        "messages": [],
        "index": None,
        "all_documents": [],
        "uploaded_files": {},
        "qdrant_client": None,
        "is_ready": False,
        "processing_log": []
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ══════════════════════════════════════════════════════════════════════════════
# SECURE API KEY HANDLING
# ══════════════════════════════════════════════════════════════════════════════
def get_api_keys() -> Tuple[Optional[str], Optional[str]]:
    """Retrieves API keys from environment or secrets store."""
    llama_key, openai_key = None, None
    try:
        # Check Streamlit Secrets first
        if hasattr(st, 'secrets'):
            llama_key = st.secrets.get("LLAMA_CLOUD_API_KEY")
            openai_key = st.secrets.get("OPENAI_API_KEY")
            
        # Check OS Environment as fallback
        if not llama_key:
            llama_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not openai_key:
            openai_key = os.getenv("OPENAI_API_KEY")
            
    except Exception as e:
        logger.error(f"Error retrieving API keys: {e}")
        
    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# CORE ENGINE: LLAMAPARSE (SEMANTIC TABLE RECOGNITION)
# ══════════════════════════════════════════════════════════════════════════════
def parse_pdf_with_llamaparse(pdf_path: str, filename: str, llama_api_key: str) -> Optional[List[Document]]:
    """
    ENTERPRISE PARSING PIPELINE v3.3
    Uses Multimodal Vision Models to reconstruct complex technical layouts.
    """
    try:
        logger.info(f"Starting LlamaParse for file: {filename}")
        
        # ENTERPRISE INSTRUCTION SET
        parsing_instruction = """
        Dies ist ein hochtechnisches Datenblatt aus der Hydraulik-/Fluidtechnik-Branche (z.B. Bosch Rexroth, Parker).
        
        WICHTIGSTE REGEL:
        Extrahieren Sie den "Typenschlüssel" / "Bestellangaben" (meist S. 2-6) als perfekte Markdown-Tabelle.
        Jeder Code (z.B. M, T, A, S) in der Spalte "Dichtung" oder "Option" muss seiner Erklärung zugeordnet bleiben.
        
        Ignoriere Layout-Elemente, fokussiere dich auf Tabelleninhalte.
        
        KRITISCHE ANWEISUNG FÜR TABELLENSTRUKTUREN:
        1. Suche explizit nach Tabellen mit dem Titel "Bestellangaben", "Typenschlüssel" oder "Type Code".
           - Diese befinden sich oft auf den ersten 3 Seiten.
        2. Wenn eine Tabelle Codes wie "M", "T", "A", "S" enthält (z.B. bei Dichtungsarten), extrahiere die ZUGEHÖRIGE Beschreibung in derselben Zeile.
           Stelle sicher, dass der Code (z.B. "M") und die Bedeutung (z.B. "Standard-Dichtsystem") nicht getrennt werden.
        3. Erhalte die exakte Struktur von Tabellen im Markdown-Format, damit Zeilen- und Spaltenbezüge erhalten bleiben.
        4. Ignoriere keine Fußnoten unter Tabellen, diese enthalten oft kritische Grenzwerte.
        
        EXTRAHIERE FOLGENDE DATEN MIT HÖCHSTER PRIORITÄT:
        1. Alle Tabellen mit Druckwerten (bar, MPa, psi) -> Unterscheide strikt zwischen Betriebsdruck, Prüfdruck und Berstdruck.
        2. Dichtungsarten-Codes und ihre Bedeutung (z.B. M=Standard, T=Low Friction, A=Dachmanschetten).
        3. Volumenstrom-Angaben (l/min, m³/h) und Drehmomentangaben (Nm).
        4. Temperaturangaben (°C) für Medien und Umgebung.
        5. Teilenummern und Ersatzteilreferenzen (Explosionszeichnungen beachten).
        
        OUTPUT FORMAT:
        - Markdown mit sauberen Tabellenstrukturen.
        - Keine Zusammenfassung, gib den vollen Inhalt wieder.
        """
        
        parser = LlamaParse(
            api_key=llama_api_key,
            result_type="markdown",
            num_workers=2,      # Parallel processing for speed
            verbose=True,       # Enable detailed logging
            language="de",      # Force German language model
            parsing_instruction=parsing_instruction
        )
        
        # Execute Parsing
        documents = parser.load_data(pdf_path)
        
        # Metadata Enrichment for Retrieval
        for i, doc in enumerate(documents):
            if not doc.metadata:
                doc.metadata = {}
            # Critical Metadata for Citation
            doc.metadata["page_number"] = i + 1
            doc.metadata["source_file"] = filename
            doc.metadata["processed_at"] = datetime.now().isoformat()
            doc.metadata["uploaded_by"] = st.session_state.user.get("username", "unknown")
            
        logger.info(f"Successfully parsed {len(documents)} pages from {filename}")
        return documents

    except Exception as e:
        logger.error(f"Parsing failed for {filename}: {str(e)}")
        st.error(f"❌ Fehler beim Parsing von {filename}. Bitte prüfen Sie das Format.")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# CORE ENGINE: VECTOR STORE (QDRANT + OPENAI)
# ══════════════════════════════════════════════════════════════════════════════
def create_or_update_index(documents: List[Document], openai_api_key: str) -> Optional[VectorStoreIndex]:
    """
    Builds the Semantic Vector Index using Qdrant.
    NOTE: For native Hybrid Search with QueryFusion, we keep the Qdrant store simpler.
    """
    try:
        logger.info("Initializing Vector Index update...")
        
        # Configure LLM & Embeddings
        llm = OpenAI(
            model=SystemConfig.LLM_MODEL, 
            api_key=openai_api_key, 
            temperature=SystemConfig.TEMPERATURE
        )
        embed_model = OpenAIEmbedding(
            model=SystemConfig.EMBED_MODEL, 
            api_key=openai_api_key
        )
        
        # Apply Global Settings
        Settings.llm = llm
        Settings.embed_model = embed_model
        Settings.chunk_size = SystemConfig.CHUNK_SIZE
        Settings.chunk_overlap = SystemConfig.CHUNK_OVERLAP
        
        # Initialize Qdrant Client
        if st.session_state.qdrant_client is None:
            st.session_state.qdrant_client = QdrantClient(":memory:")
            logger.info("Created new Qdrant in-memory instance.")
        
        client = st.session_state.qdrant_client
        collection_name = "hydraulik_enterprise_v3"
        
        # Clean Slate Strategy
        collections = client.get_collections().collections
        if any(c.name == collection_name for c in collections):
            client.delete_collection(collection_name)
        
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        
        # Create Store & Context
        vector_store = QdrantVectorStore(
            client=client, 
            collection_name=collection_name
        )
        node_parser = MarkdownNodeParser() # Optimized for LlamaParse Markdown output
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        # Build Index
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            node_parser=node_parser,
            show_progress=True
        )
        
        logger.info("Vector Index successfully built.")
        return index

    except Exception as e:
        logger.error(f"Index creation failed: {str(e)}")
        st.error(f"❌ Kritischer Fehler bei der Indexierung: {str(e)}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# ENTERPRISE DOMAIN ONTOLOGY (HYDRAULIK + HAUSHALTSGERÄTE)
# ══════════════════════════════════════════════════════════════════════════════

class DomainOntology:
    """
    Ultra-komplexe Domänen-Ontologie für Industriehydraulik UND komplexe Haushaltsgeräte.
    """

    HYDRAULIC_SYNONYMS = {
        "druck": ["druck", "betriebsdruck", "prüfdruck", "berstdruck", "pressure", "p_max", "pmax"],
        "volumenstrom": ["volumenstrom", "förderstrom", "q", "l/min", "lmin", "flow rate"],
        "dichtung": ["dichtung", "dichtungssatz", "seal", "sealing kit", "dichtsystem"],
        "typenschlüssel": ["typenschlüssel", "type code", "bestellangaben", "order code"],
    }

    APPLIANCE_SYNONYMS = {
        "temperaturanzeige": [
            "temperaturanzeige",
            "anzeigeeinheit",
            "display",
            "kerntemperaturanzeige",
            "temperatur-display",
            "temperaturwert auf display"
        ],
        "sensor": [
            "temperatursonde",
            "bakesensor",
            "backsensor",
            "sensorbuchse",
            "temperaturfühler",
            "kerntemperaturfühler",
            "temperatursondenbuchse",
            "steckbuchse für sensor"
        ],
        "programm": [
            "programm",
            "auto bake",
            "pro bake",
            "backprogramm",
            "garprogramm",
            "automatikprogramm"
        ],
        "fehlercode": [
            "fehlercode",
            "störungscode",
            "error code",
            "e-",
            "f-"
        ],
    }

    CROSS_DOMAIN_PATTERNS = [
        {
            "if_all": ["temperaturanzeige", "sensor"],
            "add": ["temperatursonde", "bakesensor", "temperatursondenbuchse",
                    "anzeigeeinheit", "display", "sens"]
        },
        {
            "if_any": ["fehlercode", "error code", "e-", "f-"],
            "add": ["display", "anzeigeeinheit", "störungscode", "codeanzeige"]
        },
    ]

    @classmethod
    def normalize(cls, text: str) -> str:
        import re
        t = text.lower()
        t = re.sub(r"[^\w\s\-.:/]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @classmethod
    def expand_query(cls, question: str) -> str:
        base = cls.normalize(question)
        tokens = base.split()
        expansion_terms = set(tokens)

        for key, syns in cls.HYDRAULIC_SYNONYMS.items():
            if key in tokens:
                expansion_terms.update(syns)

        for key, syns in cls.APPLIANCE_SYNONYMS.items():
            if key in tokens:
                expansion_terms.update(syns)

        for rule in cls.CROSS_DOMAIN_PATTERNS:
            if "if_all" in rule and all(term in expansion_terms for term in rule["if_all"]):
                expansion_terms.update(rule.get("add", []))
            if "if_any" in rule and any(term in expansion_terms for term in rule["if_any"]):
                expansion_terms.update(rule.get("add", []))

        return " ".join(sorted(expansion_terms))


# ══════════════════════════════════════════════════════════════════════════════
# ERWEITERTER SYSTEM PROMPT (HYDRAULIK + APPLIANCES)
# ══════════════════════════════════════════════════════════════════════════════

HYDRAULIKSYSTEMPROMPT = """
Du bist ein technischer Experte und Dokumentationsspezialist für Industriehydraulik
UND komplexe Haushaltsgeräte (z.B. Backöfen, Waschmaschinen, Geschirrspüler).

SPRACHE: Antworte IMMER in der Sprache der Benutzerfrage (Deutsch für deutsche Fragen, Englisch für englische).

Beantworte Fragen NUR basierend auf dem Kontext der bereitgestellten Dokumente.

REGELN FÜR DISPLAY- UND SENSOR-ANFRAGEN
1. Suche nach EXAKTEN Codes und Display-Anzeigen (z.B. "SEnS", "E-2", "F-xx") und
   nach Begriffen wie "Temperatursonde", "BAKESENSOR", "Temperatursondenbuchse".
2. Rekonstruiere abgeschnittene Display-Strings (z.B. "SENS ... 50 ... PEC") so präzise wie möglich.
3. Berücksichtige Begriffe wie:
   - "Temperatursonde", "Bakesensor", "Temperaturfühler", "Kerntemperaturfühler"
   - "Anzeigeeinheit", "Display", "Temperaturanzeige", "Auto bake", "Pro bake".
4. Mappe Formulierungen wie "Temperaturanzeige mit Sensor" intern auf diese Begriffe.
5. Zitiere immer: "Quelle: <Dateiname> S. <Seite>".

REGELN FÜR DRUCK / HYDRAULIK
1. Unterscheide strikt zwischen Betriebsdruck, Prüfdruck und Berstdruck.
2. Achte auf Tabellen mit "Bestellangaben", "Typenschlüssel", "Dichtung", "Volumenstrom".
3. Trenne Codes (z.B. M, T, A, S) nie von ihrer Bedeutung.

WENN KEINE 1:1-STELLE EXISTIERT
1. Nutze semantisch nahe Stellen (Sensor, Display, Programme) und erkläre das explizit.
2. Verwende "nicht enthalten" nur, wenn weder direkt noch indirekt etwas Relevantes existiert.
3. Wenn du relevante Begriffe im Kontext siehst, NUTZE sie für die Antwort.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CORE ENGINE: NATIVE HYBRID RETRIEVAL (BM25 + FUSION)
# ══════════════════════════════════════════════════════════════════════════════
def query_knowledge_base(index: VectorStoreIndex, question: str) -> Tuple[str, List[str]]:
    """
    NATIVE HYBRID RETRIEVAL STRATEGY (Memory-Safe)
    Zwingt BM25 (Keyword) und Vector Search zur Kooperation durch QueryFusion.
    """
    try:
        logger.info(f"Processing query: {question}")
        expanded = DomainOntology.expand_query(question)
        logger.info(f"Expanded query: {expanded}")
        
        # 1. Vektor-Retriever (Semantik)
        vector_retriever = index.as_retriever(
            similarity_top_k=10
        )

        # 2. BM25-Retriever (Exakte Keywords wie "SEnS", "MP5")
        # Nur verwenden wenn Index nicht leer ist
        if hasattr(index, 'docstore') and len(index.docstore.docs) > 0:
            bm25_retriever = BM25Retriever.from_defaults(
                docstore=index.docstore,
                similarity_top_k=10
            )

            # 3. Fusion (Kombination beider Ergebnisse)
            fusion_retriever = QueryFusionRetriever(
                retrievers=[vector_retriever, bm25_retriever],
                similarity_top_k=SystemConfig.RETRIEVAL_TOP_K, # Total Chunks an LLM
                num_queries=1,
                mode="reciprocal_rank", # RRF Algorithmus für faire Gewichtung
                use_async=True
            )
        else:
            # Fallback: nur Vector-Retriever wenn Index leer
            logger.warning("BM25 skipped - index empty or docstore unavailable")
            fusion_retriever = vector_retriever

        # Engine erstellen
        query_engine = RetrieverQueryEngine.from_args(
            retriever=fusion_retriever,
            llm=OpenAI(model=SystemConfig.LLM_MODEL, temperature=SystemConfig.TEMPERATURE),
            response_mode="tree_summarize"
        )
        
        # Retrieval manuell mit expanded query durchführen
        retrieved_nodes = fusion_retriever.retrieve(expanded)
        
        # Context aus Nodes aufbauen
        context_str = "\n\n".join([
            f"[Quelle: {node.metadata.get('source_file', 'Unbekannt')} S. {node.metadata.get('page_number', '?')}]\n{node.get_content()}"
            for node in retrieved_nodes
        ])
        
        # Vollständiger Prompt mit Enterprise-Instruktionen + expanded context
        full_query = f"""
{HYDRAULIKSYSTEMPROMPT}

KONTEXT AUS DOKUMENTEN:
{context_str}

USER FRAGE: {question}

ANTWORT:"""
        
        # LLM direkt aufrufen
        llm = OpenAI(model=SystemConfig.LLM_MODEL, temperature=SystemConfig.TEMPERATURE)
        response_text = llm.complete(full_query).text
        
        # Response-Objekt simulieren für Source-Extraktion
        class SimpleResponse:
            def __init__(self, text, nodes):
                self.response = text
                self.source_nodes = nodes
            def __str__(self):
                return self.response
        
        response = SimpleResponse(response_text, retrieved_nodes)
        
        # Quellen extrahieren
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
        logger.error(f"Query failed: {str(e)}")
        return f"⚠️ Fehler: {str(e)}", []

# ══════════════════════════════════════════════════════════════════════════════
# FILE PROCESSING LOGIC
# ══════════════════════════════════════════════════════════════════════════════
def process_single_pdf(uploaded_file, llama_key: str, openai_key: str) -> bool:
    """
    Handles the upload-to-index pipeline securely.
    """
    tmp_path = None
    try:
        # Create secure temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # Execute Parsing
        with st.spinner(f"⚙️ Enterprise Parser analysiert: {uploaded_file.name}..."):
            documents = parse_pdf_with_llamaparse(tmp_path, uploaded_file.name, llama_key)
        
        # Cleanup
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        
        if documents is None:
            return False
        
        # Update Session Store
        st.session_state.all_documents.extend(documents)
        st.session_state.uploaded_files[uploaded_file.name] = len(documents)
        
        # Log action
        msg = f"Uploaded {uploaded_file.name} ({len(documents)} pages)"
        st.session_state.processing_log.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")
        logger.info(msg)
        
        return True

    except Exception as e:
        logger.error(f"File processing error: {e}")
        st.error(f"Fehler beim Verarbeiten der Datei: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False

def rebuild_index(openai_key: str):
    """Triggers a full rebuild of the Vector Index."""
    if not st.session_state.all_documents:
        st.warning("Keine Dokumente im Speicher.")
        return
    
    with st.spinner("🧠 Vektorisierung & BM25-Indexierung läuft..."):
        index = create_or_update_index(st.session_state.all_documents, openai_key)
        if index:
            st.session_state.index = index
            st.session_state.is_ready = True
            st.toast("Index erfolgreich aktualisiert!", icon="✅")

def remove_document(filename: str, openai_key: str):
    """Removes a document and rebuilds the index."""
    st.session_state.all_documents = [
        doc for doc in st.session_state.all_documents 
        if doc.metadata.get("source_file") != filename
    ]
    
    if filename in st.session_state.uploaded_files:
        del st.session_state.uploaded_files[filename]
        st.toast(f"Dokument entfernt: {filename}", icon="🗑️")
    
    if st.session_state.all_documents:
        rebuild_index(openai_key)
    else:
        st.session_state.index = None
        st.session_state.is_ready = False

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════
def render_sidebar(llama_key, openai_key):
    """Renders the Control Panel."""
    with st.sidebar:
        # Branding
        st.markdown("""
        <div class="logo-container">
            <div class="logo-icon">🔧</div>
            <div class="logo-text">HydraulikDoc</div>
            <div style="color: #94a3b8; font-size: 0.8rem; letter-spacing: 2px;">ENTERPRISE AI</div>
        </div>
        """, unsafe_allow_html=True)
        
        # User Profile
        user = st.session_state.user
        if user:
            st.markdown(f"""
            <div class="user-badge">
                <div class="user-avatar">{user['name'][0].upper()}</div>
                <div>
                    <div style="font-weight: 600;">{user['name']}</div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">{user['role']}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.rerun()
        
        st.markdown("---")
        
        # API Status Panel
        st.markdown("#### 🔌 System Status")
        
        api_status_html = ""
        if llama_key:
            api_status_html += '<div class="status-badge status-active">✓ LlamaCloud</div> '
        else:
            api_status_html += '<div class="status-badge status-beta">! LlamaCloud</div> '
            
        if openai_key:
            api_status_html += '<div class="status-badge status-active">✓ OpenAI Engine</div>'
        else:
            api_status_html += '<div class="status-badge status-beta">! OpenAI Engine</div>'
            
        st.markdown(f'<div style="display:flex; gap:10px; margin-bottom:1rem;">{api_status_html}</div>', unsafe_allow_html=True)
        
        # Manual Key Input
        if not llama_key:
            llama_key = st.text_input("LlamaCloud API Key", type="password")
        if not openai_key:
            openai_key = st.text_input("OpenAI API Key", type="password")
            
        st.markdown("---")
        
        # Document Management
        st.markdown("#### 📚 Knowledge Base")
        
        if st.session_state.uploaded_files:
            for filename, pages in st.session_state.uploaded_files.items():
                col1, col2 = st.columns([4, 1])
                with col1:
                    display_name = (filename[:18] + '..') if len(filename) > 18 else filename
                    st.markdown(f"📄 **{display_name}** ({pages} S.)")
                with col2:
                    if st.button("🗑️", key=f"del_{filename}", help="Dokument entfernen"):
                        remove_document(filename, openai_key)
                        st.rerun()
        else:
            st.info("Wissensdatenbank leer.")

        uploaded_file = st.file_uploader("Neues Dokument", type=["pdf"], label_visibility="collapsed")
        
        if uploaded_file:
            if uploaded_file.name in st.session_state.uploaded_files:
                st.warning("⚠️ Datei existiert bereits.")
            elif not llama_key or not openai_key:
                st.error("🔑 API Keys erforderlich!")
            else:
                if st.button("📥 Ingest & Index", type="primary", use_container_width=True):
                    if process_single_pdf(uploaded_file, llama_key, openai_key):
                        rebuild_index(openai_key)
                        st.rerun()

        st.markdown("---")
        
        if user and user.get('role') == 'admin':
            if st.button("⚠️ System Reset", use_container_width=True):
                st.session_state.all_documents = []
                st.session_state.uploaded_files = {}
                st.session_state.index = None
                st.session_state.is_ready = False
                st.session_state.messages = []
                st.toast("System wurde zurückgesetzt.", icon="🔄")
                time.sleep(1)
                st.rerun()
                
        st.markdown(f"""
        <div style="margin-top: 2rem; text-align: center; font-size: 0.7rem; color: #64748b;">
            {SystemConfig.APP_NAME} {SystemConfig.VERSION}<br>
            Powered by LlamaIndex & GPT-4o
        </div>
        """, unsafe_allow_html=True)

    return llama_key, openai_key

# ══════════════════════════════════════════════════════════════════════════════
# MAIN HEADER
# ══════════════════════════════════════════════════════════════════════════════
def render_header():
    st.markdown(f"""
    <div class="main-header">
        <h1>🔧 {SystemConfig.APP_NAME}</h1>
        <p style="opacity: 0.9; font-size: 1.1rem; margin-top: 0.5rem;">
            Intelligent Service Operating System
        </p>
        <div style="margin-top: 1.5rem;">
            <span class="status-badge status-active">Enterprise Edition</span>
            <span class="status-badge status-active" style="margin-left: 0.5rem;">Secure</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHAT INTERFACE
# ══════════════════════════════════════════════════════════════════════════════
def render_chat_interface():
    st.markdown("### 💬 Technical Query Assistant")
    
    if not st.session_state.is_ready:
        st.markdown("""
        <div class="hydraulik-tip">
            <div>
                <strong>👋 System Ready for Ingest.</strong><br>
                Bitte laden Sie Ihre Hydraulik-Dokumente (PDF) über die Sidebar hoch.<br><br>
                <em>Optimiert für:</em>
                <ul>
                    <li>Bosch Rexroth / Parker Datenblätter</li>
                    <li>Wartungshandbücher & Schaltpläne</li>
                    <li>Ersatzteilkataloge</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar="👤" if message["role"] == "user" else "🔧"):
            st.markdown(message["content"])
            if "sources" in message and message["sources"]:
                sources_html = " <br> ".join([f"• {src}" for src in message["sources"]])
                st.markdown(f"""
                <div class="source-box">
                    <strong>📚 Verifizierte Quellen:</strong><br>
                    {sources_html}
                </div>
                """, unsafe_allow_html=True)

    if prompt := st.chat_input("Stellen Sie Ihre technische Frage (z.B. 'Welcher Dichtungssatz für CDH2?')..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        
        with st.chat_message("assistant", avatar="🔧"):
            message_placeholder = st.empty()
            with st.spinner("🔍 Analysiere Dokumente & Typenschlüssel..."):
                start_time = time.time()
                response, sources = query_knowledge_base(st.session_state.index, prompt)
                duration = time.time() - start_time
            
            message_placeholder.markdown(response)
            if sources:
                sources_html = " <br> ".join([f"• {src}" for src in sources])
                st.markdown(f"""
                <div class="source-box">
                    <strong>📚 Verifizierte Quellen:</strong><br>
                    {sources_html}
                </div>
                """, unsafe_allow_html=True)
            logger.info(f"Query processed in {duration:.2f}s")
        
        st.session_state.messages.append({"role": "assistant", "content": response, "sources": sources})

# ══════════════════════════════════════════════════════════════════════════════
# APPLICATION ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    """Main Application Orchestrator"""
    init_session_state()
    inject_css()
    
    if not st.session_state.authenticated:
        render_login_page()
        return
    
    if not IMPORTS_AVAILABLE:
        st.error(f"⚠️ KRITISCHER FEHLER: Abhängigkeiten fehlen. {IMPORT_ERROR}")
        st.stop()
    
    render_header()
    
    llama_key, openai_key = get_api_keys()
    final_l_key, final_o_key = render_sidebar(llama_key, openai_key)
    
    tab_titles = ["📄 Dokument-Suche (Enterprise)", "🎥 Video-Diagnose (Beta)"]
    tab1, tab2 = st.tabs(tab_titles)
    
    with tab1:
        render_chat_interface()
    
    with tab2:
        if GEMINI_AVAILABLE:
            render_video_analyzer_tab()
        else:
            st.warning("Video-Modul nicht geladen. Bitte `streamlit_integration.py` prüfen.")

if __name__ == "__main__":
    main()

# ================= ENTERPRISE DOMAIN CONFIG =================


