"""Drive the ConnectClips SPA through every state the operator manual
references and save the PNGs into docs/screenshots/.

Most screenshots are taken with Tailscale identity headers injected, so
the header shows ``Hi, Michael`` and admin mode auto-engages from the
identity (matching what volunteers actually see via Tailscale Serve).
The admin-password-prompt screenshot is taken from a second context with
no headers, since that flow only appears when identity is missing.

Reads ADMIN_PASSWORD from backend/.env (so we don't leak it to logs).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/home/connectadmin/ConnectClips/docs/screenshots")
BASE = "http://127.0.0.1:8765"

SERMON = "Keep_Your_Eyes_on_the_Hill_Exodus_17_Trials_to_Freedom_Series-XD8AEeSmFew.mp4"

# Headers Tailscale Serve injects. Login must match ADMIN_TAILSCALE_LOGINS
# in backend/.env so identity-based admin engages.
TS_HEADERS = {
    "Tailscale-User-Login": "br8kpoint@gmail.com",
    "Tailscale-User-Name": "Michael Fair",
    "Tailscale-User-Profile-Pic": "",
}


def read_admin_password() -> str:
    env_file = Path("/home/connectadmin/ConnectClips/backend/.env")
    for line in env_file.read_text().splitlines():
        if line.startswith("ADMIN_PASSWORD="):
            return line.split("=", 1)[1].strip()
    return ""


ADMIN_PW = read_admin_password()
if not ADMIN_PW:
    print("WARNING: ADMIN_PASSWORD not set; password-prompt screenshot will be skipped")


def capture_identity_pass(p):
    """Screenshots 01-08, 10, 11 — viewer is signed in via Tailscale identity."""
    browser = p.chromium.launch(headless=True)
    # Viewport bumped from 1366×900 to 1440×1080 because the new banner-bar
    # eats 280 px at the top — at 900 tall there's barely room for the
    # sermon list to show meaningful content below the banner.
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 1080},
        extra_http_headers=TS_HEADERS,
    )
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector(".sermon-list")
    page.wait_for_selector(".identity-badge")  # confirm header injection took
    page.wait_for_load_state("networkidle")

    # 01 — sermon list (home page) with identity badge + ADMIN MODE in header
    page.screenshot(path=str(OUT / "01-sermon-list.png"))
    print("  01-sermon-list.png")

    # 02 — add-from-youtube panel with URL pasted
    yt_input = page.locator(".add-youtube input[type='text']")
    yt_input.fill("https://www.youtube.com/watch?v=XD8AEeSmFew")
    page.locator(".add-sermon").screenshot(path=str(OUT / "02-add-from-youtube.png"))
    print("  02-add-from-youtube.png")
    yt_input.fill("")

    # Open the sermon detail page
    page.locator(f".sermon-row:has(.name:text-is('{SERMON}'))").click()
    page.wait_for_selector(".sermon-detail h1")
    page.wait_for_selector(".clips")

    # 03 — sermon detail header + pipeline (with new Range controls)
    page.screenshot(path=str(OUT / "03-sermon-detail.png"))
    print("  03-sermon-detail.png")

    # 04 — close-up of the Pick Clips step (second .step element)
    page.locator(".pipeline .step").nth(1).screenshot(path=str(OUT / "04-pick-clips.png"))
    print("  04-pick-clips.png")

    # 05 — clip cards list
    page.locator(".clips").screenshot(path=str(OUT / "05-clip-cards.png"))
    print("  05-clip-cards.png")

    # 06 — trim view WITHOUT an export. Pick a clip with no "✓ exported" badge.
    cards = page.locator(".clip-card").all()
    target_idx = None
    for i, card in enumerate(cards):
        if "✓ exported" not in card.inner_text():
            target_idx = i
            break
    if target_idx is None:
        target_idx = len(cards) - 1
    page.locator(".clip-card").nth(target_idx).locator("button").first.click()
    page.wait_for_selector(".trim h2")
    page.wait_for_selector(".cs-trigger")  # caption-style picker rendered
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "06-trim-view.png"))
    print(f"  06-trim-view.png (using clip {target_idx})")

    # Back to detail
    page.locator(".back").click()
    page.wait_for_selector(".clips")

    # 07 — trim view WITH an exported preview. Use clip 0 (already exported).
    page.locator(".clip-card").nth(0).locator("button").first.click()
    page.wait_for_selector(".trim h2")
    page.wait_for_selector(".publish")
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT / "07-export-preview.png"))
    print("  07-export-preview.png")

    # 08 — just the publish panel
    page.locator(".publish").screenshot(path=str(OUT / "08-publish-panel.png"))
    print("  08-publish-panel.png")

    # Back to list, then to Activity (admin only — visible because identity is admin)
    page.locator(".back").click()
    page.wait_for_selector(".sermon-detail h1")
    page.locator(".back").click()
    page.wait_for_selector(".sermon-row")  # wait for actual rows, not just the empty wrapper
    page.wait_for_load_state("networkidle")

    # 10 — sermon list with ADMIN MODE engaged via identity (delete buttons visible)
    page.screenshot(path=str(OUT / "10-admin-active.png"))
    print("  10-admin-active.png")

    # 11 — Activity page (admin-only) with running/finished jobs
    page.locator("button:has-text('Activity')").click()
    page.wait_for_selector(".history-table")
    page.wait_for_timeout(800)  # let any in-flight progress refresh paint
    page.screenshot(path=str(OUT / "11-activity.png"))
    print("  11-activity.png")

    browser.close()


def capture_anonymous_pass(p):
    """Screenshot 09 — admin password prompt. Only appears when no Tailscale
    identity is in scope, so we open a context with no extra headers."""
    if not ADMIN_PW:
        print("  09-admin-prompt.png SKIPPED (no admin password)")
        return
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1080})
    page = ctx.new_page()
    page.goto(BASE)
    page.wait_for_selector(".sermon-list")
    page.wait_for_load_state("networkidle")

    page.locator("button:has-text('Enter admin mode')").click()
    page.wait_for_selector(".admin-prompt input[type='password']")
    # The old `<header>` was replaced with a full-width `.banner-bar` that
    # spans the top of the page; the admin prompt now lives inside it.
    page.locator(".banner-bar").screenshot(path=str(OUT / "09-admin-prompt.png"))
    print("  09-admin-prompt.png")

    browser.close()


def main():
    with sync_playwright() as p:
        capture_identity_pass(p)
        capture_anonymous_pass(p)


if __name__ == "__main__":
    print(f"saving to {OUT}")
    main()
    print("done")
