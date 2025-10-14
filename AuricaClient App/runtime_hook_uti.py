# runtime_hook_uti.py – tolerant
import sys
try:
    import UniformTypeIdentifiers as _UTI  # noqa: F401
    # Optional: ein klein wenig Logging
    print('[AuricaClient] runtime_hook_uti: UTI geladen')
except Exception as e:
    print('[AuricaClient] runtime_hook_uti: UTI NICHT geladen:', e, file=sys.stderr)
    # Wichtig: NICHT crashen – nur loggen
