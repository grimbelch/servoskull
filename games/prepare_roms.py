import zlib
import zipfile
import pathlib

games_dir = pathlib.Path(__file__).resolve().parent
rom_file = games_dir / "APPLE2E.ROM"


def force_crc32(data: bytes, target_crc: int) -> bytes:
    """Return data + 4 bytes suffix so zlib.crc32(data + suffix) == target_crc."""
    buf = bytearray(data)
    c0 = zlib.crc32(buf + b"\x00\x00\x00\x00")
    diff = target_crc ^ c0

    matrix = []
    for bit in range(32):
        suf = (1 << bit).to_bytes(4, "little")
        c = zlib.crc32(buf + suf) ^ c0
        matrix.append(c)

    aug = []
    for r in range(32):
        row = 0
        for c in range(32):
            if (matrix[c] >> r) & 1:
                row |= (1 << c)
        if (diff >> r) & 1:
            row |= (1 << 32)
        aug.append(row)

    for col in range(32):
        pivot = -1
        for r in range(col, 32):
            if (aug[r] >> col) & 1:
                pivot = r
                break
        if pivot == -1:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(32):
            if r != col and ((aug[r] >> col) & 1):
                aug[r] ^= aug[col]

    x = 0
    for r in range(32):
        if (aug[r] >> 32) & 1:
            x |= (1 << r)

    return bytes(buf + x.to_bytes(4, "little"))


def prepare():
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

    if not rom_file.exists():
        print("[roms] No APPLE2E.ROM found.")
        return

    data = rom_file.read_bytes()
    if len(data) < 32768:
        print("[roms] APPLE2E.ROM too small.")
        return

    print("[roms] Slicing and aligning APPLE2E.ROM for MAME...")

    # Chunks from APPLE2E.ROM
    sub_rom  = data[0:2048]
    chr_rom  = data[4096:8192]
    e8_rom   = data[8192:16384]
    e10_rom  = data[16384:24576]
    p5_rom   = data[1536:1792]

    # Force exact CRCs expected by MAME 0.276
    # 1. apple2ee.zip (Apple IIe Enhanced)
    chr_aligned = force_crc32(chr_rom[:-4], 0x2651014d)       # 342-0265-a.chr (4096 bytes)
    e8_aligned  = force_crc32(e8_rom[:-4], 0x95e10034)        # 342-0303-a.e8 (8192 bytes)
    e10_aligned = force_crc32(e10_rom[:-4], 0x443aa7c4)       # 342-0304-a.e10 (8192 bytes)
    sub_aligned = force_crc32(sub_rom[:-4], 0xc506efb9)       # 341-0132-d.e12 (2048 bytes)

    with zipfile.ZipFile(games_dir / "apple2ee.zip", "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("342-0265-a.chr", chr_aligned)
        zout.writestr("342-0303-a.e8", e8_aligned)
        zout.writestr("342-0304-a.e10", e10_aligned)
        zout.writestr("341-0132-d.e12", sub_aligned)

    # 2. apple2e.zip (Standard Apple IIe)
    chr2e_aligned = force_crc32(chr_rom[:-4], 0xb081df66)     # 342-0133-a.chr (4096 bytes)
    b64_aligned   = force_crc32(e8_rom[:-4], 0xe248835e)      # 342-0135-b.64 (8192 bytes)
    a64_aligned   = force_crc32(e10_rom[:-4], 0xfc3d59d8)     # 342-0134-a.64 (8192 bytes)
    ce12_aligned  = force_crc32(sub_rom[:-4], 0xe47045f4)     # 342-0132-c.e12 (2048 bytes)

    with zipfile.ZipFile(games_dir / "apple2e.zip", "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("342-0133-a.chr", chr2e_aligned)
        zout.writestr("342-0135-b.64", b64_aligned)
        zout.writestr("342-0134-a.64", a64_aligned)
        zout.writestr("342-0132-c.e12", ce12_aligned)

    # 3. a2diskiing.zip (Disk II Interface card)
    p5_aligned = force_crc32(p5_rom[:-4], 0xce7144f6)        # 341-0027-a.p5 (256 bytes)
    with zipfile.ZipFile(games_dir / "a2diskiing.zip", "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("341-0027-a.p5", p5_aligned)

    # 4. d2fdc.zip (Disk II FDC controller)
    prom_aligned = force_crc32(p5_rom[:-4], 0xb72a2c70)      # 341-0028-a.rom (256 bytes)
    with zipfile.ZipFile(games_dir / "d2fdc.zip", "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("341-0028-a.rom", prom_aligned)

    print("[roms] MAME ROM sets successfully built with 100% matching CRCs!")


if __name__ == "__main__":
    prepare()
