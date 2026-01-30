# ═══════════════════════════════════════════════════════════════════════════
# PROJECT HEPHAESTUS - GEMINI VIDEO ANALYSIS INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

import streamlit as st
import tempfile
import os
from pathlib import Path

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

def render_video_analyzer_tab():
    """Renders the Gemini Video Analysis interface."""
    
    if not GEMINI_AVAILABLE:
        st.error("❌ Gemini SDK nicht installiert. Bitte `pip install google-generativeai` ausführen.")
        return
    
    st.markdown("### 🎥 Video-Diagnose (Project Hephaestus)")
    st.markdown("""
    **Multimodale Fehlerdiagnose für Haushaltsgeräte**  
    Laden Sie Videos von Fehlercodes, Display-Anzeigen oder Maschinenproblemen hoch.
    """, unsafe_allow_html=True)
    
    # Check if user has access (Premium Feature) - ROBUST handling
    user = st.session_state.get("user", {})
    if isinstance(user, dict):
        user_role = user.get("role", "demo")
    else:
        user_role = getattr(user, "role", "demo")
    
    if user_role == "demo":
        st.warning("⚠️ Video-Diagnose ist nur für Premium-Kunden verfügbar.")
        st.info("Upgrade auf Premium für €179/Monat um Video-Analyse freizuschalten.")
        return
    
    # API Key Input
    gemini_key = st.text_input("Google Gemini API Key", type="password", key="gemini_api_key_input")
    
    if not gemini_key:
        gemini_key = os.getenv("GEMINI_API_KEY")
    
    if not gemini_key:
        st.warning("⚠️ Bitte Gemini API Key eingeben.")
        return
    
    # Configure Gemini
    try:
        genai.configure(api_key=gemini_key)
    except Exception as e:
        st.error(f"Fehler bei Gemini-Konfiguration: {e}")
        return
    
    # File Upload
    uploaded_video = st.file_uploader(
        "Video hochladen (max. 50MB)",
        type=["mp4", "mov", "avi"],
        key="video_uploader"
    )
    
    if uploaded_video:
        st.video(uploaded_video)
        
        if st.button("🔍 Video analysieren", type="primary"):
            with st.spinner("Verarbeite Video mit Gemini 2.0 Flash..."):
                try:
                    # Save to temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_video.name).suffix) as tmp:
                        tmp.write(uploaded_video.read())
                        tmp_path = tmp.name
                    
                    # Upload to Gemini
                    video_file = genai.upload_file(tmp_path)
                    
                    # Create prompt
                    prompt = """
                    Analysiere dieses Video eines Haushaltsgeräts (Backofen, Waschmaschine, etc.).
                    
                    Fokussiere auf:
                    1. **Fehlercodes** (z.B. E-2, F-10, SEnS)
                    2. **Display-Anzeigen** (Programme, Temperatur, Symbole)
                    3. **Physische Probleme** (Geräusche, Bewegungen, Leckagen)
                    
                    Gib eine strukturierte Diagnose:
                    - Was ist zu sehen?
                    - Welche Komponente ist betroffen?
                    - Mögliche Ursache
                    - Empfohlene Lösung
                    """
                    
                    # Call Gemini
                    model = genai.GenerativeModel("gemini-2.0-flash-exp")
                    response = model.generate_content([prompt, video_file])
                    
                    # Display result
                    st.success("✅ Analyse abgeschlossen")
                    st.markdown("### 📋 Diagnose")
                    st.markdown(response.text)
                    
                    # Cleanup
                    os.unlink(tmp_path)
                    
                except Exception as e:
                    st.error(f"Fehler bei der Video-Analyse: {e}")
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.unlink(tmp_path)

