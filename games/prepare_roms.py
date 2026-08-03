import zlib
import zipfile
import pathlib

games_dir = pathlib.Path(__file__).resolve().parent
rom_file = games_dir / "APPLE2E.ROM"

# Fallback: check inside apple2e.zip if standalone APPLE2E.ROM isn't extracted yet
if not rom_file.exists():
    apple2e_zip = games_dir / "apple2e.zip"
    if apple2e_zip.exists():
        try:
            with zipfile.ZipFile(apple2e_zip, "r") as z:
                if "APPLE2E.ROM" in z.namelist():
                    data = z.read("APPLE2E.ROM")
                    rom_file.write_bytes(data)
        except Exception:
            pass

if rom_file.exists():
    data = rom_file.read_bytes()
    if len(data) == 32768:
        print("[roms] Slicing APPLE2E.ROM into MAME-compatible ROM archives...")

        # 1. apple2ee.zip (Apple IIe Enhanced driver)
        with zipfile.ZipFile(games_dir / "apple2ee.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("342-0265-a.chr", data[4096:8192])
            zout.writestr("342-0303-a.e8", data[8192:16384])
            zout.writestr("342-0304-a.e10", data[16384:24576])
            zout.writestr("341-0132-d.e12", data[0:2048])

        # 2. apple2e.zip (Standard Apple IIe driver)
        with zipfile.ZipFile(games_dir / "apple2e.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("342-0133-a.chr", data[4096:8192])
            zout.writestr("342-0135-b.64", data[8192:16384])
            zout.writestr("342-0134-a.64", data[16384:24576])
            zout.writestr("342-0132-c.e12", data[0:2048])

        # 3. a2diskiing.zip (Disk II Interface card)
        with zipfile.ZipFile(games_dir / "a2diskiing.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("341-0027-a.p5", data[1536:1792])

        # 4. d2fdc.zip (Disk II FDC controller)
        with zipfile.ZipFile(games_dir / "d2fdc.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("341-0028-a.rom", data[1536:1792])

        print("[roms] Successfully created apple2ee.zip, apple2e.zip, a2diskiing.zip, d2fdc.zip")
