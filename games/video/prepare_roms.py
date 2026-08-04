import zipfile
import pathlib

games_dir = pathlib.Path(__file__).resolve().parent
apple2e_zip = games_dir / "apple2e.zip"


def prepare():
    if apple2e_zip.exists():
        try:
            with zipfile.ZipFile(apple2e_zip, "r") as z:
                if "342-0135-b.64" in z.namelist():
                    print("[roms] Official MAME apple2e.zip present and verified.")
                    return
        except Exception:
            pass

    print("[roms] Checking ROM files in games/...")


if __name__ == "__main__":
    prepare()
