# Devtools

Local operational/debugging utilities for manual verification.

These scripts are not production runtime code and are not part of the automated pytest suite.

## Persistent tools

### list_periods.py
Lists reporting periods for manual upload testing.

### verify_rdb_upload.py
Runs DB sanity checks after RDB uploads.

## Temporary tools

### tmp_create_temp_admin.py
Creates a temporary admin user for stub-auth local testing.
Can be removed after real auth/admin seeding is implemented.