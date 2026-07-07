import sys
import os

print(f"Python Executable: {sys.executable}")
try:
    import aiosqlite
    print("✅ aiosqlite is successfully installed!")
except ImportError:
    print("❌ aiosqlite NOT found in this environment.")
    print("\nEnvironment Paths:")
    for path in sys.path:
        print(f"  - {path}")
