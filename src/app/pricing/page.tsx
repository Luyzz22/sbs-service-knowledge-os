'use client';

import Link from 'next/link';
import { useState } from 'react';

export default function PricingPage() {
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>('annual');
  
  const plans = [
    {
      name: 'Pilot',
      description: 'Proof-of-Value für 3 Monate',
      monthlyPrice: 1990,
      annualPrice: 1990, // No discount for pilot
      features: [
        'Alle 3 Module (Finance, Contract, Technical)',
        'Bis zu 5 Benutzer',
        '500 Dokumente/Monat',
        'DATEV-Export inklusive',
        '10h Onboarding & Consulting',
        'Bi-weekly Optimization Calls',
        'Dedicated Success Manager',
      ],
      cta: 'Pilot starten',
      highlight: true,
      badge: 'Empfohlen',
    },
    {
      name: 'Growth',
      description: 'Für Mittelstand 50-500 MA',
      monthlyPrice: 4990,
      annualPrice: 4158, // ~17% discount
      features: [
        'Alle 3 Module',
        'Bis zu 25 Benutzer',
        '2.500 Dokumente/Monat',
        'DATEV + SAP Integration',
        'n8n Workflow-Templates',
        'Priority Support (4h Response)',
        'Quarterly Business Reviews',
        'API-Zugang',
      ],
      cta: 'Demo buchen',
      highlight: false,
    },
    {
      name: 'Enterprise',
      description: 'Für Konzerne & Werksverbünde',
      monthlyPrice: null,
      annualPrice: null,
      features: [
        'Unlimited Benutzer',
        'Unlimited Dokumente',
        'SSO/SAML Integration',
        'Dedicated Infrastructure Option',
        'Custom Connectors (SAP, ERP)',
        'SLA mit 99.9% Uptime',
        '24/7 Premium Support',
        'On-Premise Deployment möglich',
        'Audit & Compliance Reports',
      ],
      cta: 'Kontakt aufnehmen',
      highlight: false,
    },
  ];

  const faqs = [
    {
      question: 'Was passiert nach dem Pilot?',
      answer: 'Nach 3 Monaten evaluieren wir gemeinsam den ROI. Bei positivem Ergebnis wechseln Sie nahtlos in den Growth- oder Enterprise-Tarif. Keine versteckten Kosten, keine Lock-in-Klauseln.',
    },
    {
      question: 'Welche Dokumente werden unterstützt?',
      answer: 'Finance Intelligence: PDF-Rechnungen, E-Rechnungen (XRechnung, ZUGFeRD), Scans. Contract Intelligence: PDF-Verträge aller Art. Technical Intelligence: Technische Datenblätter, Handbücher, DIN/ISO-Normen (PDF).',
    },
    {
      question: 'Wie funktioniert die DATEV-Integration?',
      answer: 'Wir exportieren Buchungssätze im DATEV-Format (CSV/XML), die direkt in DATEV Unternehmen Online oder über Ihren Steuerberater importiert werden können. Native API-Integration ist für Q3 2026 geplant.',
    },
    {
      question: 'Wo werden meine Daten gespeichert?',
      answer: '100% in deutschen Rechenzentren (Hetzner, Frankfurt). Keine Datenübertragung in die USA oder andere Drittländer. DSGVO-konform by Design.',
    },
    {
      question: 'Kann ich einzelne Module buchen?',
      answer: 'Ja, ab dem Growth-Tarif können Sie mit einem Modul starten (z.B. nur Finance Intelligence für €2.990/Monat) und später erweitern. Der Pilot enthält immer alle Module zum Testen.',
    },
    {
      question: 'Gibt es eine kostenlose Testversion?',
      answer: 'Wir bieten eine 14-tägige Sandbox mit Sample-Daten an. Für Tests mit Ihren echten Dokumenten empfehlen wir den Pilot-Tarif mit vollem Support.',
    },
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
            <Link href="/pricing" className="text-white text-sm font-medium">Pricing</Link>
            <Link href="/security" className="text-slate-400 hover:text-white text-sm">Security</Link>
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
          <h1 className="text-4xl md:text-5xl font-bold text-white mb-6">
            Transparentes Pricing für den Mittelstand
          </h1>
          <p className="text-xl text-slate-400 mb-10">
            Keine versteckten Kosten. Keine Lock-in-Klauseln. Starten Sie mit einem Pilot und skalieren Sie nach Bedarf.
          </p>
          
          {/* Billing Toggle */}
          <div className="flex items-center justify-center gap-4 mb-12">
            <span className={`text-sm ${billingCycle === 'monthly' ? 'text-white' : 'text-slate-500'}`}>
              Monatlich
            </span>
            <button
              onClick={() => setBillingCycle(billingCycle === 'monthly' ? 'annual' : 'monthly')}
              className="relative w-14 h-7 bg-slate-700 rounded-full transition"
            >
              <div className={`absolute top-1 w-5 h-5 bg-orange-500 rounded-full transition-all ${
                billingCycle === 'annual' ? 'left-8' : 'left-1'
              }`} />
            </button>
            <span className={`text-sm ${billingCycle === 'annual' ? 'text-white' : 'text-slate-500'}`}>
              Jährlich
            </span>
            {billingCycle === 'annual' && (
              <span className="bg-green-500/20 text-green-400 text-xs px-2 py-1 rounded-full">
                2 Monate gratis
              </span>
            )}
          </div>
        </div>
      </section>

      {/* Pricing Cards */}
      <section className="pb-20 px-6">
        <div className="max-w-6xl mx-auto grid md:grid-cols-3 gap-8">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`relative rounded-2xl p-8 ${
                plan.highlight
                  ? 'bg-gradient-to-b from-orange-500/20 to-slate-800/50 border-2 border-orange-500/50'
                  : 'bg-slate-800/50 border border-slate-700/50'
              }`}
            >
              {plan.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="bg-orange-500 text-white text-xs font-medium px-3 py-1 rounded-full">
                    {plan.badge}
                  </span>
                </div>
              )}
              
              <h3 className="text-2xl font-bold text-white mb-2">{plan.name}</h3>
              <p className="text-slate-400 text-sm mb-6">{plan.description}</p>
              
              <div className="mb-8">
                {plan.monthlyPrice ? (
                  <>
                    <span className="text-4xl font-bold text-white">
                      €{billingCycle === 'annual' ? plan.annualPrice?.toLocaleString() : plan.monthlyPrice.toLocaleString()}
                    </span>
                    <span className="text-slate-400">/Monat</span>
                    {billingCycle === 'annual' && plan.name !== 'Pilot' && (
                      <p className="text-green-400 text-sm mt-1">
                        €{((plan.monthlyPrice - (plan.annualPrice || 0)) * 12).toLocaleString()} jährlich gespart
                      </p>
                    )}
                  </>
                ) : (
                  <span className="text-3xl font-bold text-white">Auf Anfrage</span>
                )}
              </div>
              
              <ul className="space-y-3 mb-8">
                {plan.features.map((feature, idx) => (
                  <li key={idx} className="flex items-start gap-3 text-sm text-slate-300">
                    <svg className="w-5 h-5 text-green-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {feature}
                  </li>
                ))}
              </ul>
              
              <Link
                href="https://calendly.com/ki-sbsdeutschland/sbs-nexus-30-minuten-discovery-call"
                className={`block text-center py-3 rounded-lg font-medium transition ${
                  plan.highlight
                    ? 'bg-orange-500 hover:bg-orange-600 text-white'
                    : 'bg-slate-700 hover:bg-slate-600 text-white'
                }`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Usage Overages */}
      <section className="py-16 px-6 border-t border-slate-800/50">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-2xl font-bold text-white text-center mb-10">
            Flexible Nutzungsabrechnung
          </h2>
          <div className="grid md:grid-cols-4 gap-6">
            {[
              { item: 'Zusätzliche Rechnungen', price: '€0,30', unit: 'pro Rechnung' },
              { item: 'Zusätzliche Verträge', price: '€2,50', unit: 'pro Vertrag' },
              { item: 'Zusätzliche Tech-Docs', price: '€5,00', unit: 'pro Dokument' },
              { item: 'AI Query Credits', price: '€0,05', unit: 'pro Query' },
            ].map((item, idx) => (
              <div key={idx} className="bg-slate-800/30 rounded-xl p-5 text-center">
                <p className="text-slate-400 text-sm mb-2">{item.item}</p>
                <p className="text-2xl font-bold text-white">{item.price}</p>
                <p className="text-slate-500 text-xs">{item.unit}</p>
              </div>
            ))}
          </div>
          <p className="text-center text-slate-500 text-sm mt-6">
            * Overages werden nur berechnet, wenn das monatliche Kontingent überschritten wird.
          </p>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 px-6 border-t border-slate-800/50">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold text-white text-center mb-12">
            Häufig gestellte Fragen
          </h2>
          <div className="space-y-6">
            {faqs.map((faq, idx) => (
              <div key={idx} className="bg-slate-800/30 rounded-xl p-6">
                <h3 className="text-lg font-semibold text-white mb-3">{faq.question}</h3>
                <p className="text-slate-400">{faq.answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-6">
            Bereit für den nächsten Schritt?
          </h2>
          <p className="text-slate-400 mb-8">
            30-Minuten Discovery Call – wir zeigen Ihnen live, wie SBS Nexus Ihre Prozesse automatisiert.
          </p>
          <Link
            href="https://calendly.com/ki-sbsdeutschland/sbs-nexus-30-minuten-discovery-call"
            className="inline-flex items-center gap-2 bg-orange-500 hover:bg-orange-600 text-white px-8 py-4 rounded-xl font-semibold text-lg transition"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            Demo buchen
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 py-8 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-slate-500 text-sm">
            © 2026 SBS Deutschland GmbH · Weinheim · Alle Rechte vorbehalten.
          </p>
          <div className="flex gap-6">
            <Link href="/security" className="text-slate-500 hover:text-white text-sm">Security</Link>
            <Link href="/impressum" className="text-slate-500 hover:text-white text-sm">Impressum</Link>
            <Link href="/datenschutz" className="text-slate-500 hover:text-white text-sm">Datenschutz</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
