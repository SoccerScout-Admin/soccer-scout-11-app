"""Shared email branding helpers (Feb 2026).

Renders the Soccer Scout 11 logo header used at the top of user-facing emails.
The asset (`/email-logo.png`) is the S11 mark + wordmark on a solid black
background so it stays legible on BOTH light- and dark-themed email clients.
"""
import os


def _public_app_url() -> str:
    return (os.environ.get("PUBLIC_APP_URL")
            or "https://soccerscout11.com").rstrip("/")


def email_logo_header(width: int = 200, margin_bottom: int = 20,
                      align: str = "left") -> str:
    """Return an HTML snippet with the brand logo, linked to the app.

    `width` is the displayed width in px (asset is 2x for retina sharpness).
    `align` controls the wrapper text-align ("left" or "center").
    """
    base = _public_app_url()
    return (
        f'<div style="text-align:{align};margin:0 0 {margin_bottom}px 0;">'
        f'<a href="{base}" style="text-decoration:none;border:0;">'
        f'<img src="{base}/email-logo.png" width="{width}" '
        f'alt="Soccer Scout 11" '
        f'style="display:inline-block;border:0;outline:none;text-decoration:none;'
        f'-ms-interpolation-mode:bicubic;width:{width}px;max-width:100%;height:auto;" />'
        f'</a></div>'
    )
