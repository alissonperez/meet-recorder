## Context

See `proposal.md` and the delta specs for the intended behaviour. Capture currently has two independent live sources: a `sounddevice.InputStream` writes microphone chunks to `mic.wav`, and a ScreenCaptureKit handle writes system-audio chunks to `sys.wav`. Writer threads make the source files, a padding thread continuously aligns their frame counts, and a silence-monitor thread treats missing chunks as silence. The final output merges both files positionally.

The existing `pause_mic()` path is intentionally not reusable as the whole-recording pause: it leaves ScreenCaptureKit and the padding thread running so device-switch intervals are represented as silence on the microphone channel. Conversely, the new operation must make the paused interval disappear from both source files. The menubar currently models recording as one boolean and selects one of four preloaded icon states.

## Goals / Non-Goals

**Goals:**

- Introduce an explicit recording-paused state in the capture module, separate from microphone-device-switch state.
- Stop and restart both source streams while retaining the existing queues, writer threads, temporary files, and recording session.
- Quiesce time-based helpers while paused so they neither pad the files nor report silence.
- Make menubar menu enablement, labels, and icon choice derive from active, paused, and idle states.
- Serialize capture lifecycle changes and make resume transactional so concurrent or failed transitions cannot leave one source active or resurrect a finalized session.

**Non-Goals:**

- Pause or resume an already failed ScreenCaptureKit stream automatically.
- Change the normal microphone device-switch workflow or refresh audio devices when the previous microphone can be reopened normally during resume.
- Preserve audio recorded during the pause, split recordings into multiple files, or expose pause/resume through the CLI test command.
- Rework the existing padding algorithm outside the pause-specific guard.

## Decisions

### Use a session-level paused flag, separate from `mic_paused`

Add a `recording_paused` state field owned by the capture module. `mic_paused` retains its narrow meaning: the microphone stream is temporarily absent while a device switch occurs and system audio continues. Every public transition validates `recording_active` and the relevant paused state, making invalid direct calls harmless no-ops; menu callback enablement prevents those calls in normal use. A whole-recording pause is also an invalid no-op while `mic_paused` is set, so it cannot overlap the device-selection flow.

*Alternative considered:* infer whole-recording pause when both stream handles are absent. This conflates transient setup/teardown states with a user-visible state and cannot prevent timers from acting during the interval.

### Serialize lifecycle transitions and recreate only source streams

All capture lifecycle entry points — start, whole-recording pause/resume, microphone-only pause/resume, save, and discard — are serialized by one module-owned transition lock. This protects direct callers as well as the menubar and ensures teardown cannot clear shared queues and callbacks while another transition is recreating streams.

`pause_recording()` will stop and close the microphone stream, stop the current ScreenCaptureKit handle, and clear those live handles without stopping writers or deleting temporary paths. `resume_recording()` will recreate both sources using the existing callbacks, queues, and writer threads, which keeps all captured chunks in the same output session. Resume is transactional: newly opened resources remain local until both sources have started, and any failure closes every resource opened by that attempt before returning an error. Only then are both handles published and `recording_paused` cleared. Consequently a failed resume leaves both channels stopped and the session paused, and a lifecycle operation that runs afterward cannot be undone by a late worker.

Resume first tries the last selected microphone without device enumeration. If that device can no longer be opened, it refreshes PortAudio's device list, resolves and opens the current default microphone, updates `last_mic_device`, and completes the resume while reporting the fallback to the caller so the menubar can alert the user. If the fallback or ScreenCaptureKit recreation fails, the transactional cleanup applies and the session remains paused. The microphone-switch flow is disabled while the recording is globally paused or transitioning and continues to use `pause_mic()`/`resume_mic()` once active. Conversely, whole-recording pause is disabled in the menubar and rejected by the capture guard while a microphone switch is in progress.

*Alternative considered:* preserve both native streams and discard callback chunks while paused. This relies on a gate being reached before every buffer, continues system-level capture while the user expects it stopped, and leaves silence detection susceptible to stale timing.

### Suspend padding and silence helpers for the global pause interval

Before source teardown, the pause transition marks `recording_paused`; the padding loop and silence monitor skip their work while that flag is set. Pause invalidates and cancels the early system-buffer timer. Its callback verifies both its timer generation and the current active, unpaused state, so a callback already racing with cancellation cannot emit a stale warning. If no system buffer has ever arrived, a successful resume starts a new complete early-buffer window; if one arrived before the pause, the check remains satisfied and is not restarted.

Frame counts and queued real audio remain intact, but no zeros are enqueued solely because one source is stopped for the user pause. A successful resume clears stale rolling silence buffers and per-channel timing and starts a fresh monitoring grace period, so pre-pause timing cannot immediately trigger a post-resume warning. On final save/discard, helper shutdown handles both active and paused states, and final alignment is limited to any pre-existing stream skew rather than representing the paused wall-clock interval.

*Alternative considered:* stop and recreate helper threads for every pause. A shared state guard has fewer lifecycle races, retains established thread ownership, and is sufficient because helpers have no work to perform while both sources are stopped.

### Model the menubar as active recording plus paused state

Add `is_paused` and a pause/resume-transition flag alongside `is_recording`. The pause/resume menu item changes its title and callback atomically through a single recording-state refresh method: idle disables it, active recording exposes "Pausar", and paused recording exposes "Retomar". Stop, stop-without-transcription, discard, and quit continue to treat both stable active and paused states as an in-progress recording. The microphone-switch action is enabled only when actively capturing and no whole-recording transition or microphone switch is underway.

Pause/resume operations run off the AppKit event loop, following the existing background-start pattern because ScreenCaptureKit start/stop can wait for a completion callback. While either operation is in flight, the menu temporarily disables pause/resume, both stop actions, discard, microphone switching, and quit, preventing another UI lifecycle operation from racing it. Successful completion is marshalled back to the main thread to publish the new state. Failure restores the previous usable state and shows an alert; a successful microphone fallback also publishes the active state and shows a non-fatal alert identifying the fallback device. Completion handlers verify that they still correspond to the current transition before changing UI state.

While a microphone-device selection is underway, the whole-recording pause action is disabled. If another already-supported finalizer ends the session before the asynchronous microphone resume callback runs, the capture guard makes that callback harmless and the menubar ignores its stale completion rather than reopening capture or replacing the idle UI state.

*Alternative considered:* invoke pause/resume on the menu callback thread. This is smaller but can freeze the menu bar during ScreenCaptureKit's bounded start/stop waits.

### Add explicit paused icon states

Extend the icon state set with paused and paused-plus-transcribing assets, generated at the same canvas and point size as current assets. `_current_state_name()` will combine one mutually exclusive session state — idle, actively capturing, or paused — with the existing transcription state before applying the existing microphone-attention blink, which remains active only for active recording. This meets the requirement for a visually distinct paused state without overloading the idle icon, which would incorrectly imply no session can be saved or discarded.

*Alternative considered:* use blinking or the idle icon for pause. Blinking is already reserved for microphone attention; idle hides the fact that an in-progress recording remains controllable.

## Risks / Trade-offs

- [Stopping the two sources is not sample-atomic] → Stop both before declaring the UI paused, retain queued pre-pause chunks, and avoid padding through the pause; any normal capture-boundary skew is handled by the existing final alignment mechanism.
- [ScreenCaptureKit or microphone recreation fails on resume] → Publish neither new handle until both are running, close all resources created by the attempt, keep the session paused, preserve its temporary files, and restore a usable resume action. If only the previous microphone fails, refresh devices and retry with the current default before treating resume as failed.
- [A lifecycle operation races a pause/resume worker] → Serialize all capture lifecycle entry points with one lock, represent transition-in-progress separately in the menubar, disable all conflicting menu actions until completion, and ignore stale UI completions.
- [Whole-recording pause overlaps microphone switching] → Disable each operation while the other is underway and guard the same invariant in the capture module so direct calls cannot activate a microphone during global pause.
- [A stale silence buffer triggers a warning after resume] → Pause suppresses monitoring and resume resets per-channel timing/buffers or grace state before monitors evaluate newly captured chunks.
- [New icon assets become visually inconsistent] → Generate them with the existing icon asset build process and verify the fixed dimensions used by the menubar.

## Migration Plan

1. Ship the new controls as an additive menubar capability; existing recordings and orphan directories need no migration because the same per-session temporary-file format remains in use.
2. Roll back by removing the pause UI; recordings created before or after the feature remain ordinary stereo WAV files and are unaffected.

## Open Questions

None.
