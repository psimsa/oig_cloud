# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Battery planner wizard options: selector for Hybrid / Hybrid+Autonomy preview profiles + cheap-window and DP tuning fields (EN/CZ translations).
- Autonomy QA coverage: regression tests for the cheap-window helper and DP optimizer.

### Changed

- Timeline dialog: plan toggle switches between live Hybrid control and Autonomy preview dataset.
- Analytics tile action: “Autonomní plán” opens the timeline dialog pre-filtered to the Autonomy plan.

## [2.0.6-pre.5] - 2025-12-17

### Fixed

- Local mode: discharge-today uses proxy counter (`tbl_batt_bat_and`) to match OIG Proxy totals.
- Energy sensors: restore fallback uses entity state if attributes are missing (prevents `computed_batt_charge_energy_today` showing `0` after restart).

## [2.0.6-pre.6] - 2025-12-17

### Fixed

- Local mode: charge-today maps 1:1 to proxy counter (`tbl_batt_bat_apd`) to match OIG Proxy totals.

## [2.0.6-pre.7] - 2025-12-17

### Fixed

- OTE cache: load/persist moved off the event loop (prevents HA warning “Detected blocking call to open … oig_cloud/api/ote_api.py”).

## [2.0.6-pre.4] - 2025-12-17

### Changed

- CI: test workflow runs on `temp` and Sonar workflow validation fixed.
- Hassfest: manifest/services/translations adjusted to pass validation.
- Logging: reduced noisy debug output in runtime.
- Dashboard: mobile load/render stabilized (non-blocking chart scripts, CSS loaded without chained `@import`).
- Balancing: `battery_balancing` sensor state/attributes normalized (no `unknown` during planned balancing).

### Documentation

- User docs expanded (data source, planner, statistics) and README updated (Cloud/Local data sources + screenshots).

## [2.0.6-pre.3] - 2025-12-16

### Changed

- Repository hygiene: removed local-only helper scripts and test data; extended `.gitignore` rules to prevent re-adding.

## [2.0.6-pre.2] - 2025-12-16

### Changed

- Repository hygiene: ignore local data exports, dev-only documentation, and environment artifacts to keep the repository clean.

## [2.0.6-pre.1] - 2025-12-16

### Added

- Local datasource mode: mirror values from local HA entities into cloud OIG sensors (event-driven) with UI/dashboard support.
- Local SonarQube tooling: `docker-compose.sonarqube.yml`, `scripts/sonar_local.sh`, and coverage config to run scans locally.

### Changed

- Dashboard value updates: split-flap/flip-style animations + alignment fixes for tiles and configurable side tiles.
- Hybrid optimizer refactor: extracted helper functions to reduce cognitive complexity (no behavior change intended).

### Fixed

- Options flow (HA 2025.12): hardening around handler-based entry id/protected attrs and initialization issues.
- Frontend HYBRID key mapping: consistent key mapping across dashboard JS modules.

## [2.0.5] - 2025-10-29

### Added

- Extended Timeline API (“Historie vs Plán”): 3-day view (yesterday/today/tomorrow), actual vs planned comparison, daily plan fixation, and accuracy metrics.
- New dashboard tab “HISTORIE vs PLÁN” for visualization of historical vs planned bars and deltas.

### Changed

- Mode recommendations filtering switched from `today_start` to `NOW` for future-only data.

### Fixed

- DP optimization: ensure optimal interval modes are applied before battery calculations; fix timeline starting point to `NOW`.

### Documentation

- Added/updated docs for `timeline_extended` and `daily_plan_state` response structures.

## [2.0.4] - 2025-10-24

### Added

- ČHMÚ weather warnings integration (CAP XML client + sensors for local/global warnings, severity mapping, dashboard badge + modal).

### Changed

- Grid charging sensor refactor: numeric → binary sensor; energy/cost moved to attributes; count only actual battery charging.

### Fixed

- Dashboard chart: default zoom now shows current time; improved initialization after hard refresh; fixed timezone handling.

### Removed

- Experimental automatic battery charging based on weather conditions.

## [2.0.3-preview] - 2025-10-20

### Added

- Energy Flow dashboard (real-time visualization of grid/solar/battery/home/boiler flows).
- ServiceShield improvements (event-based monitoring, better queue UX, retries, safer serialization of operations).
- Wizard config flow (guided setup, improved validation, and Czech localization).
- Light/Dark theme support across the frontend.
- Docker-based test infrastructure + CI wiring for consistent testing.
- Documentation expansion under `docs/user/` and `docs/dev/`.

### Changed

- Minimum supported Home Assistant version raised (internal APIs modernized).
- API client vendored into the repository (self-contained installation).

### Fixed

- Grid delivery mode/limit mapping and service ordering.
- Boiler mode stability (no UI blinking on changes).

### Notes

This is a preview release intended for testers. Some UI elements may be present but disabled (waiting for upstream OIG documentation); `formating_mode` uses a fixed timeout.

## [2.0.0-beta] - 2025-10-19

### Added

- Multi-device support for multiple battery boxes on one OIG Cloud account (`device_id` selector in services).
- Vendored OIG Cloud client under `custom_components/oig_cloud/lib/oig_cloud_client/` (self-contained installation).
- Wizard configuration flow (new install UX with guided steps and localization).
- ServiceShield improvements (configurable timeout, better monitoring, and diagnostics).
- API update optimizations (ETag support and polling jitter).
- Documentation restructure under `docs/user/` and `docs/dev/`.
- Tests + CI wiring (pytest, coverage, basic linting checks).

### Changed

- Configuration flow redesigned (existing installs should migrate automatically; new installs go through the wizard).
- Internal imports updated to use the vendored API client.
- Device handling generalized to support multiple devices per config entry.

### Fixed

- Jitter and caching behavior in the coordinator.
- Service schema validation for `device_id`.
- Device identifier parsing (`_shield` / `_analytics` suffixes).
- Orphaned device cleanup when a battery box disappears from the account.

### Removed

- External dependency on the `oig-cloud-client` PyPI package.

### Migration

If you use multiple devices, update automations/service calls to include `device_id` as needed; see `docs/user/SERVICES.md`.

## [1.0.6] - 2024-12-15

### Added

- Extended sensors for battery charging/discharging tracking.
- Separate measurement of battery charging from PV vs. grid.
- Configurable update intervals for standard and extended statistics.
- More accurate energy measurements using custom integration.
- Improved boiler power calculation.

### Changed

- Statistics reset at end of day/month/year.
- Code structure improvements for reliability.
- Enhanced logging for debugging.

### Fixed

- Various bug fixes and stability improvements.

## [1.0.5] - 2024-11-01

### Added

- ServiceShield™ protection against unwanted mode changes.
- Basic multi-language support.

### Fixed

- Stability improvements.
- API communication fixes.

## [1.0.0] - 2024-09-01

### Added

- Initial release.
- Basic ČEZ Battery Box integration.
- Energy dashboard support.
- Service calls for mode control.
- Statistics tracking.

[Unreleased]: https://github.com/psimsa/oig_cloud/compare/v2.0.6-pre.3...HEAD
[2.0.6-pre.3]: https://github.com/psimsa/oig_cloud/compare/v2.0.6-pre.2...v2.0.6-pre.3
[2.0.6-pre.2]: https://github.com/psimsa/oig_cloud/compare/v2.0.4...v2.0.6-pre.2
[2.0.4]: https://github.com/psimsa/oig_cloud/compare/v2.0.3-preview...v2.0.4
[2.0.3-preview]: https://github.com/psimsa/oig_cloud/compare/v2.0.2-preview...v2.0.3-preview
[2.0.0-beta]: https://github.com/psimsa/oig_cloud/compare/v1.0.6...v2.0.0-beta
[1.0.6]: https://github.com/psimsa/oig_cloud/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/psimsa/oig_cloud/compare/v1.0.0...v1.0.5
[1.0.0]: https://github.com/psimsa/oig_cloud/releases/tag/v1.0.0
