# GUI controls and layout

This is the GUI's control/layout contract. Apply it to new panels and when
changing existing ones. It standardizes presentation, not scientific behavior.

## Sources of truth

- [`gui/src/theme.ts`](../gui/src/theme.ts) sets application-wide MUI defaults:
  button, input, label, toggle, checkbox, tab, chip and focus styling.
- [`gui/src/ui/layout.ts`](../gui/src/ui/layout.ts) exports the dimensions and
  reusable toolbar/action styles. Import them rather than copying pixel values.
- [`layout.test.tsx`](../gui/src/ui/layout.test.tsx) checks these contracts.
- Mol* controls remain owned by Mol*. Sequence/alignment residue cells retain
  their scientific grid geometry; they are not ordinary toolbar buttons.

## Button appearance

| Element | Size and appearance | Use |
|---|---|---|
| Default button | 32 px high, at least 80 px wide, 12 px horizontal padding, 12 px sentence-case label | Ordinary actions throughout the application |
| Main workflow action | 160 × 32 px (`primaryActionSx`) | Run, Generate MSA, Parse sequence; Homology workflow toolbar buttons share this width |
| Icon-only action | 32 × 32 px, 18 px icon, 6 px corner radius | Refresh, add, focus, remove; always a tooltip and an accessible name |
| Dense-row icon | 24 × 24 px, 14 px icon (`compactIconButtonSx`) | Elements tree, expandable data rows, alignment gap arrows, docking tab chrome |
| Inline text action | 24 px high (`inlineActionSx`), otherwise the normal label style | Open in Text Files inside report headers; not a smaller workflow toolbar |
| Toggle segment | 32 px high, at least 32 px wide | A/B viewer target, severity and numbering selectors |
| Status/legend chip | 24 px high | Passive status, counts, compact filter tags; not a substitute for Run/Import buttons |

Use the default theme size even when specifying `size="small"`. Do not add
one-off 20/22/28 px toolbar controls, shrink button labels, or adjust vertical
position with `translateY`, negative margins or arbitrary padding.

### Variants and states

- **Contained:** the main affirmative action in a group: Run, Save, Generate.
  Avoid several equally prominent contained buttons in one toolbar.
- **Outlined:** secondary actions: Import files, Add new, Structural align.
- **Text:** low-emphasis actions: Reset, Cancel a dialog, open a report.
- **Error color:** destructive/cancel-running actions and actual failed-run
  status. Never make an entire stderr report red just because it is stderr.
- **Disabled/loading:** preserve dimensions and label position. Replace an icon
  with a small spinner without changing button width. Explain prerequisites in
  a tooltip; wrap disabled controls in an inline-flex span if necessary.
- **Keyboard focus:** keep the theme's visible outline. Do not disable outlines
  on application actions. A tooltip is not an accessible name: icon buttons need
  `aria-label`, and toggles should expose selection state.

## Placement and alignment

### Panel/workflow toolbars

Use `panelToolbarSx` for panel headers and `workflowToolbarSx` for Homology
workflow rows. Both use a 48 px minimum height, 12 px horizontal / 8 px vertical
padding, 8 px gaps, centered controls and wrapping. Workflow rows have an opaque
`background.paper` and no extra outline box. Panel headers have a bottom divider.

Place context selectors/fields on the left, a related `actionGroupSx` on the
right, and the primary action at the end of its group. Keep contextual viewer
actions together next to their chain selectors. Labels/status are not spacers:
use flex layout and `ml: 'auto'` for the action group instead of manual offsets.

When fields have helper text, use `formActionRowSx`: align their top edges with
the action group's controls, leaving the caption below the field. Do not center
the action against the combined input-plus-helper height.

### Fields and text

- Single-line outlined inputs/selects share the 32 px control height. Small
  floating labels and padding are defined **once in the theme**.
- `controlSx` provides 160 px selectors; `wideControlSx` provides up to 320 px
  file/name fields. Content-driven flexible fields may grow with their panel.
- Multiline FASTA/notes editors retain their own height. Do not force multiline
  inputs to 32 px. Preserve residue/grid widths used for alignment selection.
- Use body text at 12 px and supporting captions around 11 px. Do not reduce
  toolbar labels/counts to tiny 8–9 px text to force them onto one line.
- Use `minWidth: 0`, truncation with a title, or `overflowWrap: 'anywhere'` for
  long workspace/file names. Narrow panels wrap whole controls, not button text.
- Do not impose toolbar-wide child selectors that override a deliberately wider
  field. Prefer an explicit `sx={controlSx}` on the field itself.

### Reports

The selected tool owns its status and output; another tool's output must never
appear during switching/loading. The diagnostic/output report and run log are
two separately labelled, keyboard-focusable scroll regions. Their Open in Text
Files actions stay at the right of each header and wrap with the header when
space is limited. Use neutral report backgrounds and text, not an error-colored
stderr container.

## Examples

### Consistent workflow row

```tsx
<Box sx={panelToolbarSx}>
  <TextField label="Input" sx={wideControlSx} />
  <Box sx={actionGroupSx}>
    <Tooltip title="Refresh inputs">
      <IconButton aria-label="Refresh inputs"><RefreshIcon /></IconButton>
    </Tooltip>
    <Button variant="contained" sx={primaryActionSx}>Run</Button>
  </Box>
</Box>
```

### Avoid local geometry patches

```tsx
// Avoid: a different button baseline and a third control height.
<Button sx={{ height: 28, transform: 'translateY(-3px)' }}>Run</Button>

// Use: shared geometry; fix the parent row, not the button's position.
<Button variant="contained" sx={primaryActionSx}>Run</Button>
```

## Verification checklist

1. Compare normal, disabled, loading, selected and keyboard-focused states.
2. Check narrow docked panels, long filenames/workspace names and toolbar wrapping.
3. Confirm labelled inputs, buttons and icon actions share a baseline; helper text
   and multiline editors must not displace neighboring controls.
4. Confirm tool switching and report navigation still work; leave molecular
   selection, masks, chain identity and scientific calculations unchanged.
5. Run `npm run lint`, `npm run typecheck`, `npm test -- --run` and `npm run build`
   from `gui/` for an application-wide styling change. Use narrow tests while
   iterating; do not silently trigger a full scientific test run.

## Workspace file identity and filtering

[`ArtifactFileIdentity`](../gui/src/components/ArtifactFileIdentity.tsx) renders
one compact row cell: category icon (18 px), flexible ellipsized display name,
and a persistent outlined format chip (24 px high, 52–88 px wide). Category uses
recorded artifact metadata when available and recognizable path extensions as a
fallback. Format always comes from the actual path, never the editable name.
Icon shape, accessible category label and badge text must remain useful without
color; do not use error/warning colors simply to distinguish file types.

The tooltip preserves the complete case-sensitive workspace path and recorded
command/source provenance. Unknown provenance stays explicitly unknown. A format
badge is presentation, not proof that every viewer/backend accepts that format.

**Show structures only / Show all files** is an outlined toggle action. The
structure-only filter includes CIF/mmCIF and other recognized structure formats,
not just `.pdb`. Rendering, range selection and arrow reordering share the same
visible list; switching the filter must not reorder files or unhide internal
bookkeeping artifacts. Classification/filtering policy lives in
[`artifact-presentation.ts`](../gui/src/lib/artifact-presentation.ts).

See also the [GUI overview](../gui/README.md) and
[Homology workspace guide](gui-homology.md).
