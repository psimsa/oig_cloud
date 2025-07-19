

# OIG Cloud Repository Summary

## Purpose
This repository provides a Home Assistant integration for ČEZ Battery Box systems via OIG Cloud. The integration allows users to:
- Monitor battery status, production, consumption, and historical data
- Set operating modes and regulate grid overflow
- Integrate with Home Assistant's Energy dashboard
- Configure the system through Home Assistant's UI

## General Setup
- **Platform**: Home Assistant custom integration
- **Language**: Python
- **Main Component**: `custom_components/oig_cloud/`
- **Distribution**: HACS (Home Assistant Community Store)

## Repository Structure

### Root Level
- `README.md`: Main documentation in Czech
- `LICENSE`: License information
- `requirements.txt` / `requirements-dev.txt`: Python dependencies
- `.github/workflows/`: GitHub Actions CI/CD configuration

### Custom Component (`custom_components/oig_cloud/`)
- `__init__.py`: Main integration initialization
- `api/`: API client for OIG Cloud
- `sensor.py`, `binary_sensor.py`: Sensor implementations
- `sensor_types.py`, `binary_sensor_types.py`: Sensor type definitions
- `config_flow.py`: Configuration flow for Home Assistant
- `coordinator.py`: Data update coordinator
- `services.py`/`services.yaml`: Service definitions
- `manifest.json`: Integration metadata

### Tests
- `tests/`: Unit tests for the integration
- Test files cover API, models, and coordinator functionality

## CI/CD Workflows

1. **HACS Validation** (`.github/workflows/hacs.yml`)
   - Validates HACS integration compatibility
   - Runs on push, pull request, and daily schedule

2. **Hassfest Validation** (`.github/workflows/hassfest.yml`)
   - Validates Home Assistant integration standards
   - Runs on push, pull request, and daily schedule

3. **Testing** (`.github/workflows/test.yml`)
   - Runs pytest unit tests
   - Triggers on push/pull request to main branch
   - Uses Python 3.13

4. **Release Management** (`.github/workflows/release.yml`)
   - Manual workflow for creating releases
   - Updates version information in manifest and release constants
   - Creates GitHub releases and tags

