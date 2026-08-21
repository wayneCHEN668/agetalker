---
name: AgeTalker
description: A warm voice companion for elderly nursing-home residents — calm, unhurried, never clinical.
colors:
  dusty-rose: "#C17B6A"
  on-primary: "#FFFFFF"
  blush-container: "#F5E4DE"
  deep-umber: "#3D231B"
  warm-taupe: "#7A6E68"
  warm-cream: "#FBF7F4"
  paper-surface: "#FFFFFF"
  dimmed-linen: "#F5F1ED"
  soft-sand-outline: "#E8E0DB"
  caregiver-alert: "#D4453B"
  text-primary: "#2D2320"
  text-secondary: "#6B5E58"
  text-hint: "#8B7D76"
  aura-happy: "#FFDCC0"
  aura-sad: "#D5D8E8"
  aura-angry: "#F8CEC8"
  aura-crisis-safe: "#FFE2C4"
typography:
  display:
    fontFamily: "Lexend_400Regular, sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: "40px"
  headline:
    fontFamily: "Lexend_400Regular, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: "32px"
  message:
    fontFamily: "Lexend_400Regular, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: "28px"
  caption:
    fontFamily: "Lexend_400Regular, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "20px"
  label:
    fontFamily: "Lexend_400Regular, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    letterSpacing: "1.5px"
rounded:
  sm: "12px"
  lg: "24px"
spacing:
  base: "24px"
  inner: "20px"
components:
  button-primary:
    backgroundColor: "{colors.dusty-rose}"
    textColor: "{colors.on-primary}"
    rounded: "32px"
    padding: "0 24px"
    height: "64px"
  button-primary-pressed:
    backgroundColor: "{colors.dusty-rose}"
    textColor: "{colors.on-primary}"
    rounded: "32px"
    height: "64px"
  chip-emotion:
    backgroundColor: "rgba(193,123,106,0.15)"
    textColor: "{colors.deep-umber}"
    rounded: "{rounded.sm}"
    padding: "3px 10px"
  chip-category:
    backgroundColor: "rgba(193,123,106,0.08)"
    textColor: "{colors.warm-taupe}"
    rounded: "{rounded.sm}"
    padding: "3px 10px"
  card-memory-faceup:
    backgroundColor: "{colors.paper-surface}"
    rounded: "{rounded.sm}"
  card-memory-matched:
    backgroundColor: "{colors.blush-container}"
    rounded: "{rounded.sm}"
  chat-bubble-user:
    backgroundColor: "{colors.blush-container}"
    textColor: "{colors.deep-umber}"
    rounded: "{rounded.lg}"
    padding: "14px 18px"
  chat-bubble-assistant:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "14px 18px"
---

# Design System: AgeTalker

## 1. Overview

**Creative North Star: "The Healing Hour"**

AgeTalker exists for one quiet hour at a time: a resident alone with their phone, wanting to be heard. Every screen behaves like a calm room, not a control panel. Nothing blinks for attention, nothing scores or streaks the user, nothing announces itself with urgency. Warmth is carried structurally, through dusty-rose and warm cream held at low saturation, through generous rounded shapes, and through type that stays large and unhurried rather than dense.

This system explicitly rejects three lanes: it is not a **medical-device interface** (no clinical blues/grays, no alarm-red — red is reserved for caregiver-only surfaces the resident never sees), not a **tech-company product** (no dark mode, no neon, no dashboard chrome, no hard geometric edges), and not a **children's app** (no oversized mascots, no candy colors, no bouncy easing). It is an adult companion, dressed like a warm, unhurried living room rather than a screen.

**Key Characteristics:**
- Warm, desaturated dusty-rose + cream palette; near-black text tinted warm, never pure `#000`
- Single humanist typeface (Lexend) at generous sizes throughout — no secondary display font
- Pill and soft-rounded-rectangle shapes everywhere; no sharp corners
- Shadows nearly flat (ambient, opacity 0.04–0.12); lift appears only at the moments that matter
- No badges, streaks, red dots, or urgency-driven UI patterns anywhere in the resident-facing surface

## 2. Colors

A single warm hue family carries the whole system — dusty-rose as the one accent, warm cream as the ground it rests on. Nothing else competes with it.

### Primary
- **Dusty Rose** (`#C17B6A`): The one accent. Primary buttons, active tab state, avatar fill, focus/active borders. Used sparingly and consistently — it marks "this is the thing to notice."
- **Blush Container** (`#F5E4DE`): Dusty Rose diluted into a background tint. User's own chat bubble, active-state fills, matched-card feedback.
- **Deep Umber** (`#3D231B`): Text sitting on Blush Container — a warm near-black, not pure black.

### Neutral
- **Warm Cream** (`#FBF7F4`): App background. Warm and soft, deliberately not white — reduces glare for aging eyes.
- **Paper Surface** (`#FFFFFF`): Cards, dialogs, assistant chat bubbles — the "raised paper" layer above the cream ground.
- **Dimmed Linen** (`#F5F1ED`): Idle/inactive surfaces (status pill at rest, face-down memory cards).
- **Soft Sand Outline** (`#E8E0DB`): The only border color in the system. 1px hairlines, never heavier.
- **Warm Taupe** (`#7A6E68`): Secondary text, recording-state indicator, category tags.
- **Text Primary** (`#2D2320`) / **Text Secondary** (`#6B5E58`) / **Text Hint** (`#8B7D76`): Three-step warm-gray text ramp, all tinted toward the same hue as the rest of the palette — never neutral gray.

### Named Rules
**The One Warm Hue Rule.** Every color in the system — background, text, borders, emotion auras — is a tint or shade of the same warm rose/umber hue family. There is no cool gray, no blue-black, no neutral anywhere. A second, unrelated hue entering the palette is always wrong.

**The Caregiver-Only Red Rule.** `#D4453B` (crisis/alert red) never colors the *ambient* experience — background aura, dialog copy, chrome — even during an actual detected crisis; that stays a warm amber (`#FFE2C4`), safety-feeling rather than alarming. The one deliberate exception is the "联系护理员" (Contact Caregiver) action button itself: it's allowed to be red precisely because, in a crisis, that one control needs to read as unmistakably actionable against an otherwise calm screen. Red decorates the escalation control; it never colors the room around it.

## 3. Typography

**Display/Body/Label Font:** Lexend (with system sans-serif fallback)

**Character:** One typeface for everything, no pairing. Lexend was designed for reading-proficiency gains, which is exactly the point here — it stays legible at low weight and generous size for aging eyes, so the system never needs a second "body" font to compensate.

### Hierarchy
- **Display** (600, 32px, 40px line-height): Reserved for the rare full-screen headline moment (e.g. onboarding). Not used in daily-use screens.
- **Headline** (600, 24px, 32px line-height): Screen-level headings.
- **Message** (400, 18px, 28px line-height): The workhorse size — chat bubble text, primary reading content. Generous line-height carries the "unhurried" feeling.
- **Caption** (400, 14px, 20px line-height): Secondary metadata (status text, card word labels).
- **Label** (500, 13px, 1.5px letter-spacing): Uppercase-feeling small labels; used sparingly (strategy badges).

### Named Rules
**The No-Small-Print Rule.** 13px (Label) is the floor. Nothing in the resident-facing UI goes smaller — this is a hard accessibility line, not a stylistic one.

## 4. Elevation

Almost flat. Shadows are ambient, not structural — they exist to make white paper feel like it's resting gently on the cream ground, never to imply mechanical layers or glassy depth. Most surfaces sit at `shadowOpacity: 0.04`; only the moments that most need attention (the primary "talk to me" button, modal dialogs) lift further, and even then it stays soft and diffuse. Elevation increases are earned by importance, not applied for decoration.

### Shadow Vocabulary
- **Whisper** (`shadowOpacity: 0.04, shadowRadius: 4-8, elevation: 1-2`): Default for chat bubbles, status pill. Barely perceptible — presence, not depth.
- **Held** (`shadowOpacity: 0.12, shadowRadius: 24, elevation: 10`): Modal dialogs. A firmer lift because it's interrupting the flow and needs to read as "above" everything else.
- **Called-out** (`shadowOpacity: 0.2, shadowRadius: 16, elevation: 10`, tinted with the component's own color rather than black): The primary CTA button and the AI avatar — the one or two elements per screen allowed to visually invite touch.

### Named Rules
**The Earned Lift Rule.** Shadow strength scales with how much a component deserves attention, not with its visual hierarchy in code. A chat bubble is structurally important but stays flat; the one button meant to be pressed lifts.

## 5. Components

Soft and steady, never flimsy or heavy: buttons and cards read like felt or brushed cloth, not glass or metal. Every interactive surface uses large rounded geometry and a full-color background rather than an outline-only style, so touch targets read as obviously touchable even from across a room.

### Buttons
- **Shape:** Full pill (`borderRadius` = half the height). The primary CTA is 64px tall, 32px radius.
- **Primary:** Dusty Rose fill, white bold text, 20px font, tinted colored shadow ("Called-out" above). Press state scales to 0.96 with a spring — soft, not snappy.
- **Recording/active state:** Same shape and weight, fill swaps to Warm Taupe rather than a stop-sign red — even "hang up" avoids alarm color.
- **Secondary (dialog cancel):** Dimmed Linen fill, secondary-text color, small radius (12px) rather than full pill — visually quieter, sits behind the primary action.

### Chips
- **Style:** Small pill (12px radius), no border on the "emotion" variant, a hairline Soft Sand border on the lower-emphasis "category" variant. Background is always the primary hue at 8–15% opacity — never a flat saturated fill.
- **State:** Not interactive; purely informational tags under a chat bubble. Two tiers of emphasis via opacity, not two different hues.

### Cards / Containers
- **Corner style:** 12px (small elements: chips, memory cards) or 24px (chat bubbles, dialogs) — the radius scales with the size of the element, never sharp.
- **Background:** Paper Surface at rest, Blush Container on the one positive-feedback state (matched memory-game pair). There is deliberately no negative-feedback color anywhere in the game.
- **Shadow strategy:** "Whisper" for the status pill and other uniformly-rounded surfaces. Chat bubbles and memory-game cards carry no shadow at all: memory cards because 24 of them share the screen and any shadow at that density would read as noisy; chat bubbles because their asymmetric "speech-bubble tail" corner (one corner flattened to 4px against the other three at 24px) doesn't clip cleanly under Android's shadow renderer — a shadow needs a uniform radius to render artifact-free, so components with a cut corner skip it entirely rather than fight the platform.
- **Border:** 1px Soft Sand Outline is the only border weight in the system.
- **Internal padding:** 18–20px horizontal on bubbles/dialogs, matching the `spacing.inner` (20px) token.

### Navigation
- Bottom tab bar, 72px tall, text-only labels (no icons — removed deliberately; see Do's and Don'ts). Active tab tinted Dusty Rose, inactive tabs in Text Secondary. Header title and the single "关于" (About) text-link both sit inside a safe-area-aware header that reserves space for the status bar rather than a fixed pixel height.

### Chat Bubble (signature component)
The core interaction surface. Assistant messages carry a small round avatar (36px, filled with a hue mapped to detected emotion) and, below the bubble, up to two small chips showing detected emotion + psychological category — metadata is always secondary to the message text, positioned after it, never competing with it in size or color.

## 6. Do's and Don'ts

### Do:
- **Do** keep every color a tint or shade of the dusty-rose/warm-umber hue family (see The One Warm Hue Rule).
- **Do** use full pill shapes for primary actions and generous (12–24px) radii everywhere else — nothing sharp-cornered.
- **Do** keep shadows near-flat by default (`opacity ≤ 0.12`) and reserve any stronger lift for the one primary action per screen.
- **Do** keep body text at 18px/28px line-height minimum for anything the resident is meant to read closely; never go below 13px anywhere.
- **Do** route anything urgent or crisis-related through warm amber, never red, on any resident-facing screen.

### Don't:
- **Don't** introduce cold blues/grays, alarm-red, or "instrument panel" precision — this must never read as a medical device.
- **Don't** add oversized rounded mascots, candy colors, or bouncy/elastic easing — this is an adult companion, not a children's app.
- **Don't** use dark-mode-by-default, neon accents, geometric hard edges, or dashboard-style chrome — this must never read as a tech-company product.
- **Don't** add popups, red notification dots, badges, streaks, or marketing-voice copy anywhere — the app's job is companionship, not engagement-maximization, and anything that nudges or scores the user works against that.
- **Don't** put a decorative icon above every tab bar label by default — text-only labels were a deliberate choice; if an icon is ever reintroduced, it needs its own explicit design decision, not a library's fallback default.
- **Don't** give the memory game a negative-feedback color or shake animation on a mismatch — the only feedback state in that flow is the positive "matched" tint.
