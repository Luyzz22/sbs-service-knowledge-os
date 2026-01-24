#!/usr/bin/env python3
"""
Script to add Gemini Video Analyzer to HydraulikDoc AI
"""

import sys

def modify_app():
    """Add Gemini integration and tabs to app.py"""
    
    # Read current app.py
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Add Gemini import after existing imports
    import_addition = """
# ══════════════════════════════════════════════════════════════════════════════
# GEMINI VIDEO ANALYZER (Project Hephaestus)
# ══════════════════════════════════════════════════════════════════════════════
try:
    from streamlit_integration import render_video_analyzer_tab
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
"""
    
    old_import_block = """    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG"""
    
    new_import_block = """    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)
""" + import_addition + """
# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG"""
    
    content = content.replace(old_import_block, new_import_block)
    
    # 2. Modify main() function to use tabs
    old_main = """    inject_css()
    render_header()
    llama_key, openai_key = render_sidebar()
    render_chat_interface()
    
    st.markdown(\"\"\"
    <div class="footer">"""
    
    new_main = """    inject_css()
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
    
    st.markdown(\"\"\"
    <div class="footer">"""
    
    content = content.replace(old_main, new_main)
    
    # 3. Update version number
    content = content.replace(
        "HYDRAULIKDOC AI - Enterprise Edition v1.1",
        "HYDRAULIKDOC AI - Enterprise Edition v2.0"
    )
    
    content = content.replace(
        """CHANGELOG v1.1:
- Verbesserter Enterprise-grade System Prompt
- Bessere Synonym-Erkennung (Nenndruck, Hubgeschwindigkeit, etc.)
- Optimierte Chunk-Größe für besseren Kontext
- Hilfreichere Antworten statt "nicht enthalten\"""",
        """CHANGELOG v2.0 (Project Hephaestus):
- 🎥 Multimodal: Video + Audio + PDF Analyse mit Gemini 1.5 Pro
- 🔊 Audio-Anomalie Erkennung für Maschinendignose
- 📊 Tab-basierte UI: Dokument-Suche & Video-Diagnose
- ⚡ Enterprise-grade System Prompts (v1.1)"""
    )
    
    # Write modified content
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ app.py erfolgreich modifiziert!")
    print("\nÄnderungen:")
    print("  1. ✅ Gemini Video Analyzer Import hinzugefügt")
    print("  2. ✅ Tab-Struktur implementiert")
    print("  3. ✅ Version auf v2.0 erhöht")
    print("\nNächster Schritt: git diff app.py")

if __name__ == "__main__":
    try:
        modify_app()
    except Exception as e:
        print(f"❌ Fehler: {e}")
        sys.exit(1)
