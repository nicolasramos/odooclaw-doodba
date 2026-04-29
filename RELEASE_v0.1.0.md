# Release v0.1.0

## Summary

Initial public "clone-and-run" Doodba template for OdooClaw, focused on safe
bootstrapping, deterministic setup, and practical day-1 operations.

## Highlights

- Added a unified setup orchestrator:
  - `scripts/setup-odooclaw-doodba.sh`
  - Ordered flow: bootstrap -> config sync/validation -> DB/module preparation
  - Interactive and non-interactive modes
- Added bootstrap helper:
  - `scripts/bootstrap-odooclaw.sh`
  - Creates runtime files from safe examples (`config.json`, `.docker/odoo.env`)
- Added DB/module preparation helper:
  - `scripts/prepare-odoo-db.sh`
  - Enforces `mail_bot_odooclaw` source path under `odoo/custom/src/private`
  - Fails fast on invalid module install and verifies final installed state
- Added smoke testing:
  - `scripts/smoke-test-odooclaw.sh`
  - Validates service health, webhook reachability, MCP registration, and module
    presence
- Added deterministic multi-DB behavior in template setup:
  - Auto-manages `ODOO_DB`, `ODOO_DBFILTER`, and `ODOOCLAW_CHANNELS_ODOO_TARGET_DB`
- Added generic MCP command routing in template config/examples:
  - `python3 -m odoo_mcp.server`
  - `whisper-stt-mcp.py`, `edge-tts-mcp.py`, `ocr-invoice-mcp.py`, `rlm-utils-mcp.py`

## Documentation

- Expanded root `README.md` quick-start flow
- Added/updated `docs/ODOOCLAW_QUICKSTART.md`
- Updated Doodba setup guides and voice/config references

## Why this matters

This release reduces onboarding friction to a practical clone-and-run baseline while
preserving security and portability:

- No hardcoded personal credentials
- Environment-driven configuration
- Clear operational checks and troubleshooting path

## Notes

- This is the first template release baseline.
- Users should still provide their own credentials and provider settings in
  `.docker/odoo.env`.
