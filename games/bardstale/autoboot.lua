-- MAME Autoboot Script for Bard's Tale (Apple IIe)
-- Automates disk swapping so the game transitions seamlessly from the Boot Disk to the Character Disk.

local swapped = false
local frame = 0

emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if frame == 120 and not swapped then
        swapped = true
        local img = manager.machine.images[":sl6:diskiing:0:525"]
        if img then
            local char_disk = "/home/sspeer/skull/games/bardstale/disks/bards_tale_character.dsk"
            img:unload()
            img:load(char_disk)
            print("[bardstale] MAME Lua: Auto-swapped Drive 1 to bards_tale_character.dsk")
        end
    end
end)
