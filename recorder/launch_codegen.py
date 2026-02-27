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

        self.python_bin = sys.executable

    def launch(self, url: str, output_file: str | None = None):
        """
        Launch Playwright Codegen with a large viewport.
        """
        cmd = [
            self.python_bin,
            "-m",
            "playwright",
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
        result = subprocess.run(cmd, check=False)
        return result.returncode


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

    return_code = launcher.launch(url=args.url, output_file=args.output)

    # Always exit 0 — user closing the browser is normal behavior
    if return_code not in (0,):
        sys.exit(return_code)
    sys.exit(0)


if __name__ == "__main__":

    main()
 