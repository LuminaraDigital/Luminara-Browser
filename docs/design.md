---
version: alpha
name: Luminara Browser v4 Design System
description: Warm Atelier Precision x Calm Spatial OS for multiplayer human + AI co-browsing, with WCAG 2.2 AA Light/Dark/System modes and ambient per-Bot color washes.

colors:
  bg_canvas_light: "#FAF9F6"
  bg_rail_light: "#F3F1EC"
  bg_surface_light: "#FFFFFF"
  bg_elevated_light: "#ECEAE3"
  ink_primary_light: "#1C1E24"
  ink_secondary_light: "#555A66"
  ink_muted_light: "#5A5F6B"
  bg_canvas_dark: "#141519"
  bg_rail_dark: "#1A1C22"
  bg_surface_dark: "#1F2229"
  bg_elevated_dark: "#282C35"
  ink_primary_dark: "#F6F5F0"
  ink_secondary_dark: "#B5BAC6"
  ink_muted_dark: "#8F96A5"
  accent_brand: "#117A5E"
  accent_brand_dark: "#3CD0A3"
  accent_ink_light: "#FFFFFF"
  accent_ink_dark: "#081C15"
  bot_remy: "#16A095"
  bot_dana: "#2E7CF6"
  bot_pi: "#7C4DFF"
  status_warn: "#8F5906"
  status_warn_dark: "#F2B649"
  status_danger: "#BA2D2D"
  status_danger_dark: "#F06E6E"
  danger_ink_light: "#FFFFFF"
  danger_ink_dark: "#1B0909"
  hairline_light: "#E4E2DB"
  hairline_dark: "#2C303A"
  border_control_light: "#8C8980"
  border_control_dark: "#676E82"

typography:
  display:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.035em"
  heading:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  body:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "-0.005em"
  caption:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.01em"
  kicker:
    fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.09em"

rounded:
  shell: "20px"
  card: "16px"
  control: "10px"
  pill: "999px"

spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  rail: "248px"
  drawer: "336px"

components:
  button-primary:
    backgroundColor: "{colors.accent_brand}"
    textColor: "{colors.accent_ink_light}"
    typography: "{typography.caption}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-danger:
    backgroundColor: "{colors.status_danger}"
    textColor: "{colors.danger_ink_light}"
    typography: "{typography.caption}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-ghost:
    backgroundColor: "{colors.bg_surface_light}"
    textColor: "{colors.ink_primary_light}"
    typography: "{typography.caption}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  approval-card:
    backgroundColor: "{colors.bg_surface_light}"
    textColor: "{colors.ink_primary_light}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: "16px"
  omnibox-shell:
    backgroundColor: "{colors.bg_surface_light}"
    textColor: "{colors.ink_primary_light}"
    typography: "{typography.body}"
    rounded: "{rounded.shell}"
    padding: "10px"
---

# Luminara Browser v4 Design System

## Overview
Luminara Browser v4 pairs **Warm Atelier Precision** with a **Calm Spatial OS** built for daily human browsing alongside a local team of named AI Bots. Everyday surfaces feel calm, quiet, and immediately legible—like a refined studio workspace—never like a cyberpunk DevOps dashboard. Power-user diagnostics (MCP endpoints, cryptographic ledgers, sequence guards, VRT) live behind an opt-in Developer Mode.

## Colors
Light (Warm Alabaster `#FAF9F6` canvas, Soft Stone `#F3F1EC` rail), Dark (Deep Obsidian `#141519` canvas, Smoked Graphite `#1A1C22` rail), and System/Auto modes are all first-class citizens mathematically verified against WCAG 2.2 AA (`>= 4.5:1` body/muted text, `>= 3:1` control borders):
- Primary brand accent: `#117A5E` light (`5.29:1` on `#FFFFFF`, `5.03:1` on `#FAF9F6`) with `#FFFFFF` ink / `#3CD0A3` dark with `#081C15` ink.
- Muted text: `#5A5F6B` light (`5.31:1` on `#ECEAE3`) / `#8F96A5` dark.
- Status warnings & danger: `#8F5906` warn (`5.83:1` on `#FFFFFF`, `4.85:1` on `#ECEAE3`) / `#F2B649` dark; `#BA2D2D` danger (`6.00:1` on `#FFFFFF`, `4.98:1` on `#ECEAE3`) with `#FFFFFF` ink / `#F06E6E` dark with `#1B0909` ink (`6.57:1`).
- Control borders: `#8C8980` light (`3.50:1` on `#FFFFFF`, `3.32:1` on `#FAF9F6`) / `#676E82` dark (`3.13:1` on `#1F2229`, `3.59:1` on `#141519`).
- Ambient Bot washes (`10–14%` radial top tint) use assigned Bot colors (`Remy` teal, `Dana` cobalt, `Pi` violet) for instant spatial orientation without neon glare.

## Typography
Human-first sans typography (`Inter` / system UI) drives 95% of the interface with optical tracking (`-0.035em` display, `-0.02em` headings) and `text-wrap: balance` on headings. `JetBrains Mono` with `font-variant-numeric: tabular-nums` is strictly reserved for URLs, keyboard shortcuts (`Alt+K / Ctrl+Shift+K` in Chromium, `Ctrl+K` in Desktop Shell), timestamps, and numeric metrics—never for everyday buttons, chat bubbles, or explanations.

## Layout
A unified **3-Zone Spatial Shell**: collapsible Left Space & Bot Rail (`248px`), full-speed Center Web Stage (`flex: 1`, native 60fps Chromium), and toggleable Right Contextual Team Drawer (`336px`). Layouts snap to a `4px / 8px / 12px / 16px / 24px` rhythm, preserve generous whitespace on Home (`max-width: 780px` centered focal column), and reflow cleanly down to `320px` with `min-width: 0` and zero horizontal scroll.

## Elevation & Depth
Light mode separates surfaces via warm tonal contrast plus delicate multi-layer shadows (`0 8px 28px -12px rgba(20,22,28,0.12)`) and `1px` hairlines (`#E4E2DB`). Dark mode derives depth from above using tonal surface steps (`#141519` → `#1A1C22` → `#1F2229` → `#282C35`) paired with a crisp `1px` top specular catch-light (`inset 0 1px 0 rgba(255,255,255,0.08)`).

## Shapes
Enforce the **Concentric Radius Law** ($R_{\text{outer}} = R_{\text{inner}} + \text{padding}$): outer omnibox/window shells use `20px`, inner cards use `16px`, interactive controls/inputs use `10px`, and status/receipt/action pills use `999px`.

## Components
Every interactive control ships default, hover (`translateY(-1px)`), active (`scale(0.97)`), `:focus-visible` (`2px` accent ring, `2px` offset), disabled, and loading (`STOP` `AbortController`) states. AI outputs render as clean conversational cards with collapsible `Work receipt` pills (`duration · source · shield`) plus Copy/Regenerate actions. Risky mutations pause on a uniform **Approval Card** (warm `var(--warn)` left accent) showing plain-English intent, expandable *"Why am I asked?"* policy trace, scrubbed diff, and `Deny | Allow once (primary) | Always for site`.

## Do's and Don'ts
- **Do** start instantly (`<50ms`) with a crisp `<1 KB` SVG mark and zero blocking splash overlays.
- **Do** use plain human language on every button, notification, and approval card.
- **Do** implement all 4 async states (`empty`, `loading`, `error` with recovery, `success`) and honor `prefers-reduced-motion`.
- **Do** keep `docs/design.md` and `docs/design.html` synchronized on every token edit.
- **Don't** display raw `JSON.stringify` dumps, port numbers (`:9229`, `:8796`), `.void0` trap jargon, or SHA-256 hashes in daily browsing views.
- **Don't** animate from `scale(0)`, burn continuous 60fps GPU shaders on idle tabs, or mix neon purple-blue gradients with gold/emerald palettes.
- **Don't** assign `.innerHTML` anywhere in generated UI or extension scripts.
