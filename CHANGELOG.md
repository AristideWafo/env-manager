# Changelog

All notable changes to this project are documented here. Entries are
generated automatically from conventional commits by the release pipeline.

<!-- entries below are prepended automatically, newest first -->
## v0.12.2 - 2026-08-31

### [0.12.2](https://github.com/AristideWafo/env-manager/compare/v0.12.1...v0.12.2) (2026-08-31)


### Code Refactoring

* **ui:** remove django-cotton, add plain-CSS design system ([#17](https://github.com/AristideWafo/env-manager/issues/17)) ([59dca01](https://github.com/AristideWafo/env-manager/commit/59dca01a383972e92c0d2f5ad0dbef9f8e431871))

## v0.12.1 - 2026-08-28

### [0.12.1](https://github.com/AristideWafo/env-manager/compare/v0.12.0...v0.12.1) (2026-08-28)


### Bug Fixes

* **ui:** remove content ghost-gap, stabilize variables table columns ([#16](https://github.com/AristideWafo/env-manager/issues/16)) ([84ad96b](https://github.com/AristideWafo/env-manager/commit/84ad96bad0fecad8e4f19014d2b9d45d79c0aa0a))

## v0.12.0 - 2026-08-28

## [0.12.0](https://github.com/AristideWafo/env-manager/compare/v0.11.0...v0.12.0) (2026-08-28)


### Features

* **auth:** auto-logout after 10 minutes idle ([#15](https://github.com/AristideWafo/env-manager/issues/15)) ([edfbfa2](https://github.com/AristideWafo/env-manager/commit/edfbfa27ceb857ab546564db18994698c712f2ab))

## v0.11.0 - 2026-08-28

## [0.11.0](https://github.com/AristideWafo/env-manager/compare/v0.10.0...v0.11.0) (2026-08-28)


### Features

* **ui:** responsive mobile sidebar nav with slide-in toggle ([#14](https://github.com/AristideWafo/env-manager/issues/14)) ([1182ee6](https://github.com/AristideWafo/env-manager/commit/1182ee6c7cd6e1b231e4aca10982efd6a2d026df))

## v0.10.0 - 2026-08-28

## [0.10.0](https://github.com/AristideWafo/env-manager/compare/v0.9.3...v0.10.0) (2026-08-28)


### Features

* **sync:** Refresh from file now overwrites tracked variables ([#13](https://github.com/AristideWafo/env-manager/issues/13)) ([82e90a2](https://github.com/AristideWafo/env-manager/commit/82e90a2246d302a5483d3659c5d604dbafcab9cc))

## v0.9.3 - 2026-08-28

### [0.9.3](https://github.com/AristideWafo/env-manager/compare/v0.9.2...v0.9.3) (2026-08-28)


### Bug Fixes

* **ui:** surface result/error feedback on Refresh from file ([#12](https://github.com/AristideWafo/env-manager/issues/12)) ([510773e](https://github.com/AristideWafo/env-manager/commit/510773e7ae085c885cd7cf311ba3b976f7db87d7))

## v0.9.2 - 2026-08-28

### [0.9.2](https://github.com/AristideWafo/env-manager/compare/v0.9.1...v0.9.2) (2026-08-28)


### Bug Fixes

* **ui:** group name with '/' broke rename/ungroup URL routing ([#11](https://github.com/AristideWafo/env-manager/issues/11)) ([3dc71b8](https://github.com/AristideWafo/env-manager/commit/3dc71b87cc63eba34a02c4d4f170dfaf94338f13))

## v0.9.1 - 2026-08-28

### [0.9.1](https://github.com/AristideWafo/env-manager/compare/v0.9.0...v0.9.1) (2026-08-28)


### Bug Fixes

* **prod:** staticfiles manifest never generated at Docker build time ([#10](https://github.com/AristideWafo/env-manager/issues/10)) ([2015cbc](https://github.com/AristideWafo/env-manager/commit/2015cbca481d1e0c4f7b01c1384c771204ec6b0a))

## v0.9.0 - 2026-08-28

## [0.9.0](https://github.com/AristideWafo/env-manager/compare/v0.8.0...v0.9.0) (2026-08-28)


### Features

* **editor:** preserve group header decoration style (====, ---, length) ([#9](https://github.com/AristideWafo/env-manager/issues/9)) ([4fe5b4d](https://github.com/AristideWafo/env-manager/commit/4fe5b4dbe0c452c956b5903a4877ee37234eab63))

## v0.8.0 - 2026-08-28

## [0.8.0](https://github.com/AristideWafo/env-manager/compare/v0.7.1...v0.8.0) (2026-08-28)


### Features

* **editor:** write structured file, group-contiguity invariant, refresh button ([#8](https://github.com/AristideWafo/env-manager/issues/8)) ([72bfe51](https://github.com/AristideWafo/env-manager/commit/72bfe5107253e99d613553fdf11244d881c31f5a)), closes [#1](https://github.com/AristideWafo/env-manager/issues/1)

## v0.7.1 - 2026-08-28

### [0.7.1](https://github.com/AristideWafo/env-manager/compare/v0.7.0...v0.7.1) (2026-08-28)


### Bug Fixes

* **static:** use non-manifest static storage in DEBUG to avoid requiring collectstatic locally ([2d3e5ec](https://github.com/AristideWafo/env-manager/commit/2d3e5ec424748c305b3cf88c8beeaa41c587e0be))

## v0.7.0 - 2026-08-28

## [0.7.0](https://github.com/AristideWafo/env-manager/compare/v0.6.0...v0.7.0) (2026-08-28)


### Features

* **editor:** variable reorder (up/down) and group rename/ungroup ([#6](https://github.com/AristideWafo/env-manager/issues/6)) ([9f0bb4d](https://github.com/AristideWafo/env-manager/commit/9f0bb4d018841aa41754de2c25a47200295a69d1))


### Bug Fixes

* **ci:** run collectstatic before tests so full-page views are testable ([#7](https://github.com/AristideWafo/env-manager/issues/7)) ([ff019e9](https://github.com/AristideWafo/env-manager/commit/ff019e9a4c1ca28a9599fca5476c5b49a5b001fa))

## v0.6.0 - 2026-08-28

## [0.6.0](https://github.com/AristideWafo/env-manager/compare/v0.5.0...v0.6.0) (2026-08-28)


### Features

* **ui:** render variables grouped, with comments; edit group/comment inline ([#5](https://github.com/AristideWafo/env-manager/issues/5)) ([d2d66d9](https://github.com/AristideWafo/env-manager/commit/d2d66d9f81baecda5e90080be36d0ddef452cd05))

