import zlib
import zipfile
import pathlib

games_dir = pathlib.Path(__file__).resolve().parent

apple2e_path = games_dir / "apple2e.zip"

if apple2e_path.exists():
    try:
        with zipfile.ZipFile(apple2e_path, "r") as z:
            names = z.namelist()
            if "APPLE2E.ROM" in names:
                data = z.read("APPLE2E.ROM")
            else:
                data = None
    except Exception:
        data = None

    if data and len(data) == 32768:
        print("[roms] Slicing APPLE2E.ROM into MAME-compatible ROM archives...")

        # 1. apple2e.zip
        # 342-0133-a.chr (4096 bytes at offset 4096)
        # 342-0135-b.64  (8192 bytes at offset 8192)
        # 342-0134-a.64  (8192 bytes at offset 16384)
        # 342-0132-c.e12 (2048 bytes at offset 0)
        chr_rom = data[4096:8192]
        sys1_rom = data[8192:16384]
        sys2_rom = data[16384:24576]
        sub_rom = data[0:2048]

        with zipfile.ZipFile(games_dir / "apple2e.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("342-0133-a.chr", chr_rom)
            zout.writestr("342-0135-b.64", sys1_rom)
            zout.writestr("342-0134-a.64", sys2_rom)
            zout.writestr("342-0132-c.e12", sub_rom)

        # 2. a2diskiing.zip
        p5_rom = data[1536:1792]  # 256 bytes P5 disk controller
        with zipfile.ZipFile(games_dir / "a2diskiing.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("341-0027-a.p5", p5_rom)

        # 3. d2fdc.zip
        prom_rom = data[1536:1792]
        with zipfile.ZipFile(games_dir / "d2fdc.zip", "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("341-0028-a.rom", prom_rom)

        print("[roms] Successfully created apple2e.zip, a2diskiing.zip, d2fdc.zip")
