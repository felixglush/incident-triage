# Frontend Design Language

This document defines the design system and patterns for OpsRelay's frontend interface.

## Design Philosophy

**Sharp, utilitarian, data-dense.** Inspired by Linear's clean aesthetic, the interface prioritizes:
- Information density over whitespace
- Flat edges over rounded corners
- Subtle borders and dividers over heavy shadows
- Table-like layouts for scannable data
- Consistent hover states and interactions

## Visual Language

### Colors (Tailwind Classes)

**Surfaces:**
- Container: `border border-mist/10 bg-graphite/30`
- Hover state: `hover:bg-slate/30` or `hover:bg-slate/40`
- Row dividers: `divide-y divide-mist/5`
- Section dividers: `border-b border-mist/10`

**Text:**
- Primary: `text-white`
- Secondary: `text-mist/60` or `text-mist/50`
- Tertiary/labels: `text-mist/40`
- Interactive hover: `hover:text-accent` (yellow)

**Status Colors:**
- Critical/Error: `text-critical` or `bg-critical/20 text-critical`
- Warning: `text-warning` or `bg-warning/20 text-warning`
- Info/Open: `text-info` or `bg-info/20 text-info`
- Success/Resolved: `text-success` or `bg-success/20 text-success`

**Borders:**
- Primary borders: `border-mist/10`
- Dividers: `border-mist/5`
- No rounded corners: avoid `rounded-*` classes (except buttons which can use minimal rounding)

### Typography

**Headers:**
- Page title: `text-2xl text-white` (in TopBar)
- Section header: `text-sm font-medium text-white`
- Subtitle/breadcrumb: `text-xs uppercase tracking-[0.2em] text-mist/50`

**Body:**
- Primary text: `text-sm text-white`
- Secondary text: `text-xs text-mist/60`
- Monospace (IDs, services): `font-mono text-xs text-mist/50`

**Buttons:**
- Text: `text-xs` with `uppercase` or normal case depending on importance
- Primary action: `bg-critical px-4 py-2 text-xs text-white`
- Secondary action: `border border-mist/20 px-4 py-2 text-xs text-mist/70`
- Tertiary action: `px-3 py-1.5 text-xs text-mist/60 hover:text-white`

## Layout Patterns

### Page Structure

```tsx
<AppShell rightPanel={optional}>
  <TopBar title="Page Title" subtitle="Context" />
  
  {/* Content sections */}
</AppShell>
```

**AppShell provides:**
- Fixed sidebar (256px wide, no collapse)
- Flexible content area
- Optional right panel (420px wide, sticky)

### Container Pattern

Standard container for all list/table views:

```tsx
<div className="border border-mist/10 bg-graphite/30">
  {/* Header row */}
  <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
    <h3 className="text-sm font-medium text-white">Section Title</h3>
    <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white">
      Action
    </button>
  </div>

  {/* Content - either DataTable or custom rows */}
  <div className="divide-y divide-mist/5">
    {/* Rows */}
  </div>
</div>
```

### Search Bar Pattern

For pages with search functionality:

```tsx
<div className="border border-mist/10 bg-graphite/30">
  <div className="flex items-center gap-3 px-4 py-3 border-b border-mist/10">
    <svg className="w-4 h-4 text-mist/40">{/* search icon */}</svg>
    <input
      className="flex-1 bg-transparent text-sm text-mist placeholder:text-mist/40 focus:outline-none"
      placeholder="Search..."
    />
    <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white">
      Filters
    </button>
  </div>
  
  <DataTable {...props} noBorder />
</div>
```

## Component Patterns

### DataTable

Use the shared `DataTable` component for all tabular data:

```tsx
import DataTable, { Column } from "../components/DataTable";

const columns: Column<ItemType>[] = [
  {
    key: "id",
    header: "ID",
    width: "90px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/50">{item.id}</span>
    ),
  },
  {
    key: "title",
    header: "Title",
    render: (item) => (
      <span className="text-sm text-white group-hover:text-accent transition-colors">
        {item.title}
      </span>
    ),
  },
  // ... more columns
];

<DataTable
  columns={columns}
  data={items}
  keyExtractor={(item) => item.id}
  href={(item) => `/path/${item.id}`}
  noBorder  // when nested in container with border
/>
```

**Column guidelines:**
- Fixed widths for IDs, status, timestamps: `80px - 120px`
- Flexible main content: no width specified
- Right-align timestamps: `align: "right"`
- Use monospace for IDs and service names
- Add `group-hover:text-accent` to clickable titles

### List Rows

For non-tabular lists (connectors, timeline, etc.):

```tsx
<div className="divide-y divide-mist/5">
  {items.map((item) => (
    <div
      key={item.id}
      className="flex items-center gap-3 px-4 py-3 hover:bg-slate/30 transition-colors group"
    >
      {/* Row content */}
    </div>
  ))}
</div>
```

**Row structure:**
- Padding: `px-4 py-3`
- Always include hover state: `hover:bg-slate/30`
- Use `group` class for nested hover effects
- Divide with `divide-y divide-mist/5`

### Badges/Pills

**Status badges:**
```tsx
<span className="bg-info/20 text-info px-2 py-0.5 text-xs">
  Status
</span>
```

**Small tags:**
```tsx
<span className="bg-slate/60 px-2 py-0.5 text-xs text-mist/60">
  tag
</span>
```

### Metrics Bar

Horizontal metrics with dividers:

```tsx
<div className="border border-mist/10 bg-graphite/30">
  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 divide-x divide-mist/10">
    {metrics.map((metric) => (
      <div key={metric.label} className="px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-display text-white">{metric.value}</span>
          <span className="text-xs text-mist/50">{metric.unit}</span>
        </div>
        <p className="text-xs text-mist/40 mt-0.5">{metric.label}</p>
      </div>
    ))}
  </div>
</div>
```

## Sidebar

Fixed width (256px), always visible, no collapse functionality.

**Structure:**
- Background: `bg-graphite/50 border-r border-mist/10`
- Active link: `bg-info/15 text-info border-l-2 border-info`
- Inactive link: `text-mist/70 hover:bg-slate/50 hover:text-white`
- No rounded corners

## Chat Panel

When present, appears on right edge:
- Width: `420px`
- Height: `h-screen sticky top-0`
- Hidden on smaller screens: `hidden xl:block`

## Spacing

**Container padding:** `p-4` (16px)

**Row padding:** `px-4 py-3` (16px horizontal, 12px vertical)

**Section gaps:** `space-y-6` (24px between sections)

**Grid gaps:** `gap-6` for layouts, `gap-4` for cards

**Divider spacing:** Use `divide-y` with `divide-mist/5` for thin dividers

## Interactions

**Hover states:**
- Rows: `hover:bg-slate/30` or `hover:bg-slate/40`
- Links: `hover:text-accent`
- Buttons: `hover:bg-slate/50 hover:text-white`

**Transitions:**
- All interactive elements: `transition-colors`
- Keep transitions subtle (no duration specified = default 150ms)

**Focus:**
- Inputs: `focus:outline-none focus:border-info/50`

## Anti-Patterns

**Don't:**
- Use rounded corners on containers (`rounded-xl`, `card` class with rounding)
- Use heavy shadows
- Use colored backgrounds for containers (keep to `graphite/30`)
- Make data cards instead of rows
- Hide useful information for aesthetics
- Use large spacing between list items

**Do:**
- Keep edges sharp and clean
- Use subtle borders for separation
- Make information scannable
- Use consistent hover states
- Align content in tables/grids
- Show as much data density as reasonable

## File Organization

```
frontend/
├── app/
│   ├── page.tsx              # Dashboard
│   ├── incidents/
│   │   ├── page.tsx          # List view
│   │   └── [id]/page.tsx     # Detail view
│   ├── alerts/page.tsx
│   ├── runbooks/page.tsx
│   └── connectors/page.tsx
├── components/
│   ├── AppShell.tsx          # Layout wrapper
│   ├── Sidebar.tsx           # Navigation
│   ├── TopBar.tsx            # Page header
│   ├── ChatPanel.tsx         # AI assistant
│   ├── DataTable.tsx         # Shared table component
│   └── IncidentHeatmap.tsx   # Activity visualization
└── globals.css               # Global styles
```

## Common Patterns by Page Type

### List Page
1. TopBar with title
2. Optional search bar in container
3. DataTable with defined columns
4. Consistent hover states

### Detail Page
1. Header with metadata and actions
2. Two-column layout (timeline left, reference right) on desktop
3. Optional ChatPanel on far right
4. All sections use container pattern

### Dashboard
1. Metrics bar at top
2. Heatmap/visualization
3. Live incident queue table
4. Focus on at-a-glance information

## Responsive Behavior

**Breakpoints:**
- `sm:` 640px - Adjust grid columns
- `lg:` 1024px - Show/hide sidebar features
- `xl:` 1280px - Show chat panel

**Mobile-first approach:**
- Stack columns on small screens
- Hide chat panel below xl
- Keep data tables scrollable horizontally if needed
