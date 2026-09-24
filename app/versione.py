from pathlib import Path
VERSION = (Path(__file__).parent / 'VERSION.txt').read_text(encoding='utf-8').strip()
