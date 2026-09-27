-- MAME control script for Omega-7's Bard's Tale player (games/bardstale/emulator.py).
--
-- MAME runs headless (-video none); this script is its only interface. It talks to
-- Python through files in a tmpfs directory ($OMEGA7_BT_DIR):
--   cmd        Python writes it (atomic rename), this script executes and deletes it.
--              One command per line:
--                keys <hex>          type these bytes on the Apple II keyboard
--                load <drive> <path> insert a disk image into drive 0 or 1
--                turbo on|off        run unthrottled (fast-forward) or at real speed
--                peek <addr> <len>…  memory bytes (hex) to "peek", one field per range
--                ram                 dump main memory $0000-$BFFF (raw bytes) to "ram"
--                save <name>         write a save state (to MAME's -state_directory)
--                restore <name>      restore a save state
--                exit                quit MAME
--   frame      Raw screen pixels (BGRA, width x height), rewritten only when the picture
--              changes; "frame.info" holds "<seq> <width> <height>".

local dir = os.getenv("OMEGA7_BT_DIR") or "/dev/shm/omega7-bardstale"
local FRAME_EVERY = 6          -- 60 Hz / 6 = up to 10 captures a second
local frames, seq, last_px = 0, 0, nil

local function write_atomic(name, data)
  local tmp = dir .. "/" .. name .. ".tmp"
  local f = io.open(tmp, "wb")
  if not f then return end
  f:write(data)
  f:close()
  os.rename(tmp, dir .. "/" .. name)
end

local function unhex(h)
  return (h:gsub("%x%x", function(b) return string.char(tonumber(b, 16)) end))
end

local function run(line)
  local verb, rest = line:match("^(%S+)%s*(.*)$")
  if verb == "keys" then
    manager.machine.natkeyboard:post(unhex(rest))
  elseif verb == "load" then
    local drive, path = rest:match("^(%d)%s+(.+)$")
    local img = manager.machine.images[":sl6:diskiing:" .. drive .. ":525"]
    if img and path then
      img:unload()
      img:load(path)
      print("[bardstale.lua] drive " .. drive .. " <- " .. path)
    end
  elseif verb == "turbo" then
    manager.machine.video.throttled = (rest ~= "on")
  elseif verb == "peek" then
    -- one or more "<hex addr> <len>" pairs; ranges are written space-separated
    local space = manager.machine.devices[":maincpu"].spaces["program"]
    local ranges = {}
    for addr, len in rest:gmatch("(%x+)%s+(%d+)") do
      local out = {}
      for a = tonumber(addr, 16), tonumber(addr, 16) + tonumber(len) - 1 do
        out[#out + 1] = string.format("%02x", space:read_u8(a))
      end
      ranges[#ranges + 1] = table.concat(out)
    end
    write_atomic("peek", table.concat(ranges, " "))
  elseif verb == "ram" then
    local space = manager.machine.devices[":maincpu"].spaces["program"]
    local out = {}
    for a = 0, 0xBFFF do out[a + 1] = space:read_u8(a) end
    local parts = {}
    for i = 1, #out, 4096 do
      parts[#parts + 1] = string.char(table.unpack(out, i, math.min(i + 4095, #out)))
    end
    write_atomic("ram", table.concat(parts))
  elseif verb == "save" then
    manager.machine:save(rest)
  elseif verb == "restore" then
    manager.machine:load(rest)
  elseif verb == "exit" then
    manager.machine:exit()
  end
end

-- Keep a reference: MAME drops notifiers whose subscription is garbage-collected.
_G.omega7_sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames % FRAME_EVERY ~= 0 then return end

  local f = io.open(dir .. "/cmd", "rb")
  if f then
    local text = f:read("a")
    f:close()
    os.remove(dir .. "/cmd")
    for line in text:gmatch("[^\n]+") do
      local ok, err = pcall(run, line)
      if not ok then print("[bardstale.lua] command failed: " .. tostring(err)) end
    end
  end

  local screen = manager.machine.screens[":screen"]
  local px, w, h = screen:pixels()
  if px ~= last_px then
    last_px = px
    seq = seq + 1
    write_atomic("frame", px)
    write_atomic("frame.info", seq .. " " .. w .. " " .. h)
  end
end)
