# Product

## Register

product

## Users

Elderly residents in nursing homes, using the app on their own (or with light staff assistance) as a daily voice companion. Many have limited literacy in small text, may have tremor or reduced fine motor control, and are not digitally fluent — this is likely one of very few apps on their phone. Sessions happen in a quiet, personal moment: talking to the app when they want company, not while multitasking.

The job to be done is emotional: being heard and responded to with warmth, not completing a task efficiently. Screens should never make the user feel evaluated, hurried, or lost.

## Product Purpose

AgeTalker is a voice-based AI companion that listens (ASR), reads emotional tone (emotion recognition), responds with a psychologically-grounded reply (CARE-framework LLM), and speaks back in a voice that mirrors the user's emotional state (emotion-aware TTS). Secondary surfaces: a "练练脑" memory/cognitive game, and a "我自己" profile area.

Success looks like: a lonely or distressed elderly user finishes a session feeling calmer and accompanied, uses it again without needing to be reminded how, and crisis-risk conversations get detected and escalated without ever making the user on-screen feel alarmed.

## Brand Personality

Warm, healing, textured (温暖 / 疗愈 / 有质感). Calm and steady rather than energetic — the interface should feel like a constant, unhurried presence, not something that competes for attention. Restrained, not cute: an adult companion, not a childlike assistant.

## Anti-references

- **Not clinical/medical-device.** No cold blues/grays, no alarm-red, no "instrument panel" precision. (Already reflected in code: crisis states use warm amber, not red — red is reserved for caregiver-facing controls only, never shown to the user in crisis.)
- **Not childlike/cartoonish.** No oversized rounded mascots, no candy colors, no playful bounce animations. The user is an adult who deserves to be treated as one.
- **Not tech-company/cyber.** No dark-mode-by-default, no neon accents, no geometric hard edges, no "startup dashboard" chrome.
- **Not commercial/pushy.** No popups, no red notification dots, no marketing-voice copy, no urgency-driven UI patterns (badges, streaks, upsells). The app's job is companionship, not engagement-maximization.

## Design Principles

1. **Never alarm the person in front of you.** Even in a crisis-detection flow, the user-facing screen stays warm and safe-feeling; anything urgent-looking is reserved for caregiver-side surfaces only.
2. **Calm over efficient.** This isn't a productivity tool — favor generous spacing, unhurried pacing, and large/legible text over information density.
3. **Adult, not childlike.** Respect the user's dignity: simple and legible, never cutesy or condescending.
4. **One steady presence, not a feed.** Avoid social/notification patterns (badges, streaks, popups) that create anxiety or the sense of being watched/scored.
5. **Consistency over novelty.** Extend the existing warm dusty-rose/cream palette and Lexend typography rather than introducing new visual language per screen.

## Accessibility & Inclusion

Large text and high color contrast throughout (already the baseline in the existing type scale and palette). No formal WCAG level target beyond that — prioritize practical legibility and large touch targets for users with reduced fine motor control over formal compliance checklists.
