'use client';

import Link from 'next/link';

export default function SecurityPage() {
  const securityFeatures = [
    {
      icon: '🇩🇪',
      title: 'Datenstandort Deutschland',
      description: 'Alle Daten werden ausschließlich in deutschen Rechenzentren (Hetzner, Frankfurt) gespeichert und verarbeitet. Keine Datenübertragung in Drittländer.',
      status: 'active',
    },
    {
      icon: '🔐',
      title: 'Verschlüsselung',
      description: 'AES-256 Verschlüsselung für Daten at rest. TLS 1.3 für alle Datenübertragungen. Keine unverschlüsselten Verbindungen möglich.',
      status: 'active',
    },
    {
      icon: '👤',
      title: 'Rollen-basierte Zugriffskontrolle (RBAC)',
      description: 'Granulare Berechtigungen für jeden Benutzer. Trennung zwischen Admin, User und Read-Only Rollen. Abteilungsspezifische Zugriffsrechte.',
      status: 'active',
    },
    {
      icon: '📝',
      title: 'Audit Logs',
      description: 'Vollständige Protokollierung aller Aktionen. Export-Funktion für Compliance-Audits. 12 Monate Aufbewahrung standardmäßig.',
      status: 'active',
    },
    {
      icon: '🔑',
      title: 'Single Sign-On (SSO)',
      description: 'Google OAuth bereits verfügbar. Microsoft Entra ID (Azure AD) in Entwicklung für Q2 2026. SAML 2.0 für Enterprise-Kunden.',
      status: 'partial',
    },
    {
      icon: '🛡️',
      title: 'SOC 2 Type II',
      description: 'Zertifizierung geplant für Q3 2026. Basierend auf bereits implementierten Kontrollen. Unabhängige Prüfung durch akkreditierten Auditor.',
      status: 'planned',
    },
  ];

  const complianceItems = [
    {
      name: 'DSGVO',
      status: 'compliant',
      details: 'Vollständig konform mit der EU-Datenschutz-Grundverordnung. Auftragsverarbeitungsvertrag (AVV) verfügbar.',
    },
    {
      name: 'GoBD',
      status: 'compliant',
      details: 'Konform mit den Grundsätzen zur ordnungsmäßigen Führung und Aufbewahrung von Büchern. Revisionssichere Archivierung.',
    },
    {
      name: 'ISO 27001',
      status: 'in-progress',
      details: 'Implementierung eines ISMS nach ISO 27001. Zertifizierung geplant für 2027.',
    },
  ];

  const dataFlowSteps = [
    { step: '1', title: 'Upload', description: 'Dokumente werden über HTTPS/TLS 1.3 hochgeladen' },
    { step: '2', title: 'Verarbeitung', description: 'AI-Analyse in isolierter Umgebung, keine Datenweitergabe an Dritte' },
    { step: '3', title: 'Speicherung', description: 'AES-256 verschlüsselt in deutschem Rechenzentrum' },
    { step: '4', title: 'Export', description: 'DATEV/SAP-Export über sichere API-Verbindung' },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800/50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 bg-orange-500 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">SBS</span>
            </div>
            <span className="text-white font-semibold">SBS Nexus</span>
          </Link>
          <nav className="flex items-center gap-6">
            <Link href="/#modules" className="text-slate-400 hover:text-white text-sm">Module</Link>
            <Link href="/pricing" className="text-slate-400 hover:text-white text-sm">Pricing</Link>
            <Link href="/security" className="text-white text-sm font-medium">Security</Link>
            <Link 
              href="https://calendly.com/ki-sbsdeutschland/sbs-nexus-30-minuten-discovery-call"
              className="bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition"
            >
              Demo buchen
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="py-20 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-green-500/20 text-green-400 px-4 py-2 rounded-full text-sm mb-6">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            Trust Center
          </div>
          <h1 className="text-4xl md:text-5xl font-bold text-white mb-6">
            Sicherheit & Datenschutz
          </h1>
          <p className="text-xl text-slate-400">
            Ihre Daten bleiben in Deutschland. DSGVO-konform by Design. 
            Gebaut für die Sicherheitsanforderungen des deutschen Mittelstands.
          </p>
        </div>
      </section>

      {/* Trust Badges */}
      <section className="pb-16 px-6">
        <div className="max-w-4xl mx-auto flex flex-wrap justify-center gap-4">
          {[
            { label: '100% Deutsche Server', icon: '🇩🇪' },
            { label: 'DSGVO-konform', icon: '✅' },
            { label: 'AES-256 Verschlüsselung', icon: '🔐' },
            { label: 'Audit Logs', icon: '📝' },
          ].map((badge, idx) => (
            <div key={idx} className="flex items-center gap-2 bg-slate-800/50 px-4 py-2 rounded-full">
              <span>{badge.icon}</span>
              <span className="text-white text-sm font-medium">{badge.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Security Features Grid */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl font-bold text-white text-center mb-12">
            Sicherheitsfeatures
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {securityFeatures.map((feature, idx) => (
              <div key={idx} className="bg-slate-800/30 rounded-xl p-6 border border-slate-700/50">
                <div className="flex items-start justify-between mb-4">
                  <span className="text-3xl">{feature.icon}</span>
                  <span className={`text-xs px-2 py-1 rounded-full ${
                    feature.status === 'active' 
                      ? 'bg-green-500/20 text-green-400' 
                      : feature.status === 'partial'
                      ? 'bg-yellow-500/20 text-yellow-400'
                      : 'bg-blue-500/20 text-blue-400'
                  }`}>
                    {feature.status === 'active' ? 'Aktiv' : feature.status === 'partial' ? 'Teilweise' : 'Geplant'}
                  </span>
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                <p className="text-slate-400 text-sm">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Data Flow Diagram */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-white text-center mb-4">
            Datenfluss
          </h2>
          <p className="text-slate-400 text-center mb-12">
            So werden Ihre Dokumente sicher verarbeitet
          </p>
          <div className="grid md:grid-cols-4 gap-4">
            {dataFlowSteps.map((item, idx) => (
              <div key={idx} className="relative">
                <div className="bg-slate-800/50 rounded-xl p-6 text-center h-full">
                  <div className="w-10 h-10 bg-orange-500 rounded-full flex items-center justify-center text-white font-bold mx-auto mb-4">
                    {item.step}
                  </div>
                  <h3 className="text-white font-semibold mb-2">{item.title}</h3>
                  <p className="text-slate-400 text-sm">{item.description}</p>
                </div>
                {idx < dataFlowSteps.length - 1 && (
                  <div className="hidden md:block absolute top-1/2 -right-2 transform -translate-y-1/2">
                    <svg className="w-4 h-4 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Compliance Table */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-white text-center mb-12">
            Compliance & Zertifizierungen
          </h2>
          <div className="bg-slate-800/30 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-800/50">
                <tr>
                  <th className="text-left text-white font-semibold px-6 py-4">Standard</th>
                  <th className="text-left text-white font-semibold px-6 py-4">Status</th>
                  <th className="text-left text-white font-semibold px-6 py-4">Details</th>
                </tr>
              </thead>
              <tbody>
                {complianceItems.map((item, idx) => (
                  <tr key={idx} className="border-t border-slate-700/50">
                    <td className="px-6 py-4 text-white font-medium">{item.name}</td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1 text-sm px-3 py-1 rounded-full ${
                        item.status === 'compliant' 
                          ? 'bg-green-500/20 text-green-400' 
                          : 'bg-yellow-500/20 text-yellow-400'
                      }`}>
                        {item.status === 'compliant' ? (
                          <>
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                            Konform
                          </>
                        ) : (
                          <>
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            In Arbeit
                          </>
                        )}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-400 text-sm">{item.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Subprocessors */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-white text-center mb-4">
            Unterauftragsverarbeiter
          </h2>
          <p className="text-slate-400 text-center mb-12">
            Diese Drittanbieter verarbeiten Daten in unserem Auftrag
          </p>
          <div className="grid md:grid-cols-2 gap-6">
            {[
              { name: 'Hetzner Online GmbH', location: 'Frankfurt, Deutschland', purpose: 'Cloud Hosting, Datenspeicherung' },
              { name: 'Vercel Inc.', location: 'USA (EU Data Region)', purpose: 'Frontend Hosting (nur statische Assets)' },
              { name: 'OpenAI', location: 'USA', purpose: 'AI-Verarbeitung (keine Speicherung, API-only)' },
              { name: 'Anthropic', location: 'USA', purpose: 'AI-Verarbeitung (keine Speicherung, API-only)' },
            ].map((item, idx) => (
              <div key={idx} className="bg-slate-800/30 rounded-xl p-5 border border-slate-700/50">
                <h3 className="text-white font-semibold mb-1">{item.name}</h3>
                <p className="text-orange-400 text-sm mb-2">{item.location}</p>
                <p className="text-slate-400 text-sm">{item.purpose}</p>
              </div>
            ))}
          </div>
          <p className="text-center text-slate-500 text-sm mt-8">
            * AI-Anfragen an OpenAI/Anthropic enthalten keine personenbezogenen Daten. 
            Dokumente werden vor der Verarbeitung anonymisiert.
          </p>
        </div>
      </section>

      {/* AVV Download */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-6">
            Dokumente für Ihre IT-Abteilung
          </h2>
          <p className="text-slate-400 mb-8">
            Laden Sie die erforderlichen Compliance-Dokumente herunter
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            {[
              { name: 'Auftragsverarbeitungsvertrag (AVV)', format: 'PDF' },
              { name: 'Technische & Organisatorische Maßnahmen (TOMs)', format: 'PDF' },
              { name: 'Security Whitepaper', format: 'PDF' },
            ].map((doc, idx) => (
              <button
                key={idx}
                className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-white px-5 py-3 rounded-lg transition"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                {doc.name}
                <span className="text-xs text-slate-400">({doc.format})</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Contact Security */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-6">
            Fragen zur Sicherheit?
          </h2>
          <p className="text-slate-400 mb-8">
            Unser Team steht für Sicherheitsaudits, Penetration Tests oder spezifische Compliance-Fragen zur Verfügung.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Link
              href="mailto:security@sbsdeutschland.com"
              className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 text-white px-6 py-3 rounded-lg font-medium transition"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              security@sbsdeutschland.com
            </Link>
            <Link
              href="https://calendly.com/ki-sbsdeutschland/sbs-nexus-30-minuten-discovery-call"
              className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 text-white px-6 py-3 rounded-lg font-medium transition"
            >
              Security Call vereinbaren
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 py-8 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-slate-500 text-sm">
            © 2026 SBS Deutschland GmbH · Weinheim · Alle Rechte vorbehalten.
          </p>
          <div className="flex gap-6">
            <Link href="/security" className="text-white text-sm">Security</Link>
            <Link href="/impressum" className="text-slate-500 hover:text-white text-sm">Impressum</Link>
            <Link href="/datenschutz" className="text-slate-500 hover:text-white text-sm">Datenschutz</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
