# GCS Regression Notes

- Control must not auto-release on a timeout; only focus/visibility changes or a real disconnect may deactivate browser control.
- The focused and visible dashboard browser is the active controller inside `gcs_server`.
- Losing dashboard focus must publish neutral controls immediately so motion cannot stick.
