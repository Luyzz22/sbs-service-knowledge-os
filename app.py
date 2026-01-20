"""
================================================================================
SBS DEUTSCHLAND GMBH - SERVICE KNOWLEDGE OS
================================================================================
RAG-System für technische Handbücher - OpenAI Version
================================================================================
"""

import streamlit as st
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Tuple
import hashlib

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

st.set_page_config(
    page_title="SBS Service Knowledge OS",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a365d 0%, #2d3748 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 0 0 10px 10px;
        margin-bottom: 2rem;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; font-weight: 600; }
    .main-header p { margin: 0.5rem 0 0 0; opacity: 0.9; }
    .source-box {
        background-color: #ebf8ff;
        border-left: 4px solid #3182ce;
        padding: 0.75rem 1rem;
        margin-top: 1rem;
        border-radius: 0 4px 4px 0;
    }
    [data-testid="stSidebar"] { background-color: #f8fafc; }
</style>
""", unsafe_allow_html=True)

def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "index" not in st.session_state:
        st.session_state.index = None
    if "parsed_documents" not in st.session_state:
        st.session_state.parsed_documents = None
    if "parsing_complete" not in st.session_state:
        st.session_state.parsing_complete = False
    if "current_pdf_name" not in st.session_state:
        st.session_state.current_pdf_name = None

def parse_pdf_with_llamaparse(pdf_path: str, llama_api_key: str) -> Optional[List[Document]]:
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
            doc.metadata["source_file"] = Path(pdf_path).name
        return documents
    except Exception as e:
        st.error(f"Fehler beim PDF-Parsing: {str(e)}")
        return None

def create_vector_index(documents: List[Document], openai_api_key: str) -> Optional[VectorStoreIndex]:
    try:
        llm = OpenAI(
            model="gpt-4o",
            api_key=openai_api_key,
            temperature=0.1,
        )
        embed_model = OpenAIEmbedding(
            model="text-embedding-3-small",
            api_key=openai_api_key,
        )
        Settings.llm = llm
        Settings.embed_model = embed_model
        Settings.chunk_size = 1024
        Settings.chunk_overlap = 100
        
        client = QdrantClient(":memory:")
        collection_name = "service_knowledge"
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
            documents, storage_context=storage_context,
            node_parser=node_parser, show_progress=True
        )
        return index
    except Exception as e:
        st.error(f"Fehler bei der Index-Erstellung: {str(e)}")
        return None

def query_knowledge_base(index: VectorStoreIndex, question: str) -> Tuple[str, List[str]]:
    try:
        query_engine = index.as_query_engine(similarity_top_k=5, response_mode="compact")
        SYSTEM_PROMPT = """
Du bist ein technischer Assistent für Wartungshandbücher im deutschen Maschinenbau.
STRIKTE REGELN:
1. Antworte NUR basierend auf den bereitgestellten Dokumentauszügen.
2. Wenn die Information NICHT enthalten ist, sage: "Diese Information ist im hochgeladenen Dokument nicht enthalten."
3. Erfinde NIEMALS Informationen.
4. Gib IMMER die Seitenzahl als Quelle an.
5. Antworte auf Deutsch.
"""
        full_query = f"{SYSTEM_PROMPT}\n\nFrage: {question}"
        response = query_engine.query(full_query)
        sources = []
        if response.source_nodes:
            for node in response.source_nodes:
                page_num = node.metadata.get("page_number", "Unbekannt")
                sources.append(f"Seite {page_num}")
        return str(response), sources
    except Exception as e:
        return f"Fehler bei der Anfrage: {str(e)}", []

def render_header():
    st.markdown("""
    <div class="main-header">
        <h1>SBS Service Knowledge OS</h1>
        <p>Intelligente Suche in technischen Handbüchern | RAG-System für den Maschinenbau</p>
    </div>
    """, unsafe_allow_html=True)

def render_sidebar():
    with st.sidebar:
        st.markdown("### SBS Deutschland GmbH")
        st.markdown("---")
        st.markdown("#### API-Konfiguration")
        
        st.markdown("**LlamaCloud API Key**")
        st.markdown('<small><a href="https://cloud.llamaindex.ai/" target="_blank">Key hier erstellen</a></small>', unsafe_allow_html=True)
        llama_key = st.text_input("LlamaCloud Key", type="password", placeholder="llx-...", label_visibility="collapsed")
        
        st.markdown("")
        st.markdown("**OpenAI API Key**")
        st.markdown('<small><a href="https://platform.openai.com/api-keys" target="_blank">Key hier erstellen</a></small>', unsafe_allow_html=True)
        openai_key = st.text_input("OpenAI Key", type="password", placeholder="sk-...", label_visibility="collapsed")
        
        st.markdown("---")
        st.markdown("#### Dokument hochladen")
        uploaded_file = st.file_uploader("Wartungshandbuch (PDF)", type=["pdf"])
        
        if uploaded_file is not None:
            if not llama_key or len(llama_key) < 10:
                st.warning("LlamaCloud API Key fehlt")
            elif not openai_key or len(openai_key) < 10:
                st.warning("OpenAI API Key fehlt")
            else:
                if st.button("Dokument verarbeiten", type="primary", use_container_width=True):
                    process_uploaded_pdf(uploaded_file, llama_key, openai_key)
        
        st.markdown("---")
        st.markdown("#### Systemstatus")
        if st.session_state.parsing_complete and st.session_state.index:
            st.success(f"✓ Bereit: {st.session_state.current_pdf_name}")
        else:
            st.info("○ Warte auf Dokument")
        
        if st.button("Chat zurücksetzen", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        
        st.markdown("---")
        st.markdown('<small>SBS Deutschland GmbH<br><a href="https://sbsdeutschland.com">sbsdeutschland.com</a></small>', unsafe_allow_html=True)
    
    return llama_key, openai_key

def process_uploaded_pdf(uploaded_file, llama_key: str, openai_key: str):
    progress_bar = st.progress(0)
    status_text = st.empty()
    try:
        status_text.text("Dokument wird vorbereitet...")
        progress_bar.progress(10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        status_text.text("PDF wird analysiert...")
        progress_bar.progress(30)
        documents = parse_pdf_with_llamaparse(tmp_path, llama_key)
        if documents is None:
            return
        st.session_state.parsed_documents = documents
        progress_bar.progress(60)
        
        status_text.text("Wissensindex wird erstellt...")
        progress_bar.progress(80)
        index = create_vector_index(documents, openai_key)
        if index is None:
            return
        
        st.session_state.index = index
        st.session_state.parsing_complete = True
        st.session_state.current_pdf_name = uploaded_file.name
        progress_bar.progress(100)
        status_text.text("Fertig!")
        os.unlink(tmp_path)
        st.success(f"✓ {len(documents)} Seiten indexiert")
        st.rerun()
    except Exception as e:
        st.error(f"Fehler: {str(e)}")

def render_chat_interface():
    st.markdown("#### Technische Anfrage")
    if not st.session_state.parsing_complete or not st.session_state.index:
        st.info("Laden Sie zunächst ein technisches Handbuch in der Sidebar hoch.")
        return
    
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "sources" in message and message["sources"]:
                st.markdown(f'<div class="source-box"><strong>Quellen:</strong> {", ".join(message["sources"])}</div>', unsafe_allow_html=True)
    
    if prompt := st.chat_input("Ihre technische Frage..."):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant"):
            with st.spinner("Durchsuche Dokumentation..."):
                response, sources = query_knowledge_base(st.session_state.index, prompt)
            st.markdown(response)
            if sources:
                st.markdown(f'<div class="source-box"><strong>Quellen:</strong> {", ".join(sources)}</div>', unsafe_allow_html=True)
        st.session_state.messages.append({"role": "assistant", "content": response, "sources": sources})

def main():
    init_session_state()
    if not IMPORTS_AVAILABLE:
        st.error(f"Fehlende Abhängigkeiten: {IMPORT_ERROR}")
        return
    render_header()
    llama_key, openai_key = render_sidebar()
    render_chat_interface()
    with st.expander("Hinweise zur Nutzung"):
        st.markdown("""
        **Beispielanfragen:**
        - "Wie hoch ist das Anzugsdrehmoment für Schraube M12?"
        - "Welches Öl wird für das Getriebe empfohlen?"
        - "Was sind die Wartungsintervalle?"
        """)

if __name__ == "__main__":
    main()
