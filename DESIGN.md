---
version: alpha
name: HydraulikDoc Industrial Evidence System
description: A restrained industrial workspace that keeps assets, source evidence, risk and human responsibility visually explicit.
colors:
  primary: "#C55218"
  primary-hover: "#9F3F10"
  canvas: "#F4F6F7"
  surface: "#FFFFFF"
  ink: "#16202A"
  muted: "#536171"
  border: "#D6DDE3"
  navigation: "#102B3F"
  focus: "#2383C4"
  warning: "#B7791F"
  danger: "#B42318"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 60px
    fontWeight: 650
    lineHeight: 0.98
    letterSpacing: -0.04em
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
rounded:
  control: 8px
  surface: 16px
spacing:
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  section: 64px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    height: 44px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
  focus-indicator:
    backgroundColor: "{colors.focus}"
  page:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.surface}"
  divider:
    backgroundColor: "{colors.border}"
  sidebar:
    backgroundColor: "{colors.navigation}"
    textColor: "{colors.surface}"
  caption:
    textColor: "{colors.muted}"
  notice-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  warning-accent:
    backgroundColor: "{colors.warning}"
  notice-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
---

## Overview

HydraulikDoc is an evidence-first industrial interface. It prioritizes operational state, original sources, review responsibility and release evidence over decorative AI effects. The interface must never make a generated answer look like an approved instruction.

## Colors

`primary` and `primary-hover` mark the single primary action. `canvas` separates the application background from `surface` cards. `ink`, `muted` and `border` establish readable information hierarchy. `navigation` anchors the sidebar. `focus` is reserved for visible keyboard focus. `warning` marks mandatory review and `danger` marks blocked or safety-critical states; both are always accompanied by text.

## Typography

Use the system sans-serif stack to avoid third-party font requests and reduce layout shift. Display typography is limited to the product hero. Body text uses a 16 px base and compact but readable line height. Tables and evidence IDs may use the platform monospace style, never as the primary reading face.

## Layout

The working canvas is capped at 1440 px. The hero uses a two-column evidence layout on desktop and collapses to one column below 1100 px so that tablet layouts remain readable beside responsive navigation. Primary data tables remain horizontally scrollable instead of truncating safety-relevant fields. At 360 px, forms become single-column and retain 44 px controls. At 768, 1280 and 1440 px, hierarchy and navigation remain unchanged.

## Elevation & Depth

Depth comes from surface contrast and one-pixel borders, not heavy shadows or glass effects. Critical states use a four-pixel left rule and clear heading. Modal depth is delegated to accessible Streamlit primitives.

## Shapes

Controls use 8 px corners and bounded work surfaces use 16 px corners. Pills are reserved for real status semantics. Circular decoration, blob backgrounds and excessive nested cards are forbidden.

## Components

The primary button is copper with white text, a darker hover state and blue keyboard focus. Cards use white on the gray canvas with the border token. Sidebar navigation is navy. Captions use muted ink. Warning and danger notices combine their accent token with explicit copy. Answer panels must show limitations, sources, provenance and review controls as one unit.

Interaction states must cover loading, disabled, empty, error, blocked, draft, accepted, rejected and expert-review states. Reduced-motion preferences remove transitions. Keyboard order follows visual order; all native controls retain their accessible name and state.

Evidence boundaries are visible: “implemented” references code, “configured” references deployment state, and “external gate” references evidence not inferable from the UI. No component may display “DSGVO-konform”, “EU-only”, “certified”, an uptime figure or a customer logo unless the corresponding approved evidence is connected.

## Do's and Don'ts

- Do lead with asset, source, risk and next responsible action.
- Do show model deployment, snapshot, prompt version, region and review state together.
- Do preserve German technical terminology and explicit safety qualifiers.
- Do use text plus color for every status.
- Don't present AI output as a maintenance release, legal conclusion or manufacturer instruction.
- Don't hide sources, limitations or external release gates behind tooltips.
- Don't add third-party fonts, trackers, remote images or client-side secrets.
- Don't use gradients, glassmorphism, animated counters, fake certification marks or unsupported compliance claims.
