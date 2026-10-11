# radiant-events

Radiant Central Coast's events feed. Every hour, GitHub Actions reads Radiant's public Church Center calendar and registrations and publishes:

- `https://legacyco.github.io/radiant-events/events.json` (read by the Squarespace embeds)
- `https://legacyco.github.io/radiant-events/events.ics` (calendar people can subscribe to)
- `https://legacyco.github.io/radiant-events/events.rss.xml`
- `https://legacyco.github.io/radiant-events/changes.json` (what changed since the last run, plus Register link warnings)

No secrets. Only events Radiant published on Church Center come through.

The source of truth for this code, the 4 Squarespace embeds, and the setup notes is `church-events-sync/` in `LegacyCo/legacy_playground` (Radiant's folder is `church-events-sync/clients/radiant-central-coast/`). Change things there and copy `pco_events_sync.py` and the workflow over, so the two don't drift.

If a run fails, nothing is published and the site keeps the last good list. The run page says why.
