import os
import shutil
import pathlib

# Files to migrate
FILES = [
    "settings.json",
    "owner.json",
    "memory.json",
    "longterm_memory.json",
    "mood.json",
    "reminders.json",
    "quiet.json",
    "history.json",
    "current_game.json",
    "settings.json.bak",
    "owner.json.bak",
    "memory.json.bak",
    "longterm_memory.json.bak",
    "mood.json.bak",
    "reminders.json.bak",
    "quiet.json.bak",
    "history.json.bak",
    "current_game.json.bak"
]

def main():
    # Since this file sits in ~/skull/scratch/migrate_config.py,
    # the parent of parent is the repository root (e.g. ~/skull).
    src_dir = pathlib.Path(__file__).resolve().parent.parent
    dest_dir = pathlib.Path("~/.config/omega7").expanduser()
    
    print(f"Source directory: {src_dir}")
    print(f"Destination directory: {dest_dir}")
    
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    copied_count = 0
    for name in FILES:
        src = src_dir / name
        dest = dest_dir / name
        if src.exists():
            if not dest.exists():
                try:
                    shutil.copy2(src, dest)
                    print(f"Migrated: {name} -> {dest}")
                    copied_count += 1
                except Exception as e:
                    print(f"Failed to copy {name}: {e}")
            else:
                print(f"Skipped (already exists at destination): {name}")
                
    print(f"Migration completed. {copied_count} file(s) copied.")

if __name__ == "__main__":
    main()
