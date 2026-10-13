#!/usr/bin/env python3
"""
Flappy Window - a simple Flappy Bird clone for macOS using Python and PyObjC.
"""

import math
import os
import random
import signal
import sys

import Quartz
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventTypeKeyDown,
    NSFont,
    NSScreen,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect, NSTimer

# ------------------------------------------------------------------ #
#  Game parameters                                                   #
# ------------------------------------------------------------------ #
CELL           = 40
BIRD_X         = 300
BIRD_W         = 60
BIRD_H         = 50
PIPE_WIDTH     = 70
PIPE_GAP       = 250
PIPE_SPEED     = 5
PIPE_COUNT     = 4
PIPE_SPACING   = 280
GRAVITY        = 1.0
JUMP           = 14
FPS            = 60
TICK           = 1.0 / FPS
COUNTDOWN_FROM = 3.0
GO_DISPLAY     = 0.7

KEY_SPACE  = 49
KEY_ESCAPE = 53
CAPTURED_KEYS = {KEY_SPACE, KEY_ESCAPE}

screen_frame = NSScreen.mainScreen().frame()
SCREEN_W = int(screen_frame.size.width)
SCREEN_H = int(screen_frame.size.height)


# ------------------------------------------------------------------ #
#  Accessibility                                                      #
# ------------------------------------------------------------------ #
def ensure_accessibility_permission() -> bool:
    """
    Check if the application has accessibility permission.
    """

    if AXIsProcessTrusted():
        return True

    trusted = AXIsProcessTrustedWithOptions(
        {"AXTrustedCheckOptionPrompt": True}
    )

    if trusted:
        print("✅ Acessibility granted.")
        return True

    print()
    print("❌ Accessibility permission not granted.")
    print("   Open: System Settings - Privacy & Security - Accessibility")
    print("   And restart terminal / IDE. Then run Flappy again.")
    print()
    return False


# ------------------------------------------------------------------ #
#  Key interception                                                  #
# ------------------------------------------------------------------ #
_global_key_tap = None
_global_tap_runloop = None
_global_local_monitor = None


def install_key_interceptor(handler, captured_keys: set):
    """
    Install a global key interceptor for the specified keys.
    """

    global _global_key_tap, _global_tap_runloop, _global_local_monitor

    def local_monitor(event):
        if event.type() != NSEventTypeKeyDown:
            return event
        code = event.keyCode()
        if code in captured_keys:
            handler(int(code))
            return None
        return event

    if _global_local_monitor is None:
        try:
            _global_local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown,
                local_monitor,
            )
        except Exception as exc:
            print(f"⚠️ fallback not created: {exc}")

    if _global_key_tap is not None:
        return True

    def tap_callback(proxy, event_type, event, refcon):
        if event_type != Quartz.kCGEventKeyDown:
            return event

        key_code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if key_code in captured_keys:
            handler(int(key_code))
            return None
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        tap_callback,
        None,
    )

    if tap is None:
        print("❌ CGEventTap not created.")
        return False

    _global_key_tap = tap
    _global_tap_runloop = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        _global_tap_runloop,
        Quartz.kCFRunLoopCommonModes,
    )
    Quartz.CGEventTapEnable(tap, True)
    return True


# ------------------------------------------------------------------ #
#  Window-Objects                                                    #
# ------------------------------------------------------------------ #
def make_window(x, y, w, h, color, level=25):
    """
    Create a transparent window at the specified position and size.
    """

    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, w, h),
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    win.setBackgroundColor_(color)
    win.setLevel_(level)
    win.setOpaque_(False)
    win.setHasShadow_(False)
    win.setIgnoresMouseEvents_(True)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )
    win.makeKeyAndOrderFront_(None)
    return win


def make_pixel_block(x, y, w, h, color, level=25):
    """
    Create a pixel block at the specified position and size.
    """

    return make_window(x, y, w, h, color, level=level)


class PixelBirdView(NSView):
    """
    Custom view for drawing the pixelated bird.
    """

    def drawRect_(self, rect):
        """
        Draw the pixelated bird using a predefined pattern
        and color palette.
        """

        w, h = self.bounds().size.width, self.bounds().size.height

        palette = {
            '.': None,
            'W': NSColor.whiteColor(),
            'B': NSColor.blackColor(),
            'Y': NSColor.yellowColor(),
            'R': NSColor.colorWithDeviceRed_green_blue_alpha_(0.8, 0.0, 0.0, 1.0),
            'O': NSColor.orangeColor(),
        }

        rows = [
            "      BBBBBBBB     ",
            "    BBYYYYYBWWB    ",
            "   BYYYYYYBWWWWB   ",
            "  BYYYYYYYBWWWBWB  ",
            " BYYYYYYYYBWWWBWB  ",
            " BBBBBYYYYYBWWWWB  ",
            "BYYYYYBYYYYYBBBBBB ",
            "BYYYYYBYYYYBRRRRRRB",
            " BBBBBOOOOBRBBBBBB ",
            "  BOOOOOOOOBRRRRRB ",
            "   BBOOOOOOOBBBBB  ",
            "     BBBBBBB       ",
        ]

        cols = max(len(r) for r in rows)
        cell = min(w // cols, h // len(rows))
        if cell <= 0:
            cell = 1
        start_x = (w - cols * cell) / 2.0
        start_y = (h - len(rows) * cell) / 2.0

        for row_index, row in enumerate(rows):
            for col_index, ch in enumerate(row):
                color = palette.get(ch)
                if color is None:
                    continue
                x = start_x + col_index * cell
                y = start_y + (len(rows) - 1 - row_index) * cell
                color.set()
                NSBezierPath.bezierPathWithRect_(NSMakeRect(x, y, cell, cell)).fill()


class PixelPipeView(NSView):
    """
    Custom view for drawing the pixelated pipes.
    """

    def drawRect_(self, rect):
        """
        Draw the pixelated pipe with a green body and black outline.
        """

        w, h = self.bounds().size.width, self.bounds().size.height
        if w <= 0 or h <= 0:
            return

        is_lower = bool(getattr(self, 'invert', False))
        body_green = NSColor.colorWithDeviceRed_green_blue_alpha_(0.25, 0.75, 0.29, 1.0)
        body_dark = NSColor.colorWithDeviceRed_green_blue_alpha_(0.17, 0.54, 0.24, 1.0)
        outline = NSColor.blackColor()

        border = 2
        margin = max(2, int(w * 0.18))
        body_x = margin
        body_w = max(1, w - margin * 2)

        if is_lower:
            mouth_h = max(18, min(h * 0.18, 28))
            body_h = max(1, h - mouth_h)
            body_y = 0
            mouth_y = h - mouth_h
        else:
            mouth_h = max(18, min(h * 0.18, 28))
            body_h = max(1, h - mouth_h)
            body_y = mouth_h
            mouth_y = 0

        mouth_w = max(body_w + 18, w * 0.9)
        mouth_x = (w - mouth_w) / 2.0

        # Fill mouth first, then body, then clean black outline.
        body_green.set()
        NSBezierPath.bezierPathWithRect_(NSMakeRect(mouth_x, mouth_y, mouth_w, mouth_h)).fill()

        body_dark.set()
        NSBezierPath.bezierPathWithRect_(NSMakeRect(body_x, body_y, body_w, body_h)).fill()

        outline.set()
        for x, y, ww, hh in [
            (body_x, body_y, body_w, border),
            (body_x, body_y + body_h - border, body_w, border),
            (body_x, body_y, border, body_h),
            (body_x + body_w - border, body_y, border, body_h),
            (mouth_x, mouth_y, mouth_w, border),
            (mouth_x, mouth_y + mouth_h - border, mouth_w, border),
            (mouth_x, mouth_y, border, mouth_h),
            (mouth_x + mouth_w - border, mouth_y, border, mouth_h),
        ]:
            NSBezierPath.bezierPathWithRect_(NSMakeRect(x, y, ww, hh)).fill()


# ------------------------------------------------------------------ #
#  Game state                                                        #
# ------------------------------------------------------------------ #
bird_win = None
bird_parts = []
pipe_top_win = None
pipe_bottom_win = None
pipes = []
score_win = None
score_field = None
prompt_win = None
prompt_field = None

bird_y = 0
bird_vy = 0
pipe_x = 0
gap_y = 0
score = 0
passed_pipe = False

state = "start_prompt"       # 'start_prompt' | 'countdown' | 'playing' | 'game_over_pause'
countdown = COUNTDOWN_FROM
go_timer = 0.0
post_game_pause = 0.0


# ------------------------------------------------------------------ #
#  UI                                                                 #
# ------------------------------------------------------------------ #
def create_bird():
    """
    Create the bird window and its pixelated view.
    """

    global bird_win, bird_parts

    if bird_win is not None:
        bird_win.orderOut_(None)
    bird_parts = []

    bird_win = make_window(BIRD_X, bird_y, BIRD_W, BIRD_H, NSColor.clearColor(), level=26)
    bird_win.setOpaque_(False)
    bird_win.setBackgroundColor_(NSColor.clearColor())
    bird_canvas = PixelBirdView.alloc().initWithFrame_(NSMakeRect(0, 0, BIRD_W, BIRD_H))
    bird_win.setContentView_(bird_canvas)
    bird_parts = [bird_canvas]


def update_bird_sprite():
    """
    Update the bird's position and redraw its sprite.
    """

    if not bird_win:
        return
    bird_win.setFrameOrigin_((BIRD_X, bird_y))
    if bird_win.contentView():
        bird_win.contentView().setNeedsDisplay_(True)


def show_bird():
    """
    Show the bird window.
    """

    if bird_win:
        bird_win.makeKeyAndOrderFront_(None)


def hide_bird():
    """
    Hide the bird window.
    """

    if bird_win:
        bird_win.orderOut_(None)


def make_pipe_pair(x, gap_y):
    """
    Create a pair of pipe windows (top and bottom)
    at the specified x position and gap_y.
    """

    top_y = gap_y + PIPE_GAP
    top_h = max(1, SCREEN_H - top_y)
    bot_h = max(1, gap_y)

    top_pipe = make_window(x, top_y, PIPE_WIDTH, top_h, NSColor.clearColor())
    bottom_pipe = make_window(x, 0, PIPE_WIDTH, bot_h, NSColor.clearColor())
    top_pipe.setOpaque_(False)
    bottom_pipe.setOpaque_(False)

    top_view = PixelPipeView.alloc().initWithFrame_(NSMakeRect(0, 0, PIPE_WIDTH, top_h))
    bottom_view = PixelPipeView.alloc().initWithFrame_(NSMakeRect(0, 0, PIPE_WIDTH, bot_h))
    top_view.invert = False
    bottom_view.invert = True
    top_pipe.setContentView_(top_view)
    bottom_pipe.setContentView_(bottom_view)

    return {
        "x": x,
        "gap_y": gap_y,
        "top": top_pipe,
        "bottom": bottom_pipe,
        "passed": False,
    }


def create_pipes():
    """
    Create the initial set of pipe pairs and position them off-screen.
    """

    global pipe_top_win, pipe_bottom_win, pipes

    for pipe in pipes:
        for win in (pipe["top"], pipe["bottom"]):
            if win:
                win.orderOut_(None)
    pipes = []

    start_x = SCREEN_W + 180
    for i in range(PIPE_COUNT):
        gap_y = random.randint(190, SCREEN_H - 190 - PIPE_GAP)
        pair = make_pipe_pair(start_x + i * PIPE_SPACING, gap_y)
        pipes.append(pair)

    if pipes:
        pipe_top_win = pipes[0]["top"]
        pipe_bottom_win = pipes[0]["bottom"]


def create_score():
    """
    Create the score window and its text field.
    """

    global score_win, score_field
    score_w = 520
    score_h = 90
    score_x = SCREEN_W / 2 - score_w / 2
    score_y = SCREEN_H - score_h - 30

    score_win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(score_x, score_y, score_w, score_h),
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    score_win.setBackgroundColor_(NSColor.clearColor())
    score_win.setOpaque_(False)
    score_win.setLevel_(26)
    score_win.setIgnoresMouseEvents_(True)
    score_win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )

    score_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, score_w, score_h))
    score_field.setStringValue_("")
    score_field.setBezeled_(False)
    score_field.setDrawsBackground_(False)
    score_field.setEditable_(False)
    score_field.setSelectable_(False)
    score_field.setAlignment_(1)
    score_field.setFont_(NSFont.boldSystemFontOfSize_(52))
    score_field.setTextColor_(NSColor.yellowColor())

    score_win.setContentView_(score_field)
    score_win.makeKeyAndOrderFront_(None)


def create_prompt_window():
    """
    Create the prompt window and its text field.
    """

    global prompt_win, prompt_field
    if prompt_win is not None:
        prompt_win.orderOut_(None)

    prompt_win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(SCREEN_W / 2 - 180, SCREEN_H / 2 - 40, 360, 80),
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    prompt_win.setBackgroundColor_(NSColor.clearColor())
    prompt_win.setOpaque_(False)
    prompt_win.setLevel_(27)
    prompt_win.setIgnoresMouseEvents_(True)
    prompt_win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )

    prompt_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 80))
    prompt_field.setStringValue_("")
    prompt_field.setBezeled_(False)
    prompt_field.setDrawsBackground_(False)
    prompt_field.setEditable_(False)
    prompt_field.setSelectable_(False)
    prompt_field.setAlignment_(1)
    prompt_field.setFont_(NSFont.boldSystemFontOfSize_(42))
    prompt_field.setTextColor_(NSColor.yellowColor())

    prompt_win.setContentView_(prompt_field)
    prompt_win.makeKeyAndOrderFront_(None)
    prompt_win.orderOut_(None)


def set_score_text(text, color=None, size=None):
    """
    Update the score text field with the specified text,
    color, and font size.
    """

    if score_field:
        score_field.setStringValue_(str(text))
        if color:
            score_field.setTextColor_(color)
        if size:
            score_field.setFont_(NSFont.boldSystemFontOfSize_(size))


# ------------------------------------------------------------------ #
#  Geometry / Collision detection                                    #
# ------------------------------------------------------------------ #
def reset_pipe():
    """
    Reset the pipe position and gap.
    """

    global pipe_x, gap_y, passed_pipe
    pipe_x = SCREEN_W + 100
    gap_y = random.randint(180, SCREEN_H - 180 - PIPE_GAP)
    passed_pipe = False


def position_pipe(pipe):
    """
    Position the top and bottom pipe windows
    based on the pipe's x position and gap_y.
    """

    x = pipe["x"]
    gap_y = pipe["gap_y"]
    top_y = gap_y + PIPE_GAP
    top_h = max(1, SCREEN_H - top_y)
    bot_h = max(1, gap_y)

    pipe["top"].setFrame_display_(NSMakeRect(x, top_y, PIPE_WIDTH, top_h), True)
    pipe["bottom"].setFrame_display_(NSMakeRect(x, 0, PIPE_WIDTH, bot_h), True)
    pipe["top"].contentView().setNeedsDisplay_(True)
    pipe["bottom"].contentView().setNeedsDisplay_(True)


def position_pipes():
    """
    Position all pipe windows.
    """

    for pipe in pipes:
        position_pipe(pipe)


def overlaps(a, b):
    """
    Check if two rectangles overlap.
    """

    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


# ------------------------------------------------------------------ #
#  Start prompt                                                      #
# ------------------------------------------------------------------ #
def show_start_prompt():
    """
    Show the start prompt window and reset the game state.
    """

    global state, post_game_pause
    state = "start_prompt"
    post_game_pause = 0.0
    hide_bird()
    for pipe in pipes:
        for win in (pipe["top"], pipe["bottom"]):
            if win:
                win.orderOut_(None)
    if prompt_field:
        prompt_field.setStringValue_("PRESS SPACE")
        prompt_field.setTextColor_(NSColor.yellowColor())
        prompt_field.setFont_(NSFont.boldSystemFontOfSize_(42))
    if prompt_win:
        prompt_win.makeKeyAndOrderFront_(None)


def start_countdown():
    """
    Start the countdown before the game begins.
    """

    global state, countdown, go_timer, post_game_pause
    global bird_y, bird_vy, score, passed_pipe

    state = "countdown"
    countdown = COUNTDOWN_FROM
    go_timer = 0.0
    post_game_pause = 0.0

    bird_y = SCREEN_H / 2
    bird_vy = 0
    score = 0
    passed_pipe = False

    create_pipes()
    position_pipes()
    if prompt_win:
        prompt_win.orderOut_(None)

    create_bird()
    bird_win.setFrameOrigin_((BIRD_X, bird_y))
    bird_win.setBackgroundColor_(NSColor.clearColor())
    update_bird_sprite()
    show_bird()
    for pipe in pipes:
        for win in (pipe["top"], pipe["bottom"]):
            win.makeKeyAndOrderFront_(None)

    set_score_text(str(int(math.ceil(COUNTDOWN_FROM))),
                   NSColor.yellowColor(), size=52)


def start_playing():
    """
    Transition from countdown to playing state.
    """

    global state, go_timer
    state = "playing"
    go_timer = GO_DISPLAY
    set_score_text("GO!", NSColor.greenColor(), size=52)


def game_over():
    """
    Handle the game over state.
    """

    global state, post_game_pause
    state = "game_over_pause"
    post_game_pause = 1.8
    hide_bird()
    for pipe in pipes:
        for win in (pipe["top"], pipe["bottom"]):
            if win:
                win.orderOut_(None)
    score_text = f"GAME OVER - {int(score)}"
    if prompt_win:
        prompt_win.orderOut_(None)
    score_field.setStringValue_(score_text)
    score_field.setTextColor_(NSColor.redColor())
    score_field.setFont_(NSFont.boldSystemFontOfSize_(30))
    score_field.setAlignment_(1)


# ------------------------------------------------------------------ #
#  Game loop                                                         #
# ------------------------------------------------------------------ #
def tick(_):
    """
    Main game loop tick function, called at a fixed interval.
    """

    global bird_y, bird_vy, pipe_x, score, passed_pipe
    global countdown, state, go_timer, post_game_pause

    if state == "start_prompt":
        return

    if state == "countdown":
        countdown -= TICK
        if countdown > 0:
            set_score_text(str(int(math.ceil(countdown))),
                           NSColor.yellowColor(), size=52)
        else:
            start_playing()
        return

    if state == "game_over_pause":
        post_game_pause -= TICK
        if post_game_pause <= 0:
            show_start_prompt()
        return

    # state == 'playing'
    if go_timer > 0:
        go_timer -= TICK
        if go_timer <= 0:
            set_score_text(str(score), NSColor.yellowColor(), size=52)

    # Bird
    bird_vy -= GRAVITY
    bird_y += bird_vy

    if bird_y <= 0 or bird_y + CELL >= SCREEN_H:
        game_over()
        return

    bird_win.setFrameOrigin_((BIRD_X, bird_y))
    bird_win.setBackgroundColor_(NSColor.clearColor())
    update_bird_sprite()

    # Pipes
    rightmost_x = SCREEN_W + 100
    for pipe in pipes:
        pipe["x"] -= PIPE_SPEED

        if not pipe["passed"] and pipe["x"] + PIPE_WIDTH < BIRD_X:
            score += 1
            pipe["passed"] = True
            if go_timer <= 0:
                set_score_text(int(score), NSColor.yellowColor(), size=52)

        if pipe["x"] + PIPE_WIDTH < 0:
            pipe["x"] = rightmost_x + PIPE_SPACING
            pipe["gap_y"] = random.randint(180, SCREEN_H - 180 - PIPE_GAP)
            pipe["passed"] = False
            rightmost_x = pipe["x"]

        position_pipe(pipe)

    # Collision detection
    bird_rect = (BIRD_X, bird_y, CELL, CELL)
    for pipe in pipes:
        top_rect = (pipe["x"], pipe["gap_y"] + PIPE_GAP,
                    PIPE_WIDTH, SCREEN_H - pipe["gap_y"] - PIPE_GAP)
        bottom_rect = (pipe["x"], 0, PIPE_WIDTH, pipe["gap_y"])
        if overlaps(bird_rect, top_rect) or overlaps(bird_rect, bottom_rect):
            game_over()
            return


def jump():
    """
    Make the bird jump by setting its vertical velocity.
    """

    global bird_vy
    if state == "playing":
        bird_vy = JUMP


# ------------------------------------------------------------------ #
#  Key handler for intercepted keys                                  #
# ------------------------------------------------------------------ #
def on_key(key_code: int):
    """
    Handle key events for the game.
    """

    if key_code == KEY_ESCAPE:
        NSApplication.sharedApplication().terminate_(None)
        return

    if key_code == KEY_SPACE:
        if state == "start_prompt":
            start_countdown()
        elif state == "playing":
            jump()
        elif state == "countdown":
            pass
        elif state == "game_over_pause":
            pass


# ------------------------------------------------------------------ #
#  main                                                               #
# ------------------------------------------------------------------ #
def _handle_sigint(signum, frame):
    """
    Handle SIGINT signal (Ctrl+C).
    """

    print("\n⚠️  Ctrl+C received - exiting Flappy.")
    app = NSApplication.sharedApplication()
    try:
        app.terminate_(None)
    except Exception:
        pass
    raise SystemExit(0)


def main():
    """
    Main entry point for the Flappy Window game.
    """

    signal.signal(signal.SIGINT, _handle_sigint)

    # 1. Accessibility permission
    if not ensure_accessibility_permission():
        sys.exit(1)

    # 2. Application
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)

    # 3. Game windows
    reset_pipe()
    create_bird()
    create_pipes()
    create_score()
    create_prompt_window()
    show_start_prompt()

    # 4. Key interceptor
    if not install_key_interceptor(on_key, CAPTURED_KEYS):
        print("❌ Failed to install key interceptor. Exiting.")
        sys.exit(1)

    # 5. Game 
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(TICK, True, tick)

    app.activateIgnoringOtherApps_(True)

    print()
    print("🎮 Flappy Window")
    print("   Space  — start / jump / restart")
    print("   Escape — exit")
    print()

    app.run()


if __name__ == "__main__":
    main()