"""
================================================================================
STREAMLIT INTEGRATION - Gemini Video Analyzer
================================================================================
Integration des Gemini Video Analyzers in HydraulikDoc AI

Dieses Modul zeigt wie du Video-Analyse als Premium-Feature
in deine bestehende App integrierst.
================================================================================
"""

import streamlit as st
import tempfile
from pathlib import Path
from gemini_video_analyzer import GeminiVideoAnalyzer

# ══════════════════════════════════════════════════════════════════════════════
# VIDEO ANALYZER TAB (Für Integration in deine App)
# ══════════════════════════════════════════════════════════════════════════════

def render_video_analyzer_tab():
    """
    Neue Tab für Video-Analyse in HydraulikDoc AI
    Füge das in deine app.py ein als neuen Tab
    """
    
    st.markdown("""
    ## 🎥 Video-Diagnose (BETA)
    
    <div style='background: linear-gradient(135deg, #FF8C00 0%, #FF6B00 100%); 
                padding: 1rem; border-radius: 10px; color: white; margin: 1rem 0;'>
        <strong>🚀 NEU:</strong> Lade ein Video deiner Maschine hoch und erhalte 
        eine KI-gestützte Audio-Diagnose basierend auf dem Wartungshandbuch!
    </div>
    """, unsafe_allow_html=True)
    
    # Check if user has access (Premium Feature)
    if st.session_state.user.role == "demo":
        st.warning("⚠️ Video-Diagnose ist nur für Premium-Kunden verfügbar.")
        st.info("Upgrade auf Premium für €179/Monat um Video-Analyse freizuschalten.")
        return
    
    # Get Google Cloud credentials from Streamlit Secrets
    try:
        project_id = st.secrets["google_cloud"]["project_id"]
        location = st.secrets["google_cloud"].get("location", "europe-west3")
    except:
        st.error("❌ Google Cloud nicht konfiguriert. Kontaktiere den Administrator.")
        return
    
    # File uploaders
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📹 Video hochladen")
        video_file = st.file_uploader(
            "Video der laufenden Maschine",
            type=["mp4", "mov", "avi", "webm"],
            help="Max. 50MB. Empfohlen: 10-30 Sekunden"
        )
        
        if video_file:
            st.video(video_file)
            st.caption(f"📊 Größe: {video_file.size / 1024 / 1024:.1f} MB")
    
    with col2:
        st.markdown("### 📄 Wartungshandbuch")
        pdf_file = st.file_uploader(
            "Handbuch (PDF)",
            type=["pdf"],
            help="Wartungshandbuch der Maschine"
        )
        
        if pdf_file:
            st.success(f"✅ {pdf_file.name}")
            st.caption(f"📊 Größe: {pdf_file.size / 1024 / 1024:.1f} MB")
    
    # Analysis options
    st.markdown("---")
    st.markdown("### 🔍 Analyse-Optionen")
    
    analysis_type = st.radio(
        "Was möchtest du analysieren?",
        [
            "🔊 Audio-Anomalie Diagnose (Empfohlen)",
            "🎯 Spezifische Frage beantworten",
            "📋 Allgemeine Inspektion"
        ]
    )
    
    # Custom question for specific analysis
    custom_question = None
    expected_behavior = None
    
    if "Spezifische Frage" in analysis_type:
        custom_question = st.text_area(
            "Deine Frage:",
            placeholder="z.B. Welches Lager könnte das Quietschen bei 0:08 verursachen?",
            height=100
        )
    
    elif "Audio-Anomalie" in analysis_type:
        expected_behavior = st.text_input(
            "Erwartetes Verhalten (optional):",
            placeholder="z.B. Gleichmäßiges Laufgeräusch bei 1450 U/min"
        )
    
    # Analyze button
    st.markdown("---")
    
    can_analyze = video_file and pdf_file
    if not can_analyze:
        st.info("📤 Lade Video und PDF hoch um die Analyse zu starten")
    
    if st.button("🚀 Analyse starten", disabled=not can_analyze, type="primary", use_container_width=True):
        analyze_with_gemini(
            video_file=video_file,
            pdf_file=pdf_file,
            analysis_type=analysis_type,
            custom_question=custom_question,
            expected_behavior=expected_behavior,
            project_id=project_id,
            location=location
        )


def analyze_with_gemini(
    video_file,
    pdf_file,
    analysis_type: str,
    custom_question: str = None,
    expected_behavior: str = None,
    project_id: str = None,
    location: str = "europe-west3"
):
    """
    Führe die Gemini-Analyse aus
    """
    
    with st.spinner("🤖 KI analysiert Video und Handbuch... (kann 30-60 Sek. dauern)"):
        
        # Save uploaded files temporarily
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            
            # Save video
            video_path = temp_dir / video_file.name
            with open(video_path, 'wb') as f:
                f.write(video_file.getbuffer())
            
            # Save PDF
            pdf_path = temp_dir / pdf_file.name
            with open(pdf_path, 'wb') as f:
                f.write(pdf_file.getbuffer())
            
            # Initialize analyzer
            analyzer = GeminiVideoAnalyzer(
                project_id=project_id,
                location=location
            )
            
            # Run analysis based on type
            try:
                if "Audio-Anomalie" in analysis_type:
                    result = analyzer.analyze_audio_anomaly(
                        video_path=str(video_path),
                        pdf_path=str(pdf_path),
                        expected_behavior=expected_behavior
                    )
                else:
                    result = analyzer.analyze_video_with_manual(
                        video_path=str(video_path),
                        pdf_path=str(pdf_path),
                        question=custom_question
                    )
                
                # Display results
                if result["success"]:
                    st.success("✅ Analyse abgeschlossen!")
                    
                    # Main result
                    st.markdown("---")
                    st.markdown("## 📊 Diagnose-Ergebnis")
                    
                    # Display in nice format
                    st.markdown(f"""
                    <div style='background: #f8f9fa; padding: 1.5rem; 
                                border-radius: 10px; border-left: 4px solid #FF8C00;'>
                        {result['analysis'].replace('\n', '<br>')}
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Metadata
                    st.markdown("---")
                    with st.expander("ℹ️ Analyse-Details"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Modell", result['model'])
                        with col2:
                            st.metric("Video", video_file.name)
                        with col3:
                            st.metric("Handbuch", pdf_file.name)
                    
                    # Action buttons
                    st.markdown("---")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        if st.button("📥 Diagnose als PDF exportieren"):
                            st.info("Feature kommt bald!")
                    
                    with col2:
                        if st.button("📧 An Serviceteam senden"):
                            st.info("Feature kommt bald!")
                    
                    with col3:
                        if st.button("🔄 Neue Analyse"):
                            st.rerun()
                
                else:
                    st.error(f"❌ Fehler bei der Analyse: {result['error']}")
                    
            except Exception as e:
                st.error(f"❌ Unerwarteter Fehler: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION IN BESTEHENDE APP
# ══════════════════════════════════════════════════════════════════════════════

def add_to_existing_app():
    """
    So fügst du das in deine bestehende app.py ein:
    
    1. Import hinzufügen (oben in app.py):
       from streamlit_integration import render_video_analyzer_tab
    
    2. Neuen Tab in der Tab-Leiste hinzufügen:
       tab1, tab2, tab3 = st.tabs(["📄 PDF Suche", "🎥 Video-Diagnose", "⚙️ Einstellungen"])
       
       with tab1:
           # Dein bestehender PDF-Suche Code
       
       with tab2:
           render_video_analyzer_tab()
       
       with tab3:
           # Einstellungen
    
    3. Secrets in Streamlit Cloud hinzufügen:
       [google_cloud]
       project_id = "your-project-id"
       location = "europe-west3"
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE DEMO APP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Standalone Demo der Video-Analyse
    Führe aus mit: streamlit run streamlit_integration.py
    """
    
    st.set_page_config(
        page_title="Video-Diagnose Demo | HydraulikDoc AI",
        page_icon="🎥",
        layout="wide"
    )
    
    # Header
    st.markdown("""
    # 🎥 Video-Diagnose Demo
    ### HydraulikDoc AI - Multimodal Edition
    """)
    
    # Mock session state
    if 'user' not in st.session_state:
        st.session_state.user = {"role": "admin"}
    
    render_video_analyzer_tab()
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; padding: 2rem;'>
        <small>Powered by Google Gemini 1.5 Pro • Made by SBS Deutschland GmbH</small>
    </div>
    """, unsafe_allow_html=True)
