"""
Regression test for the iter62 blank-screen bug class.

The original bug: `MatchDetail.js` referenced `<HighlightReelsPanel />` inside
JSX without ever importing the component. The CRA dev server's lint didn't
trip on it (only ran on edited files in watch mode). Users hit a fully blank
screen — React's error boundary unmounted everything when the `ReferenceError`
fired during render.

This test runs the project's stricter ESLint flat config (rooted at
/app/frontend/eslint.config.mjs) over the entire src tree and fails if any
JSX tag references an undefined identifier, or any non-JSX identifier is
likewise undefined.

If this test starts failing, you almost certainly have:
  - A missing `import` for a component referenced in JSX (the iter62 bug)
  - A typo'd function/variable name (e.g., setFoo when destructure spells
    out setBar) — also iter62-class, we caught one in useClipCollection too
"""
import os
import subprocess
import shutil


FRONTEND_DIR = "/app/frontend"
LINT_CONFIG = os.path.join(FRONTEND_DIR, "eslint.config.mjs")


def test_eslint_strict_config_file_exists():
    """If this file vanishes the regression test loses all teeth — fail loud."""
    assert os.path.exists(LINT_CONFIG), (
        f"Strict ESLint flat config not found at {LINT_CONFIG}. "
        "Without it, undefined JSX components / identifiers slip through "
        "to runtime (cf. iter62 blank-screen bug)."
    )


def test_no_undefined_jsx_components_or_identifiers():
    """Run the strict ESLint flat config across src/ and fail on any error.

    Specifically guards against:
      - react/jsx-no-undef → catches `<HighlightReelsPanel />` w/o import
      - no-undef            → catches `setCollectionCopied(...)` when only
                              `collectionCopied` was destructured
    """
    if not shutil.which("npx"):
        # CI image without Node — skip rather than hard-fail. Local devs and
        # the deploy pipeline both have npx, so this only protects the
        # narrow case of running pytest in a Python-only container.
        import pytest
        pytest.skip("npx not available; cannot run JS lint")

    result = subprocess.run(
        ["npx", "eslint", "src/"],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Warnings are OK (e.g., unused eslint-disable directives) — only ERRORS
    # indicate the runtime-crash bug class we care about.
    if result.returncode != 0:
        # Surface the full eslint output in the failure message so the dev
        # sees exactly which file + line + rule tripped.
        raise AssertionError(
            "ESLint strict pass found undefined references — this is the "
            "iter62 blank-screen bug class. Output:\n\n"
            f"{result.stdout}\n{result.stderr}"
        )
