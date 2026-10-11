# Layout of the macOS disk image window (DECISIONS D-052), for dmgbuild:
#   dmgbuild -s packaging/macos/dmg_settings.py -D app=... -D background=... "Research History" out.dmg
# The app and the Applications folder side by side, on a picture that says to drag one onto the
# other and then open the app from Applications (tools/dmg_background.py draws it).
# ruff: noqa: F821 - dmgbuild provides `defines`

app = defines["app"]
background = defines["background"]
files = [app]
symlinks = {"Applications": "/Applications"}
format = "UDZO"
icon_size = 128
text_size = 13
icon_locations = {"Research History.app": (170, 190), "Applications": (490, 190)}
window_rect = ((200, 120), (660, 422))  # the picture is 660 × 400; a little room for the title bar
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
arrange_by = None
