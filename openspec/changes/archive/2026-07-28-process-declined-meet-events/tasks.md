## 1. Calendar filtering

- [x] 1.1 Add an `exclude_declined` parameter (default `True`) to `_eligible_events` in `meet_recorder/calendar.py`, gating the existing decline check on it while leaving the ignore-slug check unconditional.
- [x] 1.2 Update `past_events` to call `_eligible_events(raw_events, config, exclude_declined=False)`.
- [x] 1.3 Confirm `find_event` and `upcoming_events` call sites are unchanged (still default to `exclude_declined=True`).

## 2. Tests

- [x] 2.1 Add a `tests/test_calendar.py` case asserting a declined event is retained by `past_events`.
- [x] 2.2 Add/confirm a `tests/test_calendar.py` case asserting a declined event is still excluded by `upcoming_events` and `find_event` (regression guard).
- [x] 2.3 Run `poetry run pytest` and confirm the full suite passes.

## 3. Docs

- [x] 3.1 Update `README.md` / `config.example.yaml` comments if they describe decline-filtering as applying uniformly to Meet-transcript ingestion.
- [x] 3.2 Run `make lint` and fix any issues.
