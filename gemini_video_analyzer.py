"""
================================================================================
GEMINI MULTIMODAL ANALYZER - Project Hephaestus Core
================================================================================
Video + Audio + PDF simultane Analyse für industrielle Instandhaltung

Technology Stack:
- Google Vertex AI (Gemini 1.5 Pro - 2M Token Context)
- Video/Audio/PDF simultane Verarbeitung
- Enterprise-grade für B2B Industrial

Author: SBS Deutschland GmbH
Version: 1.1 (Streamlit Cloud Compatible)
================================================================================
"""

import os
import base64
import mimetypes
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import json

# ══════════════════════════════════════════════════════════════════════════════
# GEMINI VIDEO ANALYZER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class GeminiVideoAnalyzer:
    """
    Multimodaler Analyzer für Video + Audio + PDF
    Nutzt Gemini 1.5 Pro's massive 2M Token Context Window
    """
    
    def __init__(self, api_key: str = None, project_id: str = None, location: str = "europe-west3", credentials_json: str = None):
        """
        Initialize Gemini Video Analyzer
        
        Args:
            api_key: Google Cloud API Key (optional if using service account)
            project_id: Google Cloud Project ID
            location: Region (Default: europe-west3 = Frankfurt für DSGVO)
            credentials_json: JSON string of service account credentials (for Streamlit Cloud)
        """
        self.api_key = api_key
        self.project_id = project_id
        self.location = location
        self.model_name = "gemini-1.5-pro-002"
        self.credentials_json = credentials_json
        
        # Initialize Vertex AI
        self._initialize_vertexai()
    
    def _initialize_vertexai(self):
        """Initialize Vertex AI with proper credentials handling for Streamlit Cloud"""
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel, Part
            
            credentials = None
            
            # ═══════════════════════════════════════════════════════════════
            # CREDENTIALS HANDLING - Support multiple authentication methods
            # ═══════════════════════════════════════════════════════════════
            
            # Method 1: Explicit credentials JSON (for Streamlit Cloud)
            if self.credentials_json:
                from google.oauth2 import service_account
                
                # Parse JSON string if needed
                if isinstance(self.credentials_json, str):
                    creds_dict = json.loads(self.credentials_json)
                else:
                    creds_dict = self.credentials_json
                
                credentials = service_account.Credentials.from_service_account_info(
                    creds_dict,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                print("✅ Credentials loaded from JSON")
            
            # Method 2: Try Streamlit Secrets
            elif self._try_load_streamlit_secrets():
                credentials = self._try_load_streamlit_secrets()
                print("✅ Credentials loaded from Streamlit Secrets")
            
            # Method 3: Environment variable GOOGLE_APPLICATION_CREDENTIALS
            elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                # vertexai will handle this automatically
                print("✅ Using GOOGLE_APPLICATION_CREDENTIALS")
            
            # Method 4: Default credentials (GCE, Cloud Run, etc.)
            else:
                print("ℹ️ Using default credentials (may fail on Streamlit Cloud)")
            
            # Initialize Vertex AI
            init_kwargs = {"location": self.location}
            
            if self.project_id:
                init_kwargs["project"] = self.project_id
            
            if credentials:
                init_kwargs["credentials"] = credentials
            
            vertexai.init(**init_kwargs)
            
            self.GenerativeModel = GenerativeModel
            self.Part = Part
            self.initialized = True
            print(f"✅ Vertex AI initialized (Project: {self.project_id}, Location: {self.location})")
            
        except ImportError as e:
            print(f"⚠️ Vertex AI SDK nicht installiert: {e}")
            print("   Installiere: pip install google-cloud-aiplatform")
            self.initialized = False
        except Exception as e:
            print(f"⚠️ Vertex AI Initialisierung fehlgeschlagen: {e}")
            self.initialized = False
    
    def _try_load_streamlit_secrets(self):
        """Try to load credentials from Streamlit secrets"""
        try:
            import streamlit as st
            
            if "google_cloud" in st.secrets:
                gc = st.secrets["google_cloud"]
                
                # Update project_id and location if not set
                if not self.project_id and "project_id" in gc:
                    self.project_id = gc["project_id"]
                if "location" in gc:
                    self.location = gc["location"]
                
                # Load credentials
                if "credentials_json" in gc:
                    from google.oauth2 import service_account
                    
                    creds_str = gc["credentials_json"]
                    if isinstance(creds_str, str):
                        creds_dict = json.loads(creds_str)
                    else:
                        creds_dict = dict(creds_str)
                    
                    return service_account.Credentials.from_service_account_info(
                        creds_dict,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
            
            return None
            
        except Exception as e:
            print(f"ℹ️ Streamlit secrets not available: {e}")
            return None
    
    def _encode_file_to_base64(self, file_path: str) -> Optional[str]:
        """Encode file to base64 string"""
        try:
            with open(file_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"❌ Fehler beim Encodieren von {file_path}: {e}")
            return None
    
    def _get_mime_type(self, file_path: str) -> str:
        """Get MIME type of file"""
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or "application/octet-stream"
    
    def analyze_video_with_manual(
        self,
        video_path: str,
        pdf_path: str,
        question: Optional[str] = None,
        temperature: float = 0.1
    ) -> Dict[str, any]:
        """
        Analysiere Video + PDF gleichzeitig
        
        Args:
            video_path: Path zum Video (MP4, MOV, etc.)
            pdf_path: Path zum Wartungshandbuch (PDF)
            question: Spezifische Frage (optional)
            temperature: Kreativität (0.0 = deterministisch, 1.0 = kreativ)
            
        Returns:
            Dict mit Analyse-Ergebnissen
        """
        
        if not self.initialized:
            return {
                "success": False,
                "error": "Vertex AI nicht initialisiert. Bitte Credentials prüfen."
            }
        
        try:
            # Load files as Parts
            video_mime = self._get_mime_type(video_path)
            pdf_mime = self._get_mime_type(pdf_path)
            
            # Read video file
            video_data = self._encode_file_to_base64(video_path)
            if not video_data:
                return {"success": False, "error": f"Video konnte nicht geladen werden: {video_path}"}
            
            # Read PDF file
            pdf_data = self._encode_file_to_base64(pdf_path)
            if not pdf_data:
                return {"success": False, "error": f"PDF konnte nicht geladen werden: {pdf_path}"}
            
            # Create Parts from inline data
            video_part = self.Part.from_data(
                data=base64.b64decode(video_data),
                mime_type=video_mime
            )
            
            pdf_part = self.Part.from_data(
                data=base64.b64decode(pdf_data),
                mime_type=pdf_mime
            )
            
            # Enterprise-Grade Prompt für Techniker
            system_instruction = self._get_industrial_prompt()
            
            # User Question
            if question:
                user_prompt = f"""
Analysiere das Video und das Wartungshandbuch:

FRAGE: {question}

ANWEISUNGEN:
1. Analysiere Bild UND Ton des Videos
2. Suche relevante Informationen im Handbuch
3. Gib eine präzise technische Antwort mit Seitenzahlen
"""
            else:
                user_prompt = """
Analysiere das Video und das Wartungshandbuch:

AUFGABE:
1. Was zeigt das Video? (Maschine, Betriebszustand)
2. Welche Geräusche/Anomalien sind hörbar?
3. Welche Informationen aus dem Handbuch sind relevant?
4. Gibt es Probleme oder Wartungshinweise?
"""
            
            # Create model with system instruction
            model = self.GenerativeModel(
                self.model_name,
                system_instruction=system_instruction
            )
            
            # Generate response
            response = model.generate_content(
                [video_part, pdf_part, user_prompt],
                generation_config={
                    "temperature": temperature,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                }
            )
            
            return {
                "success": True,
                "analysis": response.text,
                "model": self.model_name,
                "video_file": video_path,
                "pdf_file": pdf_path
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def analyze_audio_anomaly(
        self,
        video_path: str,
        pdf_path: str,
        expected_behavior: str = None
    ) -> Dict[str, any]:
        """
        Spezialisierte Analyse für Audio-Anomalien
        (Das Kern-Feature für den "Digitalen Meister")
        """
        
        question = f"""
AUDIO-ANOMALIE DIAGNOSE:

Erwartetes Verhalten: {expected_behavior or "Normaler Betrieb"}

AUFGABE:
1. Höre das Video genau ab auf:
   - Ungewöhnliche Geräusche (Quietschen, Klappern, Schleifen)
   - Zeitstempel der Anomalie
   - Lautstärke/Intensität

2. Suche im Handbuch nach:
   - Wartungshinweisen für diese Geräusche
   - Toleranzwerten
   - Verschleißteilen

3. Gib eine PRÄZISE Diagnose:
   - Was ist das Problem?
   - Welches Teil ist betroffen?
   - Welche Seite im Handbuch?
   - Wie dringend ist die Reparatur?
"""
        
        return self.analyze_video_with_manual(
            video_path=video_path,
            pdf_path=pdf_path,
            question=question,
            temperature=0.0  # Sehr deterministisch für Diagnosen
        )
    
    def _get_industrial_prompt(self) -> str:
        """
        Enterprise-Grade System Instruction für industrielle Instandhaltung
        """
        return """
Du bist ein erfahrener Maschinen- und Anlagenmechaniker mit 20 Jahren Erfahrung in der industriellen Instandhaltung.

DEINE EXPERTISE:
- Hydraulik- und Pneumatiksysteme
- Mechanische Antriebe und Lager
- Audio-Diagnose (Geräusche deuten auf Verschleiß hin)
- Präventive Wartung
- Technische Dokumentation

ARBEITSWEISE:
1. VIDEO-ANALYSE:
   - Betrachte Bewegungen, Leckagen, Verschmutzung
   - HÖRE auf Geräusche: Quietschen, Klappern, Pfeifen, Schleifen
   - Notiere Zeitstempel von Anomalien

2. HANDBUCH-RECHERCHE:
   - Suche relevante Kapitel (Wartung, Störungen, Toleranzen)
   - Zitiere IMMER Seitenzahlen
   - Prüfe Tabellen und Schaltpläne

3. DIAGNOSE:
   - Beginne mit dem Hauptproblem
   - Gib konkrete Handlungsanweisungen
   - Nenne betroffene Bauteile mit Bezeichnungen aus dem Handbuch
   - Schätze Dringlichkeit: 🔴 Sofort / 🟡 Bald / 🟢 Routinewartung

4. SPRACHE:
   - Deutsch
   - Fachlich korrekt
   - Klar und handlungsorientiert
   - Keine Floskeln wie "könnte sein" → sei präzise

BEISPIEL GUTE ANTWORT:
"🔴 DRINGEND: Bei Sekunde 0:08 ist ein metallisches Schleifen hörbar. 
Diagnose: Wahrscheinlich Verschleiß am Axiallager (siehe Handbuch S. 42, Abb. 3.5).
Handlung: Maschine stoppen. Lager gemäß Montageanleitung S. 44 prüfen. 
Toleranz laut Tabelle 4 (S. 45): max. 0,1mm Spiel."
"""
    
    def _upload_to_gcs(self, local_path: str) -> str:
        """
        Upload file to Google Cloud Storage (für große Videos)
        Nur nötig wenn Video > 50MB
        """
        # Placeholder - implementiere wenn nötig
        raise NotImplementedError("GCS Upload noch nicht implementiert")


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_machine_video(
    video_path: str,
    manual_path: str,
    question: str = None,
    api_key: str = None,
    project_id: str = None,
    credentials_json: str = None
) -> Dict:
    """
    Convenience function für schnelle Analyse
    
    Args:
        video_path: Path zum Video
        manual_path: Path zum Wartungshandbuch
        question: Optionale Frage
        api_key: Google Cloud API Key
        project_id: Google Cloud Project ID
        credentials_json: JSON string of service account credentials
        
    Returns:
        Analyse-Ergebnis als Dict
    """
    analyzer = GeminiVideoAnalyzer(
        api_key=api_key, 
        project_id=project_id,
        credentials_json=credentials_json
    )
    return analyzer.analyze_video_with_manual(video_path, manual_path, question)


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT INTEGRATION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def create_analyzer_from_streamlit_secrets():
    """
    Create analyzer using Streamlit secrets
    Call this from your Streamlit app
    
    Usage in app.py:
        from gemini_video_analyzer import create_analyzer_from_streamlit_secrets
        analyzer = create_analyzer_from_streamlit_secrets()
    """
    try:
        import streamlit as st
        
        gc = st.secrets.get("google_cloud", {})
        
        return GeminiVideoAnalyzer(
            project_id=gc.get("project_id"),
            location=gc.get("location", "europe-west3"),
            credentials_json=gc.get("credentials_json")
        )
    except Exception as e:
        print(f"❌ Failed to create analyzer from secrets: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# EXAMPLE USAGE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Example: Analysiere ein Video einer laufenden Hydraulikpumpe
    """
    
    print("="*80)
    print("GEMINI MULTIMODAL ANALYZER - Demo")
    print("="*80)
    
    # Example paths
    VIDEO_PATH = "hydraulikpumpe_video.mp4"
    MANUAL_PATH = "wartungshandbuch.pdf"
    
    # Option 1: Mit spezifischer Frage
    print("\n🔍 Starte Analyse mit Frage...")
    
    analyzer = GeminiVideoAnalyzer(
        project_id="your-project-id",  # Ersetze mit deiner Project ID
        location="europe-west3"  # Frankfurt
    )
    
    result = analyzer.analyze_video_with_manual(
        video_path=VIDEO_PATH,
        pdf_path=MANUAL_PATH,
        question="Welche Anomalien sind im Video erkennbar und wie sollte ich vorgehen?"
    )
    
    if result["success"]:
        print("\n✅ Analyse erfolgreich!")
        print("\n" + "="*80)
        print("DIAGNOSE:")
        print("="*80)
        print(result["analysis"])
    else:
        print(f"\n❌ Fehler: {result['error']}")
    
    # Option 2: Audio-Anomalie Diagnose
    print("\n\n🔊 Starte Audio-Anomalie Diagnose...")
    
    audio_result = analyzer.analyze_audio_anomaly(
        video_path=VIDEO_PATH,
        pdf_path=MANUAL_PATH,
        expected_behavior="Gleichmäßiges Laufgeräusch bei 1450 U/min"
    )
    
    if audio_result["success"]:
        print("\n✅ Audio-Diagnose erfolgreich!")
        print("\n" + "="*80)
        print("AUDIO-ANALYSE:")
        print("="*80)
        print(audio_result["analysis"])
    else:
        print(f"\n❌ Fehler: {audio_result['error']}")
