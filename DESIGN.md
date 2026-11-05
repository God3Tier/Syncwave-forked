---
name: SyncWave
description: A tactile, friends-first listening room for shared music playback.
colors:
  signal-coral: "#ff7350"
  live-mint: "#79e3c3"
  queue-gold: "#f1c75b"
  ink: "#0b0f0d"
  deepest-ink: "#070a08"
  panel-ink: "#101512"
  raised-ink: "#1c2520"
  warm-paper: "#f3f0e8"
  quiet-sage: "#adb7b0"
  rule-sage: "#37443c"
  error: "#ff7e87"
typography:
  display:
    fontFamily: "Manrope Variable, Avenir Next, Segoe UI Variable, sans-serif"
    fontSize: "3rem"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Manrope Variable, Avenir Next, Segoe UI Variable, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Manrope Variable, Avenir Next, Segoe UI Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Manrope Variable, Avenir Next, Segoe UI Variable, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1.25
rounded:
  sm: "8px"
  control: "12px"
  surface: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.signal-coral}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.raised-ink}"
    textColor: "{colors.warm-paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 16px"
    height: "40px"
  input:
    backgroundColor: "{colors.panel-ink}"
    textColor: "{colors.warm-paper}"
    rounded: "{rounded.surface}"
    padding: "12px 16px"
    height: "56px"
  card:
    backgroundColor: "{colors.panel-ink}"
    textColor: "{colors.warm-paper}"
    rounded: "{rounded.surface}"
    padding: "20px"
---

# Design System: SyncWave

## Overview

**Creative North Star: “The Shared Listening Desk”**

SyncWave should feel like friends have gathered around one carefully made playback surface: immediate, tactile, and focused on the current track and the people sharing it. Familiar streaming conventions make the product understandable on first contact, while coral controls, mint live state, and generated record sleeves give it an identity separate from Spotify, Deezer, or SoundCloud.

The interface is dense enough to browse and manage queues without reading like an operations dashboard. Synchronization measurements remain available, but the visual hierarchy describes what a listener can do before it describes how the system works.

**Key Characteristics:**

- Dark ink field with warm, high-contrast type.
- Coral for primary action and current playback; mint for live, ready, and healthy state.
- Deterministic record-sleeve artwork when catalogue art is unavailable.
- Familiar media controls, compact list density, and restrained tonal containers.
- One responsive shell that becomes a four-action bottom navigation below 1024px.

## Colors

The palette combines a near-black listening-room ground with warm paper type and two scarce signals: coral for action, mint for live state.

### Primary

- **Signal Coral:** Primary actions, current selection, played waveform, and the app mark.

### Secondary

- **Live Mint:** Ready, connected, synchronized, successful, and permissioned states.

### Tertiary

- **Queue Gold:** Supporting sleeve-art details and warning states.

### Neutral

- **Ink / Deepest Ink:** Main canvas and navigation ground.
- **Panel / Raised Ink:** Inputs, grouped tasks, hover state, and contextual surfaces.
- **Warm Paper:** Primary text and high-contrast playback controls.
- **Quiet Sage / Rule Sage:** Secondary text, dividers, and inactive controls.

**The Two Signals Rule.** Coral tells people where they can act; mint tells them what is live or ready. Do not swap these meanings.

## Typography

**Display Font:** Manrope Variable (with Avenir Next and Segoe UI Variable fallbacks)
**Body Font:** Manrope Variable (with system sans fallbacks)
**Label/Mono Font:** Native UI monospace only for timestamps, IDs, and measurements.

**Character:** Manrope keeps the product contemporary and compact without turning controls into branding. Heavy headings carry the identity; ordinary interface text stays quiet.

### Hierarchy

- **Display** (800, 3rem, 1.08): Page-defining consumer messages at desktop scale.
- **Headline** (800, 1.875rem, 1.2): Page and major section titles.
- **Title** (800, 1.25rem): Track, playlist, and panel titles.
- **Body** (400, 1rem, 1.5): Descriptions with a practical 65–75 character measure.
- **Label** (700, 0.875rem): Controls, navigation, and status language.

**The Listener Language Rule.** Use mono only for actual data. Music, people, and actions use the primary sans.

## Layout

Desktop uses a fixed 15rem rail, a fluid content canvas, and a persistent player. Content tops out near 1480px with 32px desktop gutters. Below 1024px, the rail becomes a compact header and four-item bottom navigation. At 768px, search and page headers become single-column compositions; at 390px, shelves scroll horizontally, lists simplify, and Jam details switch between Queue and People tabs.

Vertical rhythm follows 8px increments with 24–32px separation between related sections and 40–56px around page-level transitions. Tables and track lists use dividers rather than individual cards.

## Elevation & Depth

The system is flat by default. Depth comes from tonal layers and single-pixel rings. Soft offset shadows appear only under the coral app mark, primary action, media artwork, menus, and modal dialogs.

**The Flat Library Rule.** Track rows and library items sit directly on the canvas; containers are reserved for grouped tasks or protected context.

## Shapes

Controls use 12px corners, grouped surfaces and generated sleeves use 16px corners, and avatars or playback controls use circles when their physical affordance benefits from it. Status indicators use compact 6–8px corners rather than universal pills.

## Components

### Buttons

- **Shape:** Tactile 12px corners with a 40px minimum height.
- **Primary:** Coral field, dark ink text, bold label, soft downward shadow.
- **Hover / Focus:** Increased contrast, explicit two-pixel mint focus outline, and a one-pixel active translation.
- **Secondary / Ghost:** Tonal ink layers or text-only treatment; no decorative gradient.

### Chips

- **Style:** Compact status rectangles with a subtle semantic tint, fine ring, and optional live dot.
- **State:** Coral denotes owner/current action; mint denotes ready/playing; gold denotes processing.

### Cards / Containers

- **Corner Style:** 16px.
- **Background:** Panel Ink with a low-contrast Rule Sage ring.
- **Shadow Strategy:** None at rest.
- **Internal Padding:** 20–24px.

### Inputs / Fields

- **Style:** Tonal Panel Ink, 12–16px corners, inset one-pixel ring, clear labels.
- **Focus:** Mint ring and the global mint focus outline.
- **Error / Disabled:** Error tint or reduced opacity without removing the control from the layout.

### Navigation

Desktop navigation uses a warm-paper active block on deepest ink. Tablet and mobile use a top brand bar and four-item bottom navigation. Jam is always reachable as the social action.

### Generated Record Sleeve

Every song ID deterministically selects a split-color sleeve, circular record line, label marks, and mini waveform. The system provides recognition without fabricating real album artwork.

## Do's and Don'ts

### Do:

- **Do** prioritize the current track, queue, and people before synchronization telemetry.
- **Do** use coral for primary action and mint for live state consistently.
- **Do** use tonal layers and dividers to organize dense music lists.
- **Do** preserve conventional play, pause, seek, previous, next, and volume behavior.
- **Do** adapt structure at 1024px, 768px, and 390px rather than merely shrinking desktop.

### Don't:

- **Don't** reintroduce violet/cyan gradients, decorative grid backgrounds, or glow-heavy controls.
- **Don't** wrap every track, metric, or section in a card.
- **Don't** expose IDs, drift, RTT, generations, or protocol names as primary consumer content.
- **Don't** use mono typography as decoration.
- **Don't** make generated sleeve art imply real licensed cover artwork.
