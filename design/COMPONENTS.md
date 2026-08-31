# Components — Env Manager

These are the reusable patterns that exist in the application today. Their
appearance is implemented in [`static/css/theme.css`](../static/css/theme.css);
this file defines composition and usage. Read [`DESIGN.md`](./DESIGN.md) first.

Tailwind utilities may arrange components, but component color and typography
must come from the CSS tokens/classes.

## Button — `.btn`

**Purpose:** trigger an action or navigate to an action-oriented destination.

```html
<button class="btn btn-primary">Save</button>
<a href="..." class="btn btn-secondary btn-sm">History</a>
```

**Structure and spacing**

- Optional icon, then a short verb-led label; use `gap: .5rem` from `.btn`.
- Default padding is `.5rem 1rem`; `.btn-sm` and `.btn-xs` are for denser
  contexts.
- Icon-only buttons need `title` or `aria-label` and an explicit usable target.

**Variants**

- `.btn-primary`: near-black with white text. One dominant action per local
  section (for example, Add variable or Save).
- `.btn-secondary`: white with a neutral border. Normal alternative action.
- `.btn-ghost`: transparent and muted. Navigation, cancel and low-emphasis
  row actions.
- `.btn-danger`: soft red treatment. Destructive actions only.

**States**

- Hover changes background/color without movement or shadow.
- Use the native `disabled` attribute; disabled controls are dimmed and lose
  the pointer cursor.
- Preserve a visible keyboard focus indicator. Do not remove the native outline
  until a tokenized `:focus-visible` style exists.
- `.btn-icon` creates the consistent square target for icon-only table actions;
  always add `title` and `aria-label`.

**Responsive behavior:** allow groups to wrap. Keep the primary action visible
and do not collapse distinct actions into an unlabeled icon set by default.

**Do not use:** as a status label, for passive metadata, or as a pill. Do not
place two equal-weight primary buttons in one section.

## Card — `.card`

**Purpose:** group one coherent region such as a variable set, project or auth
form.

```html
<section class="card">
  <header class="card-header">
    <div>
      <h2 class="card-title">Variables</h2>
      <p class="card-subtitle">Secrets are masked by default.</p>
    </div>
  </header>
  <div class="card-body">...</div>
</section>
```

**Visual rules:** white surface, 1px neutral border, `--radius`, no shadow while
embedded in the page.

**Spacing:** header and body use 16–20px padding. The header uses a 16px gap and
may wrap so actions never collide with the title.

**Variants:** header and body are optional. A list card may place divided rows
directly inside `.card`; a simple auth card may use `.card p-6`.

**Interactive states:** the card itself is not interactive. If a whole row is a
link, apply a subtle `--line-soft` hover to that row, not to the entire card.

**Responsive behavior:** header text appears before actions; actions may wrap.
Do not force a two-column card body on narrow screens.

**Do not use:** for each table row, around an existing card, or merely to add a
border around arbitrary text.

## Divided row list

**Purpose:** display repeated, scannable records that do not need table columns,
as on Projects and Revision history.

**Structure:** one `.card` containing `.row-list`; each `.row-list-item` has a
flexible `.row-list-main` identity block and compact `.row-list-end` state or
actions.

**Rules:** align icons and primary labels; truncate secondary metadata before
actions; use one subtle hover only when the row navigates. Rows stay part of one
surface rather than becoming individual cards.

**Responsive behavior:** allow the identity block to shrink; wrap or simplify
secondary metadata before hiding primary state/action information.

**Do not use:** where several columns must align across all records; use
`.table-clean` instead.

## Badge — `.badge`

**Purpose:** label a short, non-interactive state.

```html
<span class="badge badge-positive">current</span>
```

**Variants**

- `.badge-neutral`: revision/default/inactive metadata.
- `.badge-positive`: current, verified, healthy or successful.
- `.badge-negative`: failed, escalated or error state.
- `.badge-warning`: locked, secret, caution or uncertainty.

**Visual rules:** compact 12px text, optional 12px leading icon, semantic soft
fill plus matching border and text. Use the shared `--radius-xs`
rounded-rectangle shape; badges are not pills.

**States:** badges have no hover, focus or pressed state because they are not
interactive.

**Responsive behavior:** keep the label intact. If space is tight, move it to a
second line rather than truncating a critical state.

**Do not use:** for navigation, filters, buttons or long prose. Never rely on
badge hue without readable text.

## Alert — `.alert`

**Purpose:** communicate an operation result or a blocking page condition.

```html
<div class="alert alert-error">
  {% icon "x_circle" "w-5 h-5 shrink-0 mt-0.5" %}
  <div>Message text.</div>
</div>
```

**Variants:** `.alert-error`, `.alert-success` and `.alert-warning`. Warning is
used for locked or temporarily unavailable environments, not destructive
failures.

**Visual rules:** soft semantic surface, matching 1px border, readable semantic
text and a 20px icon. Alerts embedded in content have no shadow.

**Spacing:** 10px vertical/12px horizontal with an 8px icon gap. Keep copy short
and actionable.

**Responsive behavior:** text wraps beneath itself, not beneath the icon.

**Do not use:** as a decorative callout or permanent substitute for field-level
validation.

## Stat tile — `.stat-tile`

**Purpose:** summarize one comparable metric at the top of an operational view.

```html
<div class="stat-tile flex items-center gap-3">
  <div class="shrink-0 rounded-lg p-2 bg-paper text-ink">
    {% icon "folder" "w-5 h-5" %}
  </div>
  <div>
    <div class="eyebrow">Environments</div>
    <div class="stat-number text-xl">12</div>
  </div>
</div>
```

**Visual rules:** `.eyebrow` label plus `.stat-number` value is invariant. Use a
neutral icon by default; semantic color is allowed only when the metric itself
has that meaning.

**Spacing:** 16px padding, 12px internal gap. Comparable tiles use equal heights.

**Responsive behavior:** the current dashboard moves from three columns to one
below `sm`. Preserve label/value order and comparison order.

**Do not use:** for prose, an action shortcut, or a number that has no useful
summary meaning. Microcharts are not part of the current component.

## Empty state — `.empty-state`

**Purpose:** explain why a list/table has no records and what the user can do.

```html
<div class="empty-state">
  <div class="empty-state-icon">{% icon "folder" "w-8 h-8" %}</div>
  <p class="font-medium text-ink">No projects visible yet</p>
  <p class="text-sm text-muted mt-1 max-w-sm">Ask an admin for access.</p>
</div>
```

**Visual rules:** centered neutral icon, one direct title and one short
explanation. Add an action only if the current user can resolve the empty state.

**Spacing:** 48px vertical/24px horizontal. Keep explanatory text narrow.

**Responsive behavior:** naturally fits narrow screens; do not shrink the copy
below the normal body hierarchy.

**Do not use:** as a full-screen illustration or for loading/error states.

## Form field — `.field-label` + `.field-input`

**Purpose:** collect a labeled value with a consistent border and focus state.

```html
<label for="key" class="field-label">Key</label>
<input id="key" class="field-input font-mono" name="key"
       placeholder="DATABASE_URL">
```

**Structure:** a real `<label>` connected by `for`/`id`, then the input. Help or
error text follows the field. Use `font-mono` for literal keys, values and
tokens; use Inter for human-readable names and comments.

**Visual rules:** white surface, neutral 1px border, `--radius-sm`; accent border
and soft ring on focus. Placeholder text is faint but never replaces a label.

**Spacing:** label sits 6px above the field; inputs use 8px vertical/12px
horizontal padding; related fields use 12–16px gaps.

**States:** native disabled/required semantics; visible focus; semantic error
copy when validation fails. Checkboxes remain native and use the accent only for
their checked/focus state.

Use `.field-check` + `.field-checkbox` for checkbox rows. Do not reproduce their
spacing or focus color with Tailwind utilities.

**Responsive behavior:** two-column form grids become one column below `sm`.

**Do not use:** unlabeled inputs, placeholder-only forms, or monospaced prose
fields.

## Inline create/edit form

**Purpose:** temporarily replace the variables table with a focused HTMX form.

**Structure:** `#variables-table` wrapper, one `.inline-editor` soft neutral panel,
field grid, optional secret checkbox, then Save and Cancel.

**Rules:** retain the same DOM target and `outerHTML` swap contract; use one
primary Save action and one ghost Cancel action. The soft fill signals a local
editing mode without creating a nested card.

**Responsive behavior:** field pairs collapse to one column below `sm`; actions
remain in reading order.

**Do not use:** as a general modal replacement or for workflows needing several
steps.

## Table — `.table-clean`

**Purpose:** align environment variables across stable Key, Value and Actions
columns.

**Structure:** `table-fixed`, explicit `<colgroup>`, mono uppercase header,
hairline row dividers, and one fixed-width action column. Keep the surrounding
`overflow-x-auto` region.

**Visual rules:** headers are quiet; values carry the contrast. Row hover uses
`--line-soft`. Keys and literal values are monospaced and may break long strings
rather than silently truncate them.

**Variants:** group headers and comment rows are structural rows within the same
table, not separate cards.

**Interactive states:** row actions use compact ghost/danger buttons. Secret
reveal is explicit, audited and automatically remasked; design must never weaken
that behavior.

**Responsive behavior:** preserve column meaning and horizontal scrolling. Do
not casually convert secret data into stacked label/value cards on mobile.

**Do not use:** for a simple one-dimensional list or when columns do not need to
align.

## Navigation link — `.nav-link`

**Purpose:** represent one top-level destination in the authenticated sidebar.

**Structure:** 20px outline icon followed by a short label.

**States:** muted by default, soft neutral hover, `.is-active` for the current
destination. Active navigation uses the same light neutral surface as the
reference and exposes `aria-current="page"`.

**Responsive behavior:** the whole sidebar becomes an off-canvas drawer below
`md`; links keep labels and order.

**Do not use:** for row actions, tabs, badges or destinations outside the main
information architecture.

## Page shells

Shared shell fragments live in `templates/components/`:

- `font_assets.html` is the single source for Inter, JetBrains Mono and
  `theme.css` loading;
- `brand.html` renders the shared shield mark and name, with an optional centered
  auth variant;
- `alert.html` renders server-side semantic alerts. Client-side WebAuthn feedback
  uses the matching safe DOM helper in `static/js/ui.js`.

### `templates/layouts/app.html`

Authenticated sidebar + topbar + content shell. Pages fill `title`, `heading`,
optional `subheading`, optional `actions`, and `content` blocks. Use this for all
signed-in operational pages.

### `templates/layouts/auth.html`

Centered `max-w-sm` card without app navigation. Use only for login,
registration and closely related pre-authentication flows.

Do not build a third shell before checking whether one of these can cover the
new page without conditional complexity.

## Reference patterns not yet implemented

The mockups also contain floating notifications, filter popovers, segmented
filters, chat/command inputs, microcharts and a high-emphasis AI focus card.
They are evidence for the overall language, not Env Manager components. Do not
copy or document them as available primitives until a product requirement
introduces them.

If a detached popover/toast is added, it may use one soft elevation shadow;
embedded cards must remain flat.
