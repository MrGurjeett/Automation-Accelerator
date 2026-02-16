import subprocess

import os

import argparse

import sys


class LaunchCodegen:

    """

    Launches Playwright Codegen for a given URL and language,

    optionally saving generated output to a file.

    """

    def __init__(self, language: str = "python"):

        self.language = language

        self.playwright_bin = self._resolve_playwright_binary()

    def _resolve_playwright_binary(self) -> str:

        """

        Resolve Playwright executable from virtualenv or fallback to global.

        """

        venv_bin = os.path.join(".venv", "Scripts", "playwright.exe")

        if os.path.exists(venv_bin):

            return venv_bin

        # Fallback to global playwright

        return "playwright"

    def launch(self, url: str, output_file: str | None = None):
        """
        Launch Playwright Codegen with a large viewport.
        """
        cmd = [
            self.playwright_bin,
            "codegen",
            url,
            "--target",
            self.language,
            "--viewport-size=1920,1080"
        ]

        if output_file:
            cmd.extend(["--output", output_file])

        print(f"Launching Codegen: {' '.join(cmd)}")

        # Run codegen — don't check return code (browser close = normal)
        subprocess.run(cmd, check=False)


def main():

    parser = argparse.ArgumentParser(

        description="Launch Playwright codegen and save generated output"

    )

    parser.add_argument(

        "--url",

        required=True,

        help="URL to start codegen with"

    )

    parser.add_argument(

        "--output",

        help="File path to save generated code"

    )

    parser.add_argument(

        "--language",

        default="python",

        help="Target language (default: python)"

    )

    args = parser.parse_args()

    launcher = LaunchCodegen(language=args.language)

    launcher.launch(url=args.url, output_file=args.output)

    # Always exit 0 — user closing the browser is normal behavior
    sys.exit(0)


if __name__ == "__main__":

    main()
 