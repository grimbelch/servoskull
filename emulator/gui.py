import curses
import math
import random
import time

from emulator.patches import EmulatorState


def run_gui(state: EmulatorState, trigger_wake_fn):
    try:
        curses.wrapper(lambda stdscr: _main(stdscr, state, trigger_wake_fn))
    except KeyboardInterrupt:
        pass


def _bar(pct: float, width: int = 22) -> str:
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _put(stdscr, row: int, col: int, text: str, attr: int = 0) -> None:
    h, w = stdscr.getmaxyx()
    if row < 0 or row >= h - 1:
        return
    text = text[: max(0, w - col - 1)]
    try:
        stdscr.addstr(row, col, text, attr)
    except curses.error:
        pass


def _main(stdscr, state: EmulatorState, trigger_wake_fn):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_RED,     -1)
    curses.init_pair(2, curses.COLOR_YELLOW,  -1)
    curses.init_pair(3, curses.COLOR_GREEN,   -1)
    curses.init_pair(4, curses.COLOR_CYAN,    -1)
    curses.init_pair(5, curses.COLOR_WHITE,   -1)
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)

    RED    = curses.color_pair(1)
    YELLOW = curses.color_pair(2)
    GREEN  = curses.color_pair(3)
    CYAN   = curses.color_pair(4)
    WHITE  = curses.color_pair(5)
    MAG    = curses.color_pair(6)
    BOLD   = curses.A_BOLD
    DIM    = curses.A_DIM

    stdscr.nodelay(True)
    stdscr.timeout(50)

    t0 = time.monotonic()

    while True:
        try:
            key = stdscr.getch()
            if key in (ord(" "), ord("\n"), 10, 13):
                trigger_wake_fn()
            elif key in (ord("q"), ord("Q"), 27):
                break
        except curses.error:
            pass

        t = time.monotonic() - t0
        stdscr.erase()

        # ── Header ────────────────────────────────────────────────────────────
        _put(stdscr, 0, 0, "  OMEGA-7  SERVO SKULL EMULATOR", RED | BOLD)
        _put(stdscr, 1, 0, "  " + "─" * 42, WHITE | DIM)

        # ── Eye LEDs ──────────────────────────────────────────────────────────
        ep = state.eye_brightness
        _put(stdscr, 3, 2,  "EYE LEDs   ", WHITE)
        _put(stdscr, 3, 13, _bar(ep), RED | (BOLD if ep > 50 else DIM))
        _put(stdscr, 3, 36, f" {ep:5.1f}%", WHITE | DIM)

        # ── Candle LEDs ───────────────────────────────────────────────────────
        cs = state.candle_state
        if cs == "idle":
            base = 30 + 20 * math.sin(t * 1.3) + 10 * math.sin(t * 3.7 + 1.1)
            cp = max(5.0, min(65.0, base + random.uniform(-8, 8)))
        elif cs == "listen":
            cp = 75 + 10 * math.sin(t * 4)
        elif cs == "think":
            cp = 20 + 35 * (0.5 + 0.5 * math.sin(t * 1.5))
        else:
            cp = 0.0

        _put(stdscr, 4, 2,  "CANDLE LEDs", WHITE)
        _put(stdscr, 4, 13, _bar(cp), YELLOW | (BOLD if cp > 50 else DIM))
        _put(stdscr, 4, 36, f" {cp:5.1f}%", WHITE | DIM)

        # ── Status ────────────────────────────────────────────────────────────
        speaking = cs == "idle" and ep > 10
        if speaking:
            slabel, sattr = "● SPEAKING",  RED | BOLD
        elif cs == "listen":
            slabel, sattr = "● LISTENING", YELLOW | BOLD
        elif cs == "think":
            slabel, sattr = "● THINKING",  CYAN | BOLD
        elif cs == "idle":
            slabel, sattr = "● IDLE",      GREEN
        else:
            slabel, sattr = "● OFFLINE",   WHITE | DIM

        _put(stdscr, 6, 2, "STATUS  ", WHITE)
        _put(stdscr, 6, 10, slabel, sattr)

        # ── Conversation ──────────────────────────────────────────────────────
        _put(stdscr, 8,  2, "HEARD",   WHITE | DIM)
        _put(stdscr, 9,  4, (state.last_heard or "—")[:68], WHITE)

        _put(stdscr, 11, 2, "OMEGA-7", RED)
        reply = state.last_reply or "—"
        row = 12
        line = ""
        for word in reply.split():
            if len(line) + len(word) + 1 > 68:
                _put(stdscr, row, 4, line, RED)
                row += 1
                line = word
            else:
                line = (line + " " + word).strip()
        if line:
            _put(stdscr, row, 4, line, RED)

        # ── Footer ────────────────────────────────────────────────────────────
        h, _ = stdscr.getmaxyx()
        _put(stdscr, h - 2, 2, "[ SPACE ] Trigger Wake Word    [ Q ] Quit", MAG)

        stdscr.refresh()
