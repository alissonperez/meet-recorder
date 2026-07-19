# Prompts

meet-recorder drives three configurable prompts, all set in
`~/.config/meet-recorder/config.yaml` (see
[`config.example.yaml`](../config.example.yaml) for the defaults). This
document describes **what each prompt is for**, **what dynamic context is
prepended to it and when**, and shows an example of the **frontmatter**
written to the output files.

> Keeping this document in sync with prompt behavior is a contribution
> checklist item — see `CLAUDE.md`. Any change to what context is fed
> alongside these prompts should update this file in the same change.

## The three prompts

| Config field | Used for | LLM call |
|---|---|---|
| `transcription_prompt` | Speech-to-text hint sent alongside the audio | `/audio/transcriptions` (per chunk) |
| `summary_prompt` | System prompt for the structured Markdown summary | `chat.completions` |
| `title_prompt` | System prompt for the short (≤60 char) recording title | `chat.completions` |

## Dynamic calendar-event context

When a recording is matched to a calendar event (see
[Google Calendar integration](../README.md#google-calendar-optional)), a
small context block is built from the event and prepended to some of the
prompts. The block is produced by `_event_context()` in
`meet_recorder/transcriber.py` and looks like this:

```
Título da reunião: Weekly Sync
Descrição: Agenda: revisar roadmap do Q3 e bloqueios em aberto
Participantes: Alice Silva, Bob Santos
```

- The **title** line is always present.
- The **`Descrição:`** line is included only when the matched event has a
  non-empty description (the Google Calendar event body).
- The **`Participantes:`** line is included only when the event has
  attendees (capped by `calendar_max_attendees`).

### Where the context is applied

| Prompt | Behavior with a calendar match | Behavior without a match |
|---|---|---|
| `transcription_prompt` | The event context is prepended to `transcription_prompt` and sent as the `prompt` hint on **every** chunk request. If `transcription_prompt` is empty, the event context is still sent on its own. | The configured `transcription_prompt` is sent as-is when non-empty; the `prompt` hint is omitted when it is empty. |
| `summary_prompt` | The event context is prepended to the **user** message (the transcript); the `summary_prompt` system message is unchanged. | The transcript alone is sent as the user message. |
| `title_prompt` | **Not used.** When an event matches, the event's own title is used directly and the title LLM call is skipped. | The title is generated from the summary via the `title_prompt` (with a bounded retry loop enforcing the 60-character limit). |

## Output frontmatter

Both the transcript and the summary Markdown files start with YAML
frontmatter, built by `_frontmatter()` in `meet_recorder/transcriber.py`.

Without a calendar match, only the title is written:

```yaml
---
title: "Ponto semanal do time"
---
```

With a calendar match, the calendar-derived fields are added (each omitted
if absent on the event):

```yaml
---
title: "Weekly Sync"
calendar: "work"
event_start: "2026-07-18T10:00:00-03:00"
event_end: "2026-07-18T11:00:00-03:00"
attendees:
  - "Alice Silva"
  - "Bob Santos"
---
```

> Note: the event **description** is used only as prompt/STT context — it is
> intentionally **not** written to frontmatter.
