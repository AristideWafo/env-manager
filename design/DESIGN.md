# Design system — Env Manager

This document turns the visual evidence in `mockup/*.png` into reusable
rules for Env Manager. The mockups show another operational product, so their
content and product-specific components are references, not requirements.

Confidence labels are used where the distinction matters:

- **HIGH** — repeated or clearly visible in the references and/or code.
- **MEDIUM** — supported, but not demonstrated in every reference.
- **LOW** — plausible direction that must be validated before implementation.

Exact implementation values live in [`static/css/theme.css`](../static/css/theme.css).
This document defines how to use them.

## Project frontend audit

| Concern | Current implementation |
|---|---|
| Framework | Server-rendered Django templates |
| Interaction | HTMX 1.9; small page-local JavaScript for WebAuthn and session expiry |
| Layout utilities | Tailwind CSS loaded from the CDN; no local Tailwind config/build |
| Visual styling | CSS custom properties and component classes in `static/css/theme.css` |
| Component library | None; reusable plain-CSS classes and Django partials |
| Icons | Local inline SVG set through `{% icon %}` in `core/templatetags/icons.py` |
| Fonts | Inter for UI text; JetBrains Mono for data and technical labels |
| Theme | One light theme; no dark-mode implementation |

Use Tailwind for composition and spacing. Use the CSS tokens/classes for
color, typography, borders, radii and component appearance. Avoid new ad-hoc
color utilities in templates.

## Design intent

Env Manager should feel like a precise operational console: calm enough for
frequent use, dense enough to scan quickly, and explicit about security and
system state. It is not a marketing surface. Hierarchy comes from typography,
borders, alignment and selective contrast rather than decoration. **HIGH**

The visual character is:

- technical and editorial, not playful;
- mostly monochrome, with semantic color used as signal;
- compact inside data regions, with breathing room around regions;
- restrained but not sterile: small human details may appear in content, not
  as decorative UI chrome.

## Visual principles

1. **Separate language from data.** Use Inter for headings, labels and prose;
   use JetBrains Mono for keys, values, timestamps, measurements and uppercase
   technical labels. **HIGH**
2. **Borders build the interface.** Use one-pixel neutral lines and small
   background shifts to group content. Embedded surfaces stay flat. **HIGH**
3. **Black leads; green confirms.** The main action is near-black. Green marks
   positive, active or verified information and focus—not every action.
   **HIGH**
4. **Color must explain state.** Red is destructive/error/escalated; amber is
   warning/locked/uncertain; gray is neutral/inactive. **HIGH**
5. **Dense data, generous frame.** Keep rows and controls compact, then use
   consistent padding and gaps around sections so the screen does not feel
   cramped. **HIGH**
6. **One focal point at a time.** A strong fill, image, gradient or floating
   elevation is exceptional and must identify the single item needing
   attention. **MEDIUM**

## Color system

The CSS variables are the source of truth:

| Role | Token | Rule |
|---|---|---|
| Page canvas | `--paper` | Warm/off-white background behind the app surfaces |
| Surface | `--surface` | Cards, fields, sidebar and primary content regions |
| Primary text/action | `--ink` | Headings, high-value text and the dominant CTA |
| Secondary text | `--ink-muted` | Supporting copy, metadata and field labels |
| Faint content | `--ink-faint` | Placeholders, low-emphasis icons and disabled cues |
| Border | `--line`, `--line-soft` | Structural dividers and subtle hover/background shifts |
| Positive/focus | `--accent*` | Success, current/active state, positive deltas and focus |
| Error/destructive | `--danger*` | Errors, destructive actions and blocked states |
| Warning | `--warning*` | Locked, secret or uncertain states |

Rules:

- Keep most of any screen neutral; semantic hues should be visually scarce.
- Pair semantic color with text and/or an icon. Never rely on hue alone.
- Primary buttons use `--ink`, not `--accent`.
- Do not sample new hex values from the photographed mockups. Lighting,
  perspective and compression make exact sampling unreliable.
- The green-to-black focus card visible in two references is a supported
  exception, not a general surface treatment. Env Manager has no such named
  component today; do not add gradients until a real focus-card use case is
  defined.

## Typography

The reference images strongly support the role split, but not exact font
identification. The project therefore keeps its existing font choices:

- **Inter** — headings, navigation, buttons, field labels and body copy.
- **JetBrains Mono** — environment keys/values, figures, timestamps, revision
  metadata and `.eyebrow` labels.

Hierarchy:

- Page heading: concise, semibold, tight tracking; one per page.
- Section/card title: semibold and close to body size; cards should not compete
  with the page title.
- Body: regular weight with comfortable line height.
- Supporting text: smaller and muted, never faint when it carries required
  instructions.
- `.eyebrow`: 11px minimum, uppercase, tracked mono.
- `.stat-number`: mono, medium weight, with the largest size in its local tile.

Avoid all-caps prose, oversized display headlines and decorative font mixing.
Do not introduce another webfont without evidence and a loading/privacy plan.

## Layout and composition

The reference layouts use strong app chrome and modular working regions rather
than a centered marketing container. **HIGH**

- Authenticated pages use the existing sidebar + topbar + fluid main region.
- Main content fills available width with `px-4` on small screens and `px-8`
  from `md` upward. Do not add a narrow global max-width to data pages.
- Authentication pages are the exception: one centered `max-w-sm` card.
- Prefer one primary column of stacked sections. Use grids where the items are
  truly comparable (stats, filters), not simply to make a page look busier.
- Within a section, align titles, values and actions to stable edges. Keep
  action columns predictable for scanability.
- A varied row of stats plus one emphasized item is more faithful to the
  references than a generic grid of identical feature cards. Only use that
  asymmetry when the emphasized item is genuinely more important.
- Tables and row lists should remain visually continuous; avoid wrapping every
  row in its own card.

The physical screens, perspective angles and overlapping product panels in
`image.png` and `image copy 3.png` are presentation framing, not app layout.

## Spacing

Use Tailwind's existing 4px-based scale. Common intervals in the implementation
and references are 8, 12, 16, 20, 24, 32 and 48px.

- 8px: tight icon/text and row-action gaps.
- 12–16px: control groups and compact tile padding.
- 20–24px: card padding and separation between related blocks.
- 24–32px: page padding and major section rhythm.
- 48px: empty-state breathing room; use sparingly.

Do not introduce one-off 13/17/22px gaps. Dense tables may be compact, but
interactive targets must retain adequate hit area.

## Geometry, borders and elevation

Current implementation values:

- `--radius-sm: 0.5rem` for controls and compact elements.
- `--radius: 0.75rem` for cards and panels.
- 1px `--line` borders for structural separation.
- badges are fully rounded in the current CSS.

Reference evidence supports low-to-moderate radii and hairline borders, but not
those exact values. Embedded cards, tables, buttons and fields have no drop
shadow. **HIGH**

Elevation is reserved for detached content: a toast, popover, dialog or a card
floating over imagery may use one soft shadow. Do not apply elevation to every
card. **HIGH**

## Imagery and data graphics

Env Manager currently has no image component. The landscape imagery in two
references acts as contextual framing behind opaque white work surfaces; it is
not evidence for decorative page backgrounds. If imagery is introduced later:

- use one subdued, editorial crop;
- keep dense text on an opaque surface;
- preserve strong contrast and never place secrets/data directly on imagery;
- do not add stock illustration merely to fill empty space.

Microcharts in the references are compact context for a headline value. They
do not replace the value or its label. Env Manager has no chart primitive yet;
create one only when time-series or distribution data becomes a real feature.

## Icons

Use the existing 24×24 outline icons with `currentColor`, 1.5px stroke and
rounded caps/joins. Icons support labels; they do not sit in decorative colored
boxes by default. Icon-only buttons require an accessible `title` or
`aria-label`. Do not mix filled and outline families without a defined state
reason.

## Motion and interaction

No motion is visible in the static references. Keep motion functional:

- color and border transitions around 150ms for hover/focus/state feedback;
- the existing 200ms mobile drawer transition;
- no entrance, scroll, parallax or looping decorative animation;
- respect reduced-motion preferences when adding any non-trivial transition.

Keep visible focus. Never remove a browser outline unless an equally clear
`focus-visible` treatment replaces it.

## Responsive behavior

The mockups are desktop compositions; they provide **no reliable mobile
evidence**. Responsive rules below come from the existing implementation:

- below `md`, the sidebar becomes an off-canvas drawer with a backdrop;
- page gutters reduce from 32px to 16px;
- stat tiles move from three columns to one below `sm`;
- card headers may wrap while keeping the title before its actions;
- wide data tables scroll horizontally and preserve stable column roles;
- mobile stacking must keep meaning and reading order, not just flatten every
  region indiscriminately.

When adding a component, verify at a narrow phone width, around the `sm`/`md`
boundaries, and at a wide desktop width.

## Anti-patterns

- Generic SaaS hero sections, feature-card trios and oversized slogans.
- Decorative gradients, glassmorphism, glow or image backgrounds.
- A shadow on every surface.
- Accent-filled CTAs; green is primarily a data/state signal.
- Excessive pills, rounded icon boxes or nested cards.
- Color-only status communication.
- Ad-hoc Tailwind color classes or hard-coded colors in templates.
- New component machinery when an existing class or Django partial suffices.
- Treating the staged product photography as literal application chrome.

## Decision hierarchy

When a new UI requirement is ambiguous:

1. Preserve usability, security clarity and information hierarchy.
2. Reuse the relevant pattern in [`COMPONENTS.md`](./COMPONENTS.md).
3. Reuse the semantic tokens in `theme.css`; exact code values beat values
   estimated from a screenshot.
4. Prefer a repeated reference pattern over an isolated visual flourish.
5. Choose the simpler, flatter solution at equal utility.
6. If a new visual primitive is genuinely needed, add a named token/class and
   document it—do not hard-code a one-off treatment.

## Evidence limits and known differences

- Exact colors, fonts, radii and spacing cannot be measured reliably from the
  photographed/perspective references. Existing code is authoritative for
  exact values.
- Reference status tags are compact rounded rectangles; `.badge` currently
  uses a full pill. Keep the implementation consistent unless a deliberate
  component-wide change is requested.
- Reference active navigation uses a light-gray selection in the clearest
  sidebar view; `.nav-link.is-active` currently uses black. This is an
  implementation choice, not a high-confidence extracted rule.
- Reference shadows appear on floating notifications and detached panels, but
  not on embedded app surfaces. A blanket “no shadows” rule would be wrong.
- The green gradient focus card is repeated as part of the same dashboard
  concept, not across unrelated screens. Confidence that it should generalize
  to Env Manager is **LOW**.
- Responsive behavior is implementation-led because all supplied images are
  1024×768 desktop references.
