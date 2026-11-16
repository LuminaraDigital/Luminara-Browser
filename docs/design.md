# Luminara Browser — Design System (`docs/design.md`)

Archetype: **Precision Dark UI × High-Density Telemetry Cockpit** (with full `light-dark()` WCAG 2.2 AA support).

```yaml
name: Luminara Browser Design System
version: "2.1.0"
archetype: precision-dark-telemetry-cockpit
colors:
  bg_canvas: "light-dark(oklch(0.975 0.005 255), oklch(0.115 0.012 255))"
  bg_panel: "light-dark(oklch(0.95 0.007 255), oklch(0.15 0.013 255))"
  bg_elevated: "light-dark(oklch(0.915 0.009 255), oklch(0.188 0.015 255))"
  bg_topbar: "light-dark(oklch(0.965 0.006 255 / 0.88), oklch(0.12 0.012 255 / 0.86))"
  ink_primary: "light-dark(oklch(0.15 0.015 255), oklch(0.965 0.005 255))"
  ink_secondary: "light-dark(oklch(0.34 0.015 255), oklch(0.78 0.012 255))"
  ink_muted: "light-dark(oklch(0.44 0.015 255), oklch(0.67 0.012 255))"
  accent_emerald: "light-dark(oklch(0.48 0.15 162), oklch(0.75 0.16 162))"
  status_amber: "light-dark(oklch(0.52 0.15 72), oklch(0.79 0.15 78))"
  status_danger: "light-dark(oklch(0.50 0.19 26), oklch(0.68 0.18 25))"
  hairline: "light-dark(oklch(0.15 0.01 255 / 0.12), oklch(1 0 0 / 0.09))"
typography:
  font_sans: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  font_mono: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace"
  display: "clamp(1.85rem, 3.4vw, 2.8rem) / 1.05 / -0.04em"
  heading: "clamp(1.05rem, 1.4vw, 1.35rem) / 1.2 / -0.025em"
  kicker: "0.6875rem / 1.2 / +0.11em uppercase mono"
  body: "clamp(0.84rem, 0.8rem + 0.2vw, 0.9375rem) / 1.5"
radii:
  shell_outer: "20px"
  card_outer: "16px"
  control_inner: "10px"
  badge_pill: "999px"
spacing:
  card_padding: "16px"
  shell_padding: "10px"
  grid_gap: "14px"
motion:
  ease_out: "cubic-bezier(0.16, 1, 0.3, 1)"
  duration_enter: "180ms"
  duration_exit: "120ms"
```

## Craft & Accessibility Rules (`H1–H50`)
- **Concentric Radius Law**: Outer shell (`20px`) = inner control (`10px`) + shell padding (`10px`).
- **Contrast**: `ink_muted` is `oklch(0.67 0.012 255)` on dark surfaces (`>= 4.8:1` WCAG AA) and `oklch(0.44 0.015 255)` on light surfaces (`>= 5.1:1` WCAG AA).
- **Focus Rings (`H38`)**: Universal `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`.
- **Async States (`H28–H32`, `H49`)**: Every live view implements `empty`, `loading` (with `STOP ■` `AbortController` on streaming/long tasks), `error` (what/why/retry), and `success`.
- **320px Reflow (`H9`)**: Every grid uses `min-width: 0` and `minmax(min(100%, 280px), 1fr)` with horizontal table scroll wrappers.
