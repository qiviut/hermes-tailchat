# Mobile browser suspension and reconnect research

Bead: `hermes-tailchat-1b7`
Date: 2026-04-11

## Why this matters

Tailchat is already useful on the tailnet from a browser, but the current MVP assumes a stable foreground desktop tab.

The user wants:
- mobile-friendly use
- correct behavior when the screen rotates
- resilience when another app is in focus or the screen is off
- background work to keep running server-side while the UI reconnects later

This note records what the current implementation does, what browser/platform behavior means for it, and what the next implementation bead should probably change.

## Current implementation findings from the codebase

### 1. The UI is desktop-first, not mobile-first

Current layout in `app/static/index.html`:
- `.wrap { display: grid; grid-template-columns: 300px 1fr; height: 100vh; }`
- fixed 300px sidebar plus main pane
- no media queries
- no orientation-specific rules
- no compact nav/drawer mode

Implications on phones:
- portrait width will be heavily constrained by the fixed sidebar
- landscape is likely better than portrait but still not purpose-built
- `height: 100vh` is risky on mobile browsers because browser chrome visibility changes can make vh sizing awkward
- there is no explicit handling for safe areas, soft keyboard overlap, or small-screen composer layout

### 2. Event streaming is a raw `EventSource` with no reconnect orchestration

Current frontend behavior:
- `openChat()` creates a new `EventSource` for `/api/conversations/{id}/events`
- if a chat is reopened, any previous source is closed first
- there is no custom `onerror` handling
- there is no `visibilitychange`, `pageshow`, `pagehide`, `online`, or `offline` listener
- there is no replay cursor in the live stream URL

Current backend behavior in `app/main.py`:
- `/api/conversations/{conversation_id}/events` streams items from an in-memory queue
- the live stream endpoint does not currently accept a cursor or replay missed events
- there is an `/events/history` endpoint, but the UI does not use it for catch-up

Implications:
- if a mobile browser backgrounds the tab, suspends JavaScript, or drops the network, the live stream may stop or silently reconnect without recovering missed events cleanly
- because the stream is queue-based, reconnecting later cannot guarantee complete replay of what happened while the browser was asleep
- the transcript may still look mostly okay after a refresh because messages are persisted, but in-progress state and transient event continuity are weak

### 3. Background jobs already continue server-side

This is good news.

Current design already supports:
- creating background jobs server-side
- a worker loop in the app process
- persisted job and message state in SQLite

Implication:
- mobile resilience does not require background execution to be invented
- the main missing piece is client reconnection/catch-up UX, not server-side continuation

## Browser/platform behavior references consulted

### MDN: Page Visibility API
Reference:
- <https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API>

Key takeaways from the article:
- browsers fire `visibilitychange` when a tab becomes hidden or visible
- hidden/background tabs are expected to reduce activity to save battery/performance
- background tabs often get timer throttling
- MDN explicitly calls out standby/screen-off style scenarios as a relevant use case

Why it matters for Tailchat:
- relying on steady foreground execution is not safe on mobile
- the client should react to `visibilitychange` and treat becoming visible again as a cue to resync

### MDN: `online` event
Reference:
- <https://developer.mozilla.org/en-US/docs/Web/API/Window/online_event>

Key takeaways:
- `online` fires when the browser regains network access and `Navigator.onLine` becomes true
- MDN warns this does not prove a specific site is reachable

Why it matters for Tailchat:
- `online` is useful as a reconnection hint
- it is not sufficient by itself; the app still needs explicit fetch/reconnect logic and probably a health/catch-up step

### MDN: `offline` event
Reference:
- <https://developer.mozilla.org/en-US/docs/Web/API/Window/offline_event>

Key takeaways:
- `offline` fires when the browser loses network access and `Navigator.onLine` becomes false

Why it matters for Tailchat:
- the UI should surface that live updates are stale
- on mobile, this can be used to switch status from "idle/streaming" to a reconnecting/degraded state instead of pretending the stream is healthy

### MDN: Using server-sent events
Reference:
- <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events>

Key takeaways:
- `EventSource` is a simple one-way event channel
- there is an error-handling section for broken streams
- MDN warns that without HTTP/2 there are low connection limits per browser+domain across tabs

Why it matters for Tailchat:
- the app should not assume `EventSource` alone gives a great mobile reconnection UX
- explicit error handling and resubscription logic are needed
- for a single-user app the connection-limit issue is not the main concern, but it is another reason to keep the design disciplined

## What is most likely to break today on mobile

### Expected weak spots
1. Portrait layout readability
   - fixed 300px sidebar is the biggest immediate UI smell
2. Orientation changes
   - no dedicated handling today
3. Screen-off / app-background periods during streaming
   - live stream continuity is weak
4. Temporary network loss on tailnet/mobile
   - no explicit reconnect state machine
5. Returning after background work completed
   - persisted messages exist, but the UI has no formal catch-up/replay model

## Practical conclusions

### Highest-value immediate product direction
The user explicitly said the first mobile priority is being able to see everything clearly in portrait and landscape.

So the best sequence remains:
1. improve mobile layout first
2. then improve reconnect/resume semantics
3. then refine background-job return-to-app UX

### Highest-value technical direction for reconnect
When implementing reconnect/resume, prefer this model:
- treat `EventSource` as live delivery only
- treat the database-backed message/history endpoints as the source of truth for catch-up
- on `visibilitychange` back to visible, `pageshow`, `online`, or `EventSource.onerror`:
  - refresh current conversation messages
  - refresh jobs/approvals
  - recreate the event stream
- optionally add event cursor/replay later, but do not block on that for the first iteration

### Highest-value UI direction for mobile
The next implementation bead should probably include:
- collapse sidebar into stacked or toggleable layout below a breakpoint
- remove fixed two-column assumption on narrow screens
- make composer/button layout work in portrait and landscape
- avoid pure `100vh` dependence where it hurts mobile browser chrome behavior
- keep jobs/approvals accessible without forcing constant horizontal competition with the transcript

## Concrete recommendations for follow-up beads

### `hermes-tailchat-t6f` / children
Implement first:
- responsive single-column mobile layout
- portrait/landscape checks
- explicit small-screen navigation behavior

### `hermes-tailchat-ipx` / `hermes-tailchat-qvf`
Implement next:
- `EventSource.onerror` handling
- `visibilitychange` listener
- `online` / `offline` listeners
- visible reconnecting/stale status
- fetch-based transcript/job refresh on resume

### `hermes-tailchat-ppb` / children
After that:
- show clearer completed/failed background-job summaries
- highlight what changed while the app was away

## Bottom line

Current Tailchat is already useful, but its mobile story is still MVP-level:
- layout is desktop-oriented
- background jobs continue server-side, which is good
- reconnect/catch-up behavior is the main missing resilience feature

The best unlock-first decision is still to ship mobile layout improvements before deeper reconnect logic, because that makes the app easier to use immediately and gives a better foundation for testing the reconnect work on actual phones.
